"""The plugin manifest + skill frontmatter stay valid. Mirrors the local
`claude plugin validate .` gate and the CI step, but runs with no external CLI so
a broken plugin.json / marketplace.json / SKILL.md is caught by the test suite too.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "engine" / "scripts" / "validate_plugin.py"


def test_validator_exists():
    assert VALIDATOR.exists(), VALIDATOR


def test_plugin_manifest_and_skills_valid():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
