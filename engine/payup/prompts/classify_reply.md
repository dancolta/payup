# Reply classification prompt (optional LLM path)

The deterministic `reply.classify_reply()` is the shipped default. When an
Anthropic key is configured, the bot may use this prompt for a sharper read.
The result is **context only**. It must never decide to stop chasing: resolve is
owned entirely by Wave invoice status.

System intent:

> You label a single inbound reply to a payment reminder. Return one of:
> `paid`, `will_pay`, `dispute`, `silence`, `unknown`, plus a confidence 0..1.
> Do not infer payment from optimism. "I'll sort it out" is `will_pay`, not
> `paid`. A complaint about the invoice is `dispute`. Never recommend stopping a
> chase; that decision belongs to the accounting system, not the email text.

Output JSON: `{"label": "...", "confidence": 0.0}`
