# CLAUDE.md: contributor guide for PayUp

This is the public contract for anyone (human or agent) working on PayUp. Read it before changing code.

## What PayUp is

A tool that chases overdue invoices: reads overdue-and-unpaid invoices from QuickBooks (or Wave), drafts tiered reminders, and sends them via Gmail after a human approves in Slack. It is **state-light** (no database) and it **never moves money**.

## The non-negotiable invariants

These are enforced by tests in `engine/tests/test_guardrails.py` and friends. Do not weaken them.

1. **No money movement.** The engine only ever reads from the accounting source (QuickBooks/Wave). No mutations, no payment/transfer/refund code paths. `test_no_money_movement_symbols` scans for this.
2. **No send without explicit approval.** `gmail.send_message` raises if `approved` is not `True`, before any network call. The Slack bot sends only on an explicit send intent. The CLI `send` refuses without `--approved-ids`.
3. **Resolve is source-only.** Whether to stop chasing is decided by the accounting tool's status (paid invoice drops out of the overdue query). A reply that claims payment is context only and never resolves.
4. **Final tier never threatens.** No legal / collections / threat language. `templating.BLACKLIST` is enforced by `test_no_legal_or_collection_language`.
5. **Public-safe repo.** No secrets, no PII, no state files committed. `test_no_secrets_committed` + `.gitignore` guard this.
6. **No em dashes** in shipped output or docs. `test_no_em_dashes` enforces it.

## Architecture (state-light)

```
bot/            Slack bot (Socket Mode): intents.py (pure NL parse), handlers.py
                (conversation + HITL gate), scheduler.py (daily timer), app.py (entry)
engine/payup/
  lib/models.py       the shared Invoice type all connectors parse into.
  lib/quickbooks.py   read-only QBO connector (overdue + unpaid). Default source of truth #1.
  lib/wave.py         read-only Wave connector (US/CA alternative). Same Invoice shape.
  lib/sources.py      source registry: name -> list_overdue_unpaid (default quickbooks).
  lib/gmail.py        the ONLY network-write. send (approval-gated), prior_reminders
                      (dedupe + tier count, source of truth #2), thread replies (context).
  lib/escalation.py   pure tier selection (gentle/firm/final, min_gap hold).
  lib/templating.py   pure draft rendering. Subject carries the invoice number (dedupe key).
  lib/planner.py      pure: joins source + Gmail -> Action | Skip.
  lib/runner.py       build_plan (fetch + join) and execute (send approved only).
  lib/reply.py        pure reply classifier. Context only, never resolves.
  lib/ledger.py       optional local JSONL (status view only, not authoritative).
  lib/net.py          SSRF-guarded HTTPS transport (no redirects). Choke point for
                      all non-Gmail HTTP (QuickBooks, Wave, OAuth refresh).
  cli.py              plan-chase | send | status. Shared by skills + humans.
skills/, commands/, hooks/   Claude Code plugin surface (setup + dry-run).
```

The accounting source (QuickBooks/Wave) and Gmail are the source of truth. There is no database; the ledger is a convenience log only.

## Running

```bash
pip install -e '.[dev]'   # tests + lint
pytest                    # fully mocked, < 2s
ruff check engine bot
claude plugin validate .  # plugin manifest gate (local)

PYTHONPATH=engine python3 -m payup.cli plan-chase \
  --invoices fixtures-sandbox/demo_business.json --now "$(date +%F)"
```

## Conventions

- Python 3.10+, stdlib-only core engine. Bot/runtime deps live behind the `[bot]` extra and are imported lazily, so the engine and tests never require them.
- External HTTP to the accounting APIs and OAuth goes through `net.py` (HTTPS-only, public-host-only, no redirects). The one exception is Gmail, which uses Google's official API client and manages its own transport; that path is still gated by the approval check in `gmail.send_message`. Tests never hit the network: QuickBooks mocks `_query`, Wave mocks `_post_graphql`, Gmail injects a fake transport.
- Pure functions (escalation, templating, planner, intents, reply) take their inputs explicitly and are unit-tested on synthetic data with a fixed `NOW`.
- New behaviour ships with tests, and the guardrail suite must stay green.
