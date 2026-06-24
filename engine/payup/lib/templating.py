"""Reminder email templating. Pure, deterministic, tone-locked.

The shipped draft is fully deterministic (no LLM, no API key). Optional polish
can be layered on later by the bot, but the safety properties live here:

  * the subject ALWAYS contains the invoice number (the Gmail dedupe key),
  * no tier may contain legal / collection / threat language,
  * no em dashes anywhere.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

from .escalation import Tier
from .models import Invoice

__all__ = [
    "Draft",
    "render_email",
    "BLACKLIST",
    "TemplatingConfig",
    "TemplateSet",
    "TemplatingError",
]

# The em dash is banned in rendered output. Built via codepoint (U+2014) so this
# source file itself stays em-dash-free (the no-em-dash scan covers engine/payup).
EM_DASH = chr(0x2014)

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


class TemplatingError(ValueError):
    """Raised when a rendered draft violates a safety property: a blacklist term,
    an em dash, or a missing invoice number in the subject (the dedupe key)."""


# Built-in default templates. These reproduce today's exact copy from _subject /
# _body, expressed as format strings so custom templates share one render path.
# Placeholders: {customer_name} {invoice_number} {amount} {due_date}
#               {sender_name} {business_name}
_DEFAULT_SUBJECTS: dict[str, str] = {
    "gentle": "Reminder: Invoice #{invoice_number}",
    "firm": "Payment due: Invoice #{invoice_number}",
    "final": "Final reminder: Invoice #{invoice_number}",
}
_DEFAULT_BODIES: dict[str, str] = {
    "gentle": (
        "Hi {customer_name},\n\n"
        "Just a friendly heads up that invoice #{invoice_number} for {amount} "
        "was due on {due_date} and looks still open on our side.\n\n"
        "It may have slipped through. If it is already on its way, thank you and "
        "please ignore this note. Otherwise, a quick update on timing would be great.\n\n"
        "Thanks so much,\n{sender_name}\n{business_name}"
    ),
    "firm": (
        "Hi {customer_name},\n\n"
        "Following up on invoice #{invoice_number} for {amount}, which was due "
        "on {due_date} and is now past due.\n\n"
        "Could you let me know the expected payment date? If anything is blocking "
        "it on your end, tell me and I will help sort it out.\n\n"
        "Appreciate your help,\n{sender_name}\n{business_name}"
    ),
    "final": (
        "Hi {customer_name},\n\n"
        "This is a final reminder that invoice #{invoice_number} for {amount}, "
        "due on {due_date}, remains unpaid.\n\n"
        "Please arrange payment, or reply with a firm date so we can close this out. "
        "If you have already paid, let me know and I will confirm on our side.\n\n"
        "Thank you,\n{sender_name}\n{business_name}"
    ),
}


class _SafeFormatter(string.Formatter):
    """A str.format that leaves unknown placeholders untouched instead of raising,
    so a custom template with a stray {field} never crashes a chase run."""

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)


_FORMATTER = _SafeFormatter()


@dataclass(frozen=True)
class TemplateSet:
    """Per-tier subject + body format strings. Each field falls back to the
    built-in default when None, so a partial custom file overrides only what it
    sets."""

    gentle_subject: str | None = None
    gentle_body: str | None = None
    firm_subject: str | None = None
    firm_body: str | None = None
    final_subject: str | None = None
    final_body: str | None = None

    def subject_for(self, tier: str) -> str:
        return getattr(self, f"{tier}_subject") or _DEFAULT_SUBJECTS[tier]

    def body_for(self, tier: str) -> str:
        return getattr(self, f"{tier}_body") or _DEFAULT_BODIES[tier]

    @classmethod
    def load(cls, path: str | None = None) -> TemplateSet:
        """Load from a YAML file if pyyaml + path are available, else defaults.
        Mirrors EscalationConfig.load exactly: no path / import failure /
        FileNotFound all fall back to the built-in defaults, and any field a file
        omits keeps its built-in default (per-field fallback)."""
        if not path:
            return cls()
        try:
            import yaml  # optional; only present in the bot/dev extras
        except Exception:
            return cls()
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            return cls()

        def _tier(name: str, field: str):
            block = data.get(name) or {}
            val = block.get(field)
            return str(val) if val is not None else None

        return cls(
            gentle_subject=_tier("gentle", "subject"),
            gentle_body=_tier("gentle", "body"),
            firm_subject=_tier("firm", "subject"),
            firm_body=_tier("firm", "body"),
            final_subject=_tier("final", "subject"),
            final_body=_tier("final", "body"),
        )


@dataclass(frozen=True)
class TemplatingConfig:
    sender_name: str = "Accounts"
    business_name: str = "our team"
    templates: TemplateSet | None = None


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


def _assert_clean(subject: str, body: str, invoice_number: str) -> None:
    """Runtime safety guard, enforced on EVERY rendered draft (default or custom
    template). Raises TemplatingError on a blacklist term, an em dash, or a
    subject missing the invoice number (the non-negotiable dedupe key)."""
    haystack = (subject + " " + body).lower()
    for term in BLACKLIST:
        # Word-boundary match so benign words that merely contain a blacklisted
        # term as a substring (e.g. "issue"/"pursue" contain "sue", "deceased"
        # contains "cease") do not falsely trip a legitimate custom template.
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            raise TemplatingError(f"blacklisted term {term!r} in rendered draft")
    if EM_DASH in subject or EM_DASH in body:
        raise TemplatingError("em dash in rendered draft")
    if not invoice_number or invoice_number not in subject:
        raise TemplatingError(
            f"invoice number {invoice_number!r} missing from subject (dedupe key)"
        )


def render_email(inv: Invoice, tier: Tier, cfg: TemplatingConfig | None = None) -> Draft:
    cfg = cfg or TemplatingConfig()
    templates = cfg.templates or TemplateSet()
    fields = {
        "customer_name": inv.customer_name or "there",
        "invoice_number": inv.invoice_number,
        "amount": _format_amount(inv.amount_due_cents, inv.currency),
        "due_date": inv.due_date.isoformat(),
        "sender_name": cfg.sender_name,
        "business_name": cfg.business_name,
    }
    subject = _FORMATTER.format(templates.subject_for(tier.value), **fields)
    body = _FORMATTER.format(templates.body_for(tier.value), **fields)
    _assert_clean(subject, body, inv.invoice_number)
    return Draft(
        to=inv.customer_email,
        subject=subject,
        body=body,
        invoice_id=inv.invoice_id,
        invoice_number=inv.invoice_number,
        tier=tier.value,
    )
