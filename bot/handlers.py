"""Conversation handlers: turn an Intent into engine calls.

State is intentionally tiny: the last posted plan per channel, so "send 1 and 3"
can map row numbers back to invoices. Wave + Gmail remain the source of truth, so
this cache is disposable (a refresh rebuilds it).

The HITL gate lives here: send happens ONLY on an explicit send Intent.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date

from payup.lib import ledger, output, runner
from payup.lib.planner import Action, PayupConfig

from .intents import parse_intent

__all__ = ["BotDeps", "ChaseSession", "HELP_TEXT"]

# Strip Slack markup (@mentions, channel refs, links) from a follow-up reply so
# an @mention prefix does not end up inside the saved template copy.
_SLACK_MARKUP = re.compile(r"<[^>]+>")
_CANCEL_WORDS = {"cancel", "stop", "quit", "nevermind", "never mind"}
_TIER_LABEL = {"gentle": "first friendly nudge", "firm": "past due", "final": "last call"}

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
        # Per-channel state for the guided "edit template" flow. Absent = not
        # editing. {"tier": None} = waiting for a tier pick; {"tier": "gentle"} =
        # waiting for the new copy for that tier.
        self._edit: dict[str, dict] = {}
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

    def _edit_start(self, channel: str, tier: str | None) -> str:
        """Enter the guided editor. With a tier already named ("edit gentle"),
        jump straight to asking for the new copy; otherwise ask which reminder."""
        if tier:
            self._edit[channel] = {"tier": tier}
            return self._prompt_for_copy(tier)
        self._edit[channel] = {"tier": None}
        return (
            "Which reminder do you want to change?\n"
            "  1. gentle   (first friendly nudge)\n"
            "  2. firm     (past due)\n"
            "  3. final     (last call)\n"
            'Reply 1, 2, or 3. Say "cancel" to stop.'
        )

    def _prompt_for_copy(self, tier: str) -> str:
        from payup.lib.templating import TemplateSet

        current = self.deps.cfg.templating.templates or TemplateSet()
        return (
            f"Your current {tier} reminder ({_TIER_LABEL[tier]}):\n\n"
            f"Subject: {current.subject_for(tier)}\n"
            f"Body:\n{current.body_for(tier)}\n\n"
            "Paste the new wording (this becomes the body). Keep the pieces in "
            "{curly braces} so they auto-fill. To also change the subject line, put "
            'it on a first line starting with "Subject:". Say "cancel" to stop.'
        )

    def _edit_step(self, channel: str, text: str) -> str:
        """Handle one reply inside the guided editor: a tier pick, the new copy,
        or a cancel. Editing copy never sends: it only rewrites stored templates,
        which are still guardrail-checked at render time and still need explicit
        approval to go out. A bad edit is rejected before anything is saved."""
        from dataclasses import replace

        from payup.lib.escalation import Tier
        from payup.lib.models import Invoice
        from payup.lib.templating import (
            TemplateSet,
            TemplatingConfig,
            TemplatingError,
            render_email,
        )

        cleaned = _SLACK_MARKUP.sub(" ", text or "").strip()
        if cleaned.lower() in _CANCEL_WORDS:
            self._edit.pop(channel, None)
            return "Okay, cancelled. Nothing changed."

        tier = self._edit.get(channel, {}).get("tier")

        # Stage 1: waiting for a tier pick.
        if not tier:
            low = cleaned.lower()
            picked = None
            for name, num in (("gentle", "1"), ("firm", "2"), ("final", "3")):
                if low == num or re.search(rf"\b{name}\b", low):
                    picked = name
                    break
            if not picked:
                return 'Reply 1 (gentle), 2 (firm), or 3 (final). Say "cancel" to stop.'
            self._edit[channel] = {"tier": picked}
            return self._prompt_for_copy(picked)

        # Stage 2: the reply is the new copy.
        subject, body = self._split_subject_body(cleaned)
        changes: dict[str, str] = {}
        if subject:
            changes[f"{tier}_subject"] = subject
        if body:
            changes[f"{tier}_body"] = body
        if not changes:
            return 'I did not catch any new wording. Paste the text, or say "cancel".'

        tmpl_cfg: TemplatingConfig = self.deps.cfg.templating
        current: TemplateSet = tmpl_cfg.templates or TemplateSet()
        candidate = replace(current, **changes)

        # Validate against the SAME render-time guardrails every draft passes,
        # using a synthetic invoice. Reject before saving; stay in edit mode so the
        # user can just try again.
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
                f"That would break a rule: {exc}. Nothing saved. Try again, or say "
                '"cancel". Keep {invoice_number} in the subject, and avoid '
                "legal/collections wording and em dashes."
            )

        # Persist so it survives a restart, then hot-swap the in-memory config so
        # the very next "show overdue" renders with the new copy.
        saved = self._persist_template_fields(tier, changes)
        self.deps.cfg = replace(
            self.deps.cfg, templating=replace(tmpl_cfg, templates=candidate)
        )
        self._edit.pop(channel, None)
        what = " and ".join(key.split("_", 1)[1] for key in changes)
        tail = "" if saved else " (in memory only: the templates file was not writable)"
        return (
            f'Saved. Your {tier} {what} is updated and live. Say "show overdue" to '
            f"see it in the next batch. Nothing was sent.{tail}"
        )

    @staticmethod
    def _split_subject_body(raw: str) -> tuple[str | None, str]:
        """A first non-empty line starting with 'Subject:' sets the subject and the
        rest is the body; otherwise the whole message is the body."""
        lines = raw.split("\n")
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            if line.strip().lower().startswith("subject:"):
                subject = line.strip()[len("subject:"):].strip()
                body = "\n".join(lines[idx + 1:]).strip()
                return (subject or None, body)
            break
        return (None, raw.strip())

    def _persist_template_fields(self, tier: str, changes: dict[str, str]) -> bool:
        """Merge the edited field(s) into the templates YAML file, creating it if
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
        tier_block = data.setdefault(tier, {})
        for key, val in changes.items():
            tier_block[key.split("_", 1)[1]] = val  # gentle_subject -> subject
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

        # A guided template edit in progress consumes replies until it finishes or
        # is cancelled, so the pasted copy is never re-parsed as a send/skip/etc.
        if channel in self._edit:
            return self._edit_step(channel, text)

        rows = self._rows(channel)
        intent = parse_intent(text, [{"n": r["n"], "customer": r["customer"]} for r in rows])

        if intent.kind == "help":
            return HELP_TEXT
        if intent.kind == "show_overdue":
            return self.refresh(channel)
        if intent.kind == "edit_template":
            return self._edit_start(channel, intent.tier)
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
