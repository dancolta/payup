"""Stories B1/B2 — Wave connector parsing, filtering, pagination, auth errors.

The mock seam is wave._post_graphql; net is never reached.
"""

from datetime import date

import pytest

from payup.lib import net, wave
from payup.lib.wave import WaveAuthError, WaveError, list_overdue_unpaid

from .conftest import load_fixture

NOW = date(2026, 6, 4)


def _mock_single_page(monkeypatch, fixture_name):
    data = load_fixture(fixture_name)["data"]
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: data)


def test_parses_overdue_unpaid(monkeypatch):
    _mock_single_page(monkeypatch, "wave_overdue.json")
    invoices = list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
    numbers = {i.invoice_number for i in invoices}
    # 1001, 1051, 0998 are overdue+unpaid; 2000 paid and 3000 not-yet-due excluded
    assert numbers == {"1001", "1051", "0998"}


def test_amount_parsed_to_cents(monkeypatch):
    _mock_single_page(monkeypatch, "wave_overdue.json")
    invoices = list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
    acme = next(i for i in invoices if i.invoice_number == "1001")
    assert acme.amount_due_cents == 240000
    assert acme.customer_email == "ap@acmestudio.example"


def test_paid_invoice_excluded(monkeypatch):
    _mock_single_page(monkeypatch, "wave_overdue.json")
    invoices = list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
    assert all(i.invoice_number != "2000" for i in invoices)


def test_not_yet_due_excluded(monkeypatch):
    _mock_single_page(monkeypatch, "wave_overdue.json")
    invoices = list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
    assert all(i.invoice_number != "3000" for i in invoices)


def test_empty_returns_empty(monkeypatch):
    _mock_single_page(monkeypatch, "wave_empty.json")
    assert list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW) == []


def test_pagination_concatenates(monkeypatch):
    p1 = load_fixture("wave_paginated_p1.json")["data"]
    p2 = load_fixture("wave_paginated_p2.json")["data"]

    def fake_post(token, query, variables):
        return p1 if variables["page"] == 1 else p2

    monkeypatch.setattr(wave, "_post_graphql", fake_post)
    invoices = list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
    assert {i.invoice_number for i in invoices} == {"7001", "7002"}


def test_auth_error_translated(monkeypatch):
    def boom(url, headers, payload, *, timeout=30.0):
        raise net.HTTPStatusError(401, "unauthorized")

    monkeypatch.setattr(net, "post_json", boom)
    with pytest.raises(WaveAuthError):
        list_overdue_unpaid("bad", "SANDBOX-DEMO-0001", now=NOW)


def test_generic_http_error_is_wave_error(monkeypatch):
    def boom(url, headers, payload, *, timeout=30.0):
        raise net.HTTPStatusError(500, "server error")

    monkeypatch.setattr(net, "post_json", boom)
    with pytest.raises(WaveError):
        list_overdue_unpaid("tok", "SANDBOX-DEMO-0001", now=NOW)
