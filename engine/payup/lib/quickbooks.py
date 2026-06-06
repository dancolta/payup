"""QuickBooks Online connector. Read-only: we query invoices, we never mutate.

Primary source of truth (Wave is geo-locked to US/Canada, so QBO is the default).
QBO tells us who is overdue AND still unpaid; a paid invoice has Balance 0 and
drops out, which is how chasing resolves itself.

REST + OAuth 2.0 bearer token. The query endpoint is a GET with a SQL-like query.
Tests mock `_query`, so no network is touched in CI.

Auth note: QBO access tokens expire hourly. For unattended running, the bot
refreshes via `refresh_access_token` (refresh tokens last ~100 days). For a
one-off Gate 0 check, a short-lived access token from Intuit's OAuth Playground
is enough.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from . import net
from .models import Invoice

__all__ = [
    "QBOError",
    "QBOAuthError",
    "QBOAPIError",
    "list_overdue_unpaid",
    "refresh_access_token",
    "SANDBOX_HOST",
    "PRODUCTION_HOST",
]

SANDBOX_HOST = "sandbox-quickbooks.api.intuit.com"
PRODUCTION_HOST = "quickbooks.api.intuit.com"
TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_MINOR_VERSION = "70"
_PAGE_SIZE = 100


class QBOError(Exception):
    """Base QuickBooks connector error."""


class QBOAuthError(QBOError):
    """Token rejected (HTTP 401). The access token likely expired."""


class QBOAPIError(QBOError):
    """QuickBooks returned a non-auth error or a Fault payload."""


def _query(access_token: str, realm_id: str, query: str, *, host: str) -> dict:
    """Run a QBO query (GET). Single mock seam for tests."""
    url = f"https://{host}/v3/company/{realm_id}/query"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = net.get_json(
            url, headers, params={"query": query, "minorversion": _MINOR_VERSION}
        )
    except net.HTTPStatusError as exc:
        if exc.status == 401:
            raise QBOAuthError("QuickBooks rejected the access token (401, likely expired)") from exc
        raise QBOAPIError(f"QuickBooks HTTP error {exc.status}") from exc
    except net.NetError as exc:
        raise QBOAPIError(str(exc)) from exc
    if resp.get("Fault") or resp.get("fault"):
        raise QBOAPIError(str(resp.get("Fault") or resp.get("fault")))
    return resp


def _to_cents(value) -> int:
    if value is None:
        return 0
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return 0


def _parse_invoice(node: dict) -> Invoice:
    customer = node.get("CustomerRef") or {}
    bill_email = node.get("BillEmail") or {}
    currency = node.get("CurrencyRef") or {}
    balance_cents = _to_cents(node.get("Balance"))
    due_raw = node.get("DueDate") or ""
    try:
        due = date.fromisoformat(due_raw)
    except ValueError:
        due = date.max
    return Invoice(
        invoice_id=str(node.get("Id", "")),
        invoice_number=str(node.get("DocNumber") or node.get("Id", "")),
        customer_name=str(customer.get("name", "")),
        customer_email=str(bill_email.get("Address", "")),
        amount_due_cents=balance_cents,
        currency=str(currency.get("value", "USD")),
        due_date=due,
        # QBO has no single "paid" enum; Balance 0 means settled.
        status="PAID" if balance_cents <= 0 else "OPEN",
    )


def list_overdue_unpaid(
    access_token: str,
    realm_id: str,
    *,
    now: date,
    host: str = SANDBOX_HOST,
) -> list[Invoice]:
    """Return invoices past due AND still unpaid (Balance > 0), across all pages."""
    out: list[Invoice] = []
    start = 1
    iso = now.isoformat()
    while True:
        query = (
            "SELECT * FROM Invoice "
            f"WHERE Balance > '0' AND DueDate < '{iso}' "
            f"STARTPOSITION {start} MAXRESULTS {_PAGE_SIZE}"
        )
        resp = _query(access_token, realm_id, query, host=host)
        qr = resp.get("QueryResponse") or {}
        rows = qr.get("Invoice") or []
        for node in rows:
            inv = _parse_invoice(node)
            if inv.is_paid or inv.due_date >= now:
                continue
            out.append(inv)
        if len(rows) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return out


def refresh_access_token(
    refresh_token: str, client_id: str, client_secret: str
) -> dict:  # pragma: no cover - exercised live, not in unit tests
    """Exchange a refresh token for a fresh access token (OAuth 2.0).

    Returns the raw token payload (access_token, refresh_token, expires_in, ...).
    """
    import base64

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    headers = {"Authorization": f"Basic {basic}"}
    try:
        return net.post_form(
            TOKEN_ENDPOINT,
            headers,
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    except net.HTTPStatusError as exc:
        raise QBOAuthError(f"token refresh failed ({exc.status})") from exc
