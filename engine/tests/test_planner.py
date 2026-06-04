"""Story C3 — planner join logic (Wave + Gmail-prior -> Action|Skip)."""

from datetime import date

from payup.lib.escalation import Tier
from payup.lib.planner import Action, PayupConfig, Skip, plan_chase
from payup.lib.wave import Invoice

NOW = date(2026, 6, 4)


def _inv(number, due, cents=100000):
    return Invoice(
        invoice_id=f"id_{number}",
        invoice_number=number,
        customer_name=f"Cust {number}",
        customer_email=f"{number}@x.example",
        amount_due_cents=cents,
        currency="USD",
        due_date=due,
        status="OVERDUE",
    )


def test_no_priors_gentle_action():
    inv = _inv("A", date(2026, 5, 28))  # 7 days overdue
    plan = plan_chase([inv], {}, now=NOW)
    assert len(plan) == 1
    assert isinstance(plan[0], Action)
    assert plan[0].tier is Tier.GENTLE
    assert plan[0].draft.invoice_number == "A"


def test_escalates_with_prior_count():
    inv = _inv("B", date(2026, 5, 20))  # 15 days overdue
    priors = {"B": [date(2026, 5, 21)]}  # one prior, 14 days ago
    plan = plan_chase([inv], priors, now=NOW)
    assert isinstance(plan[0], Action)
    assert plan[0].tier in (Tier.FIRM, Tier.FINAL)


def test_within_gap_is_skipped():
    inv = _inv("C", date(2026, 5, 10))  # very overdue
    priors = {"C": [date(2026, 6, 2)]}  # chased 2 days ago, min_gap 7
    plan = plan_chase([inv], priors, now=NOW)
    assert isinstance(plan[0], Skip)
    assert plan[0].reason == "within min_gap"


def test_mixed_batch():
    overdue = _inv("D", date(2026, 5, 1))
    recent = _inv("E", date(2026, 4, 1))
    priors = {"E": [date(2026, 6, 3)]}  # E chased yesterday -> skip
    plan = plan_chase([overdue, recent], priors, now=NOW)
    kinds = [type(p).__name__ for p in plan]
    assert kinds == ["Action", "Skip"]


def test_config_is_respected():
    inv = _inv("F", date(2026, 5, 28))  # 7 days overdue
    cfg = PayupConfig()
    plan = plan_chase([inv], {}, now=NOW, cfg=cfg)
    assert isinstance(plan[0], Action)
