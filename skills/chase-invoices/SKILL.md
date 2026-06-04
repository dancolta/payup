---
name: chase-invoices
description: Dry-run the overdue-invoice chase inside Claude Code. Renders the proposed batch of tiered reminder drafts (gentle, firm, final) for the current overdue-and-unpaid invoices, without sending anything. Use when the user says "chase invoices", "/chase-invoices", "show overdue invoices", "preview reminders", or wants to see what PayUp would send before operating from Slack.
allowed-tools: Bash, Read
---

# /chase-invoices (dry-run preview)

Render the proposed chase batch in chat. This is the same plan the Slack bot posts, shown here for setup and demos. It **sends nothing**.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m payup.cli plan-chase \
  --invoices "${PAYUP_INVOICES:-fixtures-sandbox/demo_business.json}" \
  --now "$(date +%F)"
```

The output lists each overdue-and-unpaid invoice with its tier and days late, plus how many were skipped for being inside the no-nag window.

To actually send, operate from Slack (the bot holds the approved Gmail transport). The CLI `send` subcommand intentionally refuses without explicit `--approved-ids`, and even then defers live sending to the bot:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m payup.cli send   # prints a refusal, sends nothing
```

Reminders escalate by how overdue an invoice is and how many times it was already chased. A reminder is never sent twice inside `min_gap_days`, and an invoice paid in Wave drops out of the batch automatically.
