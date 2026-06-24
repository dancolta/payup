# PayUp: chase overdue invoices from Slack

> Replace Bill.com's AR/reminder slice with a near-$0 tool wired to your real stack. **It never moves money.**

PayUp watches **QuickBooks** for invoices that are overdue *and still unpaid*, drafts escalating-but-polite reminders (gentle, firm, final), and sends them via **Gmail**, but only after you approve, conversationally, from **Slack**. When the invoice is marked paid, chasing stops automatically. (Wave is supported too, for US/Canada businesses.)

- **Set it up in Claude Code.** Wire your QuickBooks token, Gmail, and tiers with the `/payup-setup` skill.
- **Run it from Slack.** An always-on bot posts your overdue batch; you reply `send 1 and 3`, `skip Delta`, or `show overdue`. Nothing sends until you say so.
- **No database.** Your accounting tool and Gmail are the source of truth.

## How it works

```
QuickBooks (overdue + unpaid) ─┐
                                ├─→ planner → tiered draft → Slack batch → you approve → Gmail send
Gmail sent-history (dedupe)   ─┘                                       (resolve = invoice marked paid)
```

- **QuickBooks** says who is overdue and still unpaid (Balance > 0, past due). A paid invoice drops out of the query, so chasing resolves itself. This is authoritative, not a guess from a reply that says "paid". Swappable: `PAYUP_SOURCE=wave` uses Wave instead.
- **Gmail sent-history** is the memory: a search keyed on the invoice number gives the prior-reminder count (for escalation) and the last-sent date (so we never re-nag inside `min_gap_days`).
- **Templates** produce the draft with no API key and no cost. (A Claude-polished wording step is planned for v1.1; today the deterministic templates are used as-is.)

## What runs automatically (and what does not)

The bot runs a daily timer on its always-on host. When it fires it **prepares and posts** the overdue batch to Slack, then stops. It does **not** send anything on its own.

| Automatic (no input from you) | Your call, every time |
|---|---|
| detect overdue-and-unpaid invoices in QuickBooks | approving a send |
| pick the tier (gentle / firm / final) | |
| draft the reminder | |
| skip anything chased inside `min_gap_days` | |
| drop invoices that get marked paid | |
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
| `QBO_ACCESS_TOKEN`, `QBO_REALM_ID` | https://developer.intuit.com (free sandbox company + OAuth Playground token) |
| Gmail OAuth (`config/token.json`) | run `python engine/scripts/gmail_oauth_setup.py` once |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | https://api.slack.com/apps (enable Socket Mode) |
| `QBO_REFRESH_TOKEN` + `QBO_CLIENT_ID` + `QBO_CLIENT_SECRET` *(for always-on)* | so the bot renews the hourly QBO access token itself |

> Using Wave instead (US/Canada only)? Set `PAYUP_SOURCE=wave` and provide `WAVE_API_TOKEN` + `WAVE_BUSINESS_ID`.
>
> `ANTHROPIC_API_KEY` is reserved for a planned v1.1 draft-polish step and has no effect yet.

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
fly secrets set QBO_ACCESS_TOKEN=... QBO_REALM_ID=... \
                QBO_REFRESH_TOKEN=... QBO_CLIENT_ID=... QBO_CLIENT_SECRET=... \
                SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... \
                PAYUP_LIVE=1
fly deploy
```
Railway, Render, a small VPS, or any machine that stays on will work the same way (`docker build` + run with the env vars).

> QuickBooks access tokens expire hourly. For an always-on bot, set `QBO_REFRESH_TOKEN` + `QBO_CLIENT_ID` + `QBO_CLIENT_SECRET` so PayUp renews the token before each daily run; otherwise it works only until the first token expires. Set `PAYUP_QBO_ENV=production` to point at your real company (the default is the Intuit sandbox).

## Slack commands

| You say | PayUp does |
|---|---|
| `show overdue` | rebuild and post the current batch |
| `send all` | send every reminder in the batch |
| `send 1 and 3` | send specific rows |
| `draft all` | save every reminder as a Gmail draft (sends nothing) |
| `draft 1 and 3` | save specific rows as Gmail drafts |
| `skip Delta` | drop a row (sends nothing) |
| `help` | list commands |

Anything ambiguous is treated as "do nothing" and PayUp asks you to clarify. It never sends on a guess.

### Draft vs send

`draft` saves the reminder into your Gmail Drafts folder instead of sending it. Use it when you want to tweak the wording, add a line, or eyeball the message in Gmail before it goes out. Open Gmail, review or edit the draft, and hit send yourself.

A draft is **not** a chase. PayUp only counts an invoice as chased once a reminder actually lands in your Sent mail (the dedupe key is the invoice number in the subject of a sent message). So a drafted invoice still shows up in the next batch until you send it. `draft` gets the same guards as `send`: a question or a negation ("should I draft these?", "do not draft all") is treated as "do nothing".

### Customizing templates

The reminder wording lives in [config/templates.yml](config/templates.yml), one `subject` plus `body` block per tier (gentle, firm, final). Edit it to match your voice; anything you leave out keeps the built-in default. Available placeholders:

```
{customer_name}  {invoice_number}  {amount}  {due_date}  {sender_name}  {business_name}
```

Two rules are enforced at render time on every draft, including your custom copy:

- the **subject must contain `{invoice_number}`** (it is the Gmail dedupe key), and
- no legal / collections / threat language and **no em dashes**.

Break either and PayUp refuses to render that draft rather than send something off-key. Point at a different file with `PAYUP_TEMPLATES_CONFIG`.

> Draft support added the `gmail.compose` scope. If you set PayUp up before drafts existed, delete `config/token.json` and re-run `python engine/scripts/gmail_oauth_setup.py` to re-consent.

## Development

```bash
pip install -e '.[dev]'
ruff check engine bot
pytest                 # fully mocked, runs in well under 2 seconds
```

Architecture and conventions: see [CLAUDE.md](CLAUDE.md).

## License

MIT. See [LICENSE](LICENSE).
