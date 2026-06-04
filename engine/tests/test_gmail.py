"""Stories D1/D2/D3 — Gmail send gate, dedupe search, thread replies."""

from datetime import date

import pytest

from payup.lib import gmail
from payup.lib.escalation import Tier
from payup.lib.gmail import NotApprovedError, build_search_query, prior_reminders, send_message
from payup.lib.templating import render_email
from payup.lib.wave import Invoice

from .conftest import FakeGmail, epoch_ms

INV = Invoice(
    invoice_id="inv_1",
    invoice_number="1042",
    customer_name="Acme",
    customer_email="ap@acme.example",
    amount_due_cents=240000,
    currency="USD",
    due_date=date(2026, 5, 13),
    status="OVERDUE",
)
DRAFT = render_email(INV, Tier.FIRM)


def test_send_blocked_without_approval_zero_calls():
    tp = FakeGmail()
    with pytest.raises(NotApprovedError):
        send_message(DRAFT, approved=False, dry_run=False, transport=tp)
    assert tp.sent == []  # nothing left the machine


def test_dry_run_sends_nothing():
    tp = FakeGmail()
    result = send_message(DRAFT, approved=True, dry_run=True, transport=tp)
    assert result.dry_run is True
    assert tp.sent == []


def test_approved_send_builds_payload():
    tp = FakeGmail()
    result = send_message(DRAFT, approved=True, dry_run=False, transport=tp)
    assert result.dry_run is False
    assert len(tp.sent) == 1
    # the encoded message carries the subject (with invoice number) + recipient
    import base64

    raw = base64.urlsafe_b64decode(tp.sent[0]).decode("utf-8")
    assert "1042" in raw
    assert "ap@acme.example" in raw
    assert "X-PayUp-Invoice-Id: 1042" in raw


def test_build_search_query_shape():
    q = build_search_query("1042", "ap@acme.example", 7)
    assert 'subject:("Invoice #1042")' in q
    assert "to:ap@acme.example" in q
    assert "in:sent" in q
    assert "newer_than:7d" in q


def test_prior_reminders_parses_and_sorts():
    results = [
        {"id": "m2", "internalDate": epoch_ms("2026-06-01T09:00:00")},
        {"id": "m1", "internalDate": epoch_ms("2026-05-20T09:00:00")},
    ]
    tp = FakeGmail(search_results=results)
    refs = prior_reminders("1042", "ap@acme.example", lookback_days=30, transport=tp)
    assert [r.message_id for r in refs] == ["m1", "m2"]  # sorted by ts ascending
    assert tp.last_query is not None and "1042" in tp.last_query


def test_prior_reminders_empty():
    tp = FakeGmail(search_results=[])
    assert prior_reminders("1042", "ap@acme.example", transport=tp) == []


def test_list_thread_replies_parses():
    thread = [
        {
            "id": "r1",
            "internalDate": epoch_ms("2026-06-02T10:00:00"),
            "snippet": "will pay friday",
            "payload": {"headers": [{"name": "From", "value": "ap@acme.example"}]},
        }
    ]
    tp = FakeGmail(thread_results=thread)
    replies = gmail.list_thread_replies("thr_1", transport=tp)
    assert len(replies) == 1
    assert replies[0].from_addr == "ap@acme.example"
    assert "friday" in replies[0].snippet
