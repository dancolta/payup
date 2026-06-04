"""Story A3 — no em dashes anywhere the tool speaks (or in shipped docs).

Dan's house rule, enforced as a build gate.
"""

import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCAN_DIRS = ["engine/payup", "bot", "skills", "commands", "hooks", "config"]
SCAN_FILES = ["README.md", "CLAUDE.md"]
EXTS = {".py", ".md", ".yml", ".yaml", ".json", ".toml"}
EM_DASH = "—"


def _iter_files():
    for d in SCAN_DIRS:
        base = os.path.join(REPO, d)
        for root, _, files in os.walk(base):
            for f in files:
                if os.path.splitext(f)[1] in EXTS:
                    yield os.path.join(root, f)
    for f in SCAN_FILES:
        p = os.path.join(REPO, f)
        if os.path.exists(p):
            yield p


def test_no_em_dashes_in_source_or_docs():
    offenders = []
    for path in _iter_files():
        try:
            with open(path, encoding="utf-8") as fh:
                if EM_DASH in fh.read():
                    offenders.append(os.path.relpath(path, REPO))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    assert not offenders, f"em dash found in: {offenders}"
