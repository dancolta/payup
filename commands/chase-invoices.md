---
description: Preview the overdue-invoice chase batch (dry-run, sends nothing).
---

Run the PayUp dry-run preview by following the `chase-invoices` skill: render the proposed batch of tiered reminder drafts for the current overdue-and-unpaid invoices, without sending anything.

If the user passes an invoices JSON path as an argument, use it; otherwise default to the sandbox seed `fixtures-sandbox/demo_business.json`.
