"""Story E2 + F1 (Slack half) : handlers route intents to the engine, and the
HITL gate holds: nothing sends without an explicit send intent."""

from datetime import date

import pytest
from payup.lib import wave

from bot.handlers import BotDeps, ChaseSession

from .conftest import load_wave

NOW = date(2026, 6, 4)
CH = "C123"


@pytest.fixture
def session(monkeypatch, fake_gmail):
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        token="t",
        source_name="wave",
        business_id="SANDBOX-DEMO-0001",
        dry_run=False,
        gmail_transport=fake_gmail,
        now_fn=lambda: NOW,
    )
    s = ChaseSession(deps)
    s._gmail = fake_gmail  # for assertions
    return s


def test_show_overdue_lists_three(session):
    out = session.refresh(CH)
    assert "1001" in out and "1051" in out and "0998" in out
    assert session._gmail.sent == []  # listing sends nothing


def test_send_specific_rows(session):
    session.refresh(CH)
    out = session.handle(CH, "send 1 and 3")
    # rows are ordered as built: 1=Acme(1001), 2=Bryce(1051), 3=Delta(0998)
    assert "Sent 2" in out
    assert len(session._gmail.sent) == 2


def test_send_all(session):
    session.refresh(CH)
    out = session.handle(CH, "send all")
    assert "Sent 3" in out
    assert len(session._gmail.sent) == 3


def test_unknown_message_sends_nothing(session):
    session.refresh(CH)
    out = session.handle(CH, "lol ok thanks")
    assert "did not catch" in out.lower()
    assert session._gmail.sent == []


def test_skip_sends_nothing(session):
    session.refresh(CH)
    out = session.handle(CH, "skip Delta")
    assert "Nothing was sent" in out
    assert session._gmail.sent == []


def test_send_before_batch_is_safe(session):
    # No "show overdue" first -> there is no batch -> no send
    out = session.handle(CH, "send all")
    assert "No batch" in out
    assert session._gmail.sent == []


def test_help(session):
    out = session.handle(CH, "help")
    assert "PayUp commands" in out


def test_send_all_twice_does_not_resend(session):
    # Regression: after a real send the batch must clear so a repeated "send all"
    # cannot double-send every reminder.
    session.refresh(CH)
    out1 = session.handle(CH, "send all")
    assert "Sent 3" in out1
    assert len(session._gmail.sent) == 3

    out2 = session.handle(CH, "send all")
    assert len(session._gmail.sent) == 3  # nothing sent twice
    assert "No batch" in out2


def test_skip_then_send_all_excludes_skipped(session):
    # Regression: "skip" must actually remove the row, so a later "send all"
    # does not send the invoice the user was told was skipped.
    session.refresh(CH)
    session.handle(CH, "skip Delta")  # row 3 = Delta (#0998)
    out = session.handle(CH, "send all")
    assert len(session._gmail.sent) == 2  # Delta dropped
    assert "0998" not in out


def test_duplicate_event_id_is_ignored(session):
    # Regression: Slack delivers a channel @mention as both app_mention and
    # message; the same event id must be handled once.
    session.refresh(CH)
    first = session.handle(CH, "help", event_id="evt-1")
    assert first is not None and "PayUp commands" in first
    dup = session.handle(CH, "help", event_id="evt-1")
    assert dup is None


def test_real_send_records_to_ledger(monkeypatch, fake_gmail, tmp_path):
    # Regression: the run ledger (which powers /chase-status) was never written.
    import json

    ledger_file = tmp_path / "runs.jsonl"
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        token="t",
        source_name="wave",
        business_id="SANDBOX-DEMO-0001",
        dry_run=False,
        gmail_transport=fake_gmail,
        now_fn=lambda: NOW,
        ledger_path=str(ledger_file),
    )
    s = ChaseSession(deps)
    s.refresh(CH)
    s.handle(CH, "send all")

    lines = ledger_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["date"] == "2026-06-04"
    assert len(rec["sent"]) == 3


def test_no_ledger_write_without_path(session, tmp_path):
    # Default deps have no ledger_path -> no filesystem writes during a send.
    session.refresh(CH)
    session.handle(CH, "send all")  # must not raise despite no ledger_path
    assert list(tmp_path.iterdir()) == []


def test_draft_specific_rows_creates_drafts_not_sends(session):
    session.refresh(CH)
    out = session.handle(CH, "draft 1 and 3")
    assert "Drafted 2" in out
    assert len(session._gmail.drafted) == 2
    assert session._gmail.sent == []  # drafting never sends


def test_draft_all_creates_drafts(session):
    session.refresh(CH)
    out = session.handle(CH, "draft all")
    assert "Drafted 3" in out
    assert len(session._gmail.drafted) == 3
    assert session._gmail.sent == []


def test_draft_does_not_clear_the_batch(session):
    # A draft is not a chase: the batch must survive so the user can still send.
    session.refresh(CH)
    session.handle(CH, "draft all")
    out = session.handle(CH, "send all")
    assert "Sent 3" in out  # batch was still there
    assert len(session._gmail.sent) == 3


def test_dry_run_draft_copy(monkeypatch, fake_gmail):
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        token="t",
        source_name="wave",
        business_id="SANDBOX-DEMO-0001",
        dry_run=True,
        gmail_transport=fake_gmail,
        now_fn=lambda: NOW,
    )
    s = ChaseSession(deps)
    s.refresh(CH)
    out = s.handle(CH, "draft all")
    assert out.startswith("[dry-run] ")
    assert fake_gmail.drafted == []  # dry-run touches nothing


def test_draft_records_to_ledger_with_action_draft(monkeypatch, fake_gmail, tmp_path):
    import json

    ledger_file = tmp_path / "runs.jsonl"
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        token="t",
        source_name="wave",
        business_id="SANDBOX-DEMO-0001",
        dry_run=False,
        gmail_transport=fake_gmail,
        now_fn=lambda: NOW,
        ledger_path=str(ledger_file),
    )
    s = ChaseSession(deps)
    s.refresh(CH)
    s.handle(CH, "draft all")

    lines = ledger_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["action"] == "draft"
    assert len(rec["drafted"]) == 3


def test_refresh_reports_source_error_instead_of_silence(session, monkeypatch):
    # A failing accounting source/token must produce a clear chat reply, not silence.
    from payup.lib import runner

    def boom(**kwargs):
        raise RuntimeError("token refresh failed (400)")

    monkeypatch.setattr(runner, "build_plan", boom)
    out = session.refresh(CH)
    assert "could not reach" in out.lower()
    assert session._gmail.sent == []
