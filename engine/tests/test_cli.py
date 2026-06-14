"""Story H2 — CLI dry-run plan renders the sandbox batch and never sends."""

import os

from payup import cli

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED = os.path.join(REPO, "fixtures-sandbox", "demo_business.json")


def test_plan_chase_renders_sandbox_batch(capsys):
    rc = cli.main(["plan-chase", "--invoices", SEED, "--now", "2026-06-04"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Acme Studio" in out
    assert "#1001" in out and "#0998" in out
    assert "—" not in out  # no em dash in tool output


def test_status_empty(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("PAYUP_LEDGER", str(tmp_path / "none.jsonl"))
    rc = cli.main(["status", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No runs recorded yet" in out


def test_status_shows_recorded_run(capsys, tmp_path, monkeypatch):
    # cli status must read PAYUP_LEDGER at call time and show recorded runs.
    from payup.lib import ledger

    p = tmp_path / "runs.jsonl"
    ledger.append_run({"date": "2026-06-04", "sent": ["1001"], "skipped": []}, str(p))
    monkeypatch.setenv("PAYUP_LEDGER", str(p))
    rc = cli.main(["status", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1001" in out
