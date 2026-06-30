"""Rendering helpers for the batch table and confirmation messages.

Plain text / lightweight markdown so it reads well in both Slack and a Claude
Code chat. No em dashes (enforced by test).
"""

from __future__ import annotations

from .planner import Action, Skip
from .templating import _format_amount

__all__ = ["render_batch", "render_confirmation", "render_draft_confirmation"]


def render_batch(plan: list[Action | Skip], *, now=None) -> str:
    """Render the proposed chase batch for approval, plus a separate list of
    invoices already nudged (held inside the no-nag window) so the two never get
    confused. The 'already nudged' list shows when each one was last sent."""
    actions = [p for p in plan if isinstance(p, Action)]
    nudged = [p for p in plan if isinstance(p, Skip) and p.last_sent is not None]

    if not actions and not nudged:
        return "No invoices to chase right now."

    lines: list[str] = []
    if actions:
        lines.append(f"PayUp found {len(actions)} invoice(s) ready to chase. Reply to approve.")
        lines.append("")
        for i, act in enumerate(actions, start=1):
            inv = act.invoice
            amount = _format_amount(inv.amount_due_cents, inv.currency)
            days = (now - inv.due_date).days if now else "?"
            lines.append(
                f"{i}. {inv.customer_name} | #{inv.invoice_number} | {amount} "
                f"| {act.tier.value} | {days}d late"
            )
        lines.append("")
        lines.append('Reply: "send all", "send 1 and 3", "draft all", or "skip Delta".')
    else:
        lines.append("Nothing ready to chase right now.")

    if nudged:
        lines.append("")
        lines.append(
            f"Already nudged, waiting out the no-nag gap ({len(nudged)}, not in the list above):"
        )
        for s in nudged:
            inv = s.invoice
            if now and s.last_sent is not None:
                ago = (now - s.last_sent).days
                when = "today" if ago <= 0 else f"{ago}d ago"
                lines.append(f"- {inv.customer_name} | #{inv.invoice_number} | last nudged {when}")
            else:
                lines.append(f"- {inv.customer_name} | #{inv.invoice_number}")

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


def render_draft_confirmation(drafted: list[str], skipped: list[str]) -> str:
    """Render the post-draft summary. Mirrors render_confirmation, but for drafts
    saved to Gmail (not sent). No em dashes."""
    parts = []
    if drafted:
        parts.append(f"Drafted {len(drafted)} reminder(s): {', '.join(drafted)}.")
    else:
        parts.append("Drafted 0 reminders.")
    if skipped:
        parts.append(f"Skipped {len(skipped)}: {', '.join(skipped)}.")
    return " ".join(parts)
