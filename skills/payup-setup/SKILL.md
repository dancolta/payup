---
name: payup-setup
description: One-time setup wizard for PayUp, the overdue-invoice chaser. Walks through wiring a QuickBooks (or Wave) API token, running Gmail OAuth, verifying the sandbox (Gate 0), configuring escalation tiers, and deploying the always-on Slack bot. Use when the user says "set up payup", "/payup-setup", "configure invoice chaser", "connect quickbooks", or is installing PayUp for the first time.
allowed-tools: Bash, Read, Edit
---

# /payup-setup (onboarding)

Set up PayUp end to end. Operate it day to day from Slack; this wizard is the one-time wiring inside Claude Code.

PayUp is **state-light**: your accounting tool tells us who is overdue and unpaid (and resolves a chase when the invoice is marked paid), Gmail's sent history is the dedupe memory. There is no database. PayUp **never moves money**.

## Steps

Run these in order. Confirm each before moving on.

### 1. Invoice source + sandbox (Gate 0)
Default source is **QuickBooks** (works globally). Wave is also supported but only for US/Canada businesses.

QuickBooks:
- Create a free Intuit developer account + sandbox company at https://developer.intuit.com. The sandbox comes preloaded with sample invoices (some overdue).
- Mint an access token from the OAuth Playground (scope `com.intuit.quickbooks.accounting`). Put it in `.env` as `QBO_ACCESS_TOKEN` and your sandbox company id as `QBO_REALM_ID`. Keep `PAYUP_SOURCE=quickbooks`.
- QuickBooks access tokens expire hourly. For a one-off check a fresh token is fine. For the always-on bot, also set `QBO_REFRESH_TOKEN`, `QBO_CLIENT_ID`, and `QBO_CLIENT_SECRET` (all three) so PayUp renews the token itself before each daily run.

Then preview the batch (renders against the bundled sandbox seed, sends nothing):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m payup.cli plan-chase --invoices fixtures-sandbox/demo_business.json --now "$(date +%F)" 2>&1 || true
```

Confirm the batch renders. This is Gate 0: PayUp trusts the accounting tool for status, so make sure paid invoices drop out (Balance 0 in QuickBooks).

> Prefer Wave (US/CA)? Set `PAYUP_SOURCE=wave`, `WAVE_API_TOKEN`, `WAVE_BUSINESS_ID` instead.

### 2. Gmail OAuth (one-shot)
```bash
cd "$CLAUDE_PLUGIN_ROOT" && python3 engine/scripts/gmail_oauth_setup.py
```
This opens a consent screen once and writes `config/token.json` (gitignored). PayUp only ever sends after you approve in Slack.

### 3. Escalation tiers (optional)
Edit `config/escalation.yml` to taste (gentle/firm/final day bands, `min_gap_days`). Defaults are sensible.

### 4. Slack app (Socket Mode)
- Create an app at https://api.slack.com/apps, enable Socket Mode, add bot scopes `chat:write`, `app_mentions:read`, `channels:history`.
- Put `SLACK_BOT_TOKEN` (xoxb) and `SLACK_APP_TOKEN` (xapp) in `.env`, set `SLACK_CHANNEL`.

### 5. Deploy the bot
Local test:
```bash
cd "$CLAUDE_PLUGIN_ROOT" && pip install -e '.[bot]' && PAYUP_LIVE=0 python3 -m bot.app
```
`PAYUP_LIVE=0` keeps it in dry-run (drafts but never sends) until you are ready. Keep `PAYUP_QBO_ENV=sandbox` while testing; set it to `production` only when you are ready to chase your real QuickBooks company. For always-on hosting, see the deploy guide in `README.md` (Fly.io recommended).

## Safety reminders to surface
- Nothing sends without explicit approval, in both Claude and Slack.
- The "final" tier is firm but never threatens (no legal/collection language).
- Keep `PAYUP_LIVE=0` until the dry-run batch looks right.
