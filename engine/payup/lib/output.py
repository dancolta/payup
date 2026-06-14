"""Rendering helpers for the batch table and confirmation messages.

Plain text / lightweight markdown so it reads well in both Slack and a Claude
Code chat. No em dashes (enforced by test).
"""

from __future__ import annotations

from .planner import Action, Skip
from .templating import _format_amount

__all__ = ["render_batch", "render_confirmation"]


def render_batch(plan: list[Action | Skip], *, now=None) -> str:
    """Render the proposed chase batch as a numbered list for approval."""
    actions = [p for p in plan if isinstance(p, Action)]
    skips = [p for p in plan if isinstance(p, Skip)]

    if not actions:
        msg = "No invoices to chase right now."
        if skips:
            msg += f" ({len(skips)} overdue but skipped: within the no-nag window.)"
        return msg

    lines = [f"PayUp found {len(actions)} invoice(s) ready to chase. Reply to approve.", ""]
    for i, act in enumerate(actions, start=1):
        inv = act.invoice
        amount = _format_amount(inv.amount_due_cents, inv.currency)
        days = (now - inv.due_date).days if now else "?"
        lines.append(
            f"{i}. {inv.customer_name} | #{inv.invoice_number} | {amount} "
            f"| {act.tier.value} | {days}d late"
        )
    lines.append("")
    lines.append('Reply: "send all", "send 1 and 3", "skip Delta", or "show overdue".')
    if skips:
        lines.append(f"({len(skips)} other overdue invoice(s) skipped: still inside the no-nag window.)")
    return "\n".join(lines)


def render_confirmation(sent: list[str], skipped: list[str]) -> str:
    """Render the post-send summary."""
    parts = []
    if sent:
        parts.append(f"Sent {len(sent)} reminder(s): {', '.join(sent)}.")
    else:
        parts.append("Sent 0 reminders.")
    if skipped:
        parts.append(f"Skipped {len(skipped)}: {', '.join(skipped)}.")
    return " ".join(parts)
