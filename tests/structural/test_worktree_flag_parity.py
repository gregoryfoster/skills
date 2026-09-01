"""Flag-position parity between worktree-create.sh and worktree-destroy.sh (#262).

The two scripts took flags in OPPOSITE positions — create wanted its flag
before `<branch>`, destroy wanted its flags after — and each mis-diagnosed the
other's habit in a way that pointed the reader at the wrong token:

- `destroy --force <branch>` read '--force' AS the branch (a blind positional
  `$1` with no shape check), shifted past it, and handed the real branch to the
  unknown-flag arm. The error named the one argument that was correct.
- `create <branch> --new` dropped the trailing flag in silence; the failure
  surfaced as git's `fatal: invalid reference: <branch>`.
- `--help` was recognised only as `$1` in both. On create that was
  side-effecting: `create <existing-branch> --help` provisioned a worktree and
  printed its path instead of printing help.

`--force` is the routine destroy invocation for any repo with submodules
(`git worktree remove` refuses those without it), so the destroy direction was
hit on ordinary use, not at an edge.

These tests own the PARITY rather than either script's individual behaviour:
divergence between the pair is the defect that recurs, and `worktree-list.sh`
already documents the convention both should follow ("scan all args for --help
first so any combination still prints help rather than running the command").

No API calls. Self-contained: each test gets a fresh tmp repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "using-git-worktrees"
    / "scripts"
)
CREATE = SCRIPTS / "worktree-create.sh"
DESTROY = SCRIPTS / "worktree-destroy.sh"


def _clean_env(repo: Path) -> dict:
    """Env without inherited GIT_* vars, pinned to the fixture's worktree root.

    Pre-commit and other tooling set GIT_INDEX_FILE / GIT_DIR / GIT_WORK_TREE,
    which would otherwise leak into the scripts' git calls.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["WORKTREE_ROOT"] = str(repo / ".worktrees")
    return env


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(repo),
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )


def _worktree_count(repo: Path) -> int:
    out = _git(repo, "worktree", "list", "--porcelain").stdout
    return out.count("\nworktree ") + out.startswith("worktree ")


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A repo with `merged` pointing at main's commit, so the Iron Law passes.

    Base resolution finds no origin, falls back to local `main`; `merged` is
    the same commit, so it is trivially an ancestor and destroy is free to
    exercise flag ORDER without the merge gate interfering.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "merged")
    (repo / ".worktrees").mkdir()
    return repo


# --- The two filed repros --------------------------------------------------


def test_destroy_accepts_force_before_branch(tmp_repo: Path):
    """`destroy --force <branch>` must not read '--force' as the branch.

    The filed repro: the error named 'feat/some-branch', the one token that was
    correct, and the worktree stayed in place.
    """
    _run(CREATE, tmp_repo, "merged")
    result = _run(DESTROY, tmp_repo, "--force", "merged")
    assert result.returncode == 0, (
        f"flag-first destroy must work, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unknown flag 'merged'" not in result.stderr, (
        "the branch must never be reported as a flag"
    )
    assert _worktree_count(tmp_repo) == 1, "the worktree must actually be gone"


def test_create_accepts_new_after_branch(tmp_repo: Path):
    """`create <branch> --new` must create the branch, not drop the flag.

    Trailing `--new` used to vanish without a word, surfacing as git's
    `fatal: invalid reference` for a branch the caller asked to have created.
    """
    result = _run(CREATE, tmp_repo, "feat/trailing", "--new")
    assert result.returncode == 0, (
        f"trailing --new must be honoured, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    assert "invalid reference" not in result.stderr
    branches = _git(tmp_repo, "branch", "--list", "feat/trailing").stdout
    assert "feat/trailing" in branches, "--new must have created the branch"


# --- Parity: the property that must hold for BOTH --------------------------


@pytest.mark.parametrize(
    ("script", "args_before", "args_after"),
    [
        pytest.param(CREATE, ["--new", "flag/first"], ["flag/last", "--new"], id="create"),
        pytest.param(
            DESTROY,
            ["--descoped", "probe", "merged"],
            ["merged", "--descoped", "probe"],
            id="destroy",
        ),
    ],
)
def test_flag_order_is_immaterial(
    tmp_repo: Path, script: Path, args_before: list, args_after: list
):
    """Flags before and after <branch> must be equivalent in both scripts."""
    if script is DESTROY:
        _run(CREATE, tmp_repo, "merged")
    first = _run(script, tmp_repo, *args_before)
    assert first.returncode == 0, f"flag-first failed\nstderr: {first.stderr}"

    if script is DESTROY:
        _run(CREATE, tmp_repo, "merged")
    second = _run(script, tmp_repo, *args_after)
    assert second.returncode == 0, f"flag-last failed\nstderr: {second.stderr}"


@pytest.mark.parametrize("script", [CREATE, DESTROY], ids=["create", "destroy"])
def test_help_works_in_any_position(tmp_repo: Path, script: Path):
    """`--help` after <branch> prints help, in both scripts.

    worktree-list.sh already scans every argument for --help before running;
    these two did not.
    """
    result = _run(script, tmp_repo, "merged", "--help")
    assert result.returncode == 0, (
        f"trailing --help must exit 0, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert result.stdout.startswith("Usage:"), (
        f"trailing --help must print usage, got: {result.stdout[:120]!r}"
    )


def test_help_after_existing_branch_does_not_provision(tmp_repo: Path):
    """The escalation: a documentation request must not mutate the repo.

    `create <existing-branch> --help` fell through to provisioning — it created
    a worktree and printed its path where help was asked for.
    """
    before = _worktree_count(tmp_repo)
    result = _run(CREATE, tmp_repo, "merged", "--help")
    assert result.stdout.startswith("Usage:")
    assert _worktree_count(tmp_repo) == before, (
        "--help must never provision a worktree"
    )


@pytest.mark.parametrize("script", [CREATE, DESTROY], ids=["create", "destroy"])
def test_second_positional_is_a_named_error(tmp_repo: Path, script: Path):
    """A stray bare word is rejected AS an argument, not dropped or misnamed.

    create silently ignored it; destroy called it an "unknown flag", which is
    its own misdiagnosis — a bare word is not a flag.
    """
    result = _run(script, tmp_repo, "merged", "stray")
    assert result.returncode == 2, (
        f"expected tooling exit 2, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unexpected argument 'stray'" in result.stderr
    assert "unknown flag" not in result.stderr, "a bare word must not be called a flag"


@pytest.mark.parametrize("script", [CREATE, DESTROY], ids=["create", "destroy"])
def test_argument_error_does_not_bury_the_diagnosis(tmp_repo: Path, script: Path):
    """An argument error prints a short hint, not the whole usage block.

    The full dump (23 lines for create, 69 for destroy) printed to stderr
    directly under the ERROR line, so the diagnosis scrolled off the top and a
    `| tail` on the output showed only boilerplate — which is how the #262
    misdiagnosis was lost. `--help` still prints everything.
    """
    result = _run(script, tmp_repo, "--bogus")
    assert result.returncode == 2
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    assert lines[0].startswith("ERROR:"), "the diagnosis must come first"
    assert len(lines) <= 4, (
        f"argument errors must stay short enough to survive a `| tail`; "
        f"got {len(lines)} lines: {lines!r}"
    )
    assert "--help" in result.stderr, "the short hint must point at the full usage"

    full = _run(script, tmp_repo, "--help")
    assert len(full.stdout.splitlines()) > len(lines), (
        "--help must still print the full description"
    )
