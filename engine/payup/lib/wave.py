"""Wave Accounting connector. Read-only: we list invoices, we never mutate.

Source of truth #1. Wave tells us who is overdue AND still unpaid. When an
invoice is paid in Wave it simply drops out of `list_overdue_unpaid`, which is
how chasing resolves itself (no guesses from email text).

GraphQL only, single bearer token. Tests mock `_post_graphql`, so no network is
touched in CI.

Note: field shape follows Wave's documented public GraphQL schema. Gate 0 (live
sandbox verification) confirms exact field availability before this is trusted
against a real business; until then the shipped fixtures encode that shape.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from . import net
from .models import Invoice

__all__ = [
    "Invoice",
    "WaveError",
    "WaveAuthError",
    "WaveAPIError",
    "list_overdue_unpaid",
    "ENDPOINT",
]

ENDPOINT = "https://gql.waveapps.com/graphql/public"

_PAGE_SIZE = 50

_OVERDUE_QUERY = """
query OverdueInvoices($businessId: ID!, $page: Int!, $pageSize: Int!) {
  business(id: $businessId) {
    id
    invoices(page: $page, pageSize: $pageSize, status: UNPAID) {
      pageInfo { currentPage totalPages totalCount }
      edges {
        node {
          id
          invoiceNumber
          status
          dueDate
          amountDue { value }
          currency { code }
          customer { name email }
        }
      }
    }
  }
}
""".strip()


class WaveError(Exception):
    """Base Wave connector error."""


class WaveAuthError(WaveError):
    """Token rejected (HTTP 401)."""


class WaveAPIError(WaveError):
    """Wave returned a non-auth error or a GraphQL `errors` array."""


def _post_graphql(token: str, query: str, variables: dict) -> dict:
    """POST a GraphQL query. Translates transport/status errors to Wave errors.

    This is the single mock seam for tests.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = net.post_json(ENDPOINT, headers, {"query": query, "variables": variables})
    except net.HTTPStatusError as exc:
        if exc.status == 401:
            raise WaveAuthError("Wave rejected the API token (401)") from exc
        raise WaveAPIError(f"Wave HTTP error {exc.status}") from exc
    except net.NetError as exc:
        raise WaveAPIError(str(exc)) from exc
    if resp.get("errors"):
        raise WaveAPIError(str(resp["errors"]))
    return resp.get("data") or {}


def _to_cents(value: str | int | float | None) -> int:
    if value is None:
        return 0
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return 0


def _parse_invoice(node: dict) -> Invoice:
    customer = node.get("customer") or {}
    amount = node.get("amountDue") or {}
    currency = node.get("currency") or {}
    due_raw = node.get("dueDate") or ""
    try:
        due = date.fromisoformat(due_raw)
    except ValueError:
        due = date.max
    return Invoice(
        invoice_id=str(node.get("id", "")),
        invoice_number=str(node.get("invoiceNumber", "")),
        customer_name=str(customer.get("name", "")),
        customer_email=str(customer.get("email", "")),
        amount_due_cents=_to_cents(amount.get("value")),
        currency=str(currency.get("code", "USD")),
        due_date=due,
        status=str(node.get("status", "")),
    )


def list_overdue_unpaid(token: str, business_id: str, *, now: date) -> list[Invoice]:
    """Return invoices that are past due AND still unpaid, across all pages.

    Paid invoices and not-yet-due invoices are excluded. Empty result -> [].
    """
    out: list[Invoice] = []
    page = 1
    while True:
        data = _post_graphql(
            token,
            _OVERDUE_QUERY,
            {"businessId": business_id, "page": page, "pageSize": _PAGE_SIZE},
        )
        # Fail closed: an unknown or inaccessible business id comes back as a
        # null `business` (not an error). Treat that as a misconfiguration, not
        # as "nothing overdue", so a wrong WAVE_BUSINESS_ID never reads as all-paid.
        if "business" in data and data["business"] is None:
            raise WaveAPIError(
                f"Wave returned no business for id {business_id!r} "
                "(not found, or the token lacks access)"
            )
        business = data.get("business") or {}
        invoices = business.get("invoices") or {}
        edges = invoices.get("edges") or []
        for edge in edges:
            node = edge.get("node") or {}
            inv = _parse_invoice(node)
            if inv.is_paid:
                continue
            if inv.due_date >= now:
                continue
            out.append(inv)
        page_info = invoices.get("pageInfo") or {}
        current = int(page_info.get("currentPage", page))
        total = int(page_info.get("totalPages", current))
        if current >= total:
            break
        page = current + 1
    return out
