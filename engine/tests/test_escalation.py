"""Story C1 — escalation tiering."""

from payup.lib.escalation import EscalationConfig, Tier, select_tier

CFG = EscalationConfig()


def test_gentle_band():
    assert select_tier(1, 0, None, CFG) is Tier.GENTLE
    assert select_tier(14, 0, None, CFG) is Tier.GENTLE


def test_firm_band_by_days():
    assert select_tier(15, 0, None, CFG) is Tier.FIRM
    assert select_tier(30, 0, None, CFG) is Tier.FIRM


def test_firm_band_by_prior():
    # one prior reminder, sent long enough ago, still in gentle day-range -> firm
    assert select_tier(10, 1, 9, CFG) is Tier.FIRM


def test_final_band_by_days():
    assert select_tier(31, 0, None, CFG) is Tier.FINAL
    assert select_tier(120, 0, None, CFG) is Tier.FINAL


def test_final_band_by_priors():
    assert select_tier(5, 2, 30, CFG) is Tier.FINAL


def test_hold_within_min_gap():
    # chased 3 days ago, min_gap is 7 -> hold
    assert select_tier(20, 1, 3, CFG) is None


def test_not_overdue_returns_none():
    assert select_tier(0, 0, None, CFG) is None
    assert select_tier(-5, 0, None, CFG) is None


def test_config_driven_thresholds():
    loose = EscalationConfig(gentle_max_days=30, firm_max_days=60, min_gap_days=1)
    assert select_tier(25, 0, None, loose) is Tier.GENTLE  # would be firm under defaults
    assert select_tier(20, 1, 2, loose) is Tier.FIRM       # min_gap 1 -> not held


def test_load_from_yaml(tmp_path):
    # config/escalation.yml is actually loaded (was previously dead config).
    p = tmp_path / "esc.yml"
    p.write_text("min_gap_days: 3\ngentle_max_days: 5\n", encoding="utf-8")
    cfg = EscalationConfig.load(str(p))
    assert cfg.min_gap_days == 3
    assert cfg.gentle_max_days == 5
    assert cfg.firm_max_days == 30  # unspecified key keeps the default


def test_load_no_path_returns_defaults():
    assert EscalationConfig.load(None) == EscalationConfig()
