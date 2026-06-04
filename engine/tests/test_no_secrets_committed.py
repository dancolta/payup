"""Story A3 — no secrets / no PII state files in the tracked tree.

Scans tracked files for credential-looking patterns and for any committed
ledger/token artifacts that must stay local.
"""

import os
import re
import subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SECRET_PATTERNS = [
    re.compile(r"xoxb-[A-Za-z0-9-]{10,}"),          # Slack bot token
    re.compile(r"xapp-[A-Za-z0-9-]{10,}"),          # Slack app token
    re.compile(r"sk-ant-[A-Za-z0-9-]{10,}"),        # Anthropic key
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),         # Google API key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# Placeholders that are allowed to appear in examples/docs.
ALLOW = ("xoxb-...", "xapp-...", "sk-ant-...")

FORBIDDEN_TRACKED = ("config/token.json", "config/oauth.json", ".env")


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True
    )
    return [f for f in out.stdout.splitlines() if f.strip()]


def test_no_secret_patterns_in_tracked_files():
    offenders = []
    for rel in _tracked_files():
        path = os.path.join(REPO, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(content):
                if m.group(0) in ALLOW:
                    continue
                offenders.append(f"{rel}: {m.group(0)[:12]}...")
    assert not offenders, f"possible secret committed: {offenders}"


def test_no_state_or_secret_files_tracked():
    tracked = set(_tracked_files())
    for forbidden in FORBIDDEN_TRACKED:
        assert forbidden not in tracked, f"{forbidden} must not be tracked"
    assert not any(f.endswith(".jsonl") for f in tracked), "ledger .jsonl must not be tracked"
