"""The Python lint/format gate (#246).

#246 asked the repo to decide one way or the other, because the cost of not
deciding is that every review re-litigates it. The decision is **adopt**: the
tree is held clean by `ruff check` and `ruff format --check`, configured in
`[tool.ruff]` in `pyproject.toml` and enforced here.

Enforced *here*, in the structural suite, rather than as its own pre-commit
hook and `scripts/lint-python.sh`, for two reasons. The suite is already on
the commit path via the `structural-tests` hook, so a second hook would buy
nothing but a second venv-bootstrap problem of the #156 shape; and the repo
already has exactly this gate for the other half of its script surface —
`TestShellcheck` in `test_scripts.py` — so a contributor who knows one knows
both.

The version is pinned **exactly**, not floored. A lint floor is the right
shape for shellcheck because rules only accumulate, but `ruff format`'s output
is defined by the version that produced it: 0.8.0 and 0.16.6 disagree by some
three thousand lines on this very tree. A floor would therefore let a newer
build report a tree that is already committed-clean as needing reformatting,
which is a gate failing for a reason the author cannot act on. Bumping the pin
is a deliberate commit that carries the reformat with it.

No API calls. Requires `ruff` on PATH — `requirements-test.txt` installs the
pinned build into `.venv`, and its absence is a loud skip, not a silent pass.
"""

import os
import re
import shutil
import subprocess
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

# .resolve(), because test_the_tree_is_actually_covered subtracts two sets of
# resolved paths and then renders the difference with relative_to(REPO_ROOT).
# An unresolved root under a symlinked checkout — WORKTREE_ROOT can point at
# one, and macOS /tmp always is — makes that last step raise ValueError instead
# of listing the unlinted files, i.e. the reporter crashes exactly when it has
# something to report.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
LINT_SCRIPT = REPO_ROOT / "scripts" / "python-lint.sh"

# The gate, named once. `TestTheScriptAndTheSuiteAgree` holds python-lint.sh to
# these same two invocations, so the hook really is the fast spelling of this
# file rather than a second, drifting definition of what "clean" means.
GATE_COMMANDS = {
    "check": ("check", "."),
    "format": ("format", "--check", "."),
}
# The two the script additionally runs under --fix. Both branches are pinned:
# a pass added to one mode and forgotten in the other is the drift this guards.
FIX_COMMANDS = {("check", "--fix", "."), ("format", ".")}

# Matches `"$RUFF" check .` / `"$RUFF" format --check . || status=1`, and
# deliberately not `"$RUFF" --version | awk ...` — that is the version probe,
# not the gate, and it is asserted by its own behaviour in the script.
# `#` is excluded alongside `|` so a trailing comment cannot land inside the
# captured invocation: it would fail closed, but the failure would accuse the
# script of running a command it does not run.
_SCRIPT_RUFF_RE = re.compile(
    r'"\$RUFF" ((?:check|format)[^|#\n]*?)\s*(?:(?:\|\||#).*)?$', re.MULTILINE
)

# ruff's format summary: "1 file would be reformatted, 94 files already
# formatted". Both halves count as files the formatter READ, which is what
# test_the_formatter_reads_the_same_tree measures.
_FORMAT_COUNT_RE = re.compile(
    r"(\d+) files? (?:would be reformatted|already formatted)"
)

# The one pin. `test_the_pin_matches_requirements` holds it equal to the
# `ruff==` line in requirements-test.txt, so the version the gate documents
# and the version a fresh `.venv` installs cannot drift apart silently.
RUFF_PIN = (0, 16, 6)
REQUIREMENTS = REPO_ROOT / "requirements-test.txt"
_REQUIREMENTS_PIN_RE = re.compile(r"^ruff==(\d+)\.(\d+)\.(\d+)\s*$")

# `ruff --version` prints `ruff 0.16.6`. The patch component is optional so a
# hypothetical `0.17` parses rather than reading as unknown.
_RUFF_VERSION_RE = re.compile(r"^ruff\s+(\d+)\.(\d+)(?:\.(\d+))?")


