"""Story E3 : internal daily timer posts the batch and sends nothing."""

from datetime import date, datetime

from payup.lib import wave

from bot.handlers import BotDeps, ChaseSession
from bot.scheduler import run_daily, seconds_until

from .conftest import load_wave

NOW = date(2026, 6, 4)


def test_run_daily_posts_and_sends_nothing(monkeypatch, fake_gmail, poster):
    monkeypatch.setattr(wave, "_post_graphql", lambda token, query, variables: load_wave())
    deps = BotDeps(
        token="t",
        source_name="wave",
        business_id="SANDBOX-DEMO-0001",
        dry_run=False,
        gmail_transport=fake_gmail,
        now_fn=lambda: NOW,
    )
    session = ChaseSession(deps)

    text = run_daily(session, "C1", poster)

    assert len(poster.posts) == 1            # posted exactly one batch
    assert "1001" in text
    assert fake_gmail.sent == []             # scheduled run NEVER sends


def test_seconds_until_future_today():
    now = datetime(2026, 6, 4, 8, 0, 0)
    secs = seconds_until("09:00", now=now)
    assert secs == 3600


def test_seconds_until_rolls_to_tomorrow():
    now = datetime(2026, 6, 4, 10, 0, 0)
    secs = seconds_until("09:00", now=now)
    assert 23 * 3600 <= secs <= 24 * 3600
