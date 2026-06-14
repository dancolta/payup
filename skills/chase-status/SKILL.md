---
name: chase-status
description: Show recent PayUp activity from the local run ledger (how many reminders were sent and skipped on recent runs). Use when the user says "chase status", "/chase-status", "payup status", "what did payup do", or wants a quick audit of recent invoice-chasing runs.
allowed-tools: Bash, Read
---

# /chase-status (recent runs)

Read the local JSONL ledger and show recent runs. The ledger is a convenience log only; your accounting tool (QuickBooks or Wave) and Gmail remain the source of truth.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m payup.cli status --limit 20
```

If nothing prints, PayUp has not recorded a run yet (or the bot is hosted elsewhere and writes its ledger there).
