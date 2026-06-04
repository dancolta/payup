#!/usr/bin/env python3
"""One-shot Gmail OAuth consent. Produces config/token.json (gitignored).

Run once during setup:  python engine/scripts/gmail_oauth_setup.py

Requires the [bot] extra (google-auth-oauthlib). PayUp asks only for send +
read scopes. The token is stored with owner-only permissions and is never
committed.
"""

from __future__ import annotations

import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def main() -> int:
    client_path = os.environ.get("GMAIL_OAUTH_CLIENT", "config/oauth_client.json")
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "config/token.json")

    if not os.path.exists(client_path):
        print(
            f"OAuth client secret not found at {client_path}.\n"
            "Create an OAuth client (Desktop app) in Google Cloud Console, download the\n"
            "JSON, and save it there (or set GMAIL_OAUTH_CLIENT).",
            file=sys.stderr,
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception:
        print(
            "Missing dependency. Install the bot extra first:  pip install -e '.[bot]'",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
    creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, creds.to_json().encode("utf-8"))
    finally:
        os.close(fd)
    print(f"Saved Gmail token to {token_path} (owner-only). Setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
