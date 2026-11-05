"""The pre-push hook refuses a push whose tree has not passed the full suite (#537).

With selection on, a commit's hook can pass having run a fraction of the
suite. `scripts/pre-push-gate.sh` is the backstop that makes that safe: every
pushed commit's tree must have a full-suite pass, recorded or run now.

- the pushed tree checked out and clean: `structural-tests.sh` runs there,
  outside the hook's selection, and reuses a recorded pass in about a second;
- any other commit (a push by SHA, a dirty checkout): it is checked out into
  a temporary worktree and gated there, and the worktree is removed;
- a branch deletion pushes no tree, so nothing runs;
- a failed suite, or no venv to run it with, blocks the push.

pytest is faked as in test_structural_tests_select.py. No API calls.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COPIED = (
    "scripts/pre-push-gate.sh",
    "scripts/structural-tests.sh",
    "scripts/gate_select.py",
    "skills/shipping-work/scripts/gate-stamp.sh",
    "skills/shipping-work/scripts/gate-workers.sh",
)
FAKE_PYTEST = """#!/bin/sh
echo "$(pwd -P) $*" >> "$FAKE_PYTEST_LOG"
exit "${FAKE_PYTEST_RC:-0}"
"""
ZERO = "0" * 40


def _env(**extra: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "GATE_", "PRE_COMMIT", "PYTEST_"))
    }
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel in COPIED:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, repo / rel)
    (repo / "tests" / "structural").mkdir(parents=True)
    (repo / "tests" / "structural" / "test_x.py").write_text("def test(): pass\n")
    (repo / ".gitignore").write_text(".venv\n")
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text(f'export PATH="{venv_bin}:$PATH"\n')
    (venv_bin / "pytest").write_text(FAKE_PYTEST)
    (venv_bin / "pytest").chmod(0o755)
    (venv_bin / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (venv_bin / "python").chmod(0o755)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _push(repo: Path, to: str | None = None, **env: str) -> subprocess.CompletedProcess:
    extra = {
        "FAKE_PYTEST_LOG": str(repo.parent / "pytest.log"),
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "1",
        "PRE_COMMIT_FROM_REF": ZERO,
        "PRE_COMMIT_TO_REF": to or _git(repo, "rev-parse", "HEAD"),
    }
    extra.update(env)
    return subprocess.run(
        ["bash", "scripts/pre-push-gate.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        env=_env(**extra),
    )


def _calls(repo: Path) -> list[str]:
    log = repo.parent / "pytest.log"
    return log.read_text().splitlines() if log.exists() else []


def test_help():
    r = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/pre-push-gate.sh"), "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and "Exit codes" in r.stdout


def test_an_unproven_tree_runs_the_full_suite(repo):
    r = _push(repo)
    assert r.returncode == 0, r.stderr
    (call,) = _calls(repo)
    assert "tests/structural/" in call.split()


def test_a_proven_tree_reuses_its_pass(repo):
    assert _push(repo).returncode == 0
    r = _push(repo)
    assert r.returncode == 0, r.stderr
    assert len(_calls(repo)) == 1, "the second push re-ran a tree that had passed"


def test_the_hooks_selection_does_not_apply(repo):
    """pre-commit exports PRE_COMMIT=1 to pre-push hooks too."""
    (repo / ".git" / "gate-map.json").write_text('{"version": 1, "tests": {}}')
    r = _push(repo, PRE_COMMIT="1")
    assert r.returncode == 0, r.stderr
    assert "tests/structural/" in _calls(repo)[-1].split()


def test_a_failing_suite_blocks_the_push(repo):
    r = _push(repo, FAKE_PYTEST_RC="1")
    assert r.returncode == 1
    assert "push refused" in r.stderr


def test_another_commit_is_gated_in_a_temporary_worktree(repo):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("x\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "second")
    r = _push(repo, to=first)
    assert r.returncode == 0, r.stderr
    (call,) = _calls(repo)
    assert not call.startswith(str(repo.resolve()) + " "), "ran in the checkout"
    assert _git(repo, "worktree", "list").count("\n") == 0, "worktree left behind"


def test_a_dirty_checkout_is_not_what_gets_gated(repo):
    (repo / "tests" / "structural" / "test_x.py").write_text("def test(): assert 0\n")
    r = _push(repo)
    assert r.returncode == 0, r.stderr
    (call,) = _calls(repo)
    assert not call.startswith(str(repo.resolve()) + " ")


def test_a_branch_deletion_runs_nothing(repo):
    r = _push(repo, to=ZERO)
    assert r.returncode == 0 and _calls(repo) == []


def test_no_venv_blocks_the_push(repo):
    shutil.rmtree(repo / ".venv")
    r = _push(repo)
    assert r.returncode == 1
    assert "push refused" in r.stderr
