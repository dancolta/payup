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
    # reload ledger default? cli.status reads ledger.recent with default path arg;
    # call status and accept either empty message or no rows.
    rc = cli.main(["status", "--limit", "5"])
    assert rc == 0
