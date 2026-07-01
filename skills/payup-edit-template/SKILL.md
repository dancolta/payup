---
name: payup-edit-template
description: Rewrite PayUp's overdue-invoice reminder emails in the user's own tone of voice. Reads the current gentle/firm/final templates, learns the user's voice from a description or a pasted sample, rewrites the copy while keeping every placeholder, and validates it against the guardrails before saving. Use when the user says "edit template", "/payup-edit-template", "change the reminder wording", "rewrite the emails in my voice", "make the reminders sound like me", or "edit payup templates".
allowed-tools: Bash, Read, Edit, Write
---

# /payup-edit-template (reminder copy in your voice)

Rewrite the three reminder tiers (gentle, firm, final) so they sound like the user, without breaking any of PayUp's safety rules. This edits `config/templates.yml` only. It touches no tokens, no secrets, and sends nothing.

> For a quick change the user can also do it from Slack: `@PayUp edit template` walks them through one reminder at a time. This skill is the fuller path: it rewrites all three tiers in the user's voice in one pass.

## What you are editing

`config/templates.yml` holds a `subject` and `body` per tier. Placeholders auto-fill at send time:
`{customer_name}` `{invoice_number}` `{amount}` `{due_date}` `{sender_name}` `{business_name}`.
Anything a tier omits falls back to the built-in default.

Three rules are enforced on every rendered draft (yours included). Keep them or the bot refuses to render:
1. The **subject must contain `{invoice_number}`** (it is the Gmail dedupe key).
2. **No legal / collections / threat language** (no lawyer, court, collections, penalty, garnish, etc.).
3. **No em dashes** anywhere. Use commas, periods, or restructure.

Tone still escalates gentle -> firm -> final, but "final" stays firm, never a threat.

## Steps

### 1. Show the current copy
Read `config/templates.yml` (or the path in `PAYUP_TEMPLATES_CONFIG`). Show the user the current gentle/firm/final subject + body so they know the starting point. If the file is missing, say the built-in defaults are in effect and offer to create the file.

### 2. Learn their voice
Ask the user how they want the reminders to sound. Accept either:
- **A description**: e.g. "warm and casual", "short and formal", "British, dry, no exclamation marks", plus their sign-off.
- **A sample they wrote**: paste any email/message in their real voice and mirror its register, sentence length, and greeting/closing style.

Also confirm `{sender_name}` and `{business_name}` are set the way they want (these come from `PAYUP_SENDER` / `PAYUP_BUSINESS_NAME` in `.env`, not the template file). Offer to update those env values if they ask, but do not touch any other line in `.env`.

### 3. Rewrite the three tiers
Rewrite `gentle`, `firm`, and `final` subject + body in their voice. Rules while rewriting:
- Keep at least `{invoice_number}` in every **subject**, and keep `{amount}` and `{due_date}` in the body where they make sense.
- Preserve the escalation: gentle = friendly nudge, firm = clear ask for a date, final = firm last call that still offers a way to resolve.
- Never introduce a blacklisted term or an em dash. If the user's own sample contains one, keep their voice but swap the specific word/punctuation and tell them you did.
- Write the full `config/templates.yml` (all three tiers) so the file is self-contained and easy to read.

### 4. Validate before you finish (hard gate)
Run the guardrail check and only report success if it passes:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m payup.cli validate-templates
```

- If it prints `All template tiers pass the guardrails`, show the user a short before/after of each tier and you are done.
- If any tier prints `FAIL`, read the reason, fix that tier in `config/templates.yml` (restore the missing `{invoice_number}`, replace the blacklisted word, or drop the em dash), and run the check again. Do not stop on a FAIL.

### 5. Note for the running bot
If the Slack bot is already running, remind the user the new copy loads on the **next bot restart** (templates are read at startup). No resend of anything already sent.

## Do not
- Do not edit `.env`, `config/token.json`, `config/oauth_client.json`, or any OAuth/token value. Voice editing never needs them.
- Do not weaken or remove the guardrails to make a template "pass". Fix the copy instead.
- Do not send, draft, or trigger a chase. This skill only rewrites wording.
