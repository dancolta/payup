# PayUp: chase overdue invoices from Slack

> Replace Bill.com's AR/reminder slice with a near-$0 tool wired to your real stack. **It never moves money.**

PayUp watches **Wave** for invoices that are overdue *and still unpaid*, drafts escalating-but-polite reminders (gentle, firm, final), and sends them via **Gmail**, but only after you approve, conversationally, from **Slack**. When Wave marks an invoice paid, chasing stops automatically.

- **Set it up in Claude Code.** Wire your Wave token, Gmail, and tiers with the `/payup-setup` skill.
- **Run it from Slack.** An always-on bot posts your overdue batch; you reply `send 1 and 3`, `skip Delta`, or `show overdue`. Nothing sends until you say so.
- **No database.** Wave and Gmail are the source of truth.

## How it works

```
Wave (overdue + unpaid)   ─┐
                            ├─→ planner → tiered draft → Slack batch → you approve → Gmail send
Gmail sent-history (dedupe)─┘                                       (resolve = Wave marks it paid)
```

- **Wave** says who is overdue and still unpaid. A paid invoice drops out of the query, so chasing resolves itself. This is authoritative, not a guess from a reply that says "paid".
- **Gmail sent-history** is the memory: a search keyed on the invoice number gives the prior-reminder count (for escalation) and the last-sent date (so we never re-nag inside `min_gap_days`).
- **Templates** produce the draft with no API key and no cost. An optional Claude polish is available if you set `ANTHROPIC_API_KEY`.

## What runs automatically (and what does not)

The bot runs a daily timer on its always-on host. When it fires it **prepares and posts** the overdue batch to Slack, then stops. It does **not** send anything on its own.

| Automatic (no input from you) | Your call, every time |
|---|---|
| detect overdue-and-unpaid invoices in Wave | approving a send |
| pick the tier (gentle / firm / final) | |
| draft the reminder | |
| skip anything chased inside `min_gap_days` | |
| drop invoices Wave marks paid | |
| post the batch to Slack on schedule | |

So "runs on a schedule" means it does all the busywork daily and hands you a ready-to-approve batch. The actual Gmail send always waits for you to say `send all` or `send 1 and 3`. Nothing reaches a client unsupervised.

> The scheduler calls `refresh` (post the batch), never `execute` (send). See [bot/scheduler.py](bot/scheduler.py).

## What it will never do

No payment rails. No moving money. No collections or legal escalation. The "final" tier is firm but never threatens. It chases; it never pays. These are enforced by tests, not just intentions.

## Quick start

### 1. Install (Claude Code plugin, for setup)
Add the repo as a local marketplace and install the `payup` plugin, then run `/payup-setup`. It walks you through everything below.

### 2. Wire the secrets
Copy `.env.example` to `.env` and fill in:

| Secret | Where it comes from |
|---|---|
| `WAVE_API_TOKEN`, `WAVE_BUSINESS_ID` | https://developer.waveapps.com (free, create a sandbox Business) |
| Gmail OAuth (`config/token.json`) | run `python engine/scripts/gmail_oauth_setup.py` once |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | https://api.slack.com/apps (enable Socket Mode) |
| `ANTHROPIC_API_KEY` *(optional)* | only if you want LLM-polished wording |

### 3. Preview without sending
```bash
PYTHONPATH=engine python3 -m payup.cli plan-chase \
  --invoices fixtures-sandbox/demo_business.json --now "$(date +%F)"
```

### 4. Run the bot
```bash
pip install -e '.[bot]'
PAYUP_LIVE=0 python3 -m bot.app     # dry-run: drafts but never sends
```
Set `PAYUP_LIVE=1` when the dry-run batch looks right.

## Deploy (always-on)

The bot needs to stay running so its daily timer ticks even when your laptop is off. Socket Mode means **no public URL and no inbound ports**, so any always-on host works.

**Fly.io (recommended):**
```bash
fly launch --no-deploy            # rename the app in fly.toml
fly secrets set WAVE_API_TOKEN=... WAVE_BUSINESS_ID=... \
                SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... \
                PAYUP_LIVE=1
fly deploy
```
Railway, Render, a small VPS, or any machine that stays on will work the same way (`docker build` + run with the env vars).

## Slack commands

| You say | PayUp does |
|---|---|
| `show overdue` | rebuild and post the current batch |
| `send all` | send every reminder in the batch |
| `send 1 and 3` | send specific rows |
| `skip Delta` | drop a row (sends nothing) |
| `help` | list commands |

Anything ambiguous is treated as "do nothing" and PayUp asks you to clarify. It never sends on a guess.

## Development

```bash
pip install -e '.[dev]'
ruff check engine bot
pytest                 # fully mocked, runs in well under 2 seconds
```

Architecture and conventions: see [CLAUDE.md](CLAUDE.md).

## License

MIT. See [LICENSE](LICENSE).