def _find_ruff() -> str | None:
    """The running interpreter's own ruff first, then PATH.

    `shutil.which` alone is wrong here. `.venv/bin/python -m pytest` without
    activating is a form this repo recommends in its own warning text
    (test_skill_self_budget.py), and under it the venv's bin directory is not
    on PATH — so `which` misses the pinned build sitting right beside
    `sys.executable` and the whole gate skips, reporting a green suite that
    linted nothing. Where PATH does carry a ruff it may be a system build of
    another version, which the pin then rejects, for the same silent outcome.
    Both are avoided by asking the interpreter that is actually running the
    suite where its own tools live.
    """
    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which("ruff")


_RUFF_BIN = _find_ruff()
_RUFF_REQUIRED = os.environ.get("RUFF_REQUIRED", "") not in ("", "0")


def _version_str(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


_HOW_TO_INSTALL = (
    "Install it into the repo venv — `source .venv/bin/activate && pip install "
    "-r requirements-test.txt` — or run the gate's own build with `uvx "
    f"ruff@{_version_str(RUFF_PIN)}`. Set RUFF_REQUIRED=1 to make this a "
    "failure instead of a skip."
)


def _parse_ruff_version(output: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) from `ruff --version` output, or None."""
    match = _RUFF_VERSION_RE.search(output)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


@lru_cache(maxsize=None)
def _ruff_version(binary: str) -> tuple[int, int, int] | None:
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
    return _parse_ruff_version(result.stdout)


def _wrong_version(found: tuple[int, int, int] | None) -> str:
    """Message for a binary that is present but is not the pinned build."""
    pin = _version_str(RUFF_PIN)
    if found is None:
        lead = (
            "ruff on PATH did not report a parseable version, so the gate cannot "
            f"confirm it is the pinned {pin}"
        )
    else:
        lead = f"ruff on PATH is {_version_str(found)}, not the pinned {pin}"
    return (
        f"{lead}, so the Python lint/format gate DID NOT RUN. The pin is exact "
        "because `ruff format`'s output is version-defined: under a different "
        "build this gate would report a committed-clean tree as needing "
        f"reformatting, which the author cannot act on. {_HOW_TO_INSTALL}"
    )


_RUFF_MISSING = (
    "ruff is not on PATH, so the Python lint/format gate DID NOT RUN. "
    f"{_HOW_TO_INSTALL}"
)


def _ruff_problem() -> str | None:
    """Why the gate cannot run, or None when it can — absent and wrong-version alike."""
    if not _RUFF_BIN:
        return _RUFF_MISSING
    version = _ruff_version(_RUFF_BIN)
    if version != RUFF_PIN:
        return _wrong_version(version)
    return None


def _require_ruff() -> str:
    problem = _ruff_problem()
    if problem is not None:
        if _RUFF_REQUIRED:
            pytest.fail(problem)
        pytest.skip(problem)
    return _RUFF_BIN  # non-None whenever there is no problem


def _tracked_python_files() -> list[str]:
    """Every Python file the repo actually ships, by git's reckoning."""
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _run_ruff(*args: str) -> subprocess.CompletedProcess:
    """Invoke the pinned ruff from the repo root, so `[tool.ruff]` is discovered."""
    binary = _require_ruff()
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO_ROOT,
    )


