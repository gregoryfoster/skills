"""`gate-stamp.sh` records a pass on an exact tree so a later gate reuses it (#537).

The properties that make a stamp safe to trust, each pinned below:

- The key moves with everything that can change the verdict: the tree, the
  env patterns asked for, the caller's extra material, and the content of the
  untracked inputs (D5: GATE_STAMP_INPUTS, else .skills/gate-stamp-inputs,
  which replaces the default, else `.env`).
- Only a tree that IS what is on disk can be stamped: a tracked change or an
  untracked file makes `key` exit 3. A nested repository (git lists it with a
  trailing slash) is not part of the tree and does not block.
- That holds whatever git was told to hide (#694): a submodule's `ignore`
  setting, wherever it is set, an untracked file inside a submodule, and a
  path marked skip-worktree or assume-unchanged all make `key` exit 3, in
  both modes. `_attest-gate.sh`'s clean-tree check is held to the same
  answers.
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


# --- What git was told to hide (#694) ----------------------------------------
# Each of these leaves files on disk that are not the tree, while `git diff`
# reports nothing. A gate that passes only because of the hidden difference
# would stamp the tree, and every later gate on it would reuse the pass.

SUB = "vend/sub"


def _vendor(repo: Path, tmp_path: Path) -> Path:
    """Vendor a one-file library as a submodule at SUB, committed."""
    lib = tmp_path / "lib"
    lib.mkdir()
    _git(lib, "init", "-q", "-b", "main")
    _git(lib, "config", "user.email", "test@example.com")
    _git(lib, "config", "user.name", "test")
    (lib / "s.txt").write_text("library\n")
    _git(lib, "add", "-A")
    _git(lib, "commit", "-q", "-m", "lib")
    _git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(lib),
        SUB,
    )
    _git(repo, "commit", "-q", "-m", "vendor the lib")
    sub = repo / SUB
    _git(sub, "config", "user.email", "test@example.com")
    _git(sub, "config", "user.name", "test")
    return sub


def _ignore_in_gitmodules(repo: Path, value: str) -> None:
    _git(repo, "config", "-f", ".gitmodules", f"submodule.{SUB}.ignore", value)
    _git(repo, "commit", "-q", "-am", f"ignore = {value}")


def _edit_inside(repo: Path) -> None:
    (repo / SUB / "s.txt").write_text("edited in place\n")


def _untracked_inside(repo: Path) -> None:
    (repo / SUB / "helper.sh").write_text("true\n")


def _hide_gitmodules_dirty(repo, tmp_path):
    _ignore_in_gitmodules(repo, "dirty")
    _edit_inside(repo)
    return {}


def _hide_gitmodules_all(repo, tmp_path):
    _ignore_in_gitmodules(repo, "all")
    _edit_inside(repo)
    return {}


def _hide_gitmodules_all_other_commit(repo, tmp_path):
    """The gate runs code the gitlink doesn't name."""
    _ignore_in_gitmodules(repo, "all")
    sub = repo / SUB
    (sub / "new.txt").write_text("new\n")
    _git(sub, "add", "new.txt")
    _git(sub, "commit", "-q", "-m", "another commit")
    return {}


def _hide_config_dirty(repo, tmp_path):
    _git(repo, "config", f"submodule.{SUB}.ignore", "dirty")
    _edit_inside(repo)
    return {}


def _hide_diff_ignore_submodules(repo, tmp_path):
    _git(repo, "config", "diff.ignoreSubmodules", "dirty")
    _edit_inside(repo)
    return {}


def _untracked_inside_by_default(repo, tmp_path):
    """No setting at all: `git diff` never counts a submodule's untracked files."""
    _untracked_inside(repo)
    return {}


def _hide_gitmodules_untracked(repo, tmp_path):
    _ignore_in_gitmodules(repo, "untracked")
    _untracked_inside(repo)
    return {}


def _hide_submodule_show_untracked_no(repo, tmp_path):
    _git(repo / SUB, "config", "status.showUntrackedFiles", "no")
    _untracked_inside(repo)
    return {}


