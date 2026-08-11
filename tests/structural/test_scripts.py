"""Script integrity tests.

Verifies that scripts in skills/*/scripts/ directories:
- Are executable
- Contain the required 'set -euo pipefail' safety line
- Respond to --help without error
- Pass shellcheck (issue #90)

Also verifies that scripts referenced via 'bash scripts/X.sh' in SKILL.md
actually exist in the scripts/ directory.

No API calls required.
"""

import os
import re
import shutil
import subprocess
import warnings
from functools import lru_cache
from pathlib import Path

import pytest

from tests.utils.skill_loader import Skill, all_skills

REPO_ROOT = Path(__file__).parent.parent.parent

# Collect all (skill, script_path) pairs for parametrization
_all_scripts = [
    (skill, script)
    for skill in all_skills()
    for script in skill.scripts()
]


# --- shellcheck gate (#90) -------------------------------------------------
#
# Severity floor: shellcheck's own default, `style` — i.e. no floor at all.
# The tree is clean at every level once the intentional idioms carry a
# directive, so raising the floor to `warning` would buy nothing except a blind
# spot: SC2015 ("A && B || C is not if-then-else") and SC2086 (unquoted
# expansion) are both info-level, and both are exactly the shapes worth
# catching in a script surface that runs unattended in other repos.
#
# `--external-sources` plus `--source-path=SCRIPTDIR` make the existing
# `# shellcheck source=_context-lib.sh` directives resolve. Without them every
# caller of the shared library reports SC1091, which is a resolution
# limitation, not a defect — 8 of the 27 findings this gate started from.
SHELLCHECK_SEVERITY = "style"
SHELLCHECK_ARGS = [
    "--external-sources",
    "--source-path=SCRIPTDIR",
    f"--severity={SHELLCHECK_SEVERITY}",
    "--format=gcc",
]

# Globs covering every shell script the repo ships. `.claude/hooks/` is a
# symlink farm pointing back into skills/, so the list is deduplicated by real
# path — otherwise the guard hook is linted twice and reports the library as
# missing from a directory that never holds it.
SHELL_SCRIPT_GLOBS = ("skills/*/scripts/*.sh", "scripts/*.sh", ".claude/hooks/*.sh")

_SHELLCHECK_BIN = shutil.which("shellcheck")
_SHELLCHECK_MISSING = (
    "shellcheck is not on PATH, so the shell lint gate DID NOT RUN. "
    "Install it (`brew install shellcheck` / `apt install shellcheck`) to get "
    "the coverage this suite claims. Set SHELLCHECK_REQUIRED=1 to make its "
    "absence a failure instead of a skip."
)
_SHELLCHECK_REQUIRED = os.environ.get("SHELLCHECK_REQUIRED", "") not in ("", "0")

# A justified suppression pairs the directive with a reason on the line above.
_DISABLE_RE = re.compile(r"^\s*#\s*shellcheck\s+disable=", re.IGNORECASE)
_DIRECTIVE_RE = re.compile(r"^\s*#\s*shellcheck\s+", re.IGNORECASE)


def _all_shell_scripts() -> list[Path]:
    """Every shell script in the repo, deduplicated by real path."""
    seen: dict[Path, Path] = {}
    for pattern in SHELL_SCRIPT_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            seen.setdefault(path.resolve(), path)
    return [seen[k] for k in sorted(seen)]


_all_shell_scripts_list = _all_shell_scripts()


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@pytest.fixture(params=_all_shell_scripts_list, ids=_rel)
def shell_script(request) -> Path:
    return request.param


def _require_shellcheck() -> str:
    if _SHELLCHECK_BIN:
        return _SHELLCHECK_BIN
    if _SHELLCHECK_REQUIRED:
        pytest.fail(_SHELLCHECK_MISSING)
    pytest.skip(_SHELLCHECK_MISSING)


class TestShellcheck:
    """Lint every shell script the repo ships.

    Skips (loudly) rather than fails when the binary is absent, so a
    contributor without shellcheck can still run the suite — but the skip
    carries a warning so a permanently-skipped gate is visible in the summary
    rather than lost among the other skips.
    """

    def test_shellcheck_is_available(self):
        if _SHELLCHECK_BIN is None:
            warnings.warn(_SHELLCHECK_MISSING, UserWarning, stacklevel=2)
        _require_shellcheck()
        assert _all_shell_scripts_list, "no shell scripts discovered — check SHELL_SCRIPT_GLOBS"

    def test_shellcheck_clean(self, shell_script):
        binary = _require_shellcheck()
        result = subprocess.run(
            [binary, *SHELLCHECK_ARGS, _rel(shell_script)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            f"shellcheck (severity={SHELLCHECK_SEVERITY}) findings in "
            f"{_rel(shell_script)}:\n{result.stdout}{result.stderr}\n"
            "Fix the defect, or add '# shellcheck disable=SCxxxx' with a reason "
            "comment on the line above (AGENTS.md script convention)."
        )


class TestShellcheckSuppressionsCarryReasons:
    """A bare '# shellcheck disable=' is suppression; with a reason it is a decision.

    Asserting the pairing is what keeps the gate from being talked out of
    existence one directive at a time.
    """

    def test_disable_has_reason_above(self, shell_script):
        lines = shell_script.read_text().splitlines()
        unjustified = []
        for i, line in enumerate(lines):
            if not _DISABLE_RE.match(line):
                continue
            prev = lines[i - 1].strip() if i > 0 else ""
            reason = prev[1:].strip() if prev.startswith("#") else ""
            if not reason or _DIRECTIVE_RE.match(prev):
                unjustified.append(f"  {_rel(shell_script)}:{i + 1}: {line.strip()}")
        assert not unjustified, (
            "every '# shellcheck disable=' needs a reason comment on the line "
            "directly above it (AGENTS.md script convention); missing for:\n"
            + "\n".join(unjustified)
        )


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
