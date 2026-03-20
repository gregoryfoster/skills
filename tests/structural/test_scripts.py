"""Script integrity tests.

Verifies that scripts in skills/*/scripts/ directories:
- Are executable
- Contain the required 'set -euo pipefail' safety line
- Respond to --help without error

Also verifies that scripts referenced via 'bash scripts/X.sh' in SKILL.md
actually exist in the scripts/ directory.

No API calls required.
"""

import os
import subprocess
from functools import lru_cache

import pytest

from tests.utils.skill_loader import Skill, all_skills

# Collect all (skill, script_path) pairs for parametrization
_all_scripts = [
    (skill, script)
    for skill in all_skills()
    for script in skill.scripts()
]


@lru_cache(maxsize=None)
def _run_help(script_path: str) -> subprocess.CompletedProcess:
    """Run 'bash <script> --help' once and cache the result."""
    return subprocess.run(
        ["bash", script_path, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture(
    params=_all_scripts,
    ids=lambda pair: f"{pair[0].dir_name}/{pair[1].name}",
)
def script_pair(request):
    return request.param


class TestScriptProperties:
    def test_is_executable(self, script_pair):
        _, script = script_pair
        assert os.access(script, os.X_OK), (
            f"{script} must be executable (chmod +x)"
        )

    def test_has_pipefail(self, script_pair):
        _, script = script_pair
        content = script.read_text()
        assert "set -euo pipefail" in content, (
            f"{script.name} must contain 'set -euo pipefail' (AGENTS.md script convention)"
        )

    def test_has_help_flag(self, script_pair):
        _, script = script_pair
        content = script.read_text()
        assert "--help" in content, (
            f"{script.name} must support --help (AGENTS.md script convention)"
        )

    def test_help_exits_zero(self, script_pair):
        _, script = script_pair
        result = _run_help(str(script))
        assert result.returncode == 0, (
            f"'bash {script.name} --help' exited {result.returncode}:\n{result.stderr}"
        )

    def test_help_produces_output(self, script_pair):
        _, script = script_pair
        result = _run_help(str(script))
        assert result.stdout.strip(), (
            f"'bash {script.name} --help' produced no output on stdout"
        )


class TestReferencedScriptsExist:
    """Verify that scripts referenced via 'bash scripts/X.sh' in SKILL.md exist."""

    @pytest.fixture(params=all_skills(), ids=lambda s: s.dir_name)
    def skill(self, request) -> Skill:
        return request.param

    def test_referenced_scripts_exist(self, skill):
        missing = []
        for script_name in skill.referenced_scripts():
            script_path = skill.scripts_dir / script_name
            if not script_path.exists():
                missing.append(script_name)
        assert not missing, (
            f"Scripts referenced in {skill.dir_name}/SKILL.md but missing from scripts/: "
            + ", ".join(missing)
        )
