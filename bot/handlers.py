"""Conversation handlers: turn an Intent into engine calls.

State is intentionally tiny: the last posted plan per channel, so "send 1 and 3"
can map row numbers back to invoices. Wave + Gmail remain the source of truth, so
this cache is disposable (a refresh rebuilds it).

The HITL gate lives here: send happens ONLY on an explicit send Intent.
"""

from __future__ import annotations

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
    lookback_days: int = 7
    dry_run: bool = True
    gmail_creds: object = None
    gmail_transport: object = None
    now_fn: object = date.today

    def now(self) -> date:
        return self.now_fn()


class ChaseSession:
    """Per-process conversation state. One instance serves the bot."""

    def __init__(self, deps: BotDeps):
        self.deps = deps
        self._plans: dict[str, list] = {}

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
            token=self.deps.token,
            business_id=self.deps.business_id,
            source_name=self.deps.source_name,
            gmail_creds=self.deps.gmail_creds,
            gmail_transport=self.deps.gmail_transport,
            lookback_days=self.deps.lookback_days,
            cfg=self.deps.cfg,
        )
        self._plans[channel] = plan
        return output.render_batch(plan, now=self.deps.now())

    def handle(self, channel: str, text: str) -> str:
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
            dropped = {r["invoice_number"] for r in rows if r["n"] in intent.ids}
            return f"Skipped {', '.join('#' + d for d in sorted(dropped)) or 'nothing'}. Nothing was sent."

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
        prefix = "[dry-run] " if self.deps.dry_run else ""
        return prefix + output.render_confirmation(
            [f"#{s}" for s in sent], [f"#{s}" for s in skipped]
        )
