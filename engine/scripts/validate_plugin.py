#!/usr/bin/env python3
"""Lightweight plugin-manifest + skills validator.

Catches the regressions `claude plugin validate .` catches (broken plugin.json /
marketplace.json / SKILL.md frontmatter) but with zero external dependency, so it
runs both in CI (where the claude CLI is not installed) and as a pytest. It does
NOT replace the local `claude plugin validate .` gate; it is a cheap always-on
backstop for the same failure modes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# engine/scripts/validate_plugin.py -> parents[2] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _check_json(path: Path, required: tuple[str, ...]) -> list[str]:
    if not path.exists():
        return [f"missing file: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON ({exc})"]
    return [f"{path}: missing required key {key!r}" for key in required if key not in data]


def _check_skill_frontmatter(skill_md: Path) -> list[str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return [f"{skill_md}: missing YAML frontmatter (--- block)"]
    end = text.find("\n---", 3)
    if end == -1:
        return [f"{skill_md}: unterminated frontmatter"]
    front = text[3:end]
    return [f"{skill_md}: frontmatter missing {key}" for key in ("name:", "description:") if key not in front]


def validate(root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    errors += _check_json(root / ".claude-plugin" / "plugin.json", ("name", "version", "description"))
    errors += _check_json(root / ".claude-plugin" / "marketplace.json", ("name", "plugins"))

    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    if not skill_files:
        errors.append(f"no skills found under {root / 'skills'}")
    for skill_md in skill_files:
        errors += _check_skill_frontmatter(skill_md)
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Plugin validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("Plugin manifest + skills OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
