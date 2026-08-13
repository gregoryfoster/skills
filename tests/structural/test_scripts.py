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
import shlex
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
#
# Version floor (#140): `--source-path` and its `SCRIPTDIR` keyword landed in
# shellcheck 0.7.0. `--severity` landed in 0.6.0 and `--external-sources` in
# 0.4.7, so 0.7.0 is the binding floor for the invocation below. An older
# binary does not silently ignore the flag — it exits 3 with a usage dump and
# lints nothing, so every script "fails" for a reason that has nothing to do
# with the script. Below the floor the gate therefore degrades exactly as it
# does when the binary is absent: a loud skip, or a failure under
# SHELLCHECK_REQUIRED=1.
SHELLCHECK_MIN_VERSION = (0, 7, 0)
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

# `shellcheck --version` prints a `version: 0.8.0` line; the patch component is
# optional so a hypothetical `0.9` still parses rather than reading as unknown.
_SHELLCHECK_VERSION_RE = re.compile(r"^version:\s*v?(\d+)\.(\d+)(?:\.(\d+))?", re.MULTILINE)

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


def _parse_shellcheck_version(output: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) from `shellcheck --version` output, or None."""
    match = _SHELLCHECK_VERSION_RE.search(output)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


@lru_cache(maxsize=None)
def _shellcheck_version(binary: str) -> tuple[int, int, int] | None:
    """Probe the binary once; None when it cannot be asked or cannot be parsed."""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_shellcheck_version(result.stdout)


def _version_str(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _shellcheck_below_floor(found: tuple[int, int, int] | None) -> str:
    """Message for a binary that is present but unusable.

    A version the probe could not read is treated as below the floor: a gate
    that cannot prove it is running the invocation it documents should say so
    rather than report a pass it did not earn.
    """
    floor = _version_str(SHELLCHECK_MIN_VERSION)
    if found is None:
        lead = (
            "shellcheck on PATH did not report a parseable version, so the gate "
            f"cannot confirm it is at least {floor}"
        )
    else:
        lead = (
            f"shellcheck on PATH is {_version_str(found)}, below the {floor} this "
            "gate needs"
        )
    return (
        f"{lead}, so the shell lint gate DID NOT RUN. `--source-path=SCRIPTDIR` "
        f"landed in {floor}; an older binary rejects the whole invocation (exit 3 "
        "plus a usage dump) instead of linting, which reads as every script being "
        "broken. Upgrade it (`brew upgrade shellcheck` / `apt install "
        "shellcheck`) to get the coverage this suite claims. Set "
        "SHELLCHECK_REQUIRED=1 to make a too-old build a failure instead of a skip."
    )


def _shellcheck_problem() -> str | None:
    """Why the gate cannot run, or None when it can — absent and too-old alike."""
    if not _SHELLCHECK_BIN:
        return _SHELLCHECK_MISSING
    version = _shellcheck_version(_SHELLCHECK_BIN)
    if version is None or version < SHELLCHECK_MIN_VERSION:
        return _shellcheck_below_floor(version)
    return None


def _require_shellcheck() -> str:
    problem = _shellcheck_problem()
    if problem is not None:
        if _SHELLCHECK_REQUIRED:
            pytest.fail(problem)
        pytest.skip(problem)
    return _SHELLCHECK_BIN  # non-None whenever there is no problem


class TestShellcheck:
    """Lint every shell script the repo ships.

    Skips (loudly) rather than fails when the binary is absent — or is present
    but older than SHELLCHECK_MIN_VERSION — so a contributor without a usable
    shellcheck can still run the suite. Either way the skip carries a warning,
    so a permanently-skipped gate is visible in the summary rather than lost
    among the other skips.
    """

    def test_shellcheck_is_available(self):
        problem = _shellcheck_problem()
        if problem is not None:
            warnings.warn(problem, UserWarning, stacklevel=2)
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


_FAKE_VERSION_OUTPUT = (
    "ShellCheck - shell script analysis tool\n"
    "version: {version}\n"
    "license: GNU General Public License, version 3\n"
    "website: https://www.shellcheck.net\n"
)


def _shellcheck_stub(tmp_path: Path, stdout: str, exit_code: int = 0) -> str:
    """A fake `shellcheck` whose only job is to answer `--version`.

    The local build is 0.8.0, so the below-floor branch is unreachable without
    faking the version output; the stub exercises the real subprocess call
    rather than the parser in isolation.
    """
    stub = tmp_path / "shellcheck"
    stub.write_text(f"#!/bin/sh\nprintf '%s' {shlex.quote(stdout)}\nexit {exit_code}\n")
    stub.chmod(0o755)
    _shellcheck_version.cache_clear()
    return str(stub)


class TestShellcheckVersionFloor:
    """A too-old shellcheck must degrade exactly as an absent one does.

    Below 0.7.0 the binary does not ignore `--source-path=SCRIPTDIR` — it
    rejects the invocation (exit 3 + usage dump) and lints nothing, so every
    script "fails" for a reason that has nothing to do with the script. Both
    causes therefore route through the same skip/warn/`SHELLCHECK_REQUIRED`
    path.
    """

    @pytest.mark.parametrize(
        "output,expected",
        [
            (_FAKE_VERSION_OUTPUT.format(version="0.8.0"), (0, 8, 0)),
            (_FAKE_VERSION_OUTPUT.format(version="0.7.0"), (0, 7, 0)),
            (_FAKE_VERSION_OUTPUT.format(version="0.6.0"), (0, 6, 0)),
            (_FAKE_VERSION_OUTPUT.format(version="0.10.1"), (0, 10, 1)),
            (_FAKE_VERSION_OUTPUT.format(version="1.0"), (1, 0, 0)),
            ("", None),
            ("ShellCheck - shell script analysis tool\nno version here\n", None),
            ("version: unknown\n", None),
        ],
    )
    def test_version_parsing(self, output, expected):
        assert _parse_shellcheck_version(output) == expected

    def test_real_binary_version_is_parseable(self):
        """Guards the regex against drift in shellcheck's own `--version` output."""
        if _SHELLCHECK_BIN is None:
            pytest.skip("shellcheck is not on PATH")
        assert _shellcheck_version(_SHELLCHECK_BIN) is not None, (
            "could not parse `shellcheck --version` — the floor check is inert"
        )

    def test_below_floor_skips_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, _FAKE_VERSION_OUTPUT.format(version="0.6.0")),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            _require_shellcheck()
        message = str(excinfo.value)
        assert "0.6.0" in message, "the skip must name the version actually found"
        assert "0.7.0" in message, "the skip must name the version required"
        assert "SHELLCHECK_REQUIRED" in message

    def test_below_floor_fails_when_required(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, _FAKE_VERSION_OUTPUT.format(version="0.6.0")),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _require_shellcheck()
        assert "0.7.0" in str(excinfo.value)

    @pytest.mark.parametrize("version", ["0.7.0", "0.8.0", "0.10.1"])
    def test_at_or_above_floor_runs(self, tmp_path, monkeypatch, version):
        binary = _shellcheck_stub(tmp_path, _FAKE_VERSION_OUTPUT.format(version=version))
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_BIN", binary)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        assert _require_shellcheck() == binary

    def test_unparseable_version_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, "some other tool entirely\n"),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            _require_shellcheck()
        assert "0.7.0" in str(excinfo.value)

    def test_unparseable_version_fails_when_required(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, "some other tool entirely\n"),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception):
            _require_shellcheck()

    def test_version_probe_that_errors_is_treated_as_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, "", exit_code=3),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception):
            _require_shellcheck()

    def test_absent_binary_still_degrades_the_same_way(self, monkeypatch):
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_BIN", None)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as skipped:
            _require_shellcheck()
        assert "not on PATH" in str(skipped.value)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception):
            _require_shellcheck()


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
