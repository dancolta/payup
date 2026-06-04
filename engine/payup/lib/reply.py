"""Reply classification. Pure. Context only, never a resolve signal.

This labels an inbound reply so the bot can surface useful context ("they say
they paid", "they're disputing it") in Slack. It deliberately does NOT decide
whether to stop chasing: resolve is owned entirely by Wave invoice status. A
client saying "paid it" while Wave still shows unpaid must NOT silence the chase.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["Label", "classify_reply"]


class Label(str, Enum):
    PAID = "paid"
    WILL_PAY = "will_pay"
    DISPUTE = "dispute"
    SILENCE = "silence"
    UNKNOWN = "unknown"


_PAID_HINTS = (
    "paid it",
    "have paid",
    "already paid",
    "payment sent",
    "sent payment",
    "transferred",
    "wired",
    "paid the invoice",
    "paid yesterday",
    "settled",
)
_WILL_PAY_HINTS = (
    "will pay",
    "will send",
    "pay by",
    "pay on",
    "pay it friday",
    "pay next week",
    "schedule the payment",
    "processing the payment",
    "by end of",
    "eod",
    "tomorrow",
)
_DISPUTE_HINTS = (
    "this is wrong",
    "incorrect",
    "dispute",
    "did not order",
    "never received",
    "not our invoice",
    "overcharged",
    "wrong amount",
    "already disputed",
    "do not owe",
    "don't owe",
)


def _contains(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def classify_reply(text: str) -> tuple[Label, float]:
    """Return (label, confidence in 0..1). Never used to resolve an invoice."""
    if not text or not text.strip():
        return Label.SILENCE, 1.0
    t = text.lower()

    # Dispute takes precedence: if someone contests, never read it as "paid".
    if _contains(t, _DISPUTE_HINTS):
        return Label.DISPUTE, 0.85
    if _contains(t, _PAID_HINTS):
        # High confidence only when the claim is unambiguous past tense.
        conf = 0.85 if ("already paid" in t or "payment sent" in t or "paid it" in t) else 0.7
        return Label.PAID, conf
    if _contains(t, _WILL_PAY_HINTS):
        return Label.WILL_PAY, 0.75
    return Label.UNKNOWN, 0.4