def _hide_global_show_untracked_no(repo, tmp_path):
    config = tmp_path / "gitconfig"
    config.write_text("[status]\n\tshowUntrackedFiles = no\n")
    _untracked_inside(repo)
    return {"GIT_CONFIG_GLOBAL": str(config)}


HIDDEN_IN_A_SUBMODULE = {
    "gitmodules-ignore-dirty": _hide_gitmodules_dirty,
    "gitmodules-ignore-all": _hide_gitmodules_all,
    "gitmodules-ignore-all-other-commit": _hide_gitmodules_all_other_commit,
    "config-ignore-dirty": _hide_config_dirty,
    "diff-ignoreSubmodules": _hide_diff_ignore_submodules,
    "untracked-by-default": _untracked_inside_by_default,
    "gitmodules-ignore-untracked": _hide_gitmodules_untracked,
    "submodule-showUntrackedFiles-no": _hide_submodule_show_untracked_no,
    "global-showUntrackedFiles-no": _hide_global_show_untracked_no,
}


def _flag(repo, flag, edit=True):
    _git(repo, "update-index", flag, "a.txt")
    if edit:
        (repo / "a.txt").write_text("not what was committed\n")
    assert _git(repo, "status", "--porcelain") == "", "git hides the path"


FLAGGED = {
    "skip-worktree-edited": lambda repo: _flag(repo, "--skip-worktree"),
    "assume-unchanged-edited": lambda repo: _flag(repo, "--assume-unchanged"),
    # git keeps no record that could vouch for the file, edited or not.
    "skip-worktree-unedited": lambda repo: _flag(repo, "--skip-worktree", edit=False),
}

MODES = {"head": (), "index": ("--index",)}


class TestWhatGitWasToldToHideIsStillNotTheTree:
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("case", HIDDEN_IN_A_SUBMODULE)
    def test_a_hidden_difference_in_a_submodule_is_exit_3(
        self, repo, tmp_path, case, mode
    ):
        _vendor(repo, tmp_path)
        env = HIDDEN_IN_A_SUBMODULE[case](repo, tmp_path)
        assert _git(repo, "diff", "--quiet", "HEAD", "--") == "", (
            "git diff sees nothing"
        )
        result = _run(repo, "key", *MODES[mode], **env)
        assert result.returncode == 3, result.stdout + result.stderr
        assert "not stampable" in result.stderr
        assert f"submodule  {SUB}" in result.stderr

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("case", FLAGGED)
    def test_a_path_git_was_told_not_to_watch_is_exit_3(self, repo, case, mode):
        FLAGGED[case](repo)
        result = _run(repo, "key", *MODES[mode])
        assert result.returncode == 3, result.stdout + result.stderr
        assert "flagged    a.txt" in result.stderr

    @pytest.mark.parametrize("mode", MODES)
    def test_an_untracked_file_git_was_told_to_hide_is_exit_3(self, repo, mode):
        _git(repo, "config", "status.showUntrackedFiles", "no")
        (repo / "helper.js").write_text("the gate needs this\n")
        result = _run(repo, "key", *MODES[mode])
        assert result.returncode == 3, result.stdout + result.stderr
        assert "untracked  helper.js" in result.stderr

    def test_the_kind_of_difference_is_named(self, repo, tmp_path):
        _vendor(repo, tmp_path)
        (repo / "a.txt").write_text("changed\n")
        (repo / "stray.py").write_text("x = 1\n")
        _edit_inside(repo)
        _untracked_inside(repo)
        result = _run(repo, "key")
        assert result.returncode == 3
        assert "changed    a.txt" in result.stderr
        assert "untracked  stray.py" in result.stderr
        assert (
            f"submodule  {SUB} (edited inside, untracked files inside)" in result.stderr
        )

    def test_a_submodule_at_another_commit_is_named_so(self, repo, tmp_path):
        _vendor(repo, tmp_path)
        _hide_gitmodules_all_other_commit(repo, tmp_path)
        result = _run(repo, "key")
        assert f"submodule  {SUB} (at another commit)" in result.stderr

    def test_a_long_list_is_cut_short(self, repo):
        for i in range(8):
            (repo / f"stray{i}.py").write_text("x\n")
        result = _run(repo, "key")
        assert result.returncode == 3
        assert "and 3 more" in result.stderr


