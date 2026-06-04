"""Internal daily timer. The bot runs its own schedule; there is no external cron
host and no GitHub Actions in the loop.

A scheduled run only PREPARES and POSTS the batch. It never sends. The human then
approves conversationally. This keeps the HITL guarantee even when unattended.
"""

from __future__ import annotations

import time
from datetime import datetime

from .handlers import ChaseSession

__all__ = ["run_daily", "seconds_until", "loop"]


def run_daily(session: ChaseSession, channel: str, post_fn) -> str:
    """Prepare the batch and post it. Returns the posted text. Sends nothing."""
    text = session.refresh(channel)
    post_fn(channel, text)
    return text


def seconds_until(target_hhmm: str, *, now: datetime | None = None) -> float:
    """Seconds from `now` until the next occurrence of HH:MM local time."""
    now = now or datetime.now()
    hh, mm = (int(x) for x in target_hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target = target.replace(day=now.day)
        # move to tomorrow
        from datetime import timedelta

        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def loop(session: ChaseSession, channel: str, post_fn, daily_at: str, *, _sleep=time.sleep, _max_iters=None):  # pragma: no cover
    """Block forever, posting the batch once per day at `daily_at`."""
    iters = 0
    while _max_iters is None or iters < _max_iters:
        _sleep(seconds_until(daily_at))
        run_daily(session, channel, post_fn)
        iters += 1
