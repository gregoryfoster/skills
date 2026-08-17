"""Behavioral tests for the pre-commit hook's venv bootstrap (#156).

A harness-provisioned worktree (`isolation: "worktree"`, at
`.claude/worktrees/agent-<id>/`) contains no `.venv`. Before this gate the
hook's entry was the literal

    bash -c 'source .venv/bin/activate && pytest tests/structural/ -v'

which fails with bash's raw `.venv/bin/activate: No such file or directory`
*after* the work is done and the suite is green — the worst possible moment,
and a message that names neither the cause nor the remedy. Three of four
agents in the #155 Batch C hit it independently.

`scripts/structural-tests.sh` is the fix. It is the hook's entry, and before
running pytest it guarantees the venv:

1. `.venv/bin/activate` resolves (main checkout, or a worktree already
   linked) → run, unchanged.
2. It does not, and this is a *linked* worktree whose main checkout has one
   → symlink the main checkout's `.venv` into place and say so. This is the
   silent-variant fix too: a symlink is by construction the *same*
   environment, not a thinner re-resolution that collects fewer tests while
   still reporting green.
3. Neither → exit non-zero with a diagnosis that names the one-line remedy.

`--check` performs 1–3 and stops, so these tests can exercise the resolution
without running a nested pytest.

No API calls. Self-contained: each test gets a fresh tmp repo.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "structural-tests.sh"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CREATE_SCRIPT = (
    REPO_ROOT / "skills" / "using-git-worktrees" / "scripts" / "worktree-create.sh"
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars.

    pre-commit itself sets GIT_INDEX_FILE / GIT_DIR while running this very
    suite, and those would leak into the tmp repo's git calls.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
        env=_clean_env(),
    )


def _run_bootstrap(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(cwd / "scripts" / "structural-tests.sh"), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=_clean_env(),
    )


def _make_venv(root: Path) -> None:
    """A real-enough venv: what the hook actually probes is bin/activate."""
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "activate").write_text("# fake activate\n")


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A main checkout carrying a copy of the script under test.

    The script is committed, so `git worktree add` gives every linked
    worktree its own copy — exactly as in the real repo.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "test")
    shutil.copy(SCRIPT, repo / "scripts" / "structural-tests.sh")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", "initial")
    return repo


def _add_worktree(repo: Path, name: str = "agent-1") -> Path:
    """A linked worktree shaped like the harness's: a leaf under
    .claude/worktrees/ whose name differs from its branch."""
    path = repo / ".claude" / "worktrees" / name
    _run_git(repo, "worktree", "add", "-b", f"worktree-{name}", str(path))
    return path


# ---------------------------------------------------------------------------
# The hook wiring
# ---------------------------------------------------------------------------


class TestPreCommitEntry:
    """The hook must route through the bootstrap, not bare-source the venv."""

    def _structural_hook(self) -> dict:
        config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text())
        hooks = [h for r in config["repos"] for h in r.get("hooks", [])]
        matches = [h for h in hooks if h["id"] == "structural-tests"]
        assert matches, "the 'structural-tests' hook must exist"
        return matches[0]

    def test_entry_delegates_to_the_bootstrap_script(self):
        entry = self._structural_hook()["entry"]
        assert "scripts/structural-tests.sh" in entry, (
            "the structural-tests hook must run scripts/structural-tests.sh so a "
            "missing .venv is linked or diagnosed; got: " + entry
        )

    def test_entry_does_not_bare_source_the_venv(self):
        entry = self._structural_hook()["entry"]
        assert "source .venv/bin/activate" not in entry, (
            "sourcing .venv/bin/activate inline is the #156 defect: in a linked "
            "worktree it fails with bash's raw 'No such file or directory' after "
            "a green suite. Route through scripts/structural-tests.sh instead."
        )

    def test_script_is_executable(self):
        assert SCRIPT.exists(), f"{SCRIPT} must exist"
        assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"


# ---------------------------------------------------------------------------
# Venv resolution
# ---------------------------------------------------------------------------


class TestVenvBootstrap:
    def test_linked_worktree_without_venv_gets_the_main_checkouts(self, tmp_repo: Path):
        """The #156 case. The worktree has no .venv; the main checkout does."""
        _make_venv(tmp_repo)
        wt = _add_worktree(tmp_repo)
        assert not (wt / ".venv").exists(), "precondition: the worktree has no .venv"

        result = _run_bootstrap(wt, "--check")

        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        link = wt / ".venv"
        assert link.is_symlink(), ".venv must be created as a symlink, not copied"
        assert link.resolve() == (tmp_repo / ".venv").resolve(), (
            "the link must point at the main checkout's venv — the same "
            "environment, not a re-resolution"
        )
        assert (link / "bin" / "activate").exists()

    def test_linked_worktree_link_is_reported_not_silent(self, tmp_repo: Path):
        """A mutation of the working tree must announce itself."""
        _make_venv(tmp_repo)
        wt = _add_worktree(tmp_repo)
        result = _run_bootstrap(wt, "--check")
        assert ".venv" in result.stderr, (
            "linking the venv must be reported on stderr, not done silently; "
            f"stderr was: {result.stderr!r}"
        )

    def test_second_run_in_a_linked_worktree_is_idempotent(self, tmp_repo: Path):
        _make_venv(tmp_repo)
        wt = _add_worktree(tmp_repo)
        first = _run_bootstrap(wt, "--check")
        second = _run_bootstrap(wt, "--check")
        assert first.returncode == 0 and second.returncode == 0, (
            f"both runs must succeed; got {first.returncode} then "
            f"{second.returncode}\n{second.stderr}"
        )
        assert (wt / ".venv").is_symlink()

    def test_main_checkout_venv_is_left_alone(self, tmp_repo: Path):
        """The regression guard: the fix must not disturb the main checkout,
        where .venv is a real directory and everything already worked."""
        _make_venv(tmp_repo)
        result = _run_bootstrap(tmp_repo, "--check")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        venv = tmp_repo / ".venv"
        assert venv.is_dir() and not venv.is_symlink(), (
            "a real .venv in the main checkout must survive untouched"
        )

    def test_main_checkout_without_venv_diagnoses_and_fails(self, tmp_repo: Path):
        """Nothing to link to — say what to do instead of failing bare."""
        result = _run_bootstrap(tmp_repo, "--check")
        assert result.returncode != 0, "a missing venv must fail the hook"
        combined = result.stdout + result.stderr
        assert "python3 -m venv .venv" in combined, (
            "the diagnosis must name the remedy for a main checkout; got: "
            + combined
        )

    def test_linked_worktree_diagnoses_when_the_parent_has_no_venv_either(
        self, tmp_repo: Path
    ):
        wt = _add_worktree(tmp_repo)
        result = _run_bootstrap(wt, "--check")
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "ln -s" in combined, (
            "the diagnosis must name the one-line `ln -s <main>/.venv .venv` "
            "remedy, not bash's raw 'No such file or directory'; got: " + combined
        )

    def test_help_exits_clean(self, tmp_repo: Path):
        result = _run_bootstrap(tmp_repo, "--help")
        assert result.returncode == 0, result.stderr
        assert "structural-tests.sh" in result.stdout


