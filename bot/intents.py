"""Natural-language intent parsing for the Slack conversation. Pure + testable.

Turns "send 1 and 3", "skip Delta", "show overdue", "send all" into a structured
Intent. The cardinal rule: a bare or ambiguous message NEVER becomes an implicit
send. When in doubt we return Unknown and the bot asks for clarification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Intent", "parse_intent"]

_NUM_RE = re.compile(r"\b(\d{1,3})\b")
_SEND_VERBS = ("send", "approve", "chase", "remind")
_SKIP_VERBS = ("skip", "ignore", "hold", "snooze")
_SHOW_WORDS = ("show overdue", "show", "overdue", "list", "what's overdue", "whats overdue", "status")
_HELP_WORDS = ("help", "commands", "?", "how do i")

# Slack markup like <@U123>, <#C123|name>, <https://...> is stripped before
# parsing, so an @mention prefix does not leak ids/digits into matching.
_MARKUP_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[a-z0-9]+")

# A "send" command that contains a negation or reads as a question is NOT a send.
# Protects the HITL gate from "do not send all" / "should I send all?".
_NEGATION_RE = re.compile(r"\b(?:not|never|cancel|cancelled|stop|without)\b|n't")
_QUESTION_LEADS = (
    "should", "shall", "can ", "could", "would", "do i", "does", "is it",
    "is this", "are we", "are these", "what", "why", "when", "how", "may i", "ok to",
)

# Generic tokens that must never resolve a customer by name (e.g. "and" in
# "send 1 and 3" must not select a customer called "Smith and Sons").
_NAME_STOPWORDS = frozenset(
    {
        "and", "the", "for", "all", "send", "skip", "approve", "chase", "remind",
        "ignore", "hold", "snooze", "invoice", "invoices", "please", "row", "rows",
        "number", "numbers", "inc", "llc", "ltd", "corp", "company", "limited",
    }
)


@dataclass(frozen=True)
class Intent:
    kind: str  # 'send' | 'skip' | 'show_overdue' | 'help' | 'unknown'
    ids: tuple[int, ...] = field(default=())  # 1-based row numbers
    all: bool = False


def _resolve_names(text: str, batch: list[dict]) -> set[int]:
    words = set(_WORD_RE.findall(text))
    found: set[int] = set()
    for row in batch:
        name = str(row.get("customer", "")).lower()
        for token in _WORD_RE.findall(name):
            if len(token) >= 3 and token not in _NAME_STOPWORDS and token in words:
                found.add(int(row["n"]))
    return found


def _is_question(t: str) -> bool:
    return t.endswith("?") or any(t.startswith(w) for w in _QUESTION_LEADS)


def _resolve_numbers(text: str, batch: list[dict]) -> set[int]:
    valid = {int(r["n"]) for r in batch}
    return {int(m) for m in _NUM_RE.findall(text) if int(m) in valid}


def parse_intent(text: str, batch: list[dict] | None = None) -> Intent:
    """Parse a Slack message into an Intent. `batch` rows are dicts with at least
    {'n': int, 'customer': str} so names like "Delta" resolve to a row number."""
    batch = batch or []
    t = _MARKUP_RE.sub(" ", (text or "")).strip().lower()
    if not t:
        return Intent("unknown")

    has_send = any(t.startswith(v) or f" {v} " in f" {t} " for v in _SEND_VERBS)
    has_skip = any(t.startswith(v) or f" {v} " in f" {t} " for v in _SKIP_VERBS)

    # Help and show only when no action verb is present.
    if not has_send and not has_skip:
        if any(t == w or t.startswith(w) for w in _HELP_WORDS):
            return Intent("help")
        if any(w in t for w in _SHOW_WORDS):
            return Intent("show_overdue")
        return Intent("unknown")

    # If both a send and skip verb appear, it is ambiguous -> clarify.
    if has_send and has_skip:
        return Intent("unknown")

    kind = "send" if has_send else "skip"

    # HITL guard: a send that is negated or phrased as a question is not a send.
    if kind == "send" and (_NEGATION_RE.search(t) or _is_question(t)):
        return Intent("unknown")

    if re.search(r"\ball\b", t):
        return Intent(kind, all=True)

    ids = _resolve_numbers(t, batch) | _resolve_names(t, batch)
    if not ids:
        return Intent("unknown")  # "send" with no resolvable target -> never implicit
    return Intent(kind, ids=tuple(sorted(ids)))
