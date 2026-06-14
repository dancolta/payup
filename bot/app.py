"""PayUp Slack bot, Socket Mode entrypoint.

Run with: python -m bot.app  (needs the [bot] extra + the env secrets).

Socket Mode means no public URL / no inbound ports: the bot dials out to Slack.
Imports of slack_bolt / google libs are deferred to main() so the rest of the
package (and the test suite) never needs them installed.
"""

from __future__ import annotations

import os
import threading
from datetime import date

from payup.lib import quickbooks
from payup.lib.escalation import EscalationConfig
from payup.lib.planner import PayupConfig
from payup.lib.templating import TemplatingConfig

from .handlers import BotDeps, ChaseSession
from .scheduler import loop


def _require(name: str, hint: str = "") -> str:
    """Read a required env var, or exit with an actionable message (not a raw
    KeyError traceback) so a missing secret is obvious at startup."""
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"PayUp: missing required env var {name}. {hint}".rstrip())
    return val


def _load_gmail_creds():  # pragma: no cover - requires google libs + a real token
    from google.oauth2.credentials import Credentials

    token_path = os.environ.get("GMAIL_TOKEN_PATH", "config/token.json")
    if not os.path.exists(token_path):
        raise SystemExit(
            f"Gmail token not found at {token_path}. Run: python engine/scripts/gmail_oauth_setup.py"
        )
    return Credentials.from_authorized_user_file(
        token_path, ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
    )


def _load_escalation() -> EscalationConfig:
    """Escalation policy: load config/escalation.yml if present (and pyyaml is
    installed), then let explicit env vars override individual fields."""
    path = os.environ.get("PAYUP_ESCALATION_CONFIG", "config/escalation.yml")
    base = EscalationConfig.load(path if os.path.exists(path) else None)

    def _ovr(name: str, current: int) -> int:
        raw = os.environ.get(name)
        return int(raw) if raw else current

    return EscalationConfig(
        min_gap_days=_ovr("PAYUP_MIN_GAP_DAYS", base.min_gap_days),
        gentle_max_days=_ovr("PAYUP_GENTLE_MAX_DAYS", base.gentle_max_days),
        firm_max_days=_ovr("PAYUP_FIRM_MAX_DAYS", base.firm_max_days),
        final_min_priors=_ovr("PAYUP_FINAL_MIN_PRIORS", base.final_min_priors),
    )


def _build_deps() -> BotDeps:  # pragma: no cover
    source = os.environ.get("PAYUP_SOURCE", "quickbooks").lower()
    refresh_token = client_id = client_secret = None
    source_kwargs: dict = {}

    if source in ("quickbooks", "qbo"):
        token = _require("QBO_ACCESS_TOKEN", "Mint one from the Intuit OAuth Playground.")
        business_id = _require("QBO_REALM_ID", "Your QuickBooks sandbox/company (realm) id.")
        env = os.environ.get("PAYUP_QBO_ENV", "sandbox").lower()
        host = quickbooks.PRODUCTION_HOST if env == "production" else quickbooks.SANDBOX_HOST
        source_kwargs = {"host": host}
        # Optional: unattended hourly-token refresh (all three required to enable).
        refresh_token = os.environ.get("QBO_REFRESH_TOKEN") or None
        client_id = os.environ.get("QBO_CLIENT_ID") or None
        client_secret = os.environ.get("QBO_CLIENT_SECRET") or None
    elif source == "wave":
        token = _require("WAVE_API_TOKEN", "A full-access Wave GraphQL token (US/CA only).")
        business_id = _require("WAVE_BUSINESS_ID", "Your Wave business id.")
    else:
        raise SystemExit(f"PayUp: unknown PAYUP_SOURCE={source!r}. Use 'quickbooks' or 'wave'.")

    dry_run = os.environ.get("PAYUP_LIVE", "0") != "1"
    cfg = PayupConfig(
        escalation=_load_escalation(),
        templating=TemplatingConfig(
            sender_name=os.environ.get("PAYUP_SENDER", "Accounts"),
            business_name=os.environ.get("PAYUP_BUSINESS_NAME", "our team"),
        ),
    )
    return BotDeps(
        token=token,
        business_id=business_id,
        source_name=source,
        cfg=cfg,
        history_days=int(os.environ.get("PAYUP_HISTORY_DAYS", "90")),
        dry_run=dry_run,
        gmail_creds=_load_gmail_creds(),
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        source_kwargs=source_kwargs,
        ledger_path=os.environ.get("PAYUP_LEDGER", "ledger/runs.jsonl"),
        now_fn=date.today,
    )


def main() -> None:  # pragma: no cover - runtime only
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    channel_cfg = os.environ.get("SLACK_CHANNEL", "#payup")
    daily_at = os.environ.get("PAYUP_DAILY_AT", "09:00")

    deps = _build_deps()
    session = ChaseSession(deps)
    banner = "armed" if not deps.dry_run else "armed (dry-run)"

    app = App(token=_require("SLACK_BOT_TOKEN", "Bot token (xoxb-...) from your Slack app."))

    # Resolve the canonical channel id once. Socket Mode events carry channel
    # IDs (e.g. C0...), not names, so we key all state by the id the post lands
    # in. This is also what lets us ignore commands from other channels and DMs.
    try:
        resp = app.client.chat_postMessage(
            channel=channel_cfg,
            text=f"PayUp is online ({banner}). Daily check at {daily_at}. Say 'show overdue' anytime.",
        )
        channel_id = resp["channel"]
    except Exception as exc:
        print(
            f"PayUp: could not post to {channel_cfg} ({exc!r}). "
            "Invite the bot to that channel. Using the configured value as the key."
        )
        channel_id = channel_cfg

    def post_fn(ch: str, text: str) -> None:
        app.client.chat_postMessage(channel=ch, text=text)

    def _dispatch(event, say) -> None:
        # Only operate in the configured channel (never random channels or DMs).
        if event.get("channel") != channel_id:
            return
        reply = session.handle(
            channel_id,
            event.get("text", ""),
            # Dedupe Slack's double delivery of an @mention (app_mention + message).
            # `ts` (the message timestamp) is present and identical in both event
            # types for the same message, so it is the reliable shared key.
            event_id=event.get("ts") or event.get("client_msg_id"),
        )
        if reply is not None:
            say(reply)

    @app.event("app_mention")
    def on_mention(event, say):
        _dispatch(event, say)

    @app.event("message")
    def on_message(event, say):
        if event.get("bot_id") or event.get("subtype"):
            return
        _dispatch(event, say)

    print(f"PayUp Slack bot {banner}. HITL on. Daily check at {daily_at}.")

    # Daily timer in a background thread; it only posts, never sends.
    t = threading.Thread(target=loop, args=(session, channel_id, post_fn, daily_at), daemon=True)
    t.start()

    SocketModeHandler(app, _require("SLACK_APP_TOKEN", "App token (xapp-...) for Socket Mode.")).start()


if __name__ == "__main__":  # pragma: no cover
    main()
