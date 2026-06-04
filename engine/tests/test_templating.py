"""Story C2 — templating tone + subject dedupe key + tone blacklist."""

from datetime import date

import pytest
from payup.lib.escalation import Tier
from payup.lib.templating import BLACKLIST, TemplatingConfig, render_email
from payup.lib.wave import Invoice

INV = Invoice(
    invoice_id="inv_1",
    invoice_number="1042",
    customer_name="Acme Studio",
    customer_email="ap@acme.example",
    amount_due_cents=240000,
    currency="USD",
    due_date=date(2026, 5, 13),
    status="OVERDUE",
)


@pytest.mark.parametrize("tier", [Tier.GENTLE, Tier.FIRM, Tier.FINAL])
def test_subject_contains_invoice_number(tier):
    draft = render_email(INV, tier)
    assert INV.invoice_number in draft.subject


@pytest.mark.parametrize("tier", [Tier.GENTLE, Tier.FIRM, Tier.FINAL])
def test_body_has_amount_invoice_and_due(tier):
    draft = render_email(INV, tier)
    assert "1042" in draft.body
    assert "2,400.00" in draft.body
    assert "2026-05-13" in draft.body
    assert draft.to == "ap@acme.example"
    assert draft.tier == tier.value


@pytest.mark.parametrize("tier", [Tier.GENTLE, Tier.FIRM, Tier.FINAL])
def test_no_legal_or_collection_language(tier):
    draft = render_email(INV, tier)
    haystack = (draft.subject + " " + draft.body).lower()
    for word in BLACKLIST:
        assert word not in haystack, f"blacklisted term {word!r} appeared in {tier} draft"


@pytest.mark.parametrize("tier", [Tier.GENTLE, Tier.FIRM, Tier.FINAL])
def test_no_em_dash_in_draft(tier):
    draft = render_email(INV, tier)
    assert "—" not in (draft.subject + draft.body)


def test_final_tier_is_firm_not_threatening():
    draft = render_email(INV, Tier.FINAL)
    assert "final reminder" in draft.subject.lower()
    # still polite: invites a paid confirmation rather than threatening
    assert "already paid" in draft.body.lower()


def test_custom_config_signature():
    cfg = TemplatingConfig(sender_name="Dan", business_name="NodeSparks")
    draft = render_email(INV, Tier.GENTLE, cfg)
    assert "Dan" in draft.body and "NodeSparks" in draft.body
