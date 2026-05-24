"""Behavioral tests for worktree-destroy.sh --base <ref>.

Exercises the script end-to-end against a throwaway git repo:
- --base with a ref the branch IS merged into → exit 0
- --base with a ref the branch is NOT merged into → exit 1 (Iron Law)
- --base with a non-existent ref → exit 2 (tooling)
- --base with no argument → exit 2 (tooling)
- --descoped + --base together → descoped wins (exit 0, ignores --base)
- unknown flag → exit 2

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


def _run_destroy(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run worktree-destroy.sh with cwd=repo so it picks up the right project root."""
    env = _clean_env()
    env["WORKTREE_ROOT"] = str(repo / ".worktrees")
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
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
