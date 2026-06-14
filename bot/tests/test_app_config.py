"""Bot config wiring: escalation policy comes from YAML + env overrides, and the
PAYUP_MIN_GAP_DAYS knob actually sets the escalation min_gap (not the search
window). Importing bot.app is safe without the [bot] extra: slack_bolt is only
imported inside main()."""

from payup.lib.escalation import EscalationConfig

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
