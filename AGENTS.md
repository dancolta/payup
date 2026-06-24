# AGENTS.md

Instructions for any agent or contributor working on PayUp. This is the tool-agnostic
guide. Claude Code additionally reads `CLAUDE.md` (the fuller contributor contract) and
`CLAUDE.local.md` (private, gitignored). When those exist, follow them too; nothing here
contradicts them.

## What PayUp is

A tool that chases overdue invoices: it reads overdue-and-unpaid invoices from QuickBooks
(default) or Wave, drafts tiered reminders (gentle, firm, final), and sends them via Gmail
only after a human approves in Slack. It is state-light (no database) and it never moves money.

## Setup and commands

```bash
pip install -e '.[dev]'        # tests + lint
pytest                         # full suite, fully mocked, no network, under 2s
ruff check engine bot          # lint
claude plugin validate .       # plugin manifest gate (local)

# Dry-run a batch from a fixture (sends nothing):
PYTHONPATH=engine python3 -m payup.cli plan-chase \
  --invoices fixtures-sandbox/demo_business.json --now "$(date +%F)"

# Run the Slack bot locally (needs the [bot] extra + env secrets):
pip install -e '.[bot]'
PAYUP_LIVE=0 python -m bot.app   # dry-run: drafts but never sends
```

## Non-negotiable invariants (enforced by tests, do not weaken)

1. **No money movement.** The engine only reads from the accounting source. No payment,
   transfer, or refund code paths, and no GraphQL mutations.
2. **No send without explicit approval.** `gmail.send_message` raises unless `approved` is
   exactly `True`, before any network call. The Slack bot sends only on an explicit send
   intent. The CLI `send` refuses without `--approved-ids`.
3. **Resolve is source-only.** Chasing stops only because an invoice drops out of the overdue
   query (marked paid). A reply that claims payment is context only and never resolves.
4. **Final tier never threatens.** No legal, collections, or threat language
   (`templating.BLACKLIST`).
5. **Public-safe repo.** No secrets, no PII, no state files committed.
6. **No em dashes** in shipped output or docs. Use commas, periods, or restructure.

## Conventions

- Python 3.10+. The core engine (`engine/payup`) is stdlib-only. Bot and runtime deps live
  behind the `[bot]` extra and are imported lazily, so the engine and tests never require them.
- External HTTP to the accounting APIs and OAuth goes through `engine/payup/lib/net.py`
  (HTTPS-only, public-host-only, no redirects). Gmail is the one exception: it uses Google's
  official API client and is still gated by the approval check in `gmail.send_message`.
- The shared `Invoice` type lives in `engine/payup/lib/models.py`. Connectors parse into it;
  pure modules import it from `models`, not from a specific connector.
- Pure functions (escalation, templating, planner, intents, reply) take their inputs
  explicitly and are unit-tested on synthetic data with a fixed `NOW`. Tests never hit the
  network (connectors and Gmail expose mock seams).

## Definition of done

A change is not done until: `pytest` is green, `ruff check engine bot` is clean,
`claude plugin validate .` passes, and the guardrail suite holds (no money movement, no send
without approval, sandbox isolation, no secrets / em dashes / PII). New behavior ships with tests.

## Operating this repo for the maintainer

When doing setup, verification, or demo prep for the maintainer, run shell commands yourself rather than printing command lists for them to copy-paste. The maintainer handles only browser-only steps (OAuth consent, sign-in, third-party dashboards). Everything runnable from a shell (deps, file moves, scripts, tests, git) is the agent's job.

## Layout

```
engine/payup/lib/   models, quickbooks, wave, sources, gmail, escalation, templating,
                    planner, runner, reply, ledger, net, output
bot/                intents (pure NL parse), handlers (conversation + HITL gate),
                    scheduler (in-process daily timer), app (Socket Mode entry)
skills/ commands/ hooks/ .claude-plugin/   Claude Code plugin surface
engine/tests/ bot/tests/                   fully-mocked test suite
```
