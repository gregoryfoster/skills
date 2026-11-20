"""`install-cadence.sh --merge-mode pr|direct` renders for the mode named (#674).

The installer reads `.skills/merge_mode` from the primary checkout (#612), so
the branch that flips the knob, built in a linked worktree, rendered the mode
the primary reads now: the old one, byte-identical to what was installed. The
re-render had to wait for a second PR, and `main` held a `pr` knob under a
`direct` workflow until it landed (CannObserv/replicator#208). The workaround
that worked was to clone the branch so the clone became its own primary.

The flag is the issue's own proposal 1. Reading the current checkout's
committed knob was the alternative, and #674 calls it the riskier form: two
sources of truth, after #612 made the primary the only one. So the flag names
the mode, the primary's knob is still read and still reported, and where the
two disagree the installer says so, without refusing: that disagreement is
exactly the knob-flip branch.

No API calls. Every fixture repo is built with an explicit path and a
scrubbed `GIT_*` environment (#189).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_CADENCE = (
    REPO_ROOT / "skills" / "curating-context" / "scripts" / "install-cadence.sh"
)
WF = ".github/workflows/context-cadence.yml"
READ_STEP = "Read the merge mode"
CRON = ("--cron", "0 15 * * 1")


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("x\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _knob(repo: Path, text: str | None) -> None:
    k = repo / ".skills" / "merge_mode"
    if text is None:
        if k.exists():
            k.unlink()
        return
    k.parent.mkdir(exist_ok=True)
    k.write_text(text)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(),
    )


def _print(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(repo, "--print", *CRON, *args)


def _line(stdout: str, label: str) -> str:
    """A --check line with its continuation lines, joined."""
    out, keep = [], False
    for ln in stdout.splitlines():
        if ln and not ln.startswith(" "):
            keep = ln.startswith(label)
        if keep:
            out.append(ln.strip())
    return " ".join(" ".join(out).split())


class TestTheFlagPicksTheRender:
    def test_pr_renders_the_pr_workflow_with_no_knob(self, tmp_path: Path):
        repo = _repo(tmp_path / "flag")
        knobbed = _repo(tmp_path / "knob")
        _knob(knobbed, "pr\n")
        r = _print(repo, "--merge-mode", "pr")
        assert r.returncode == 0, r.stderr
        assert READ_STEP in r.stdout
        assert r.stdout == _print(knobbed).stdout, "the flag renders what the knob does"

    def test_direct_renders_the_direct_workflow_under_a_pr_knob(self, tmp_path: Path):
        repo = _repo(tmp_path / "flag")
        _knob(repo, "pr\n")
        plain = _repo(tmp_path / "plain")
        r = _print(repo, "--merge-mode", "direct")
        assert r.returncode == 0, r.stderr
        assert READ_STEP not in r.stdout
        assert r.stdout == _print(plain).stdout

    @pytest.mark.parametrize(
        ("knob", "flag", "reads"),
        [
            (None, "pr", "absent"),
            ("pr\n", "direct", "pr"),
            ("direct\n", "pr", "direct"),
        ],
        ids=["absent-to-pr", "pr-to-direct", "direct-to-pr"],
    )
    def test_a_flag_the_knob_disagrees_with_is_said_not_refused(
        self, tmp_path, knob, flag, reads
    ):
        repo = _repo(tmp_path / "r")
        _knob(repo, knob)
        r = _print(repo, "--merge-mode", flag)
        assert r.returncode == 0, r.stderr
        err = " ".join(r.stderr.split())
        assert f"--merge-mode {flag}" in err, r.stderr
        assert f"reads {reads}" in err, r.stderr
        assert "commit .skills/merge_mode" in err, r.stderr

    @pytest.mark.parametrize(("knob", "flag"), [(None, "direct"), ("pr\n", "pr")])
    def test_a_flag_the_knob_agrees_with_says_nothing(self, tmp_path, knob, flag):
        repo = _repo(tmp_path / "r")
        _knob(repo, knob)
        r = _print(repo, "--merge-mode", flag)
        assert r.returncode == 0, r.stderr
        assert r.stderr == ""

    @pytest.mark.parametrize("bad", ["PR", "pull-request", ""])
    def test_a_value_that_is_not_a_mode_is_a_usage_error(self, tmp_path, bad):
        repo = _repo(tmp_path / "r")
        r = _print(repo, "--merge-mode", bad)
        assert r.returncode == 1, r.stdout + r.stderr
        assert r.stdout == ""
        assert "--merge-mode" in r.stderr

    def test_a_missing_value_is_a_usage_error(self, tmp_path: Path):
        repo = _repo(tmp_path / "r")
        r = _run(repo, "--print", "--merge-mode")
        assert r.returncode == 1, r.stdout + r.stderr
        assert r.stdout == ""

    def test_an_unusable_knob_does_not_stop_a_named_mode(self, tmp_path: Path):
        """The refusal (exit 5) exists so an unreadable knob never reads as
        `direct`. With the flag nothing is read from it, so the render is
        safe; the knob is still named, since the job will read it."""
        repo = _repo(tmp_path / "r")
        _knob(repo, "PR\n")
        assert _print(repo).returncode == 5, "fixture: the knob is unusable"
        r = _print(repo, "--merge-mode", "pr")
        assert r.returncode == 0, r.stderr
        assert READ_STEP in r.stdout
        assert "unusable" in r.stderr.lower() or "not a merge mode" in r.stderr

    def test_help_names_the_flag(self, tmp_path: Path):
        r = _run(tmp_path, "--help")
        assert r.returncode == 0
        assert "--merge-mode" in r.stdout


class TestTheKnobFlipBranch:
    """#674's case: the primary has no knob, and a linked worktree's branch
    commits `pr`. The branch can now carry its own re-render, and --check
    with the flag proves it."""

    def _branch(self, tmp_path: Path) -> tuple[Path, Path]:
        primary = _repo(tmp_path / "primary")
        r = _run(primary, *CRON)
        assert r.returncode == 0, r.stderr
        _git(primary, "add", "-A")
        _git(primary, "commit", "-qm", "cadence, direct")
        wt = tmp_path / "wt"
        _git(primary, "worktree", "add", "-q", "-b", "flip", str(wt))
        _knob(wt, "pr\n")
        _git(wt, "add", ".skills/merge_mode")
        _git(wt, "commit", "-qm", "merge_mode pr")
        return primary, wt

    def test_without_the_flag_the_branch_renders_the_primarys_mode(self, tmp_path):
        """Today's behaviour, unchanged: it is the reason for the flag."""
        _, wt = self._branch(tmp_path)
        r = _run(wt, *CRON)
        assert r.returncode == 0, r.stderr
        assert "unchanged:" in r.stdout
        assert READ_STEP not in (wt / WF).read_text()

    def test_the_flag_renders_the_branchs_mode_in_place(self, tmp_path: Path):
        primary, wt = self._branch(tmp_path)
        r = _run(wt, *CRON, "--merge-mode", "pr")
        assert r.returncode == 0, r.stderr
        assert "updated:" in r.stdout
        assert READ_STEP in (wt / WF).read_text()
        assert READ_STEP not in (primary / WF).read_text(), "the primary is untouched"

    def test_check_with_the_flag_proves_the_branch_carries_the_render(
        self, tmp_path: Path
    ):
        primary, wt = self._branch(tmp_path)
        before = _run(wt, *CRON, "--check", "--merge-mode", "pr")
        assert before.returncode == 3, before.stdout
        assert "STALE" in _line(before.stdout, "merge mode:")
        assert "behind" in _line(before.stdout, "re-render:")
        assert _run(wt, *CRON, "--merge-mode", "pr").returncode == 0
        after = _run(wt, *CRON, "--check", "--merge-mode", "pr")
        assert "re-render:          none" in after.stdout, after.stdout
        mm = _line(after.stdout, "merge mode:")
        assert mm.startswith("merge mode: pr"), mm
        assert "--merge-mode pr" in mm and "reads absent (direct)" in mm, mm
        # The drivers are the primary's shared config, set by its install.
        assert after.returncode == 0, after.stdout

    def test_after_the_merge_the_primary_reads_none(self, tmp_path: Path):
        primary, wt = self._branch(tmp_path)
        assert _run(wt, *CRON, "--merge-mode", "pr").returncode == 0
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "re-render for pr")
        _git(primary, "merge", "-q", "--ff-only", "flip")
        r = _run(primary, *CRON, "--check")
        assert r.returncode == 0, r.stdout
        assert "re-render:          none" in r.stdout
        assert _line(r.stdout, "merge mode:").startswith("merge mode: pr")

    def test_the_flag_back_to_direct_on_a_pr_primary(self, tmp_path: Path):
        """The other flip: the primary reads `pr`, the branch deletes the knob."""
        primary = _repo(tmp_path / "primary")
        _knob(primary, "pr\n")
        _git(primary, "add", "-A")
        _git(primary, "commit", "-qm", "pr")
        assert _run(primary, *CRON).returncode == 0
        _git(primary, "add", "-A")
        _git(primary, "commit", "-qm", "cadence, pr")
        wt = tmp_path / "wt"
        _git(primary, "worktree", "add", "-q", "-b", "back", str(wt))
        _git(wt, "rm", "-q", ".skills/merge_mode")
        _git(wt, "commit", "-qm", "merge_mode back to direct")
        r = _run(wt, *CRON, "--merge-mode", "direct")
        assert r.returncode == 0, r.stderr
        assert READ_STEP not in (wt / WF).read_text()
        chk = _run(wt, *CRON, "--check", "--merge-mode", "direct")
        assert "re-render:          none" in chk.stdout, chk.stdout
        mm = _line(chk.stdout, "merge mode:")
        assert "STALE" not in mm and "--merge-mode direct" in mm, mm


class TestCheckWithoutTheFlagIsUnchanged:
    def test_the_report_is_byte_identical_without_the_flag(self, tmp_path: Path):
        """The flag given as the knob reads adds one line at most; omitted,
        nothing moves (absent, direct, pr)."""
        for knob in (None, "direct\n", "pr\n"):
            repo = _repo(tmp_path / (knob or "absent").strip())
            _knob(repo, knob)
            assert _run(repo, *CRON).returncode == 0
            plain = _run(repo, *CRON, "--check")
            assert "--merge-mode" not in plain.stdout
