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
    lookback_days: int = 7,
    cfg: PayupConfig | None = None,
) -> list[Action | Skip]:
    """Fetch overdue-unpaid invoices and join with Gmail send-history into a plan.

    `source_name` selects the invoice connector (default QuickBooks; "wave" also
    available). `token`/`business_id` are that source's credentials.
    """
    cfg = cfg or PayupConfig()
    source_fn = get_source(source_name)
    invoices = source_fn(token, business_id, now=now)
    prior_by_invoice: dict[str, list[date]] = {}
    for inv in invoices:
        refs = gmail.prior_reminders(
            inv.invoice_number,
            inv.customer_email,
            gmail_creds,
            lookback_days=lookback_days,
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
) -> tuple[list[str], list[str]]:
    """Send only the approved actions. Returns (sent_numbers, skipped_numbers).

    An action that is not in approved_ids is never sent. This is the HITL gate.
    """
    approved = set(approved_ids)
    sent: list[str] = []
    skipped: list[str] = []
    for item in plan:
        if not isinstance(item, Action):
            continue
        if item.invoice.invoice_id in approved:
            gmail.send_message(
                item.draft,
                approved=True,
                dry_run=dry_run,
                creds=gmail_creds,
                transport=gmail_transport,
            )
            sent.append(item.invoice.invoice_number)
        else:
            skipped.append(item.invoice.invoice_number)
    return sent, skipped
