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


def test_validate_templates_missing_file_is_safe(capsys):
    rc = cli.main(["validate-templates", "--templates", "/nonexistent/templates.yml"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "defaults are always safe" in out


def test_validate_templates_accepts_voice_edit(capsys, tmp_path):
    yml = tmp_path / "templates.yml"
    yml.write_text(
        'gentle:\n'
        '  subject: "Quick nudge on invoice #{invoice_number}"\n'
        '  body: |-\n'
        '    Hey {customer_name}, invoice #{invoice_number} for {amount} was due {due_date}.\n'
        '    Mind sorting it when you get a sec? Cheers, {sender_name}\n',
        encoding="utf-8",
    )
    rc = cli.main(["validate-templates", "--templates", str(yml)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pass the guardrails" in out
    assert "gentle: OK" in out


def test_validate_templates_rejects_subject_without_invoice_number(capsys):
    # A voice edit that drops {invoice_number} from the subject must fail (dedupe key).
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write('gentle:\n  subject: "A friendly reminder"\n')
        path = fh.name
    rc = cli.main(["validate-templates", "--templates", path])
    err = capsys.readouterr().err
    assert rc == 1
    assert "gentle: FAIL" in err


def test_validate_templates_rejects_collections_language(capsys):
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write(
            'final:\n'
            '  subject: "Final notice: invoice #{invoice_number}"\n'
            '  body: "Pay now or we send this to a collection agency."\n'
        )
        path = fh.name
    rc = cli.main(["validate-templates", "--templates", path])
    err = capsys.readouterr().err
    assert rc == 1
    assert "final: FAIL" in err
