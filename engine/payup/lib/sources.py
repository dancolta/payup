"""Invoice source registry. Maps a source name to its `list_overdue_unpaid`.

All connectors share the same signature `(token, business_id, *, now) -> [Invoice]`
and the same `Invoice` shape, so the rest of the engine is source-agnostic.

Default is QuickBooks (Wave is US/Canada-only and geo-locks most users). Wave
stays available as a selectable alternative for US/CA businesses.
"""

from __future__ import annotations

from . import quickbooks, wave

__all__ = ["get_source", "DEFAULT_SOURCE", "SOURCES"]

DEFAULT_SOURCE = "quickbooks"

SOURCES = {
    "quickbooks": quickbooks.list_overdue_unpaid,
    "qbo": quickbooks.list_overdue_unpaid,
    "wave": wave.list_overdue_unpaid,
}


def get_source(name: str | None):
    """Return the `list_overdue_unpaid` callable for the named source."""
    key = (name or DEFAULT_SOURCE).lower()
    if key not in SOURCES:
        raise ValueError(f"unknown invoice source {name!r}. Known: {sorted(SOURCES)}")
    return SOURCES[key]
