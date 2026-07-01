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
_DRAFT_VERBS = ("draft",)
_SHOW_WORDS = ("show overdue", "show", "overdue", "list", "what's overdue", "whats overdue", "status")
_HELP_WORDS = ("help", "commands", "?", "how do i")

# Reminder-copy editing: "edit template gentle subject: <new copy>".
_TIERS = ("gentle", "firm", "final")
_TEMPLATE_FIELDS = ("subject", "body")
_EDIT_TEMPLATE_RE = re.compile(r"edit\s+templates?\b(.*)", re.IGNORECASE | re.DOTALL)

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
        "draft", "ignore", "hold", "snooze", "invoice", "invoices", "please", "row", "rows",
        "number", "numbers", "inc", "llc", "ltd", "corp", "company", "limited",
    }
)


@dataclass(frozen=True)
class Intent:
    kind: str  # 'send' | 'draft' | 'skip' | 'show_overdue' | 'help' | 'edit_template' | 'unknown'
    ids: tuple[int, ...] = field(default=())  # 1-based row numbers
    all: bool = False
    # For kind == 'edit_template': which tier/field to rewrite and the new copy.
    # All None means "no target given" -> show current copy + usage.
    tier: str | None = None
    template_field: str | None = None
    template_text: str | None = None


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


def _parse_edit_template(raw: str):
    """Pull (tier, field, text) out of 'edit template gentle subject: <copy>'.

    Reads the original-case text so the new copy keeps the user's capitalization,
    and splits on the FIRST colon so a colon inside the copy (e.g. "Reminder:
    ...") is preserved. Returns None when there is no clear tier + field + copy,
    so the handler shows the current copy and usage instead of guessing."""
    m = _EDIT_TEMPLATE_RE.search(raw)
    if not m or ":" not in m.group(1):
        return None
    head, body = m.group(1).split(":", 1)
    body = body.strip()
    tier = fld = None
    for tok in head.lower().split():
        if tok in _TIERS:
            tier = tok
        elif tok in _TEMPLATE_FIELDS:
            fld = tok
    if tier and fld and body:
        return (tier, fld, body)
    return None


def parse_intent(text: str, batch: list[dict] | None = None) -> Intent:
    """Parse a Slack message into an Intent. `batch` rows are dicts with at least
    {'n': int, 'customer': str} so names like "Delta" resolve to a row number."""
    batch = batch or []
    raw = _MARKUP_RE.sub(" ", (text or "")).strip()
    t = raw.lower()
    if not t:
        return Intent("unknown")

    # Editing reminder copy is a distinct command, matched BEFORE the action-verb
    # logic so template body text (which may contain "send", "all", numbers, or a
    # customer name) is never misread as a send/skip/draft.
    if "edit template" in t:
        parsed = _parse_edit_template(raw)
        if parsed:
            tier, fld, body = parsed
            return Intent("edit_template", tier=tier, template_field=fld, template_text=body)
        return Intent("edit_template")

    has_send = any(t.startswith(v) or f" {v} " in f" {t} " for v in _SEND_VERBS)
    has_skip = any(t.startswith(v) or f" {v} " in f" {t} " for v in _SKIP_VERBS)
    has_draft = any(t.startswith(v) or f" {v} " in f" {t} " for v in _DRAFT_VERBS)

    # Help and show only when no action verb is present.
    if not has_send and not has_skip and not has_draft:
        if any(t == w or t.startswith(w) for w in _HELP_WORDS):
            return Intent("help")
        if any(w in t for w in _SHOW_WORDS):
            return Intent("show_overdue")
        return Intent("unknown")

    # Action verbs are mutually exclusive: any combination is ambiguous -> clarify.
    if (has_send + has_skip + has_draft) > 1:
        return Intent("unknown")

    kind = "send" if has_send else "draft" if has_draft else "skip"

    # HITL guard: a send/draft that is negated or phrased as a question is not a
    # command. Drafting writes to Gmail too, so it gets the same guards as send.
    if kind in ("send", "draft") and (_NEGATION_RE.search(t) or _is_question(t)):
        return Intent("unknown")

    if re.search(r"\ball\b", t):
        return Intent(kind, all=True)

    ids = _resolve_numbers(t, batch) | _resolve_names(t, batch)
    if not ids:
        return Intent("unknown")  # "send" with no resolvable target -> never implicit
    return Intent(kind, ids=tuple(sorted(ids)))
