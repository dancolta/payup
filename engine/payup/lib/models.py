"""Shared domain types. Source connectors (Wave, QuickBooks, ...) all parse into
this one `Invoice` shape, so everything downstream (planner, templating, bot) is
connector-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = ["Invoice", "PAID_STATUSES"]

# Status strings that mean "settled, stop chasing". Connectors normalise to these.
PAID_STATUSES = {"PAID"}


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    invoice_number: str
    customer_name: str
    customer_email: str
    amount_due_cents: int
    currency: str
    due_date: date
    status: str

    @property
    def is_paid(self) -> bool:
        return self.status.upper() in PAID_STATUSES or self.amount_due_cents <= 0
