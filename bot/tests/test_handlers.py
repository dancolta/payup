"""Story E2 + F1 (Slack half) : handlers route intents to the engine, and the
HITL gate holds: nothing sends without an explicit send intent."""

from datetime import date

import pytest

from bot.handlers import BotDeps, ChaseSession
from payup.lib import wave

from .conftest import load_wave

NOW = date(2026, 6, 4)
CH = "C123"


@pytest.fixture
def session(monkeypatch, fake_gmail):
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        wave_token="t",
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
