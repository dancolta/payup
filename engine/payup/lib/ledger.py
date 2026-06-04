"""Optional local run ledger (append-only JSONL).

NOT authoritative. Wave + Gmail are the source of truth; this only powers a fast
`status` view and a human-readable audit of what the bot did. It lives on the
bot host and is gitignored (it can contain customer-identifying data).
"""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = ["append_run", "recent", "DEFAULT_PATH"]

DEFAULT_PATH = os.environ.get("PAYUP_LEDGER", "ledger/runs.jsonl")


def append_run(record: dict[str, Any], path: str = DEFAULT_PATH) -> None:
    """Append one JSON record as a line. Creates the directory if needed."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), sort_keys=True)
    # Restrictive perms: this file may hold customer data.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def recent(n: int = 20, path: str = DEFAULT_PATH) -> list[dict[str, Any]]:
    """Return the last `n` records (oldest-first within the window)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
