"""Gmail integration. The ONLY place in the engine that writes to the network.

Three jobs:
  * send_message  - send an approved reminder (refuses unless approved=True)
  * prior_reminders - search Sent for prior chases of an invoice (dedupe + tier)
  * list_thread_replies - read replies for Slack context

The real Google client is built lazily inside `_default_transport` so importing
this module never requires google libraries. Tests inject a fake transport, so
no network is touched and the approval gate is asserted by call count.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Protocol

from .templating import Draft

__all__ = [
    "SentRef",
    "SendResult",
    "ReplyMsg",
    "GmailError",
    "NotApprovedError",
    "send_message",
    "prior_reminders",
    "list_thread_replies",
    "build_search_query",
]


class GmailError(Exception):
    """Generic Gmail failure."""


class NotApprovedError(PermissionError):
    """Raised when a send is attempted without explicit approval."""


@dataclass(frozen=True)
class SentRef:
    sent_ts: datetime
    message_id: str

    @property
    def sent_date(self):
        return self.sent_ts.date()


@dataclass(frozen=True)
class SendResult:
    message_id: str
    thread_id: str
    dry_run: bool


@dataclass(frozen=True)
class ReplyMsg:
    message_id: str
    from_addr: str
    received_ts: datetime
    snippet: str


class Transport(Protocol):
    """Minimal surface the engine needs from a Gmail client."""

    def send(self, raw_b64: str) -> dict: ...
    def search(self, query: str) -> list[dict]: ...
    def get_message(self, message_id: str) -> dict: ...
    def list_thread(self, thread_id: str) -> list[dict]: ...


def _sanitize_term(value: str) -> str:
    """Strip characters that would break out of a quoted Gmail search term
    (quotes, parens, backslashes) so an odd invoice number or email cannot
    inject search operators and silently corrupt the dedupe count."""
    return re.sub(r'["()\\]', "", str(value)).strip()


def build_search_query(invoice_number: str, customer_email: str, lookback_days: int) -> str:
    """The Sent-mail dedupe query. Invoice number is the join key (it is always
    in the subject, enforced by the templating test)."""
    inv = _sanitize_term(invoice_number)
    email = _sanitize_term(customer_email)
    return (
        f'to:{email} subject:("Invoice #{inv}") '
        f"in:sent newer_than:{lookback_days}d"
    )


def _raw_b64(draft: Draft) -> str:
    msg = EmailMessage()
    msg["To"] = draft.to
    msg["Subject"] = draft.subject
    # Stable machine-readable marker for manual tracing. The active dedupe is the
    # subject search in build_search_query: Gmail's `q` cannot reliably match
    # arbitrary custom headers, so this header is a convenience, not the key.
    msg["X-PayUp-Invoice-Id"] = draft.invoice_number
    msg.set_content(draft.body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def send_message(
    draft: Draft,
    *,
    approved: bool,
    dry_run: bool,
    creds=None,
    transport: Transport | None = None,
) -> SendResult:
    """Send a reminder. HARD GATE: raises before any network call unless approved
    is exactly True (a truthy-but-not-True value is treated as not approved)."""
    if approved is not True:
        raise NotApprovedError(
            f"refusing to send reminder for invoice #{draft.invoice_number}: not approved"
        )
    if dry_run:
        return SendResult(message_id="dry-run", thread_id="dry-run", dry_run=True)
    tp = transport or _default_transport(creds)
    result = tp.send(_raw_b64(draft))
    return SendResult(
        message_id=str(result.get("id", "")),
        thread_id=str(result.get("threadId", "")),
        dry_run=False,
    )


def _parse_internal_date(value) -> datetime:
    # Gmail internalDate is ms since epoch (string).
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc)


def prior_reminders(
    invoice_number: str,
    customer_email: str,
    creds=None,
    *,
    lookback_days: int = 7,
    transport: Transport | None = None,
) -> list[SentRef]:
    """Return prior reminders for this invoice from Sent mail (most recent last)."""
    tp = transport or _default_transport(creds)
    query = build_search_query(invoice_number, customer_email, lookback_days)
    refs: list[SentRef] = []
    for meta in tp.search(query):
        refs.append(
            SentRef(
                sent_ts=_parse_internal_date(meta.get("internalDate")),
                message_id=str(meta.get("id", "")),
            )
        )
    refs.sort(key=lambda r: r.sent_ts)
    return refs


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def list_thread_replies(
    thread_id: str,
    creds=None,
    *,
    transport: Transport | None = None,
) -> list[ReplyMsg]:
    """Return inbound replies on a thread (for Slack context only)."""
    tp = transport or _default_transport(creds)
    out: list[ReplyMsg] = []
    for msg in tp.list_thread(thread_id):
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        out.append(
            ReplyMsg(
                message_id=str(msg.get("id", "")),
                from_addr=_header(headers, "From"),
                received_ts=_parse_internal_date(msg.get("internalDate")),
                snippet=str(msg.get("snippet", "")),
            )
        )
    return out


def _default_transport(creds) -> Transport:  # pragma: no cover - requires google libs + network
    """Build a real Gmail transport. Imported lazily so the engine has no hard
    dependency on google libraries."""
    try:
        from googleapiclient.discovery import build
    except Exception as exc:  # pragma: no cover
        raise GmailError(
            "Gmail runtime not installed. Install the bot extra: pip install -e '.[bot]'"
        ) from exc
    if creds is None:
        raise GmailError("no Gmail credentials provided")

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    class _Real:
        def send(self, raw_b64: str) -> dict:
            return (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw_b64})
                .execute()
            )

        def search(self, query: str) -> list[dict]:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query)
                .execute()
            )
            out = []
            for m in resp.get("messages", []):
                full = (
                    service.users()
                    .messages()
                    .get(userId="me", id=m["id"], format="metadata")
                    .execute()
                )
                out.append(full)
            return out

        def get_message(self, message_id: str) -> dict:
            return (
                service.users()
                .messages()
                .get(userId="me", id=message_id)
                .execute()
            )

        def list_thread(self, thread_id: str) -> list[dict]:
            resp = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id)
                .execute()
            )
            return resp.get("messages", [])

    return _Real()
