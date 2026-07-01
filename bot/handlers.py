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

from payup.lib import ledger, output, runner
from payup.lib.planner import Action, PayupConfig

from .intents import parse_intent

__all__ = ["BotDeps", "ChaseSession", "HELP_TEXT"]

HELP_TEXT = (
    "PayUp commands:\n"
    '  "show overdue"   list invoices ready to chase\n'
    '  "send all"       send every reminder in the batch\n'
    '  "send 1 and 3"   send specific rows\n'
    '  "draft all"      save reminders as Gmail drafts to review (nothing is sent)\n'
    '  "skip Delta"     drop a row from this batch (nothing is sent)\n'
    '  "edit template"  change the reminder wording in your own voice (nothing is sent)\n'
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
    # Where to append the run ledger that powers /chase-status. None disables
    # writing (the default, so tests never touch the filesystem); the bot sets it.
    ledger_path: str | None = None
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
        try:
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
        except Exception:  # noqa: BLE001 - report in chat, never die silently
            import traceback

            traceback.print_exc()
            return (
                "PayUp could not reach your accounting source. The access token has "
                "likely expired. Refresh your QuickBooks or Wave token (or re-run "
                "/payup-setup), then try `show overdue` again."
            )
        self._plans[channel] = plan
        return output.render_batch(plan, now=self.deps.now())

    def _edit_template(self, intent) -> str:
        """Change the reminder wording from Slack. Editing copy is not a send: it
        only rewrites stored templates, and every future draft still passes the
        render-time guardrails and still needs explicit approval to go out. So
        there is no HITL gate here, but a bad edit is rejected before it is saved."""
        from dataclasses import replace

        from payup.lib.escalation import Tier
        from payup.lib.models import Invoice
        from payup.lib.templating import (
            TemplateSet,
            TemplatingConfig,
            TemplatingError,
            render_email,
        )

        tmpl_cfg: TemplatingConfig = self.deps.cfg.templating
        current: TemplateSet = tmpl_cfg.templates or TemplateSet()

        # No tier/field given: show the current copy and how to change it.
        if not (intent.tier and intent.template_field and intent.template_text):
            lines = ["Current reminder copy. Edit one field at a time:"]
            for tier in ("gentle", "firm", "final"):
                lines.append(f"\n{tier}")
                lines.append(f"  subject: {current.subject_for(tier)}")
                lines.append(f"  body: {current.body_for(tier)}")
            lines.append(
                '\nTo change a field, send e.g. "edit template gentle subject: '
                'Quick nudge on invoice #{invoice_number}". Placeholders: '
                "{customer_name} {invoice_number} {amount} {due_date} {sender_name} "
                "{business_name}. Rules: keep {invoice_number} in the subject; no "
                "legal/collections wording; no em dashes. Nothing is ever sent."
            )
            return "\n".join(lines)

        tier, fld, text = intent.tier, intent.template_field, intent.template_text
        candidate = replace(current, **{f"{tier}_{fld}": text})

        # Validate against the SAME render-time guardrails the bot enforces on every
        # draft, using a synthetic invoice. Reject before saving so a broken template
        # can never reach a real chase (or wedge the batch build).
        sample = Invoice(
            invoice_id="EDIT",
            invoice_number="1042",
            customer_name="Sample Customer",
            customer_email="sample@example.com",
            amount_due_cents=125000,
            currency="USD",
            due_date=date(2026, 1, 1),
            status="SENT",
        )
        trial = TemplatingConfig(
            sender_name=tmpl_cfg.sender_name,
            business_name=tmpl_cfg.business_name,
            templates=candidate,
        )
        try:
            render_email(sample, Tier(tier), trial)
        except TemplatingError as exc:
            return (
                f"Did not save the {tier} {fld}: {exc}. Nothing changed. Keep "
                "{invoice_number} in the subject, and avoid legal/collections "
                "wording and em dashes."
            )

        # Persist so the change survives a restart, then hot-swap the in-memory
        # config so the very next "show overdue" renders with the new copy.
        saved = self._persist_template(tier, fld, text)
        self.deps.cfg = replace(
            self.deps.cfg, templating=replace(tmpl_cfg, templates=candidate)
        )
        tail = "" if saved else " (in memory only: the templates file was not writable)"
        return (
            f'Updated the {tier} {fld}. It passed the guardrails and is live now. Say '
            f'"show overdue" to see it in the next batch. Nothing was sent.{tail}'
        )

    def _persist_template(self, tier: str, field_name: str, text: str) -> bool:
        """Merge one edited field into the templates YAML file, creating it if
        needed. Returns True on write. Best-effort: if pyyaml is missing or the
        path is unwritable, the in-memory edit still applies for this process."""
        import os

        path = os.environ.get("PAYUP_TEMPLATES_CONFIG", "config/templates.yml")
        try:
            import yaml
        except Exception:
            return False
        data: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception:
                data = {}
        data.setdefault(tier, {})[field_name] = text
        try:
            with open(path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(
                    data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True
                )
            return True
        except Exception:
            return False

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
        if intent.kind == "edit_template":
            return self._edit_template(intent)
        if intent.kind == "unknown":
            return CLARIFY_TEXT
        if intent.kind == "skip":
            if intent.all:
                self._plans[channel] = []
                return "Cleared this batch. Nothing was sent."
            dropped = self._drop_actions(channel, set(intent.ids))
            listed = ", ".join("#" + d for d in sorted(dropped)) or "nothing"
            return f"Skipped {listed}. Those will not be sent in this batch. Nothing was sent."

        if intent.kind == "draft":
            # Save reminders as Gmail drafts. This writes to Gmail but never
            # sends: a draft sits in the mailbox for the user to open, edit, and
            # send by hand. A draft is NOT a chase, so we do NOT clear the batch
            # (the invoice is still un-chased until the draft is actually sent).
            if not rows:
                return 'No batch yet. Say "show overdue" first.'
            if intent.all:
                approved = {r["invoice_id"] for r in rows}
            else:
                approved = {r["invoice_id"] for r in rows if r["n"] in intent.ids}
            plan = self._plans.get(channel, [])
            drafted, skipped = runner.execute(
                plan,
                approved,
                gmail_creds=self.deps.gmail_creds,
                gmail_transport=self.deps.gmail_transport,
                dry_run=self.deps.dry_run,
                mode="draft",
            )
            if not self.deps.dry_run and drafted and self.deps.ledger_path:
                ledger.append_run(
                    {
                        "date": self.deps.now().isoformat(),
                        "source": self.deps.source_name,
                        "action": "draft",
                        "drafted": drafted,
                        "skipped": skipped,
                    },
                    self.deps.ledger_path,
                )
            base = output.render_draft_confirmation(
                [f"#{d}" for d in drafted], [f"#{s}" for s in skipped]
            )
            if self.deps.dry_run:
                return "[dry-run] " + base
            note = ""
            if drafted:
                note = (
                    " Open Gmail to review, edit, and send them. "
                    "Drafts are not tracked as chased until you actually send."
                )
            return base + note

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
            # Record the run so /chase-status reflects real activity.
            if self.deps.ledger_path:
                ledger.append_run(
                    {
                        "date": self.deps.now().isoformat(),
                        "source": self.deps.source_name,
                        "action": "send",
                        "sent": sent,
                        "skipped": skipped,
                    },
                    self.deps.ledger_path,
                )
        prefix = "[dry-run] " if self.deps.dry_run else ""
        return prefix + output.render_confirmation(
            [f"#{s}" for s in sent], [f"#{s}" for s in skipped]
        )
