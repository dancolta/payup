"""Conversation handlers: turn an Intent into engine calls.

State is intentionally tiny: the last posted plan per channel, so "send 1 and 3"
can map row numbers back to invoices. Wave + Gmail remain the source of truth, so
this cache is disposable (a refresh rebuilds it).

The HITL gate lives here: send happens ONLY on an explicit send Intent.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date

from payup.lib import output, runner
from payup.lib.planner import Action, PayupConfig

from .intents import parse_intent

__all__ = ["BotDeps", "ChaseSession", "HELP_TEXT"]

HELP_TEXT = (
    "PayUp commands:\n"
    '  "show overdue"   list invoices ready to chase\n'
    '  "send all"       send every reminder in the batch\n'
    '  "send 1 and 3"   send specific rows\n'
    '  "skip Delta"     drop a row from this batch (nothing is sent)\n'
    "Nothing is ever sent until you say send."
)

CLARIFY_TEXT = (
    "I did not catch a clear instruction. Try \"show overdue\", "
    '"send all", "send 1 and 3", or "skip Delta".'
)


@dataclass
class BotDeps:
    token: str
    business_id: str
    source_name: str = "quickbooks"
    cfg: PayupConfig = field(default_factory=PayupConfig)
    # How far back the Gmail dedupe search looks (escalation history window).
    # Wider than escalation.min_gap_days on purpose: see runner.build_plan.
    history_days: int = 90
    dry_run: bool = True
    gmail_creds: object = None
    gmail_transport: object = None
    # Optional QuickBooks unattended-refresh creds. When all three are present
    # and the source is QuickBooks, access_token() mints a fresh hourly token
    # before each batch build (QBO access tokens expire in ~1 hour).
    refresh_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    # Extra keyword args forwarded to the source connector (e.g. QBO `host`).
    source_kwargs: dict = field(default_factory=dict)
    now_fn: object = date.today

    def now(self) -> date:
        return self.now_fn()

    def access_token(self) -> str:
        """Return a usable access token, refreshing the QuickBooks one first if
        unattended-refresh creds are configured. QBO access tokens expire hourly,
        so an always-on bot must refresh or every run after the first hour 401s.

        State-light note: Intuit rotates the refresh token on each use; we keep
        the new one in memory for the process lifetime. On restart the bot reads
        the (possibly rotated) value from the environment again."""
        if (
            self.source_name in ("quickbooks", "qbo")
            and self.refresh_token
            and self.client_id
            and self.client_secret
        ):
            from payup.lib import quickbooks

            payload = quickbooks.refresh_access_token(
                self.refresh_token, self.client_id, self.client_secret
            )
            self.token = payload.get("access_token", self.token)
            if payload.get("refresh_token"):
                self.refresh_token = payload["refresh_token"]
        return self.token


class ChaseSession:
    """Per-process conversation state. One instance serves the bot."""

    def __init__(self, deps: BotDeps):
        self.deps = deps
        self._plans: dict[str, list] = {}
        # Bounded set of recently handled Slack event ids. Slack delivers a
        # channel @mention as BOTH an app_mention and a message event; without
        # this, "@PayUp send all" would run (and send) twice.
        self._seen_events: deque[str] = deque(maxlen=512)

    def _drop_actions(self, channel: str, row_numbers: set[int]) -> set[str]:
        """Remove the Actions at the given 1-based row numbers from the cached
        plan. Returns the set of dropped invoice numbers."""
        plan = self._plans.get(channel, [])
        kept: list = []
        dropped: set[str] = set()
        n = 0
        for item in plan:
            if isinstance(item, Action):
                n += 1
                if n in row_numbers:
                    dropped.add(item.invoice.invoice_number)
                    continue
            kept.append(item)
        self._plans[channel] = kept
        return dropped

    def _rows(self, channel: str) -> list[dict]:
        plan = self._plans.get(channel, [])
        rows: list[dict] = []
        n = 0
        for item in plan:
            if isinstance(item, Action):
                n += 1
                rows.append(
                    {
                        "n": n,
                        "customer": item.invoice.customer_name,
                        "invoice_id": item.invoice.invoice_id,
                        "invoice_number": item.invoice.invoice_number,
                    }
                )
        return rows

    def refresh(self, channel: str) -> str:
        plan = runner.build_plan(
            now=self.deps.now(),
            token=self.deps.access_token(),
            business_id=self.deps.business_id,
            source_name=self.deps.source_name,
            gmail_creds=self.deps.gmail_creds,
            gmail_transport=self.deps.gmail_transport,
            history_days=self.deps.history_days,
            source_kwargs=self.deps.source_kwargs,
            cfg=self.deps.cfg,
        )
        self._plans[channel] = plan
        return output.render_batch(plan, now=self.deps.now())

    def handle(self, channel: str, text: str, *, event_id: str | None = None) -> str | None:
        # Dedupe Slack's double delivery of @mentions (app_mention + message).
        # Returns None for a duplicate so the caller posts nothing.
        if event_id is not None:
            if event_id in self._seen_events:
                return None
            self._seen_events.append(event_id)

        rows = self._rows(channel)
        intent = parse_intent(text, [{"n": r["n"], "customer": r["customer"]} for r in rows])

        if intent.kind == "help":
            return HELP_TEXT
        if intent.kind == "show_overdue":
            return self.refresh(channel)
        if intent.kind == "unknown":
            return CLARIFY_TEXT
        if intent.kind == "skip":
            if intent.all:
                self._plans[channel] = []
                return "Cleared this batch. Nothing was sent."
            dropped = self._drop_actions(channel, set(intent.ids))
            listed = ", ".join("#" + d for d in sorted(dropped)) or "nothing"
            return f"Skipped {listed}. Those will not be sent in this batch. Nothing was sent."

        # intent.kind == "send"  -> the only path that may send
        if not rows:
            return 'No batch yet. Say "show overdue" first.'
        if intent.all:
            approved = {r["invoice_id"] for r in rows}
        else:
            approved = {r["invoice_id"] for r in rows if r["n"] in intent.ids}
        plan = self._plans.get(channel, [])
        sent, skipped = runner.execute(
            plan,
            approved,
            gmail_creds=self.deps.gmail_creds,
            gmail_transport=self.deps.gmail_transport,
            dry_run=self.deps.dry_run,
        )
        # On a real send, drop what we sent so a repeated "send all" cannot
        # re-send it. Dry-run keeps the batch so the preview stays repeatable.
        if not self.deps.dry_run and sent:
            self._plans[channel] = [
                it
                for it in plan
                if not (isinstance(it, Action) and it.invoice.invoice_id in approved)
            ]
        prefix = "[dry-run] " if self.deps.dry_run else ""
        return prefix + output.render_confirmation(
            [f"#{s}" for s in sent], [f"#{s}" for s in skipped]
        )
