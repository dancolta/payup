"""Reminder email templating. Pure, deterministic, tone-locked.

The shipped draft is fully deterministic (no LLM, no API key). Optional polish
can be layered on later by the bot, but the safety properties live here:

  * the subject ALWAYS contains the invoice number (the Gmail dedupe key),
  * no tier may contain legal / collection / threat language,
  * no em dashes anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from .escalation import Tier
from .models import Invoice

__all__ = ["Draft", "render_email", "BLACKLIST", "TemplatingConfig"]

# Words that would turn a polite reminder into a threat or imply collections /
# legal action. The build fails if any appear in a rendered draft.
BLACKLIST: frozenset[str] = frozenset(
    {
        "legal",
        "lawyer",
        "attorney",
        "court",
        "sue",
        "lawsuit",
        "litigation",
        "collections",
        "collection agency",
        "debt collector",
        "garnish",
        "garnishment",
        "penalty",
        "penalties",
        "demand letter",
        "cease",
        "small claims",
        "credit bureau",
    }
)


@dataclass(frozen=True)
class TemplatingConfig:
    sender_name: str = "Accounts"
    business_name: str = "our team"


@dataclass(frozen=True)
class Draft:
    to: str
    subject: str
    body: str
    invoice_id: str
    invoice_number: str
    tier: str


def _format_amount(cents: int, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "$", "AUD": "$"}.get(
        currency.upper(), ""
    )
    dollars = cents / 100
    return f"{symbol}{dollars:,.2f} {currency.upper()}".strip()


def _subject(inv: Invoice, tier: Tier) -> str:
    # Invoice number is mandatory in the subject: it is the dedupe search key.
    base = f"Invoice #{inv.invoice_number}"
    if tier is Tier.GENTLE:
        return f"Reminder: {base}"
    if tier is Tier.FIRM:
        return f"Payment due: {base}"
    return f"Final reminder: {base}"


def _body(inv: Invoice, tier: Tier, cfg: TemplatingConfig) -> str:
    amount = _format_amount(inv.amount_due_cents, inv.currency)
    due = inv.due_date.isoformat()
    name = inv.customer_name or "there"
    sign = f"{cfg.sender_name}\n{cfg.business_name}"

    if tier is Tier.GENTLE:
        return (
            f"Hi {name},\n\n"
            f"Just a friendly heads up that invoice #{inv.invoice_number} for {amount} "
            f"was due on {due} and looks still open on our side.\n\n"
            f"It may have slipped through. If it is already on its way, thank you and "
            f"please ignore this note. Otherwise, a quick update on timing would be great.\n\n"
            f"Thanks so much,\n{sign}"
        )
    if tier is Tier.FIRM:
        return (
            f"Hi {name},\n\n"
            f"Following up on invoice #{inv.invoice_number} for {amount}, which was due "
            f"on {due} and is now past due.\n\n"
            f"Could you let me know the expected payment date? If anything is blocking "
            f"it on your end, tell me and I will help sort it out.\n\n"
            f"Appreciate your help,\n{sign}"
        )
    return (
        f"Hi {name},\n\n"
        f"This is a final reminder that invoice #{inv.invoice_number} for {amount}, "
        f"due on {due}, remains unpaid.\n\n"
        f"Please arrange payment, or reply with a firm date so we can close this out. "
        f"If you have already paid, let me know and I will confirm on our side.\n\n"
        f"Thank you,\n{sign}"
    )


def render_email(inv: Invoice, tier: Tier, cfg: TemplatingConfig | None = None) -> Draft:
    cfg = cfg or TemplatingConfig()
    subject = _subject(inv, tier)
    body = _body(inv, tier, cfg)
    return Draft(
        to=inv.customer_email,
        subject=subject,
        body=body,
        invoice_id=inv.invoice_id,
        invoice_number=inv.invoice_number,
        tier=tier.value,
    )
