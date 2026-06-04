"""PayUp CLI. Thin entry point shared by the bot, the Claude Code skills, and a
human at a terminal.

Safety: the `send` subcommand refuses to do anything without explicit
`--approved-ids`. Absence of approval is a dry-run that sends nothing and writes
nothing. This is asserted by the guardrail tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from .lib import ledger, output
from .lib.planner import PayupConfig, plan_chase
from .lib.wave import Invoice


def _load_invoices_from_json(path: str, *, now: date) -> list[Invoice]:
    from .lib.wave import _parse_invoice  # reuse the same parser

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    edges = (
        data.get("data", {})
        .get("business", {})
        .get("invoices", {})
        .get("edges", [])
    )
    out = []
    for edge in edges:
        inv = _parse_invoice(edge.get("node", {}))
        if inv.is_paid or inv.due_date >= now:
            continue
        out.append(inv)
    return out


def _cmd_plan(args) -> int:
    now = date.fromisoformat(args.now) if args.now else date.today()
    invoices = _load_invoices_from_json(args.invoices, now=now)
    plan = plan_chase(invoices, {}, now=now, cfg=PayupConfig())
    print(output.render_batch(plan, now=now))
    return 0


def _cmd_send(args) -> int:
    # HARD GATE: no approved ids -> dry-run, nothing leaves the machine.
    if not args.approved_ids:
        print(
            "No --approved-ids provided. Nothing was sent (dry-run). "
            "This command never sends without explicit approval.",
            file=sys.stderr,
        )
        return 0
    live = os.environ.get("PAYUP_LIVE", "0") == "1"
    if not live:
        print(
            "PAYUP_LIVE is not 1, so this is a dry-run. "
            f"Would send to approved ids: {args.approved_ids}",
            file=sys.stderr,
        )
        return 0
    # Live send path is exercised by the bot with a real transport; the CLI keeps
    # the gate explicit and refuses to improvise credentials here.
    print(
        "Live CLI send is intentionally not wired. Operate sends through the "
        "Slack bot, which holds the approved transport.",
        file=sys.stderr,
    )
    return 0


def _cmd_status(args) -> int:
    records = ledger.recent(args.limit)
    if not records:
        print("No runs recorded yet.")
        return 0
    for rec in records:
        print(json.dumps(rec, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="payup", description="Chase overdue invoices. Never moves money.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan-chase", help="Render the proposed chase batch (dry).")
    p_plan.add_argument("--invoices", required=True, help="Path to a Wave-shaped invoices JSON.")
    p_plan.add_argument("--now", help="Override today (YYYY-MM-DD).")
    p_plan.set_defaults(func=_cmd_plan)

    p_send = sub.add_parser("send", help="Send approved reminders. Refuses without --approved-ids.")
    p_send.add_argument("--approved-ids", nargs="*", default=[], help="Invoice ids approved to send.")
    p_send.set_defaults(func=_cmd_send)

    p_status = sub.add_parser("status", help="Show recent runs from the local ledger.")
    p_status.add_argument("--limit", type=int, default=20)
    p_status.set_defaults(func=_cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
