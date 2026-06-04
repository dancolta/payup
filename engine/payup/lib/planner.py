"""The chase planner. Pure. Joins Wave (who's overdue) with Gmail (who we already
chased) and decides, per invoice, whether to send a tiered draft or skip.

No side effects, no network, no sends. The bot/CLI takes the resulting plan to a
human for approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .escalation import EscalationConfig, Tier, select_tier
from .templating import Draft, TemplatingConfig, render_email
from .wave import Invoice

__all__ = ["Action", "Skip", "PayupConfig", "plan_chase"]


@dataclass(frozen=True)
class PayupConfig:
    escalation: EscalationConfig = EscalationConfig()
    templating: TemplatingConfig = TemplatingConfig()


@dataclass(frozen=True)
class Action:
    """A reminder to propose for approval."""

    invoice: Invoice
    tier: Tier
    draft: Draft


@dataclass(frozen=True)
class Skip:
    """An overdue invoice we intentionally do not chase this run."""

    invoice: Invoice
    reason: str


def plan_chase(
    invoices: list[Invoice],
    prior_by_invoice: dict[str, list[date]],
    *,
    now: date,
    cfg: PayupConfig | None = None,
) -> list[Action | Skip]:
    """Build the chase plan.

    `prior_by_invoice` maps invoice_number -> list of prior reminder dates
    (from Gmail). It drives dedupe (min_gap) and tier escalation (prior count).
    """
    cfg = cfg or PayupConfig()
    plan: list[Action | Skip] = []

    for inv in invoices:
        priors = sorted(prior_by_invoice.get(inv.invoice_number, []))
        prior_count = len(priors)
        days_overdue = (now - inv.due_date).days
        days_since_last = (now - priors[-1]).days if priors else None

        tier = select_tier(days_overdue, prior_count, days_since_last, cfg.escalation)
        if tier is None:
            reason = (
                "within min_gap" if priors else "not yet due"
            ) if days_overdue >= 1 else "not yet due"
            if priors and days_since_last is not None and days_since_last < cfg.escalation.min_gap_days:
                reason = "within min_gap"
            plan.append(Skip(invoice=inv, reason=reason))
            continue

        draft = render_email(inv, tier, cfg.templating)
        plan.append(Action(invoice=inv, tier=tier, draft=draft))

    return plan
