"""Story C2 — templating tone + subject dedupe key + tone blacklist."""

from datetime import date

import pytest
from payup.lib.escalation import Tier
from payup.lib.templating import (
    BLACKLIST,
    TemplateSet,
    TemplatingConfig,
    TemplatingError,
    render_email,
)
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


# --- custom template loading + the render-time safety guard ---

CUSTOM_YAML = """\
gentle:
  subject: "Quick nudge on Invoice #{invoice_number}"
  body: |-
    Hey {customer_name}, invoice #{invoice_number} ({amount}) was due {due_date}.
    Cheers, {sender_name}
firm:
  subject: "Past due: Invoice #{invoice_number}"
  body: "Following up on #{invoice_number} for {amount}."
final:
  subject: "Last note on Invoice #{invoice_number}"
  body: "Final note on #{invoice_number} for {amount}, due {due_date}."
"""


def _write(tmp_path, text):
    p = tmp_path / "templates.yml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_custom_yaml_renders_custom_copy(tmp_path):
    ts = TemplateSet.load(_write(tmp_path, CUSTOM_YAML))
    cfg = TemplatingConfig(sender_name="Dan", business_name="NodeSparks", templates=ts)
    draft = render_email(INV, Tier.GENTLE, cfg)
    assert draft.subject == "Quick nudge on Invoice #1042"
    assert "Hey Acme Studio" in draft.body
    assert "Cheers, Dan" in draft.body


def test_defaults_when_path_missing_or_none():
    assert TemplateSet.load(None) == TemplateSet()
    # A nonexistent file falls back to defaults (mirrors EscalationConfig.load).
    assert TemplateSet.load("/nonexistent/templates.yml") == TemplateSet()


def test_partial_per_field_fallback(tmp_path):
    # Only the gentle subject is overridden: every other field keeps its default.
    partial = "gentle:\n  subject: \"Hi about Invoice #{invoice_number}\"\n"
    ts = TemplateSet.load(_write(tmp_path, partial))
    cfg = TemplatingConfig(templates=ts)
    gentle = render_email(INV, Tier.GENTLE, cfg)
    assert gentle.subject == "Hi about Invoice #1042"
    # Default gentle body still used.
    assert "Just a friendly heads up" in gentle.body
    # Firm tier untouched -> default subject.
    firm = render_email(INV, Tier.FIRM, cfg)
    assert firm.subject == "Payment due: Invoice #1042"


def test_defaults_reproduce_shipped_copy():
    # The built-in TemplateSet must render byte-for-byte the historical copy.
    cfg = TemplatingConfig()
    gentle = render_email(INV, Tier.GENTLE, cfg)
    assert gentle.subject == "Reminder: Invoice #1042"
    assert gentle.body.startswith("Hi Acme Studio,\n\nJust a friendly heads up")
    assert gentle.body.endswith("Thanks so much,\nAccounts\nour team")


@pytest.mark.parametrize("term", ["lawyer", "collections"])
def test_blacklist_in_custom_template_raises(tmp_path, term):
    bad = (
        f'gentle:\n  subject: "Reminder: Invoice #{{invoice_number}}"\n'
        f'  body: "Pay up or we contact a {term}."\n'
    )
    ts = TemplateSet.load(_write(tmp_path, bad))
    cfg = TemplatingConfig(templates=ts)
    with pytest.raises(TemplatingError):
        render_email(INV, Tier.GENTLE, cfg)


def test_custom_subject_missing_invoice_number_raises(tmp_path):
    bad = 'gentle:\n  subject: "A friendly reminder"\n  body: "Hi {customer_name}."\n'
    ts = TemplateSet.load(_write(tmp_path, bad))
    cfg = TemplatingConfig(templates=ts)
    with pytest.raises(TemplatingError):
        render_email(INV, Tier.GENTLE, cfg)


def test_em_dash_in_custom_template_raises(tmp_path):
    bad = (
        'gentle:\n  subject: "Reminder: Invoice #{invoice_number}"\n'
        '  body: "Hi {customer_name} — please pay."\n'
    )
    ts = TemplateSet.load(_write(tmp_path, bad))
    cfg = TemplatingConfig(templates=ts)
    with pytest.raises(TemplatingError):
        render_email(INV, Tier.GENTLE, cfg)


def test_benign_word_with_blacklist_substring_is_allowed(tmp_path):
    # Word-boundary guard: "issue"/"pursue" contain "sue" as a substring but are
    # not blacklisted words. A legitimate custom template using them must render.
    ok = (
        'gentle:\n  subject: "Reminder: Invoice #{invoice_number}"\n'
        '  body: "If there is an issue with #{invoice_number} we will pursue a fix, {customer_name}."\n'
    )
    ts = TemplateSet.load(_write(tmp_path, ok))
    cfg = TemplatingConfig(templates=ts)
    draft = render_email(INV, Tier.GENTLE, cfg)
    assert "issue" in draft.body and "pursue" in draft.body


def test_empty_invoice_number_raises():
    # An empty invoice number is not a valid dedupe key; render must fail closed.
    blank = Invoice(
        invoice_id="x",
        invoice_number="",
        customer_name="A",
        customer_email="a@b.example",
        amount_due_cents=10000,
        currency="USD",
        due_date=date(2026, 5, 1),
        status="OVERDUE",
    )
    with pytest.raises(TemplatingError):
        render_email(blank, Tier.GENTLE)
