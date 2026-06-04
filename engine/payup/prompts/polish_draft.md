# Draft polish prompt (optional LLM path)

The deterministic `templating.render_email()` is the shipped draft and needs no
API key. When `ANTHROPIC_API_KEY` is set, the bot may polish the wording with
this prompt. The hard constraints below are non-negotiable and are also enforced
by tests, so polish can refine tone but can never cross the line.

System intent:

> Rewrite this payment reminder to sound warm and human while keeping it concise.
> Hard rules: keep the invoice number, amount, and due date exactly. Keep the
> subject line containing the invoice number. Never add legal, collections, or
> threatening language. Never imply you will move money or take action beyond
> asking for payment. No em dashes.

Input: the rendered draft (subject + body) and the tier.
Output: the polished subject and body only.
