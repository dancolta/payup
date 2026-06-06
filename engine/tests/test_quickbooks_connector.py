"""QuickBooks connector: parsing, filtering, pagination, auth errors.

Mock seam is quickbooks._query; net is never reached.
"""

from datetime import date

import pytest
from payup.lib import net, quickbooks
from payup.lib.quickbooks import QBOAPIError, QBOAuthError, list_overdue_unpaid

from .conftest import load_fixture

NOW = date(2026, 6, 4)


def _mock(monkeypatch, fixture="qbo_overdue.json"):
    data = load_fixture(fixture)
    monkeypatch.setattr(quickbooks, "_query", lambda token, realm, query, *, host: data)


def test_parses_overdue_unpaid(monkeypatch):
    _mock(monkeypatch)
    invoices = list_overdue_unpaid("tok", "123", now=NOW)
    assert {i.invoice_number for i in invoices} == {"1001", "1051", "0998"}


def test_balance_to_cents_and_email(monkeypatch):
    _mock(monkeypatch)
    invoices = list_overdue_unpaid("tok", "123", now=NOW)
    acme = next(i for i in invoices if i.invoice_number == "1001")
    assert acme.amount_due_cents == 240000
    assert acme.customer_email == "ap@acmestudio.example"
    assert acme.customer_name == "Acme Studio"


def test_paid_invoice_excluded(monkeypatch):
    _mock(monkeypatch)
    invoices = list_overdue_unpaid("tok", "123", now=NOW)
    assert all(i.invoice_number != "2000" for i in invoices)  # Balance 0


def test_not_yet_due_excluded(monkeypatch):
    _mock(monkeypatch)
    invoices = list_overdue_unpaid("tok", "123", now=NOW)
    assert all(i.invoice_number != "3000" for i in invoices)  # due 2026-07-01


def test_empty(monkeypatch):
    monkeypatch.setattr(
        quickbooks, "_query", lambda token, realm, query, *, host: {"QueryResponse": {}}
    )
    assert list_overdue_unpaid("tok", "123", now=NOW) == []


def test_pagination(monkeypatch):
    monkeypatch.setattr(quickbooks, "_PAGE_SIZE", 1)

    def fake_query(token, realm, query, *, host):
        # serve one invoice per STARTPOSITION, empty after position 2
        if "STARTPOSITION 1 " in query:
            return {"QueryResponse": {"Invoice": [
                {"Id": "1", "DocNumber": "7001", "DueDate": "2026-05-10", "Balance": 300.0,
                 "CurrencyRef": {"value": "USD"}, "CustomerRef": {"name": "P1"},
                 "BillEmail": {"Address": "p1@x.example"}}]}}
        if "STARTPOSITION 2 " in query:
            return {"QueryResponse": {"Invoice": [
                {"Id": "2", "DocNumber": "7002", "DueDate": "2026-05-11", "Balance": 450.0,
                 "CurrencyRef": {"value": "USD"}, "CustomerRef": {"name": "P2"},
                 "BillEmail": {"Address": "p2@x.example"}}]}}
        return {"QueryResponse": {"Invoice": []}}

    monkeypatch.setattr(quickbooks, "_query", fake_query)
    invoices = list_overdue_unpaid("tok", "123", now=NOW)
    assert {i.invoice_number for i in invoices} == {"7001", "7002"}


def test_auth_error_translated(monkeypatch):
    def boom(url, headers, *, params=None, timeout=30.0):
        raise net.HTTPStatusError(401, "unauthorized")

    monkeypatch.setattr(net, "get_json", boom)
    with pytest.raises(QBOAuthError):
        list_overdue_unpaid("bad", "123", now=NOW)


def test_fault_payload_is_api_error(monkeypatch):
    monkeypatch.setattr(
        quickbooks,
        "_query",
        lambda *a, **k: (_ for _ in ()).throw(QBOAPIError("fault")),
    )
    with pytest.raises(QBOAPIError):
        list_overdue_unpaid("tok", "123", now=NOW)


def test_quickbooks_is_read_only_for_invoice_data():
    import inspect

    src = inspect.getsource(quickbooks)
    # Invoice data is fetched via GET only; we never POST/patch invoices.
    assert "get_json" in src
    assert "post_json" not in src
    for verb in ("createpayment", "payinvoice", "sparseupdate", "delete"):
        assert verb not in src.lower()