class TestRuff:
    """Hold every Python file the repo ships clean under the pinned ruff.

    Skips (loudly) rather than fails when the binary is absent or is not the
    pinned build, so a contributor without it can still run the suite. Either
    way the skip carries a warning, so a permanently-skipped gate is visible in
    the summary rather than lost among the other skips.
    """

    def test_ruff_is_available(self):
        problem = _ruff_problem()
        if problem is not None:
            warnings.warn(problem, UserWarning, stacklevel=2)
        _require_ruff()

    def test_check_is_clean(self):
        result = _run_ruff(*GATE_COMMANDS["check"])
        assert result.returncode == 0, (
            "`ruff check .` findings:\n"
            f"{result.stdout}{result.stderr}\n"
            "Most are auto-fixable: `ruff check --fix .`. The selected rule set "
            "is E4/E7/E9/F plus I, declared in pyproject.toml — widening it is a "
            "decision to make there, not by suppressing here."
        )

    def test_format_is_clean(self):
        result = _run_ruff(*GATE_COMMANDS["format"])
        assert result.returncode == 0, (
            "`ruff format --check .` would reformat:\n"
            f"{result.stdout}{result.stderr}\n"
            f"Run `ruff format .` with the pinned {_version_str(RUFF_PIN)}."
        )

    def test_the_tree_is_actually_covered(self):
        """A gate that lints nothing passes, so prove it sees the tree.

        `ruff check .` exits 0 both when every file is clean and when the
        config's excludes have quietly grown to cover everything. The two are
        indistinguishable from the exit code, which is the whole failure mode:
        #246 was raised because `ruff check` looked clean when run against
        individual files rather than the tree.
        """
        result = _run_ruff("check", "--show-files", ".")
        seen = {
            Path(line).resolve() for line in result.stdout.splitlines() if line.strip()
        }
        expected = {(REPO_ROOT / line).resolve() for line in _tracked_python_files()}
        # Without this the test carries the very defect it was written against:
        # a git that returned nothing makes `expected` empty, `missed` empty,
        # and the assertion below pass while proving nothing at all.
        assert expected, (
            "`git ls-files '*.py'` listed no Python files, so the comparison "
            "below would pass vacuously. The gate's coverage is unproven."
        )
        missed = sorted(str(p.relative_to(REPO_ROOT)) for p in expected - seen)
        assert not missed, (
            "tracked Python files the gate does not lint:\n  "
            + "\n  ".join(missed)
            + "\nAn exclude in [tool.ruff] has grown past what it was meant to "
            "cover, and the gate reports green on a tree it never read."
        )


@pytest.fixture(scope="module")
def format_coverage() -> tuple[list[str], subprocess.CompletedProcess]:
    """One `ruff format --check --force-exclude` over the tracked list.

    Module-scoped so the measurement and the guard that vouches for it read the
    SAME run. Parsed from two separate invocations, the guard would be
    confirming that *a* summary line was printed, not that the count the
    assertion relied on came from anywhere in particular.
    """
    tracked = _tracked_python_files()
    return tracked, _run_ruff("format", "--check", "--force-exclude", *tracked)


class TestTheFormatterReadsTheSameTree:
    """The other half of coverage, measured rather than inferred.

    `check --show-files` proves what the LINTER reads; nothing there speaks for
    the formatter, and `[tool.ruff.format]` accepts its own `exclude`. The
    first attempt at this guard matched the `[tool.ruff.format]` section header
    in the file text, and was walked straight past by TOML's other spelling for
    the same table — a `format.exclude` dotted key under `[tool.ruff]`, which
    drops six files from the formatter with the whole suite still green.

    Recognising every way a config can shrink the formatter's input is the
    wrong problem. This asks the formatter what it read: `--force-exclude`
    makes ruff apply excludes to explicitly-named paths (without it, naming a
    file bypasses them and the count is trivially right), so a file dropped by
    any exclude, in any spelling, goes missing from the summary count.
    """

    def test_every_tracked_file_reaches_the_formatter(self, format_coverage):
        tracked, result = format_coverage
        assert tracked, "`git ls-files '*.py'` listed nothing to measure"
        counted = sum(int(n) for n in _FORMAT_COUNT_RE.findall(result.stdout))
        assert counted == len(tracked), (
            f"the formatter read {counted} of {len(tracked)} tracked Python "
            "files. An exclude reachable from [tool.ruff.format] — either "
            "spelling — is hiding files from `ruff format` that "
            "`ruff check` still sees, so the tree can go unformatted with "
            f"this suite green.\n{result.stdout}{result.stderr}"
        )

    def test_the_count_is_actually_being_parsed(self, format_coverage):
        """A summary ruff stopped printing would make the sum 0 == 0 someday."""
        _, result = format_coverage
        assert _FORMAT_COUNT_RE.findall(result.stdout), (
            "no file count parsed out of `ruff format --check`. Its summary "
            f"line changed shape, and the test above is comparing 0 to 0:\n"
            f"{result.stdout}{result.stderr}"
        )


