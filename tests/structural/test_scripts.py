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
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import pytest

from tests.utils.skill_loader import Skill, all_skills

REPO_ROOT = Path(__file__).parent.parent.parent

# (label, script_path) pairs for parametrization.
#
# Repo-root `scripts/` is in scope since
# [#318](https://github.com/gregoryfoster/skills/issues/318). These properties
# — executable bit, `set -euo pipefail`, a `--help` that exits 0 with output —
# are AGENTS.md's script conventions, stated for every script the repo ships,
# but the parametrization was built from `all_skills()` and so stopped at
# `skills/*/scripts/`. `SHELL_SCRIPT_GLOBS` below already covered repo-root
# scripts for shellcheck, which made the gap easy to miss: the surface looked
# gated because half of it was.
#
# The cost was not hypothetical. `scripts/run-integration-tests.sh` forwarded
# no arguments and handled no flags, so `bash scripts/run-integration-tests.sh
# --help` silently dropped the flag and ran the BILLED integration suite —
# `--help` being the one flag a reader tries precisely to find out what a
# script costs before running it.
_all_scripts = [
    (skill.dir_name, script) for skill in all_skills() for script in skill.scripts()
]
_all_scripts += [
    ("<root>", path) for path in sorted((REPO_ROOT / "scripts").glob("*.sh"))
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
# Version pin (#481): exact, the way ruff's is (#246), and installed by
# requirements-test.txt as `shellcheck-py`, which ships the binary as a wheel.
# This was a floor (#140), on the theory that a linter's rules only accumulate.
# They do, and that is the trouble: 0.9.0 added SC2317 and a later release
# SC2329, so the same commit passed on a developer's 0.8.0 and failed 5 tests
# on the cloud VM's 0.9.0, and 0.11.0 reported 13 findings 0.8.0 passed. Any
# version but the pin therefore degrades exactly as an absent binary does: a
# loud skip, or a failure under SHELLCHECK_REQUIRED=1.
#
# The floor survives as a constraint on the pin. `--source-path` and its
# `SCRIPTDIR` keyword landed in 0.7.0 (`--severity` in 0.6.0,
# `--external-sources` in 0.4.7), and an older binary does not ignore the flag
# — it exits 3 with a usage dump and lints nothing, so every script "fails" for
# a reason that has nothing to do with the script.
SHELLCHECK_PIN = (0, 11, 0)
SHELLCHECK_INVOCATION_FLOOR = (0, 7, 0)
SHELLCHECK_SEVERITY = "style"
SHELLCHECK_ARGS = [
    "--external-sources",
    "--source-path=SCRIPTDIR",
    f"--severity={SHELLCHECK_SEVERITY}",
    "--format=gcc",
]
REQUIREMENTS = REPO_ROOT / "requirements-test.txt"
# shellcheck-py versions the binary's X.Y.Z plus its own packaging revision.
_REQUIREMENTS_PIN_RE = re.compile(r"^shellcheck-py==(\d+)\.(\d+)\.(\d+)\.(\d+)\s*$")

# Globs covering every shell script the repo ships. `.claude/hooks/` is a
# symlink farm pointing back into skills/, so the list is deduplicated by real
# path — otherwise the guard hook is linted twice and reports the library as
# missing from a directory that never holds it.
SHELL_SCRIPT_GLOBS = ("skills/*/scripts/*.sh", "scripts/*.sh", ".claude/hooks/*.sh")


def _find_shellcheck() -> str | None:
    """The running interpreter's own shellcheck first, then PATH.

    For the reason `_find_ruff` gives in test_python_lint.py: a bare
    `.venv/bin/pytest` does not put the venv's bin directory on PATH, so
    `shutil.which` alone finds a system build — Homebrew's, apt's — and the
    pin either rejects it or, if PATH order ever favoured the right one by
    accident, the pin is decorative.
    """
    candidate = Path(sys.executable).parent / "shellcheck"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which("shellcheck")


_SHELLCHECK_BIN = _find_shellcheck()
_SHELLCHECK_REQUIRED = os.environ.get("SHELLCHECK_REQUIRED", "") not in ("", "0")

_HOW_TO_INSTALL = (
    "Install the pinned build into the repo venv — `source .venv/bin/activate "
    "&& pip install -r requirements-test.txt` — or run that file's own line: "
    '`uvx --from "$(grep ^shellcheck-py requirements-test.txt)" shellcheck`. '
    "Set SHELLCHECK_REQUIRED=1 to make this a failure instead of a skip."
)
_SHELLCHECK_MISSING = (
    "shellcheck is neither beside this interpreter nor on PATH, so the shell "
    f"lint gate DID NOT RUN. {_HOW_TO_INSTALL}"
)

# `shellcheck --version` prints a `version: 0.8.0` line; the patch component is
# optional so a hypothetical `0.9` still parses rather than reading as unknown.
_SHELLCHECK_VERSION_RE = re.compile(
    r"^version:\s*v?(\d+)\.(\d+)(?:\.(\d+))?", re.MULTILINE
)

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


def _wrong_version(binary: str, found: tuple[int, int, int] | None) -> str:
    """Message for a binary that is present but is not the pinned build.

    A version the probe could not read is treated as wrong: a gate that cannot
    prove it is running the build it documents should say so rather than
    report a pass it did not earn. The message names the binary, so a skip
    says which one this machine found.
    """
    pin = _version_str(SHELLCHECK_PIN)
    if found is None:
        lead = (
            f"shellcheck at {binary} did not report a parseable version, so the "
            f"gate cannot confirm it is the pinned {pin}"
        )
    else:
        lead = f"shellcheck at {binary} is {_version_str(found)}, not the pinned {pin}"
    floor = ""
    if found is not None and found < SHELLCHECK_INVOCATION_FLOOR:
        floor = (
            f" Below {_version_str(SHELLCHECK_INVOCATION_FLOOR)} it would reject "
            "the gate's `--source-path=SCRIPTDIR` outright (exit 3 plus a usage "
            "dump) and lint nothing."
        )
    return (
        f"{lead}, so the shell lint gate DID NOT RUN. The pin is exact because "
        "each release adds rules: a newer build reports findings on a "
        "committed-clean tree, and an older one passes code a current release "
        f"flags.{floor} {_HOW_TO_INSTALL}"
    )


def _shellcheck_problem() -> str | None:
    """Why the gate cannot run, or None when it can — absent and wrong alike."""
    if not _SHELLCHECK_BIN:
        return _SHELLCHECK_MISSING
    version = _shellcheck_version(_SHELLCHECK_BIN)
    if version != SHELLCHECK_PIN:
        return _wrong_version(_SHELLCHECK_BIN, version)
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
    but is not SHELLCHECK_PIN — so a contributor without the pinned build can
    still run the suite. Either way the skip carries a warning, so a
    permanently-skipped gate is visible in the summary rather than lost among
    the other skips.
    """

    def test_shellcheck_is_available(self):
        problem = _shellcheck_problem()
        if problem is not None:
            warnings.warn(problem, UserWarning, stacklevel=2)
        _require_shellcheck()
        assert _all_shell_scripts_list, (
            "no shell scripts discovered — check SHELL_SCRIPT_GLOBS"
        )

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
            f"shellcheck {_version_str(SHELLCHECK_PIN)} "
            f"(severity={SHELLCHECK_SEVERITY}) findings in "
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

    A correct checkout has the pinned build, so every wrong-version branch is
    unreachable without faking the version output; the stub exercises the real
    subprocess call rather than the parser in isolation.
    """
    stub = tmp_path / "shellcheck"
    stub.write_text(f"#!/bin/sh\nprintf '%s' {shlex.quote(stdout)}\nexit {exit_code}\n")
    stub.chmod(0o755)
    _shellcheck_version.cache_clear()
    return str(stub)


class TestShellcheckVersionPin:
    """Any shellcheck but the pinned build must degrade exactly as an absent one does.

    Newer and older alike (#481): a floor let a developer's 0.8.0 pass what the
    cloud VM's 0.9.0 failed. Below the invocation floor the reason is starker —
    the binary rejects `--source-path=SCRIPTDIR` and lints nothing (#140) — but
    the route is the same skip/warn/`SHELLCHECK_REQUIRED` path.
    """

    @pytest.mark.parametrize(
        "output,expected",
        [
            (_FAKE_VERSION_OUTPUT.format(version="0.11.0"), (0, 11, 0)),
            (_FAKE_VERSION_OUTPUT.format(version="0.8.0"), (0, 8, 0)),
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
            pytest.skip("shellcheck is neither beside this interpreter nor on PATH")
        assert _shellcheck_version(_SHELLCHECK_BIN) is not None, (
            "could not parse `shellcheck --version` — the pin check is inert"
        )

    @pytest.mark.parametrize(
        "version",
        ["0.6.0", "0.8.0", "0.10.0", "0.11.1", "0.12.0", "1.0.0"],
        ids=[
            "below-floor",
            "older",
            "one-minor-older",
            "patch-newer",
            "newer",
            "major-newer",
        ],
    )
    def test_any_other_version_skips_loudly(self, tmp_path, monkeypatch, version):
        """Asserts the comparison, not just the wording: a `>=` in place of the
        `!=` would let the three newer ids through and lint under an unknown
        build, which is the #481 failure turned around."""
        binary = _shellcheck_stub(
            tmp_path, _FAKE_VERSION_OUTPUT.format(version=version)
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_BIN", binary)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            _require_shellcheck()
        message = str(excinfo.value)
        assert version in message, "the skip must name the version actually found"
        assert binary in message, "the skip must name the binary it found"
        assert _version_str(SHELLCHECK_PIN) in message, "the skip must name the pin"
        assert "SHELLCHECK_REQUIRED" in message

    def test_below_the_invocation_floor_says_why_it_cannot_lint(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, _FAKE_VERSION_OUTPUT.format(version="0.6.0")),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            _require_shellcheck()
        assert _version_str(SHELLCHECK_INVOCATION_FLOOR) in str(excinfo.value)

    def test_wrong_version_fails_when_required(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, _FAKE_VERSION_OUTPUT.format(version="0.8.0")),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _require_shellcheck()
        assert _version_str(SHELLCHECK_PIN) in str(excinfo.value)

    def test_the_pinned_version_runs(self, tmp_path, monkeypatch):
        """The other direction: a gate nothing can satisfy is not a gate."""
        binary = _shellcheck_stub(
            tmp_path,
            _FAKE_VERSION_OUTPUT.format(version=_version_str(SHELLCHECK_PIN)),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_BIN", binary)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        assert _require_shellcheck() == binary

    def test_the_pin_clears_the_invocation_floor(self):
        """The floor test's old job, kept: a pin below 0.7.0 is a gate that
        rejects its own invocation on every script."""
        assert SHELLCHECK_PIN >= SHELLCHECK_INVOCATION_FLOOR

    def test_unparseable_version_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, "some other tool entirely\n"),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            _require_shellcheck()
        assert "cannot confirm" in str(excinfo.value)

    def test_unparseable_version_fails_when_required(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{__name__}._SHELLCHECK_BIN",
            _shellcheck_stub(tmp_path, "some other tool entirely\n"),
        )
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception):
            _require_shellcheck()

    def test_version_probe_that_errors_is_treated_as_unknown(
        self, tmp_path, monkeypatch
    ):
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
        assert "DID NOT RUN" in str(skipped.value)
        monkeypatch.setattr(f"{__name__}._SHELLCHECK_REQUIRED", True)
        with pytest.raises(pytest.fail.Exception):
            _require_shellcheck()


class TestShellcheckIsTheVenvsBuild:
    """The binary is resolved beside `sys.executable` first, PATH second.

    Without the first step the pin depends on PATH order: a bare
    `.venv/bin/pytest` leaves the venv off PATH, and Homebrew's or apt's build
    is what `shutil.which` returns.
    """

    def _stub_at(self, directory: Path) -> Path:
        directory.mkdir(parents=True)
        stub = directory / "shellcheck"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        return stub

    def test_the_interpreter_s_own_copy_beats_path(self, tmp_path, monkeypatch):
        venv_copy = self._stub_at(tmp_path / "venv" / "bin")
        self._stub_at(tmp_path / "system")
        monkeypatch.setattr(
            sys, "executable", str(tmp_path / "venv" / "bin" / "python")
        )
        monkeypatch.setenv("PATH", str(tmp_path / "system"))
        assert _find_shellcheck() == str(venv_copy)

    def test_path_is_the_fallback(self, tmp_path, monkeypatch):
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        system_copy = self._stub_at(tmp_path / "system")
        monkeypatch.setattr(
            sys, "executable", str(tmp_path / "venv" / "bin" / "python")
        )
        monkeypatch.setenv("PATH", str(tmp_path / "system"))
        assert _find_shellcheck() == str(system_copy)


class TestShellcheckPinIsSingleSourced:
    """The gate's pin and the venv's pin are one decision, in two files.

    The same contract `TestThePinIsSingleSourced` holds for ruff: a test cannot
    install anything and pip cannot read a Python constant, so without this the
    venv installs one shellcheck, the gate demands another, and every
    contributor gets a permanent loud skip in a repo that believes itself gated.
    """

    def test_the_pin_matches_requirements(self):
        lines = [
            line
            for line in REQUIREMENTS.read_text().splitlines()
            if line.startswith("shellcheck-py")
        ]
        assert len(lines) == 1, (
            f"requirements-test.txt has {len(lines)} `shellcheck-py` lines; the "
            "gate needs exactly one."
        )
        match = _REQUIREMENTS_PIN_RE.match(lines[0])
        assert match is not None, (
            f"requirements-test.txt pins shellcheck as {lines[0]!r}, which is not "
            "the exact `shellcheck-py==X.Y.Z.N` form. The gate needs one specific "
            "build; a range makes it unenforceable."
        )
        found = tuple(int(part) for part in match.groups()[:3])
        assert found == SHELLCHECK_PIN, (
            f"requirements-test.txt installs shellcheck {_version_str(found)} but "
            f"{Path(__file__).name} expects {_version_str(SHELLCHECK_PIN)}. A bump "
            "changes both, and fixes what the new build reports in the same "
            "commit."
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
    ids=lambda pair: f"{pair[0]}/{pair[1].name}",
)
def script_pair(request):
    return request.param


class TestScriptProperties:
    def test_repo_root_scripts_are_examined(self):
        """The half that keeps the extension honest (#318).

        Widening a parametrization is invisible if the new glob matches
        nothing: the suite stays green and the surface still looks gated. Pin
        that repo-root `scripts/` actually contributed, so a layout change
        fails here rather than quietly shrinking the rule back to where it was.
        """
        found = sorted(s.name for label, s in _all_scripts if label == "<root>")
        assert found, (
            "no repo-root scripts/*.sh reached TestScriptProperties — the "
            "#318 extension has silently reverted to skills/ only."
        )
        assert "pre-ship.sh" in found, (
            "scripts/pre-ship.sh is this repo's ship gate and must be held to "
            f"the script conventions it gates for. Found: {found}"
        )

    def test_is_executable(self, script_pair):
        _, script = script_pair
        assert os.access(script, os.X_OK), f"{script} must be executable (chmod +x)"

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
