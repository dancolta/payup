# PayUp: chase overdue invoices from Slack

> Replace Bill.com's AR/reminder slice with a near-$0 tool wired to your real stack. **It never moves money.**

PayUp watches **Wave** for invoices that are overdue *and still unpaid*, drafts escalating-but-polite reminders (gentle, firm, final), and sends them via **Gmail**, but only after you approve, conversationally, from **Slack**. When Wave marks an invoice paid, chasing stops automatically.

- **Set it up in Claude Code.** Wire your Wave token, Gmail, and tiers with the `payup-setup` skill.
- **Run it from Slack.** An always-on bot posts your overdue batch; you reply `send 1 and 3`, `skip Delta`, or `show overdue`. Nothing sends until you say so.
- **No database.** Wave and Gmail are the source of truth.

Status: 🚧 building in public toward v1. See [`_bmad-output/planning-artifacts/`](#) for the plan (local), and the issues board for progress.

## How it works
```
Wave (who's overdue + unpaid)  ─┐
                                 ├─→ planner → tiered draft → Slack batch → you approve → Gmail send
Gmail sent-history (dedupe)    ─┘                                         (resolve = Wave marks it paid)
```

## What it will never do
No payment rails. No moving money. No collections or legal escalation. It chases; it never pays.

## License
MIT. See [LICENSE](LICENSE).