class TestTheScriptAndTheSuiteAgree:
    """One definition of "the gate", read by both surfaces.

    The hook comment in .pre-commit-config.yaml calls the script "the fast
    spelling, not a second source of truth" — that claim is the entire reason
    two surfaces are allowed to exist, and until now nothing held it. A third
    check added to one side would leave the other quietly behind while the
    comment kept asserting they agree, which is the shape this repo already
    guards against in TestGateScriptHardening and TestThePinIsSingleSourced.
    """

    def _script_invocations(self) -> set[str]:
        return {
            match.group(1)
            for match in _SCRIPT_RUFF_RE.finditer(LINT_SCRIPT.read_text())
        }

    def test_the_script_runs_exactly_the_suite_s_two_commands(self):
        expected = {" ".join(command) for command in GATE_COMMANDS.values()}
        expected |= {" ".join(command) for command in FIX_COMMANDS}
        assert self._script_invocations() == expected, (
            f"{LINT_SCRIPT.name} invokes ruff as "
            f"{sorted(self._script_invocations())}, but the suite's gate is "
            f"{sorted(expected)}. The hook and this file must run the same "
            "checks — a pass in one and not the other means a commit can pass "
            "a gate the suite would fail, or the reverse."
        )

    def test_the_probe_finds_something(self):
        """A regex that matched nothing would make the test above pass empty."""
        assert self._script_invocations(), (
            f"no ruff invocations parsed out of {LINT_SCRIPT.name}. The script "
            "changed shape and _SCRIPT_RUFF_RE no longer sees it, so the "
            "agreement test above is comparing two empty sets."
        )


class TestThePinIsSingleSourced:
    """The gate's pin and the venv's pin are one decision, in two files.

    They have to be in two files — a test cannot install anything, and pip
    cannot read a Python constant — so the only thing holding them equal is
    this assertion. Without it the venv installs one ruff, the gate demands
    another, and every contributor gets a permanent loud skip for a repo that
    believes itself gated.
    """

    def test_the_pin_matches_requirements(self):
        # The script takes the FIRST line beginning `ruff==` and fails if it is
        # malformed, rather than scanning past it for a well-formed one. A
        # `re.search` here did scan past: with `ruff==0.16` above `ruff==0.16.6`
        # the script exited 3 while this class — the one whose name is the
        # claim — passed. Requiring exactly one such line makes the two agree
        # by construction instead of by matching selection rules.
        lines = [
            line
            for line in REQUIREMENTS.read_text().splitlines()
            if line.startswith("ruff==")
        ]
        assert len(lines) == 1, (
            f"requirements-test.txt has {len(lines)} `ruff==` lines; the gate "
            "needs exactly one. python-lint.sh reads the first and does not "
            "look past it, so any other is either dead or contradicting it."
        )
        match = _REQUIREMENTS_PIN_RE.match(lines[0])
        assert match is not None, (
            f"requirements-test.txt pins ruff as {lines[0]!r}, which is not the "
            "exact `ruff==X.Y.Z` form. The gate in this file needs one specific "
            "build (see its module docstring); a floor makes it unenforceable, "
            "and python-lint.sh rejects the same line with exit 3."
        )
        found = tuple(int(part) for part in match.groups())
        assert found == RUFF_PIN, (
            f"requirements-test.txt pins ruff=={_version_str(found)} but "
            f"{Path(__file__).name} expects {_version_str(RUFF_PIN)}. A bump "
            "changes both, and carries the reformat `ruff format .` produces "
            "under the new build in the same commit."
        )


