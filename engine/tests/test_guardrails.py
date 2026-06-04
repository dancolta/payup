"""Story F2 — the safety contract.

These tests are the reason PayUp is safe to wire to someone's real books:
  * no money-movement code path exists,
  * nothing sends without explicit approval (engine + CLI),
  * the demo is isolated from production,
  * the local ledger stays out of the tree.
"""

import json
import os

import pytest

from payup import cli
from payup.lib import gmail, ledger
from payup.lib.escalation import Tier
from payup.lib.gmail import NotApprovedError, send_message
from payup.lib.templating import render_email
from payup.lib.wave import Invoice

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE = os.path.join(REPO, "engine", "payup")

# Symbols that would imply moving money. "payment"/"paid" are intentionally NOT
# here: they appear in reminder copy and reply hints, which is fine. We forbid
# the verbs that actually move funds, and any GraphQL mutation.
FORBIDDEN_MONEY = [
    "mutation",
    "refund",
    "transferfunds",
    "createpayment",
    "chargecard",
    "movemoney",
    "initiatepayment",
    "payinvoice",
    "billpay",
]

INV = Invoice(
    invoice_id="inv_1",
    invoice_number="1042",
    customer_name="Acme",
    customer_email="ap@acme.example",
    amount_due_cents=240000,
    currency="USD",
    due_date=__import__("datetime").date(2026, 5, 13),
    status="OVERDUE",
)


def _engine_sources():
    for root, _, files in os.walk(ENGINE):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def test_no_money_movement_symbols():
    offenders = []
    for path in _engine_sources():
        with open(path, encoding="utf-8") as fh:
            lower = fh.read().lower()
        for sym in FORBIDDEN_MONEY:
            if sym in lower:
                offenders.append(f"{os.path.relpath(path, REPO)}: {sym}")
    assert not offenders, f"money-movement symbol found: {offenders}"


def test_engine_only_queries_wave_never_mutates():
    with open(os.path.join(ENGINE, "lib", "wave.py"), encoding="utf-8") as fh:
        src = fh.read().lower()
    assert "mutation" not in src
    assert "query" in src  # we do read


def test_send_refuses_without_approval():
    tp = gmail.SentRef  # noqa: F841  (ensure module imported)
    from .conftest import FakeGmail

    fake = FakeGmail()
    with pytest.raises(NotApprovedError):
        send_message(render_email(INV, Tier.FINAL), approved=False, dry_run=False, transport=fake)
    assert fake.sent == []


def test_cli_send_without_approved_ids_sends_nothing(capsys):
    rc = cli.main(["send"])
    out = capsys.readouterr()
    assert rc == 0
    assert "Nothing was sent" in out.err


def test_sandbox_isolation_demo_id_prefixed():
    with open(os.path.join(REPO, "fixtures-sandbox", "demo_business.json"), encoding="utf-8") as fh:
        demo = json.load(fh)
    assert demo["business_id"].startswith("SANDBOX-"), "demo business must be SANDBOX-prefixed"
    # every demo email is an .example address (never a real domain)
    for inv in demo["invoices"]:
        assert inv["email"].endswith(".example")


def test_ledger_default_path_is_gitignored_location():
    assert ledger.DEFAULT_PATH.startswith("ledger/")
