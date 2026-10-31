"""`gate-stamp.sh` records a pass on an exact tree so a later gate reuses it (#537).

The properties that make a stamp safe to trust, each pinned below:

- The key moves with everything that can change the verdict: the tree, the
  env patterns asked for, the caller's extra material, and the content of the
  untracked inputs (D5: GATE_STAMP_INPUTS, else .skills/gate-stamp-inputs,
  which replaces the default, else `.env`).
- Only a tree that IS what is on disk can be stamped: a tracked change or an
  untracked file makes `key` exit 3. A nested repository (git lists it with a
  trailing slash) is not part of the tree and does not block.
- `--index` keys the tree being committed, so a hook's pass becomes the ship
  gate's pass once committed.
- GATE_STAMP=off makes every check a miss.

No API calls; each test gets a fresh repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "gate-stamp.sh"


def _clean_env(**extra: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and not k.startswith("GATE_STAMP")
    }
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    ).stdout


def _run(repo: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(**env),
    )


def _key(repo: Path, *args: str, **env: str) -> str:
    result = _run(repo, "key", *args, **env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / ".gitignore").write_text(".env\nsecret.txt\n")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


class TestTheKeyMovesWithTheVerdictsInputs:
    def test_it_is_stable(self, repo):
        assert _key(repo) == _key(repo)

    def test_the_tree(self, repo):
        before = _key(repo)
        (repo / "a.txt").write_text("two\n")
        _git(repo, "commit", "-q", "-am", "change")
        assert _key(repo) != before

    def test_a_message_only_amend_keeps_it(self, repo):
        before = _key(repo)
        _git(repo, "commit", "-q", "--amend", "-m", "reworded")
        assert _key(repo) == before

    def test_an_env_pattern(self, repo):
        base = _key(repo, "--env", "*_REQUIRED")
        assert _key(repo, "--env", "*_REQUIRED", FOO_REQUIRED="1") != base

    def test_unrelated_env_does_not(self, repo):
        base = _key(repo, "--env", "*_REQUIRED")
        assert _key(repo, "--env", "*_REQUIRED", UNRELATED="1") == base

    def test_extra_material(self, repo):
        assert _key(repo, "--extra", "pytest==9.0.2") != _key(
            repo, "--extra", "pytest==9.0.3"
        )

    def test_the_default_input_is_dotenv(self, repo):
        absent = _key(repo)
        (repo / ".env").write_text("A=1\n")
        present = _key(repo)
        (repo / ".env").write_text("A=2\n")
        assert len({absent, present, _key(repo)}) == 3

    def test_the_knob_replaces_the_default(self, repo):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "gate-stamp-inputs").write_text("# only this\nsecret.txt\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "knob")
        base = _key(repo)
        (repo / ".env").write_text("A=1\n")
        assert _key(repo) == base, ".env is no longer an input"
        (repo / "secret.txt").write_text("s\n")
        assert _key(repo) != base

    def test_the_env_var_wins_over_the_knob(self, repo):
        base = _key(repo, GATE_STAMP_INPUTS="secret.txt")
        (repo / ".env").write_text("A=1\n")
        assert _key(repo, GATE_STAMP_INPUTS="secret.txt") == base
        (repo / "secret.txt").write_text("s\n")
        assert _key(repo, GATE_STAMP_INPUTS="secret.txt") != base

    def test_no_value_reaches_the_record(self, repo):
        (repo / ".env").write_text("TOKEN=hunter2\n")
        k = _key(repo)
        assert _run(repo, "write", k, "--label", "suite").returncode == 0
        record = _run(repo, "check", k).stdout
        assert "hunter2" not in record


def test_explain_shows_what_went_in_but_never_an_input_value(repo):
    (repo / ".env").write_text("TOKEN=hunter2\n")
    result = _run(repo, "key", "--explain", "--env", "*_REQUIRED", X_REQUIRED="1")
    assert result.returncode == 0
    assert "gate-stamp: tree " in result.stderr
    assert "gate-stamp: env X_REQUIRED=1" in result.stderr
    assert "gate-stamp: input .env " in result.stderr
    assert "hunter2" not in result.stderr + result.stdout


class TestOnlyWhatIsOnDiskCanBeStamped:
    def test_a_tracked_change_is_exit_3(self, repo):
        (repo / "a.txt").write_text("dirty\n")
        result = _run(repo, "key")
        assert result.returncode == 3
        assert "not stampable" in result.stderr

    def test_an_untracked_file_is_exit_3_and_named(self, repo):
        (repo / "stray.py").write_text("x = 1\n")
        result = _run(repo, "key")
        assert result.returncode == 3
        assert "stray.py" in result.stderr

    def test_a_nested_repository_does_not_block(self, repo):
        nested = repo / ".worktrees" / "other"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(nested)], check=True, env=_clean_env())
        assert _run(repo, "key").returncode == 0

    def test_index_mode_keys_what_is_being_committed(self, repo):
        (repo / "a.txt").write_text("staged\n")
        _git(repo, "add", "a.txt")
        staged = _key(repo, "--index")
        _git(repo, "commit", "-q", "-m", "staged")
        assert _key(repo) == staged

    def test_index_mode_refuses_unstaged_changes(self, repo):
        (repo / "a.txt").write_text("unstaged\n")
        assert _run(repo, "key", "--index").returncode == 3


class TestRecords:
    def test_check_misses_then_hits(self, repo):
        k = _key(repo)
        assert _run(repo, "check", k).returncode == 1
        assert (
            _run(repo, "write", k, "--label", "suite", "--seconds", "42").returncode
            == 0
        )
        hit = _run(repo, "check", k)
        assert hit.returncode == 0
        assert "\t42\tsuite\t" in hit.stdout

    def test_stamps_are_shared_by_worktrees(self, repo, tmp_path):
        k = _key(repo)
        _run(repo, "write", k)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt))
        assert _key(wt) == k
        assert _run(wt, "check", k).returncode == 0

    def test_gate_stamp_off_is_always_a_miss(self, repo):
        k = _key(repo)
        _run(repo, "write", k)
        result = _run(repo, "check", k, GATE_STAMP="off")
        assert result.returncode == 1
        assert "GATE_STAMP=off" in result.stderr

    def test_write_refuses_what_is_not_a_key(self, repo):
        result = _run(repo, "write", "../../etc/passwd")
        assert result.returncode == 2

    def test_check_refuses_what_is_not_a_key(self, repo):
        """A hit means "skip the suite", so it must never come from a path.

        Once the stamp directory exists, `../HEAD` resolves to the
        repository's own HEAD file, so an unvalidated check reported it as a
        recorded pass.
        """
        _run(repo, "write", _key(repo))
        result = _run(repo, "check", "../HEAD")
        assert result.returncode == 2
        assert result.stdout == ""

    def test_list_shows_the_newest_first(self, repo):
        k1 = _key(repo)
        _run(repo, "write", k1, "--label", "first")
        (repo / "a.txt").write_text("two\n")
        _git(repo, "commit", "-q", "-am", "two")
        k2 = _key(repo)
        _run(repo, "write", k2, "--label", "second")
        lines = _run(repo, "list").stdout.splitlines()
        assert [line.split("\t")[2] for line in lines] == ["second", "first"]

    def test_outside_a_repository_is_exit_2(self, tmp_path):
        result = _run(tmp_path, "key")
        assert result.returncode == 2
