"""Stories A2/E4 — net SSRF guard, ledger round-trip, output formatting."""

import os
from datetime import date

import pytest
from payup.lib import ledger, net, output
from payup.lib.escalation import Tier
from payup.lib.planner import Action
from payup.lib.templating import render_email
from payup.lib.wave import Invoice

NOW = date(2026, 6, 4)


# --- net SSRF guard ---
def test_net_rejects_non_https():
    with pytest.raises(net.NetError):
        net.post_json("http://example.com", {}, {})


def test_net_rejects_private_host():
    # localhost resolves to loopback -> rejected before any socket write
    with pytest.raises(net.NetError):
        net.post_json("https://localhost", {}, {})


# --- ledger round-trip ---
def test_ledger_append_and_recent(tmp_path):
    path = str(tmp_path / "runs.jsonl")
    ledger.append_run({"run": 1, "sent": 2}, path)
    ledger.append_run({"run": 2, "sent": 0}, path)
    recs = ledger.recent(10, path)
    assert [r["run"] for r in recs] == [1, 2]
    # restrictive perms (owner-only)
    assert (os.stat(path).st_mode & 0o077) == 0


def test_ledger_recent_missing_file():
    assert ledger.recent(5, "/nonexistent/path/runs.jsonl") == []


# --- output formatting ---
def _inv(num, days_late, cents):
    return Invoice(
        invoice_id=f"id{num}",
        invoice_number=num,
        customer_name=f"Cust {num}",
        customer_email=f"{num}@x.example",
        amount_due_cents=cents,
        currency="USD",
        due_date=date(2026, 6, 4 - days_late) if days_late < 4 else date(2026, 5, 31),
        status="OVERDUE",
    )


def test_render_batch_lists_actions():
    inv = _inv("1001", 3, 240000)
    action = Action(invoice=inv, tier=Tier.GENTLE, draft=render_email(inv, Tier.GENTLE))
    text = output.render_batch([action], now=NOW)
    assert "1001" in text
    assert "—" not in text  # no em dash
    assert "send all" in text


def test_render_batch_empty():
    text = output.render_batch([])
    assert "No invoices" in text


def test_render_confirmation():
    text = output.render_confirmation(["#1001", "#0998"], ["#1051"])
    assert "Sent 2" in text
    assert "Skipped 1" in text
    assert "—" not in text
