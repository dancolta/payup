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
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"),      # Google OAuth client secret
    re.compile(r"\b1//[A-Za-z0-9_\-]{30,}"),        # Google OAuth refresh token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# Placeholders that are allowed to appear in examples/docs.
ALLOW = ("xoxb-...", "xapp-...", "sk-ant-...")

# Credential / state files that must never be tracked. config/oauth_client.json
# is the Google OAuth client secret this project actually downloads.
FORBIDDEN_TRACKED = (
    "config/token.json",
    "config/oauth.json",
    "config/oauth_client.json",
    ".env",
)


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True
    )
    # Fail loudly rather than passing vacuously: an empty list from a broken git
    # invocation would make every scan below trivially "clean".
    assert out.returncode == 0, f"git ls-files failed: {out.stderr.strip()}"
    files = [f for f in out.stdout.splitlines() if f.strip()]
    assert files, "git ls-files returned no tracked files (not a repo?)"
    return files


def test_secret_patterns_match_known_credential_shapes():
    # Guards the guard: the patterns must actually fire on real secret shapes.
    # Built by concatenation so these samples are not themselves scannable
    # literals in this tracked file.
    samples = [
        "xoxb-" + "1234567890-abcdEFGH",
        "xapp-" + "1-A012-secrettokenvalue",
        "GOCSPX-" + "abcdEFGH1234567890wxyz",
        "1//" + "0gAbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    ]
    for s in samples:
        assert any(p.search(s) for p in SECRET_PATTERNS), f"no pattern matched {s!r}"


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
