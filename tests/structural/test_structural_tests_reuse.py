"""`structural-tests.sh` runs the suite once per tree, in parallel (#537).

The hook and the ship gate both enter through this script. Before #537 each
ran the whole suite serially, so a commit followed by a ship paid for it twice
on identical files. Now:

- a green run records a stamp for its tree, and the next run on the same tree
  (hook -> pre-ship, a message-only amend) reuses it instead of re-running;
- under the hook (PRE_COMMIT=1) the stamp is for the tree being committed,
  which is HEAD^{tree} once the commit lands;
- a failure, a dirty tree, an untracked file or GATE_STAMP=off records or
  reuses nothing;
- the worker count from gate-workers.sh becomes `-n N --dist loadfile`, and
  `off` means no xdist flags at all;
- pytest's own exit code still passes through — 5 especially.

pytest is faked by a `.venv/bin/pytest` that logs its arguments, so the suite
under test never recurses into itself. `python` is the real interpreter: the
script asks it for the installed-package list and whether xdist imports.
No API calls; each test gets a fresh repo.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COPIED = (
    "scripts/structural-tests.sh",
    "skills/shipping-work/scripts/gate-stamp.sh",
    "skills/shipping-work/scripts/gate-workers.sh",
)

FAKE_PYTEST = """#!/bin/sh
echo "$*" >> "$FAKE_PYTEST_LOG"
exit "${FAKE_PYTEST_RC:-0}"
"""


def _clean_env(**extra: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "GATE_STAMP", "PRE_COMMIT"))
        and k != "PYTEST_XDIST_AUTO_NUM_WORKERS"
    }
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel in COPIED:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, repo / rel)
    (repo / "tests" / "structural").mkdir(parents=True)
    (repo / "tests" / "structural" / "test_x.py").write_text("def test_x(): pass\n")
    (repo / ".gitignore").write_text(".venv\n")
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text(f'export PATH="{venv_bin}:$PATH"\n')
    (venv_bin / "pytest").write_text(FAKE_PYTEST)
    (venv_bin / "pytest").chmod(0o755)
    # A wrapper, not a symlink: a venv interpreter reached through a link
    # outside its venv finds no pyvenv.cfg and loses the venv's packages.
    (venv_bin / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (venv_bin / "python").chmod(0o755)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _suite(repo: Path, rc: int = 0, **env: str) -> subprocess.CompletedProcess:
    env.setdefault("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    return subprocess.run(
        ["bash", "scripts/structural-tests.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(
            FAKE_PYTEST_LOG=str(repo.parent / "pytest.log"),
            FAKE_PYTEST_RC=str(rc),
            **env,
        ),
    )


def _calls(repo: Path) -> list[str]:
    log = repo.parent / "pytest.log"
    return log.read_text().splitlines() if log.exists() else []


class TestOncePerTree:
    def test_a_green_run_is_reused_on_the_same_tree(self, repo):
        assert _suite(repo).returncode == 0
        second = _suite(repo)
        assert second.returncode == 0
        assert len(_calls(repo)) == 1
        assert "already passed" in second.stdout

    def test_the_hooks_pass_is_the_ship_gates_after_the_commit(self, repo):
        (repo / "tests" / "structural" / "test_x.py").write_text("def test_y(): pass\n")
        _git(repo, "add", "-A")
        assert _suite(repo, PRE_COMMIT="1").returncode == 0
        _git(repo, "commit", "-q", "-m", "change")
        assert _suite(repo).returncode == 0
        assert len(_calls(repo)) == 1

    def test_a_real_git_hooks_pass_is_reused_from_a_plain_shell(self, repo):
        """Through an actual `git commit`, not a simulated one.

        git runs a hook with its own exec-path at the front of PATH, and
        GIT_INDEX_FILE and friends set. The simulated test above shares one
        environment between the two runs, so it passed while every real
        hook-to-pre-ship pair keyed differently and re-ran the suite. This is
        the shape that caught it.
        """
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/bin/sh\nPRE_COMMIT=1 exec bash scripts/structural-tests.sh\n"
        )
        hook.chmod(0o755)
        (repo / "tests" / "structural" / "test_x.py").write_text("def test_h(): pass\n")
        env = _clean_env(
            FAKE_PYTEST_LOG=str(repo.parent / "pytest.log"),
            PYTEST_XDIST_AUTO_NUM_WORKERS="3",
        )
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "via hook"],
            check=True,
            env=env,
        )
        assert len(_calls(repo)) == 1, "the hook ran the suite once"
        second = _suite(repo)
        assert second.returncode == 0
        assert len(_calls(repo)) == 1, second.stderr
        assert "already passed" in second.stdout

    def test_a_failure_records_nothing(self, repo):
        assert _suite(repo, rc=1).returncode == 1
        assert _suite(repo).returncode == 0
        assert len(_calls(repo)) == 2

    def test_a_dirty_tree_neither_reuses_nor_records(self, repo):
        _suite(repo)
        (repo / "tests" / "structural" / "test_x.py").write_text("def test_z(): pass\n")
        _suite(repo)
        _suite(repo)
        assert len(_calls(repo)) == 3

    def test_an_untracked_file_neither_reuses_nor_records(self, repo):
        _suite(repo)
        (repo / "tests" / "structural" / "test_new.py").write_text(
            "def test_n(): pass\n"
        )
        result = _suite(repo)
        assert len(_calls(repo)) == 2
        assert "test_new.py" in result.stderr

    def test_gate_stamp_off_forces_a_run(self, repo):
        _suite(repo)
        _suite(repo, GATE_STAMP="off")
        assert len(_calls(repo)) == 2

    def test_an_outcome_changing_env_var_is_a_different_tree(self, repo):
        _suite(repo)
        _suite(repo, SHELLCHECK_REQUIRED="1")
        assert len(_calls(repo)) == 2


class TestWorkers:
    def test_the_count_becomes_xdist_flags(self, repo):
        _suite(repo, PYTEST_XDIST_AUTO_NUM_WORKERS="3")
        assert "-n 3 --dist loadfile" in _calls(repo)[0]

    def test_serial_means_no_xdist_flags(self, repo):
        _suite(repo, PYTEST_XDIST_AUTO_NUM_WORKERS="0")
        assert "-n" not in _calls(repo)[0].split()

    def test_a_broken_knob_is_exit_2_and_runs_nothing(self, repo):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-workers").write_text("lots\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "knob")
        env = _clean_env()
        result = subprocess.run(
            ["bash", "scripts/structural-tests.sh"],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**env, "FAKE_PYTEST_LOG": str(repo.parent / "pytest.log")},
        )
        assert result.returncode == 2
        assert _calls(repo) == []


def test_pytests_exit_code_passes_through(repo):
    assert _suite(repo, rc=5).returncode == 5


def test_the_slot_is_released(repo):
    _suite(repo)
    slots = repo / ".git" / "gate-slots"
    assert not any(slots.iterdir()) if slots.exists() else True
