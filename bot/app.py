"""PayUp Slack bot, Socket Mode entrypoint.

Run with: python -m bot.app  (needs the [bot] extra + the 4 env secrets).

Socket Mode means no public URL / no inbound ports: the bot dials out to Slack.
Imports of slack_bolt / google libs are deferred to main() so the rest of the
package (and the test suite) never needs them installed.
"""

from __future__ import annotations

import os
import threading
from datetime import date

from payup.lib.planner import PayupConfig
from payup.lib.templating import TemplatingConfig

from .handlers import BotDeps, ChaseSession
from .scheduler import loop


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


def _build_deps() -> BotDeps:  # pragma: no cover
    source = os.environ.get("PAYUP_SOURCE", "quickbooks").lower()
    if source in ("quickbooks", "qbo"):
        token = os.environ["QBO_ACCESS_TOKEN"]
        business_id = os.environ["QBO_REALM_ID"]
    else:  # wave (US/CA only)
        token = os.environ["WAVE_API_TOKEN"]
        business_id = os.environ["WAVE_BUSINESS_ID"]
    dry_run = os.environ.get("PAYUP_LIVE", "0") != "1"
    cfg = PayupConfig(
        templating=TemplatingConfig(
            sender_name=os.environ.get("PAYUP_SENDER", "Accounts"),
            business_name=os.environ.get("PAYUP_BUSINESS_NAME", "our team"),
        )
    )
    return BotDeps(
        token=token,
        business_id=business_id,
        source_name=source,
        cfg=cfg,
        lookback_days=int(os.environ.get("PAYUP_MIN_GAP_DAYS", "7")),
        dry_run=dry_run,
        gmail_creds=_load_gmail_creds(),
        now_fn=date.today,
    )


def main() -> None:  # pragma: no cover - runtime only
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    channel = os.environ.get("SLACK_CHANNEL", "#payup")
    daily_at = os.environ.get("PAYUP_DAILY_AT", "09:00")

    deps = _build_deps()
    session = ChaseSession(deps)

    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    def post_fn(ch: str, text: str) -> None:
        app.client.chat_postMessage(channel=ch, text=text)

    @app.event("app_mention")
    def on_mention(event, say):
        text = event.get("text", "")
        say(session.handle(event.get("channel", channel), text))

    @app.event("message")
    def on_message(event, say):
        if event.get("bot_id") or event.get("subtype"):
            return
        reply = session.handle(event.get("channel", channel), event.get("text", ""))
        say(reply)

    banner = "armed" if not deps.dry_run else "armed (dry-run)"
    print(f"PayUp Slack bot {banner}. HITL on. Daily check at {daily_at}.")

    # Daily timer in a background thread; it only posts, never sends.
    t = threading.Thread(target=loop, args=(session, channel, post_fn, daily_at), daemon=True)
    t.start()

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":  # pragma: no cover
    main()
