"""Bot config wiring: escalation policy comes from YAML + env overrides, and the
PAYUP_MIN_GAP_DAYS knob actually sets the escalation min_gap (not the search
window). Importing bot.app is safe without the [bot] extra: slack_bolt is only
imported inside main()."""

from payup.lib.escalation import EscalationConfig
from payup.lib.templating import TemplateSet

import bot.app as app


def test_load_escalation_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("PAYUP_ESCALATION_CONFIG", "/nonexistent/escalation.yml")
    monkeypatch.setenv("PAYUP_MIN_GAP_DAYS", "10")
    monkeypatch.setenv("PAYUP_GENTLE_MAX_DAYS", "20")
    monkeypatch.delenv("PAYUP_FIRM_MAX_DAYS", raising=False)
    monkeypatch.delenv("PAYUP_FINAL_MIN_PRIORS", raising=False)

    esc = app._load_escalation()
    assert esc.min_gap_days == 10          # PAYUP_MIN_GAP_DAYS -> escalation min_gap
    assert esc.gentle_max_days == 20
    assert esc.firm_max_days == EscalationConfig().firm_max_days  # default retained


def test_load_escalation_defaults_when_unset(monkeypatch):
    for var in (
        "PAYUP_MIN_GAP_DAYS",
        "PAYUP_GENTLE_MAX_DAYS",
        "PAYUP_FIRM_MAX_DAYS",
        "PAYUP_FINAL_MIN_PRIORS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PAYUP_ESCALATION_CONFIG", "/nonexistent/escalation.yml")
    assert app._load_escalation() == EscalationConfig()


def test_load_templates_from_yaml(monkeypatch, tmp_path):
    yml = tmp_path / "templates.yml"
    yml.write_text(
        'gentle:\n  subject: "Nudge: Invoice #{invoice_number}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PAYUP_TEMPLATES_CONFIG", str(yml))
    ts = app._load_templates()
    assert ts.gentle_subject == "Nudge: Invoice #{invoice_number}"
    # Untouched fields stay None (built-in default at render time).
    assert ts.firm_subject is None


def test_load_templates_defaults_when_unset(monkeypatch):
    monkeypatch.setenv("PAYUP_TEMPLATES_CONFIG", "/nonexistent/templates.yml")
    assert app._load_templates() == TemplateSet()


def test_gmail_token_source_prefers_local_file(tmp_path):
    # When the token file exists, it wins (unchanged behaviour) and no JSON is parsed.
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    env = {"GMAIL_TOKEN_PATH": str(token), "GMAIL_TOKEN_JSON": '{"never":"used"}'}
    kind, value = app._gmail_token_source(env)
    assert kind == "file"
    assert value == str(token)


def test_gmail_token_source_falls_back_to_json_blob(tmp_path):
    # No file present, but the GMAIL_TOKEN_JSON secret carries the same token
    # (the Fly/cloud path). Returns the parsed dict; no google libs required.
    missing = tmp_path / "absent.json"
    env = {
        "GMAIL_TOKEN_PATH": str(missing),
        "GMAIL_TOKEN_JSON": '{"refresh_token": "x", "scopes": ["a"]}',
    }
    kind, value = app._gmail_token_source(env)
    assert kind == "info"
    assert value == {"refresh_token": "x", "scopes": ["a"]}


def test_gmail_token_source_errors_when_neither_present(tmp_path):
    import pytest

    env = {"GMAIL_TOKEN_PATH": str(tmp_path / "absent.json")}
    with pytest.raises(SystemExit) as exc:
        app._gmail_token_source(env)
    assert "GMAIL_TOKEN_JSON" in str(exc.value)
