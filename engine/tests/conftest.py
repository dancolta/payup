"""Shared test fixtures and fakes. No network is ever touched in tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# A fixed "today" used across the suite so tiering is deterministic.
NOW_ISO = "2026-06-04"


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def fixtures_dir() -> str:
    return FIXTURES


class FakeGmail:
    """In-memory Gmail transport. Records sends so the approval gate can be
    asserted by call count, and serves canned search/thread results."""

    def __init__(self, search_results=None, thread_results=None):
        self.sent: list[str] = []
        self._search_results = search_results or []
        self._thread_results = thread_results or []
        self.last_query: str | None = None

    def send(self, raw_b64: str) -> dict:
        self.sent.append(raw_b64)
        return {"id": f"msg_{len(self.sent)}", "threadId": f"thr_{len(self.sent)}"}

    def search(self, query: str) -> list[dict]:
        self.last_query = query
        return list(self._search_results)

    def get_message(self, message_id: str) -> dict:
        return {}

    def list_thread(self, thread_id: str) -> list[dict]:
        return list(self._thread_results)


@pytest.fixture
def fake_gmail() -> FakeGmail:
    return FakeGmail()


def epoch_ms(iso: str) -> str:
    dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))
