"""Bot test fixtures: reuse the engine FakeGmail and Wave fixtures."""

from __future__ import annotations

import json
import os

import pytest

ENGINE_FIXTURES = os.path.join(
    os.path.dirname(__file__), "..", "..", "engine", "tests", "fixtures"
)


def load_wave(name: str = "wave_overdue.json") -> dict:
    with open(os.path.join(ENGINE_FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)["data"]


class FakeGmail:
    def __init__(self, search_results=None, thread_results=None):
        self.sent: list[str] = []
        self.drafted: list[str] = []
        self._search_results = search_results or []
        self._thread_results = thread_results or []
        self.last_query = None

    def send(self, raw_b64: str) -> dict:
        self.sent.append(raw_b64)
        return {"id": f"msg_{len(self.sent)}", "threadId": f"thr_{len(self.sent)}"}

    def create_draft(self, raw_b64: str) -> dict:
        self.drafted.append(raw_b64)
        n = len(self.drafted)
        return {
            "id": f"draft_{n}",
            "message": {"id": f"dmsg_{n}", "threadId": f"dthr_{n}"},
        }

    def search(self, query: str):
        self.last_query = query
        return list(self._search_results)

    def get_message(self, message_id: str):
        return {}

    def list_thread(self, thread_id: str):
        return list(self._thread_results)


@pytest.fixture
def fake_gmail():
    return FakeGmail()


class Poster:
    def __init__(self):
        self.posts: list[tuple[str, str]] = []

    def __call__(self, channel: str, text: str) -> None:
        self.posts.append((channel, text))


@pytest.fixture
def poster():
    return Poster()
