"""Story F1 (engine half) — end-to-end chase loop, no-double-chase, resolve-on-paid.

Full path with Wave + Gmail both mocked: fetch -> prior -> plan -> approve -> send.
"""

import copy
from datetime import date

from payup.lib import runner, wave
from payup.lib.planner import Action, Skip

from .conftest import FakeGmail, epoch_ms, load_fixture

NOW = date(2026, 6, 4)


def _wire_wave(monkeypatch, fixture="wave_overdue.json", data=None):
    payload = data if data is not None else load_fixture(fixture)["data"]
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: payload)


def test_full_loop_send_two_skip_one(monkeypatch):
    _wire_wave(monkeypatch)
    fake = FakeGmail(search_results=[])  # no prior reminders for anyone

    plan = runner.build_plan(
        now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake
    )
    actions = [p for p in plan if isinstance(p, Action)]
    assert len(actions) == 3  # 1001, 1051, 0998

    # Approve two of the three (Acme #1001 + Delta #0998), skip Bryce #1051.
    approved = {a.invoice.invoice_id for a in actions if a.invoice.invoice_number in {"1001", "0998"}}
    sent, skipped = runner.execute(plan, approved, gmail_transport=fake, dry_run=False)

    assert sorted(sent) == ["0998", "1001"]
    assert skipped == ["1051"]
    assert len(fake.sent) == 2  # exactly two real sends


def test_nothing_sends_without_approval(monkeypatch):
    _wire_wave(monkeypatch)
    fake = FakeGmail(search_results=[])
    plan = runner.build_plan(now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake)
    sent, skipped = runner.execute(plan, approved_ids=set(), gmail_transport=fake, dry_run=False)
    assert sent == []
    assert fake.sent == []  # zero sends with an empty approval set


def test_no_double_chase_within_gap(monkeypatch):
    _wire_wave(monkeypatch)

    # Gmail reports a reminder for invoice 1001 sent 2 days ago -> must be skipped.
    class PerInvoiceGmail(FakeGmail):
        def search(self, query: str):
            self.last_query = query
            if "1001" in query:
                return [{"id": "prev", "internalDate": epoch_ms("2026-06-02T09:00:00")}]
            return []

    fake = PerInvoiceGmail()
    plan = runner.build_plan(now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake)
    by_num = {p.invoice.invoice_number: p for p in plan}
    assert isinstance(by_num["1001"], Skip)  # chased 2 days ago, within min_gap
    assert isinstance(by_num["0998"], Action)  # never chased


def test_resolve_on_paid(monkeypatch):
    # Mark Acme #1001 as PAID in the Wave data -> it must drop out entirely.
    data = copy.deepcopy(load_fixture("wave_overdue.json")["data"])
    for edge in data["business"]["invoices"]["edges"]:
        if edge["node"]["invoiceNumber"] == "1001":
            edge["node"]["status"] = "PAID"
            edge["node"]["amountDue"]["value"] = "0.00"
    _wire_wave(monkeypatch, data=data)

    fake = FakeGmail(search_results=[])
    plan = runner.build_plan(now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake)
    numbers = {p.invoice.invoice_number for p in plan}
    assert "1001" not in numbers  # paid -> no chase, resolved implicitly


def test_build_plan_uses_wide_history_window(monkeypatch):
    # Regression: the Gmail dedupe/escalation window must be wider than min_gap,
    # else prior-count escalation can never fire. Default is 90 days.
    _wire_wave(monkeypatch)
    fake = FakeGmail(search_results=[])
    runner.build_plan(
        now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake
    )
    assert "newer_than:90d" in fake.last_query


def test_second_run_after_send_does_not_resend(monkeypatch):
    """Simulate: run 1 sends #0998; run 2 sees that prior in Gmail and skips it."""
    _wire_wave(monkeypatch)

    state = {"sent_998": False}

    class StatefulGmail(FakeGmail):
        def search(self, query: str):
            self.last_query = query
            if "0998" in query and state["sent_998"]:
                return [{"id": "p", "internalDate": epoch_ms("2026-06-04T09:00:00")}]
            return []

    fake = StatefulGmail()

    plan1 = runner.build_plan(now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake)
    delta = next(p for p in plan1 if p.invoice.invoice_number == "0998")
    runner.execute(plan1, {delta.invoice.invoice_id}, gmail_transport=fake, dry_run=False)
    state["sent_998"] = True

    plan2 = runner.build_plan(now=NOW, token="t", business_id="SANDBOX-DEMO-0001", source_name="wave", gmail_transport=fake)
    by_num = {p.invoice.invoice_number: p for p in plan2}
    assert isinstance(by_num["0998"], Skip)  # already chased today
