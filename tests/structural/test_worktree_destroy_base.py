"""Behavioral tests for worktree-destroy.sh --base <ref> and branch-first lookup.

Exercises the script end-to-end against a throwaway git repo:
- --base with a ref the branch IS merged into → exit 0
- --base with a ref the branch is NOT merged into → exit 1 (Iron Law)
- --base with a non-existent ref → exit 2 (tooling)
- --base with no argument → exit 2 (tooling)
- --descoped + --base together → descoped wins (exit 0, ignores --base)
- unknown flag → exit 2

Plus the harness-worktree cases from #149. The Claude Code Agent tool's
`isolation: "worktree"` provisions `.claude/worktrees/agent-<id>/` on branch
`worktree-agent-<id>`, so the branch and the directory leaf carry different
names and no WORKTREE_ROOT override can reach it. `TestBranchFirstLookup`
pins the registry-first resolution; `TestDryRun` pins the side-effect-free
preview that lets an agent verify resolution against a live worktree.

`TestLockedWorktrees` covers the lock gate. Note that the Agent tool holds
its lock only while the agent runs and releases it on exit, so a real
teardown normally sees no lock at all — the gate exists for the agent that
hung or died. Every test here therefore locks a throwaway worktree
explicitly; none observes (or may observe) the live, transient harness lock,
which would make the test pass or fail depending on what else is running.

No API calls. Self-contained: each test gets a fresh tmp repo via the
`tmp_repo` fixture.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "using-git-worktrees"
    / "scripts"
    / "worktree-destroy.sh"
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars.

    Pre-commit and other tooling can set GIT_INDEX_FILE / GIT_DIR /
    GIT_WORK_TREE / etc., which would otherwise leak into `git -C <tmp_repo>`
    calls and confuse them — e.g., `git worktree add` may try to honor a
    GIT_INDEX_FILE pointing at the parent repo's temp index.
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


def _run_destroy(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run worktree-destroy.sh with cwd=repo so it picks up the right project root.

    `cwd` overrides that, for the case where the script is invoked from
    *inside* a linked worktree rather than from the main checkout.
    """
    env = _clean_env()
    env["WORKTREE_ROOT"] = str(repo / ".worktrees")
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd if cwd is not None else repo),
        env=env,
    )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Build a fresh git repo shaped like a multi-agent orchestration mid-batch.

    Layout:
      main       — initial commit
      batch/x    — branch at main + 1 commit
      feature/y  — branch at batch/x (ancestor of batch/x via FF semantics)
      .worktrees/feature-y — worktree for feature/y

    feature/y is an ancestor of batch/x (same commit, FF). It is NOT an
    ancestor of main (batch/x is ahead of main).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial")

    _run_git(repo, "checkout", "-b", "batch/x")
    (repo / "batch.txt").write_text("batch\n")
    _run_git(repo, "add", "batch.txt")
    _run_git(repo, "commit", "-m", "batch work")

    # feature/y points at the same commit as batch/x — trivially an ancestor.
    _run_git(repo, "branch", "feature/y", "batch/x")

    # Create the worktree at the WORKTREE_ROOT-derived path.
    # worktree-destroy.sh resolves <root>/<slug>; slug for feature/y is "feature-y".
    worktrees_root = repo / ".worktrees"
    worktrees_root.mkdir()
    _run_git(
        repo,
        "worktree",
        "add",
        str(worktrees_root / "feature-y"),
        "feature/y",
    )
    return repo


def test_base_with_ref_branch_is_merged_into_succeeds(tmp_repo: Path):
    """feature/y == batch/x → ancestor check passes, destroy succeeds."""
    result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x")
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert not (tmp_repo / ".worktrees" / "feature-y").exists(), (
        "worktree directory should have been removed"
    )


