"""Orchestration shared by the Slack bot, the Claude Code skills, and tests.

Two steps, deliberately separate so approval always sits between them:
  build_plan(...)  -> fetch overdue (Wave) + priors (Gmail) -> tiered plan (pure)
  execute(...)     -> send ONLY the explicitly approved actions

No global state. The caller owns credentials/transports.
"""

from __future__ import annotations

from datetime import date

from . import gmail
from .planner import Action, PayupConfig, Skip, plan_chase
from .sources import get_source

__all__ = ["build_plan", "execute"]


def build_plan(
    *,
    now: date,
    token: str,
    business_id: str,
    source_name: str | None = None,
    gmail_creds=None,
    gmail_transport=None,
    history_days: int = 90,
    source_kwargs: dict | None = None,
    cfg: PayupConfig | None = None,
) -> list[Action | Skip]:
    """Fetch overdue-unpaid invoices and join with Gmail send-history into a plan.

    `source_name` selects the invoice connector (default QuickBooks; "wave" also
    available). `token`/`business_id` are that source's credentials.
    `source_kwargs` are extra keyword args for the connector (e.g. QBO `host`).

    `history_days` is how far back the Gmail dedupe search looks. It is wider
    than the escalation min_gap on purpose: min_gap (in cfg.escalation) gates how
    *recently* we chased, while history_days is how many prior reminders we count
    for tier escalation. Tying them together (the old default) made the prior
    count effectively always zero whenever a send was allowed.
    """
    cfg = cfg or PayupConfig()
    source_fn = get_source(source_name)
    invoices = source_fn(token, business_id, now=now, **(source_kwargs or {}))
    prior_by_invoice: dict[str, list[date]] = {}
    for inv in invoices:
        refs = gmail.prior_reminders(
            inv.invoice_number,
            inv.customer_email,
            gmail_creds,
            lookback_days=history_days,
            transport=gmail_transport,
        )
        prior_by_invoice[inv.invoice_number] = [r.sent_date for r in refs]
    return plan_chase(invoices, prior_by_invoice, now=now, cfg=cfg)


def execute(
    plan: list[Action | Skip],
    approved_ids: set[str] | list[str],
    *,
    gmail_creds=None,
    gmail_transport=None,
    dry_run: bool = True,
    mode: str = "send",
) -> tuple[list[str], list[str]]:
    """Act on the approved actions. Returns (acted_numbers, skipped_numbers).

    `mode` selects the Gmail write path:
      * "send" (default): send the approved reminders (the HITL send gate).
      * "draft": save the approved reminders as Gmail drafts (no send). A draft
        has not been sent, so the caller must not treat a draft as a chase.

    An action that is not in approved_ids is never acted on. This is the HITL gate.
    """
    if mode not in ("send", "draft"):
        # Fail closed: an unknown mode must never silently fall through to sending.
        raise ValueError(f"unknown execute mode {mode!r}; expected 'send' or 'draft'")
    approved = set(approved_ids)
    acted: list[str] = []
    skipped: list[str] = []
    for item in plan:
        if not isinstance(item, Action):
            continue
        if item.invoice.invoice_id in approved:
            if mode == "draft":
                gmail.create_gmail_draft(
                    item.draft,
                    dry_run=dry_run,
                    creds=gmail_creds,
                    transport=gmail_transport,
                )
            else:
                gmail.send_message(
                    item.draft,
                    approved=True,
                    dry_run=dry_run,
                    creds=gmail_creds,
                    transport=gmail_transport,
                )
            acted.append(item.invoice.invoice_number)
        else:
            skipped.append(item.invoice.invoice_number)
    return acted, skipped