class TestVersionProbe:
    """The wrong-version branch is unreachable with the pinned build installed.

    The version the gate wants is the version a correct checkout has, so the
    only way to exercise the degradation path is to fake the probe's output —
    the same reason `TestShellcheckVersionFloor` uses a stub. These cover the
    parser rather than the subprocess, which is where the branch actually
    decides.
    """

    @pytest.mark.parametrize(
        "output,expected",
        [
            ("ruff 0.16.6\n", (0, 16, 6)),
            ("ruff 0.8.0\n", (0, 8, 0)),
            ("ruff 0.17\n", (0, 17, 0)),
            ("ruff 1.0.0\n", (1, 0, 0)),
            ("", None),
            ("shellcheck 0.8.0\n", None),
        ],
    )
    def test_version_parsing(self, output, expected):
        assert _parse_ruff_version(output) == expected

    @pytest.mark.parametrize(
        "reported",
        [None, (0, 8, 0), (0, 16, 5), (0, 17, 0), (1, 0, 0)],
        ids=["unparseable", "older", "one-patch-older", "newer", "major-newer"],
    )
    def test_only_the_pinned_version_satisfies_the_gate(self, monkeypatch, reported):
        """Every version that is not the pin must degrade, newer included.

        This asserts the comparison in `_ruff_problem`, not the wording of the
        message it returns — the earlier version of this test checked only the
        latter, so it would have kept passing through exactly the change it
        claimed to prevent. A `>=` in place of the `!=` lets `(0, 17, 0)` and
        `(1, 0, 0)` through and runs the format check under an unknown build;
        those two ids are the ones that catch it, and `None` covers a probe
        that could not answer at all.
        """
        monkeypatch.setattr(f"{__name__}._RUFF_BIN", "/stub/ruff")
        monkeypatch.setattr(f"{__name__}._ruff_version", lambda _binary: reported)
        assert _ruff_problem() is not None, (
            f"a ruff reporting {reported} satisfied a gate pinned to "
            f"{_version_str(RUFF_PIN)} — the version check is no longer an "
            "equality, and `ruff format` now runs under an unknown build."
        )

    def test_the_pinned_version_satisfies_the_gate(self, monkeypatch):
        """The other direction: a gate nothing can satisfy is not a gate.

        Without this, `_ruff_problem` could be hardened into always returning a
        problem and the parametrized test above would go greener still, while
        the suite skipped the lint and format checks on every machine.
        """
        monkeypatch.setattr(f"{__name__}._RUFF_BIN", "/stub/ruff")
        monkeypatch.setattr(f"{__name__}._ruff_version", lambda _binary: RUFF_PIN)
        assert _ruff_problem() is None

    def test_a_missing_binary_degrades_before_the_version_is_asked(self, monkeypatch):
        monkeypatch.setattr(f"{__name__}._RUFF_BIN", None)
        assert _ruff_problem() == _RUFF_MISSING

    def test_the_skip_messages_name_the_remedy(self):
        """A loud skip is only useful if it says what to do about it."""
        assert "cannot confirm" in _wrong_version(None)
        assert _version_str(RUFF_PIN) in _wrong_version((0, 8, 0))
        for message in (_RUFF_MISSING, _wrong_version(None)):
            assert "requirements-test.txt" in message
            assert "RUFF_REQUIRED=1" in message