class TestWhatIsTheTreeStaysStampable:
    """A stamp never written costs every consumer a full run at each push."""

    @pytest.mark.parametrize("mode", MODES)
    def test_a_clean_initialised_submodule(self, repo, tmp_path, mode):
        _vendor(repo, tmp_path)
        assert _run(repo, "key", *MODES[mode]).returncode == 0

    @pytest.mark.parametrize("mode", MODES)
    def test_an_uninitialised_submodule(self, repo, tmp_path, mode):
        _vendor(repo, tmp_path)
        _git(repo, "submodule", "deinit", "-q", "-f", SUB)
        assert _run(repo, "key", *MODES[mode]).returncode == 0

    @pytest.mark.parametrize("mode", MODES)
    def test_an_unignored_nested_repository(self, repo, mode):
        subprocess.run(
            ["git", "init", "-q", str(repo / "nest")], check=True, env=_clean_env()
        )
        (repo / "nest" / "n.txt").write_text("n\n")
        assert _run(repo, "key", *MODES[mode]).returncode == 0

    @pytest.mark.parametrize("mode", MODES)
    def test_an_ignored_nested_worktree(self, repo, tmp_path, mode):
        (repo / ".gitignore").write_text(".env\nsecret.txt\n.worktrees/\n")
        _git(repo, "commit", "-q", "-am", "ignore worktrees")
        _git(repo, "worktree", "add", "-q", "-b", "w", str(repo / ".worktrees" / "w"))
        assert _run(repo, "key", *MODES[mode]).returncode == 0


class TestIndexModeAsksWhetherTheWorkTreeIsTheIndex:
    """`--index` keys the tree being committed, so what is staged is the tree
    and only a difference between the index and the files counts."""

    def test_a_staged_new_file_is_stampable_there_and_not_against_head(self, repo):
        (repo / "b.txt").write_text("new\n")
        _git(repo, "add", "b.txt")
        assert _run(repo, "key", "--index").returncode == 0
        assert _run(repo, "key").returncode == 3

    def test_a_staged_rename_is_stampable(self, repo):
        _git(repo, "mv", "a.txt", "b.txt")
        assert _run(repo, "key", "--index").returncode == 0

    def test_a_staged_edit_then_edited_again_is_not(self, repo):
        (repo / "a.txt").write_text("staged\n")
        _git(repo, "add", "a.txt")
        (repo / "a.txt").write_text("staged, then edited\n")
        result = _run(repo, "key", "--index")
        assert result.returncode == 3
        assert "changed    a.txt" in result.stderr

    def _stage_a_new_submodule_commit(self, repo, tmp_path):
        sub = _vendor(repo, tmp_path)
        (sub / "new.txt").write_text("new\n")
        _git(sub, "add", "new.txt")
        _git(sub, "commit", "-q", "-m", "bump")
        _git(repo, "add", SUB)
        return sub

    def test_a_staged_submodule_bump_is_stampable_there_and_not_against_head(
        self, repo, tmp_path
    ):
        self._stage_a_new_submodule_commit(repo, tmp_path)
        assert _run(repo, "key", "--index").returncode == 0
        result = _run(repo, "key")
        assert result.returncode == 3
        assert f"submodule  {SUB}" in result.stderr

    def test_a_staged_submodule_bump_then_edited_inside_is_not(self, repo, tmp_path):
        self._stage_a_new_submodule_commit(repo, tmp_path)
        _edit_inside(repo)
        result = _run(repo, "key", "--index")
        assert result.returncode == 3
        assert f"submodule  {SUB} (edited inside)" in result.stderr


