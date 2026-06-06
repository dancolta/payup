"""Source registry + end-to-end build_plan through the QuickBooks source."""

from datetime import date

import pytest
from payup.lib import quickbooks, runner, wave
from payup.lib.planner import Action
from payup.lib.sources import DEFAULT_SOURCE, get_source

from .conftest import FakeGmail, load_fixture

NOW = date(2026, 6, 4)


def test_default_source_is_quickbooks():
    assert DEFAULT_SOURCE == "quickbooks"
    assert get_source(None) is quickbooks.list_overdue_unpaid


def test_get_source_wave():
    assert get_source("wave") is wave.list_overdue_unpaid


def test_get_source_unknown_raises():
    with pytest.raises(ValueError):
        get_source("xero")


def test_build_plan_through_quickbooks(monkeypatch):
    data = load_fixture("qbo_overdue.json")
    monkeypatch.setattr(quickbooks, "_query", lambda token, realm, query, *, host: data)
    fake = FakeGmail(search_results=[])

    plan = runner.build_plan(
        now=NOW,
        token="qbo-access-token",
        business_id="4620816365000000000",
        source_name="quickbooks",
        gmail_transport=fake,
    )
    actions = [p for p in plan if isinstance(p, Action)]
    assert {a.invoice.invoice_number for a in actions} == {"1001", "1051", "0998"}
    # nothing sent just by planning
    assert fake.sent == []