# ---------------------------------------------------------------------------
# The other end: worktrees this repo's own script provisions
# ---------------------------------------------------------------------------


class TestWorktreeCreateLinksVenv:
    """worktree-create.sh links the parent's venv at provisioning time.

    This closes a window the hook cannot: the hook only runs at commit time,
    so between `worktree-create.sh` and the first commit an agent running
    `.venv/bin/python -m pytest` — the command every worker brief mandates —
    still has nothing to run. Linking at creation makes the venv present
    before the first command.

    It does NOT help harness-provisioned worktrees: the Agent tool's
    `isolation: "worktree"` calls `git worktree add` itself, never this
    script (its leaves are `.claude/worktrees/agent-<id>/` on branch
    `worktree-agent-<id>`, neither of which this script's `<root>/<slug>`
    scheme can produce). Those are covered by the hook plus AGENTS.md.
    """

    def test_created_worktree_gets_a_venv_symlink(self, tmp_repo: Path):
        _make_venv(tmp_repo)
        env = _clean_env()
        env["WORKTREE_ROOT"] = str(tmp_repo / ".worktrees")
        result = subprocess.run(
            ["bash", str(CREATE_SCRIPT), "--new", "feature/x"],
            capture_output=True,
            text=True,
            cwd=str(tmp_repo),
            env=env,
        )
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        wt = Path(result.stdout.strip())
        assert wt.is_dir(), f"stdout must stay the worktree path; got {result.stdout!r}"
        link = wt / ".venv"
        assert link.is_symlink(), (
            "worktree-create.sh must link the parent's .venv into the new "
            f"worktree; stderr: {result.stderr}"
        )
        assert (link / "bin" / "activate").exists()

    def test_no_parent_venv_is_not_an_error(self, tmp_repo: Path):
        """Non-Python repos vendor this script too — the link is opportunistic."""
        env = _clean_env()
        env["WORKTREE_ROOT"] = str(tmp_repo / ".worktrees")
        result = subprocess.run(
            ["bash", str(CREATE_SCRIPT), "--new", "feature/y"],
            capture_output=True,
            text=True,
            cwd=str(tmp_repo),
            env=env,
        )
        assert result.returncode == 0, (
            f"a parent without .venv must not fail creation; stderr: {result.stderr}"
        )
        assert not (Path(result.stdout.strip()) / ".venv").exists()