def test_base_with_ref_branch_is_not_merged_into_refuses(tmp_repo: Path):
    """Add a commit to feature/y so it's no longer ancestor-of-batch/x → exit 1."""
    feature_wt = tmp_repo / ".worktrees" / "feature-y"
    (feature_wt / "newfile.txt").write_text("ahead\n")
    _run_git(feature_wt, "add", "newfile.txt")
    _run_git(feature_wt, "commit", "-m", "ahead of batch")

    result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x")
    assert result.returncode == 1, (
        f"expected Iron Law exit 1, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "not merged into 'batch/x'" in result.stderr
    assert feature_wt.exists(), "worktree should NOT have been removed on Iron Law violation"


def test_base_with_nonexistent_ref_errors(tmp_repo: Path):
    result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/does-not-exist")
    assert result.returncode == 2, (
        f"expected tooling exit 2, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "--base ref 'batch/does-not-exist' does not exist" in result.stderr


def test_base_with_no_argument_errors(tmp_repo: Path):
    result = _run_destroy(tmp_repo, "feature/y", "--base")
    assert result.returncode == 2
    assert "--base requires a <ref> argument" in result.stderr


def test_descoped_supersedes_base(tmp_repo: Path):
    """When both flags are supplied, --descoped wins and --base is ignored.

    Verify by passing a bogus --base ref that would otherwise fail validation.
    With --descoped, the merge check is skipped entirely so the bogus ref
    never gets touched.
    """
    result = _run_destroy(
        tmp_repo,
        "feature/y",
        "--base", "this-ref-does-not-exist",
        "--descoped", "testing precedence",
    )
    assert result.returncode == 0, (
        f"expected exit 0 (descoped wins), got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "Descoped: testing precedence" in result.stdout


def test_unknown_flag_errors(tmp_repo: Path):
    result = _run_destroy(tmp_repo, "feature/y", "--bogus")
    assert result.returncode == 2
    assert "unknown flag '--bogus'" in result.stderr


# --- #149: harness-provisioned worktrees ------------------------------------


def _add_worktree(repo: Path, path: Path, branch: str, *, start: str | None = None) -> Path:
    """Register a worktree at an arbitrary path, decoupled from <root>/<slug>."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if start is not None:
        _run_git(repo, "branch", branch, start)
    _run_git(repo, "worktree", "add", str(path), branch)
    return path


class TestBranchFirstLookup:
    """The worktree is located via the git registry, not a constructed path."""

    def test_harness_shaped_worktree_is_found(self, tmp_repo: Path):
        """Directory leaf and branch name differ — the #149 shape exactly.

        `.claude/worktrees/agent-<id>/` on branch `worktree-agent-<id>`. The
        old `<root>/<slug>` scheme would look for `.worktrees/worktree-agent-x`
        and report "no worktree at ...".
        """
        wt = _add_worktree(
            tmp_repo,
            tmp_repo / ".claude" / "worktrees" / "agent-x",
            "worktree-agent-x",
            start="batch/x",
        )
        result = _run_destroy(tmp_repo, "worktree-agent-x", "--base", "batch/x")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not wt.exists(), "harness-shaped worktree should have been removed"

    def test_path_containing_spaces_is_not_truncated(self, tmp_repo: Path):
        """The porcelain `worktree` line must be read whole, not split on $2.

        `awk '{p=$2}'` yields '/…/wt' for '/…/wt with space', which then fails
        the directory check.
        """
        wt = _add_worktree(
            tmp_repo, tmp_repo / "elsewhere" / "wt with space", "spaced", start="batch/x"
        )
        result = _run_destroy(tmp_repo, "spaced", "--base", "batch/x")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert not wt.exists()

    def test_branch_name_containing_double_quote(self, tmp_repo: Path):
        """git permits `"` in refnames; it must not reach awk as program text.

        Interpolating the branch into the awk source closes awk's string
        literal and turns the program into a syntax error.
        """
        branch = 'quo"ted'
        wt = _add_worktree(tmp_repo, tmp_repo / "elsewhere" / "quoted", branch, start="batch/x")
        result = _run_destroy(tmp_repo, branch, "--base", "batch/x")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert not wt.exists()

    def test_unregistered_branch_falls_back_to_constructed_path_error(self, tmp_repo: Path):
        """A genuine typo still produces the familiar constructed-path error."""
        _run_git(tmp_repo, "branch", "typo/branch", "batch/x")
        result = _run_destroy(tmp_repo, "typo/branch", "--base", "batch/x")
        assert result.returncode == 2
        assert "no worktree at" in result.stderr
        assert str(tmp_repo / ".worktrees" / "typo-branch") in result.stderr

    def test_detached_head_worktree_does_not_confuse_lookup(self, tmp_repo: Path):
        """A detached worktree emits no `branch` line; it must never match.

        Its `worktree` line must also not leak as the resolved path for a
        later block's branch.
        """
        _run_git(tmp_repo, "worktree", "add", "--detach", str(tmp_repo / "det"), "HEAD")
        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert (tmp_repo / "det").exists(), "the detached worktree must be untouched"

    def test_refuses_to_destroy_the_worktree_it_runs_from(self, tmp_repo: Path):
        """Making harness worktrees addressable makes self-destruction possible."""
        wt = tmp_repo / ".worktrees" / "feature-y"
        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x", cwd=wt)
        assert result.returncode == 2, (
            f"expected exit 2, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "running from" in result.stderr
        assert wt.exists(), "the current worktree must survive"


class TestLockedWorktrees:
    """git refuses to remove a locked worktree even with a single --force."""

    @pytest.fixture
    def locked_repo(self, tmp_repo: Path) -> Path:
        _run_git(
            tmp_repo,
            "worktree",
            "lock",
            str(tmp_repo / ".worktrees" / "feature-y"),
            "--reason",
            "claude agent agent-x",
        )
        return tmp_repo

    def test_locked_worktree_refused_by_default(self, locked_repo: Path):
        result = _run_destroy(locked_repo, "feature/y", "--base", "batch/x")
        assert result.returncode == 2, (
            f"expected exit 2, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "locked" in result.stderr
        assert "claude agent agent-x" in result.stderr, "the lock reason must be surfaced"
        assert "--unlock" in result.stderr, "the remedy must be named"
        assert (locked_repo / ".worktrees" / "feature-y").exists()

    def test_force_alone_does_not_override_a_lock(self, locked_repo: Path):
        """--force is a single -f; git demands -f -f. It must not be the remedy."""
        result = _run_destroy(locked_repo, "feature/y", "--base", "batch/x", "--force")
        assert result.returncode == 2
        assert "--unlock" in result.stderr
        assert (locked_repo / ".worktrees" / "feature-y").exists()

    def test_unlock_releases_the_lock_and_destroys(self, locked_repo: Path):
        result = _run_destroy(locked_repo, "feature/y", "--base", "batch/x", "--unlock")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not (locked_repo / ".worktrees" / "feature-y").exists()

    def test_unlock_does_not_bypass_the_dirty_tree_check(self, locked_repo: Path):
        """--unlock is narrow: it releases the lock and nothing else.

        This is the whole reason it is not spelled --force. Uncommitted work
        must still block removal.
        """
        (locked_repo / ".worktrees" / "feature-y" / "uncommitted.txt").write_text("wip\n")
        result = _run_destroy(locked_repo, "feature/y", "--base", "batch/x", "--unlock")
        assert result.returncode == 2, (
            f"expected exit 2, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert (locked_repo / ".worktrees" / "feature-y").exists(), (
            "uncommitted work must not be discarded by --unlock"
        )

    def test_unlock_still_obeys_the_iron_law(self, locked_repo: Path):
        feature_wt = locked_repo / ".worktrees" / "feature-y"
        (feature_wt / "newfile.txt").write_text("ahead\n")
        _run_git(feature_wt, "add", "newfile.txt")
        _run_git(feature_wt, "commit", "-m", "ahead of batch")

        result = _run_destroy(locked_repo, "feature/y", "--base", "batch/x", "--unlock")
        assert result.returncode == 1, (
            f"expected Iron Law exit 1, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert feature_wt.exists()

    def test_gitignored_symlink_does_not_require_force(self, tmp_repo: Path):
        """A properly ignored .venv symlink is invisible to git's clean check.

        #149 blamed the .venv symlink for the --force requirement; the lock is
        the actual cause. This pins that the symlink alone is harmless.
        """
        feature_wt = tmp_repo / ".worktrees" / "feature-y"
        (feature_wt / ".gitignore").write_text(".venv\n")
        _run_git(feature_wt, "add", ".gitignore")
        _run_git(feature_wt, "commit", "-m", "ignore venv")
        # Fast-forward batch/x (checked out in the main repo) onto feature/y so
        # the Iron Law still passes.
        _run_git(tmp_repo, "merge", "--ff-only", "feature/y")

        (feature_wt / ".venv").symlink_to(tmp_repo)
        assert _run_git(feature_wt, "status", "--porcelain").stdout == "", (
            "the symlink must be invisible to git for this test to mean anything"
        )

        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x")
        assert result.returncode == 0, (
            f"expected exit 0 without --force, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert not feature_wt.exists()


class TestDryRun:
    """--dry-run previews the decision without touching anything."""

    def test_dry_run_reports_and_removes_nothing(self, tmp_repo: Path):
        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x", "--dry-run")
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "DRY RUN" in result.stdout
        assert str(tmp_repo / ".worktrees" / "feature-y") in result.stdout
        assert (tmp_repo / ".worktrees" / "feature-y").exists(), "dry run must not remove"

    def test_dry_run_predicts_the_iron_law_exit_code(self, tmp_repo: Path):
        """A dry run that exits 0 while the real run would exit 1 is worthless."""
        feature_wt = tmp_repo / ".worktrees" / "feature-y"
        (feature_wt / "newfile.txt").write_text("ahead\n")
        _run_git(feature_wt, "add", "newfile.txt")
        _run_git(feature_wt, "commit", "-m", "ahead of batch")

        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x", "--dry-run")
        assert result.returncode == 1, (
            f"expected Iron Law exit 1, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert feature_wt.exists()

    def test_dry_run_predicts_the_lock_exit_code(self, tmp_repo: Path):
        """A lock the operator has not acknowledged would fail the real run."""
        _run_git(
            tmp_repo,
            "worktree",
            "lock",
            str(tmp_repo / ".worktrees" / "feature-y"),
            "--reason",
            "claude agent agent-x",
        )
        result = _run_destroy(tmp_repo, "feature/y", "--base", "batch/x", "--dry-run")
        assert result.returncode == 2, (
            f"expected exit 2, got {result.returncode}\nstdout: {result.stdout}"
        )
        assert "claude agent agent-x" in result.stdout
        assert "--unlock" in result.stdout
        assert (tmp_repo / ".worktrees" / "feature-y").exists()

    def test_dry_run_with_unlock_on_a_locked_worktree_succeeds(self, tmp_repo: Path):
        """With the flag supplied, the real run would work — so the preview passes."""
        _run_git(
            tmp_repo,
            "worktree",
            "lock",
            str(tmp_repo / ".worktrees" / "feature-y"),
            "--reason",
            "claude agent agent-x",
        )
        result = _run_destroy(
            tmp_repo, "feature/y", "--base", "batch/x", "--dry-run", "--unlock"
        )
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\nstdout: {result.stdout}"
        )
        assert (tmp_repo / ".worktrees" / "feature-y").exists(), "dry run must not remove"
        # The lock itself must survive a dry run.
        listing = _run_git(tmp_repo, "worktree", "list", "--porcelain").stdout
        assert "locked claude agent agent-x" in listing, "dry run must not release the lock"