class TestTheHookIsWired:
    """The gate is also a pre-commit hook, and its position is the point.

    Running it inside the suite alone would already gate every commit, since
    `structural-tests` runs the suite — but only after ~4 minutes, to report
    that a file needs reformatting. The separate hook exists to fail in ~1s,
    which it only does while it stays *ahead* of the suite in the file.
    """

    def _hooks(self) -> list[dict]:
        config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text())
        return [hook for repo in config["repos"] for hook in repo["hooks"]]

    def test_the_hook_exists_and_runs_the_script(self):
        hooks = {hook["id"]: hook for hook in self._hooks()}
        assert "python-lint" in hooks, (
            "no `python-lint` hook in .pre-commit-config.yaml. Without it the "
            "Python gate only reports after the whole structural suite has run."
        )
        assert LINT_SCRIPT.name in hooks["python-lint"]["entry"], (
            f"the python-lint hook must run {LINT_SCRIPT.name}; an inline "
            "`ruff` invocation would reimplement the venv resolution that "
            "script delegates to structural-tests.sh (#156)."
        )
        assert LINT_SCRIPT.exists(), f"{LINT_SCRIPT.name} is missing"
        assert os.access(LINT_SCRIPT, os.X_OK), f"{LINT_SCRIPT.name} is not executable"

    def test_the_hook_precedes_the_suite(self):
        ids = [hook["id"] for hook in self._hooks()]
        assert "structural-tests" in ids, "the structural-tests hook has gone missing"
        assert ids.index("python-lint") < ids.index("structural-tests"), (
            "python-lint must come before structural-tests. Behind it the hook "
            "is pure duplication: the suite already carries the same gate, and "
            "what the separate hook buys is ending the run before the four "
            "minutes rather than after them."
        )

    def test_the_hook_stops_the_run(self):
        """Ordering without fail_fast bought ordering, and no time at all.

        pre-commit runs EVERY hook and breaks early only when a failing one
        sets fail_fast (`commands/run.py`: `if current_retval and fail_fast:
        break`), which defaults to False. Until this flag was set, a format
        breach was reported in ~0.1s and then the ~4 min suite ran anyway — so
        the hook's entire stated justification, repeated in three places, was
        false. Nothing but this assertion holds it true.
        """
        hooks = {hook["id"]: hook for hook in self._hooks()}
        assert hooks["python-lint"].get("fail_fast") is True, (
            "the python-lint hook does not set fail_fast, so a format breach "
            "no longer ends the pre-commit run — it is merely reported before "
            "the structural suite runs for four minutes regardless. That makes "
            "the hook pure duplication of the same gate inside the suite."
        )


class TestMarkdownIsNotFormatted:
    """The formatter stops at Python files, and that is a decision, not a default.

    ruff 0.16 formats fenced Python blocks inside Markdown. On this tree that
    reached `references/process-log/`, whose entries quote ANOTHER repo's
    source verbatim to explain what a run found — reformatting a quotation
    makes the record say something the quoted file does not. It also reached
    `references/*.md` snippets, which are templates for consumer repos that
    set their own line-length. `extend-exclude = ["*.md"]` in pyproject.toml
    is what holds that line, and nothing else would notice if it went.

    Both directions are asserted: the probe must be left alone under the
    repo's config, and must genuinely be reformattable without it. A probe
    that ruff would not touch anyway proves nothing.
    """

    PROBE = "```python\nx=1\n```\n"

    def _format_probe(self, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
        probe = tmp_path / "probe.md"
        probe.write_text(self.PROBE)
        binary = _require_ruff()
        return subprocess.run(
            [binary, "format", "--check", *args, str(probe)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=REPO_ROOT,
        )

    def test_the_probe_would_be_reformatted_without_the_exclude(self, tmp_path):
        # --force-exclude here too, so the ONLY difference from the test below
        # is --isolated vs the repo's config. Without it the pair differs by
        # two variables, and a future ruff that skipped explicitly-named
        # non-.py arguments under --force-exclude would make the exclusion test
        # pass for a reason that has nothing to do with pyproject.toml, with
        # this control none the wiser.
        result = self._format_probe(tmp_path, "--force-exclude", "--isolated")
        assert result.returncode == 1, (
            "the probe is already formatted, so the exclusion test below would "
            f"pass for the wrong reason:\n{result.stdout}{result.stderr}"
        )

    def test_markdown_is_excluded_under_the_repo_config(self, tmp_path):
        # --force-exclude, because ruff applies excludes to *discovered* paths
        # and an explicitly-named file bypasses them — the same flag pre-commit
        # passes for the same reason. Without it this test would pass whatever
        # pyproject.toml says.
        result = self._format_probe(
            tmp_path, "--force-exclude", "--config", "pyproject.toml"
        )
        assert result.returncode == 0 and "would be reformatted" not in result.stdout, (
            "ruff formatted a Markdown file under the repo's config. The "
            '`extend-exclude = ["*.md"]` in [tool.ruff] has gone, and the '
            "formatter now rewrites verbatim quotations in "
            f"references/process-log/:\n{result.stdout}{result.stderr}"
        )