def test_a_failing_status_is_not_a_clean_tree(repo):
    """A git that can't read the tree must never read as "no difference"."""
    (repo / ".git" / "index").write_bytes(b"not an index")
    assert _run(repo, "key").returncode == 2


def test_the_header_names_what_it_does_not_cover():
    """The promise is "never fake a pass": what the probes can't see is named
    beside it, not left for a reader to discover."""
    header = SCRIPT.read_text().split("set -euo pipefail")[0]
    assert "never fake a pass" in header
    assert "core.fileMode" in header
    assert "filter" in header


# --- One answer to "are the files the commit?" --------------------------------
# `key` and `_attest-gate.sh`'s `_attest_tree_state` (#688) ask it separately:
# `key` has an --index mode, exempts a nested repository and names kinds for
# the gate's log, while the attestation has its own remedies and runs the
# check again after the gate. So they stay two readers, held here to the same
# answers on the same cases (#694), which is how they drifted before.

ATTEST_LIB = SCRIPT.parent / "_attest-gate.sh"


def _attest_clean(repo: Path, **env: str) -> int:
    """`_attest_tree_state`'s return: 0 clean, 1 not, 2 unknown."""
    return subprocess.run(
        [
            "bash",
            "-c",
            '. "$1"; rc=0; _attest_tree_state || rc=$?; exit "$rc"',
            "_",
            str(ATTEST_LIB),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(**env),
    ).returncode


def _parity_cases():
    cases = {}
    for name, setup in HIDDEN_IN_A_SUBMODULE.items():
        cases[name] = (True, setup, False)
    for name, flag in FLAGGED.items():
        cases[name] = (False, lambda repo, tmp_path, f=flag: f(repo) or {}, False)

    def tracked(repo, tmp_path):
        (repo / "a.txt").write_text("changed\n")
        return {}

    def untracked(repo, tmp_path):
        (repo / "stray.py").write_text("x\n")
        return {}

    def hidden_untracked(repo, tmp_path):
        _git(repo, "config", "status.showUntrackedFiles", "no")
        return untracked(repo, tmp_path)

    def clean(repo, tmp_path):
        return {}

    def uninitialised(repo, tmp_path):
        _git(repo, "submodule", "deinit", "-q", "-f", SUB)
        return {}

    def ignored_worktree(repo, tmp_path):
        (repo / ".gitignore").write_text(".env\nsecret.txt\n.worktrees/\n")
        _git(repo, "commit", "-q", "-am", "ignore worktrees")
        _git(repo, "worktree", "add", "-q", "-b", "w", str(repo / ".worktrees" / "w"))
        return {}

    cases["tracked-change"] = (False, tracked, False)
    cases["untracked-file"] = (False, untracked, False)
    cases["showUntrackedFiles-no"] = (False, hidden_untracked, False)
    cases["clean-submodule"] = (True, clean, True)
    cases["uninitialised-submodule"] = (True, uninitialised, True)
    cases["ignored-nested-worktree"] = (False, ignored_worktree, True)
    return cases


PARITY = _parity_cases()


@pytest.mark.parametrize("case", PARITY)
def test_key_and_the_attestation_agree(repo, tmp_path, case):
    vendored, setup, clean = PARITY[case]
    if vendored:
        _vendor(repo, tmp_path)
    env = setup(repo, tmp_path)
    key_rc = _run(repo, "key", **env).returncode
    attest_rc = _attest_clean(repo, **env)
    assert (key_rc, attest_rc) == ((0, 0) if clean else (3, 1))


def test_the_one_named_difference_is_a_nested_repository(repo):
    """Not part of the tree, so the stamp ignores it (the header says why);
    the attestation, which speaks for a commit on GitHub, refuses it."""
    subprocess.run(
        ["git", "init", "-q", str(repo / "nest")], check=True, env=_clean_env()
    )
    (repo / "nest" / "n.txt").write_text("n\n")
    assert _run(repo, "key").returncode == 0
    assert _attest_clean(repo) == 1
