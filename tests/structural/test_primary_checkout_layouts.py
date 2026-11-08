"""The primary checkout is a working tree, in a bare or submodule layout too (CR 1839b).

`_command-knob.sh`'s `primary_checkout` and `read-next-steps.sh` took the
first `git worktree list --porcelain` entry as the primary checkout. That
entry is a git dir, not a working tree, in two layouts:

- **a bare primary,** whose linked worktrees are the only checkouts: the
  entry is `repo.git` itself;
- **a submodule,** whose entry is `<super>/.git/modules/<name>`.

Neither holds a `.skills/`, so a committed `.skills/next-steps` or
`.skills/pre_restart` read as absent (exit 3): the silent fallback #564
forbids. Both now normalise the entry with `git -C <entry> rev-parse
--show-toplevel`, and a bare one, which has no top level, falls back to the
current checkout's, as `using-git-worktrees` does.

Each fixture commits the knobs, so every checkout of the layout has them.

Two more cases (#605) take set R's rule from merge-mode.sh: a primary made
with `git init --separate-git-dir`, and a GIT_DIR or GIT_WORK_TREE inherited
from a hook. Their layouts are merge_mode_layouts.py's.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts
from tests.utils.skill_loader import SKILLS_DIR

SCRIPTS = SKILLS_DIR / "shipping-work" / "scripts"

STUB = """\
#!/usr/bin/env bash
pwd -P >"${STUB_RECORD:?}"
"""

ROW = "Data reload: data/*.csv changed -> run scripts/reload.sh"


def _env(**extra: str) -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    )


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A repo whose one commit carries the stub and both knobs."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    stub = src / "scripts" / "stub.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    (src / ".skills").mkdir()
    (src / ".skills" / "pre_restart").write_text("scripts/stub.sh\n")
    (src / ".skills" / "next-steps").write_text(f"# rows\n{ROW}\n")
    _git(src, "add", "-A")
    _git(
        src,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return src


@pytest.fixture
def bare_worktree(tmp_path: Path, src: Path) -> Path:
    """A linked worktree of a bare primary: the list's first entry is repo.git."""
    bare = tmp_path / "repo.git"
    _git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    wt = tmp_path / "wt"
    _git(bare, "worktree", "add", "-q", str(wt), "main")
    return wt


@pytest.fixture
def submodule(tmp_path: Path, src: Path) -> Path:
    """A submodule's checkout: the list's first entry is <super>/.git/modules/sub."""
    sup = tmp_path / "super"
    sup.mkdir()
    _git(sup, "init", "-q", "-b", "main")
    _git(
        sup,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "-q",
        "add",
        str(src),
        "sub",
    )
    return sup / "sub"


LAYOUTS = ["bare_worktree", "submodule"]


def _run(script: str, cwd: Path, record: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record)),
        timeout=60,
    )


@pytest.mark.parametrize("layout", LAYOUTS)
def test_read_next_steps_finds_the_committed_rows(request, tmp_path, layout):
    checkout = request.getfixturevalue(layout)
    result = _run("read-next-steps.sh", checkout, tmp_path / "record")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [ROW]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_pre_restart_runs_the_committed_check_from_the_checkout(
    request, tmp_path, layout
):
    checkout = request.getfixturevalue(layout)
    record = tmp_path / "record"
    result = _run("run-pre-restart.sh", checkout, record)
    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text().strip() == str(checkout.resolve())


# CR 1858: a primary git can't read is not a bare primary. The fallback above
# took *any* failure of `git -C <entry> rev-parse --show-toplevel` as "bare",
# so a primary under "dubious ownership" (safe.directory naming only the
# linked worktree) handed the feature branch's knobs to every script: its
# deploy command, its pre_restart check, its next-steps rows. Only a `bare`
# line in the first porcelain block means bare; any other failure exits 2,
# naming the path, with git's own reason shown.

BRANCH_ROW = "Branch row: read from the feature branch, not the primary"


@pytest.fixture
def unreadable_primary(tmp_path: Path, src: Path) -> tuple[Path, dict]:
    """A linked worktree on `feat` with its own rows, and an environment in
    which git refuses the primary as another user's but trusts the worktree."""
    (src / ".skills" / "deploy_command").write_text("scripts/stub.sh\n")
    _git(src, "add", "-A")
    _git(
        src,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "deploy knob",
    )
    wt = tmp_path / "wt"
    _git(src, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / ".skills" / "next-steps").write_text(f"{BRANCH_ROW}\n")
    # Its own upstream, so run-deploy-command.sh's pushed check would pass.
    _git(wt, "config", "branch.feat.remote", ".")
    _git(wt, "config", "branch.feat.merge", "refs/heads/feat")
    git_env = {
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(wt),
    }
    return wt, git_env


@pytest.mark.parametrize(
    "script", ["read-next-steps.sh", "run-pre-restart.sh", "run-deploy-command.sh"]
)
def test_an_unreadable_primary_exits_2_naming_it(
    unreadable_primary, src, tmp_path, script
):
    wt, git_env = unreadable_primary
    record = tmp_path / "record"
    result = subprocess.run(
        ["bash", str(SCRIPTS / script)],
        cwd=wt,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record), **git_env),
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert not record.exists(), "the branch's command ran"
    assert BRANCH_ROW not in result.stdout
    assert str(src) in result.stderr
    assert "dubious ownership" in result.stderr, result.stderr


# --- #605: set R's rule, for both of its cases (CR 1892, CR 1895) ----------
# Set R fixed merge-mode.sh and the inline merge_mode readers; these three
# scripts kept both gaps. A primary made with `git init --separate-git-dir`
# lists its store first, which names no work tree, so every reader refused,
# even run from the primary itself. And git exports GIT_DIR to every hook,
# where it beats `-C <entry>`: in a submodule's linked worktree the entry
# named itself, which holds no .skills/, and the knob read as absent (exit
# 3), the silent fallback #564 forbids. The layouts are merge_mode_layouts.py's,
# shared with merge-mode.sh's own tests; each script reads its own knob there.

KNOBS = {
    "read-next-steps.sh": "next-steps",
    "run-pre-restart.sh": "pre_restart",
    "run-deploy-command.sh": "deploy_command",
}
SCRIPT_NAMES = sorted(KNOBS)


def _knob_text(script: str, tmp_path: Path) -> str:
    """The script's knob: the row, or the stub by its absolute path, which
    needs no checkout to resolve it from."""
    if script == "read-next-steps.sh":
        return f"# rows\n{ROW}\n"
    stub = tmp_path / "bin" / "stub.sh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(STUB)
    stub.chmod(0o755)
    return f"{stub}\n"


def _pushed(checkout: Path) -> None:
    """The branch is its own upstream, so run-deploy-command.sh's check that
    HEAD was pushed passes and only the primary's resolution is tested."""
    branch = layouts.git(checkout, "symbolic-ref", "--short", "HEAD")
    layouts.git(checkout, "config", f"branch.{branch}.remote", ".")
    layouts.git(checkout, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")


def _run_with(
    script: str, cwd: Path, record: Path, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**(env if env is not None else _env()), "STUB_RECORD": str(record)},
        timeout=60,
    )


def _assert_read_from(
    script: str, result: subprocess.CompletedProcess, record: Path, primary: Path
) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    if script == "read-next-steps.sh":
        assert result.stdout.splitlines() == [ROW]
    else:
        assert record.read_text().strip() == str(primary.resolve())


def _assert_nothing_read(
    script: str, result: subprocess.CompletedProcess, record: Path
) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    assert not record.exists(), "a command ran"
    assert ROW not in result.stdout


class TestASeparateGitDirPrimary:
    """CR 1892's case: the first block names the store, and `-C <store>`
    names no work tree. From the primary itself that work tree is this
    checkout, whose git dir is the common dir; from a linked worktree git
    knows no path to it, so exit 2 says to run from the primary."""

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_the_primary_reads_its_own_knob(self, tmp_path, script):
        text = _knob_text(script, tmp_path)
        primary, _ = layouts.separate_git_dir(tmp_path / "l", text, name=KNOBS[script])
        _pushed(primary)
        record = tmp_path / "record"
        result = _run_with(script, primary, record)
        _assert_read_from(script, result, record, primary)

    def test_from_a_subdirectory_of_the_primary_too(self, tmp_path):
        text = _knob_text("read-next-steps.sh", tmp_path)
        primary, _ = layouts.separate_git_dir(tmp_path / "l", text, name="next-steps")
        sub = primary / "docs"
        sub.mkdir()
        result = _run_with("read-next-steps.sh", sub, tmp_path / "record")
        _assert_read_from("read-next-steps.sh", result, tmp_path / "record", primary)

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_no_knob_in_the_primary_is_absent_not_unusable(self, tmp_path, script):
        primary, _ = layouts.separate_git_dir(tmp_path / "l", None)
        _pushed(primary)
        result = _run_with(script, primary, tmp_path / "record")
        assert result.returncode == 3, result.stdout + result.stderr
        assert f".skills/{KNOBS[script]}" in result.stdout

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_a_linked_worktree_is_exit_2_and_says_why(self, tmp_path, script):
        text = _knob_text(script, tmp_path)
        _, linked = layouts.separate_git_dir(tmp_path / "l", text, name=KNOBS[script])
        _pushed(linked)
        record = tmp_path / "record"
        result = _run_with(script, linked, record)
        _assert_nothing_read(script, result, record)
        assert layouts.SEPARATE_GIT_DIR_HINT in result.stderr, result.stderr
        assert "primary checkout" in result.stderr, result.stderr

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_a_store_git_cannot_open_is_still_exit_2(self, tmp_path, script):
        """Never the fallback: "dubious ownership" of the store is git's
        reason, and the hint is not offered."""
        text = _knob_text(script, tmp_path)
        _, linked = layouts.separate_git_dir(tmp_path / "l", text, name=KNOBS[script])
        record = tmp_path / "record"
        result = _run_with(
            script, linked, record, env=layouts.different_owner(_env(), linked)
        )
        _assert_nothing_read(script, result, record)
        assert "dubious ownership" in result.stderr, result.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT not in result.stderr, result.stderr


class TestAnInheritedGitEnvironmentDoesNotAnswer:
    """CR 1895 and CR 1903's case: git exports GIT_DIR to every hook, and an
    inherited GIT_WORK_TREE beats a submodule's core.worktree. Either one
    made `-C <entry>` answer for this checkout, not the primary.

    Only layouts where the inherited value changes the answer are here, so
    each test fails without here_git (CR 2001, checked by mutation). A bare
    primary is not one: its knob is the current checkout's, which an
    inherited GIT_DIR or GIT_WORK_TREE also names."""

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_an_inherited_git_dir_in_a_submodule(self, tmp_path, script):
        text = _knob_text(script, tmp_path)
        checkout = layouts.submodule_linked(tmp_path / "l", text, name=KNOBS[script])
        _pushed(checkout)
        env = _env(GIT_DIR=layouts.git(checkout, "rev-parse", "--absolute-git-dir"))
        record = tmp_path / "record"
        result = _run_with(script, checkout, record, env=env)
        _assert_read_from(script, result, record, tmp_path / "l" / "super" / "sub")

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_an_inherited_git_work_tree_in_a_submodule(self, tmp_path, script):
        text = _knob_text(script, tmp_path)
        checkout = layouts.submodule_linked(tmp_path / "l", text, name=KNOBS[script])
        _pushed(checkout)
        env = _env(GIT_WORK_TREE=str(checkout))
        record = tmp_path / "record"
        result = _run_with(script, checkout, record, env=env)
        _assert_read_from(script, result, record, tmp_path / "l" / "super" / "sub")

    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_a_hook_in_a_separate_git_dir_primary(self, tmp_path, script):
        """CR 2001, both of #605's cases at once: a hook run in the primary
        inherits GIT_DIR=<store>, and `-C <store>` then names the store
        itself as the work tree, which holds no .skills/."""
        text = _knob_text(script, tmp_path)
        primary, _ = layouts.separate_git_dir(tmp_path / "l", text, name=KNOBS[script])
        _pushed(primary)
        store = layouts.git(primary, "rev-parse", "--absolute-git-dir")
        assert store.endswith("/store.git"), store
        record = tmp_path / "record"
        result = _run_with(script, primary, record, env=_env(GIT_DIR=store))
        _assert_read_from(script, result, record, primary)


def _prose(name: str) -> str:
    text = (SKILLS_DIR / "shipping-work" / "references" / name).read_text()
    return " ".join(text.split())


def test_the_deploy_reference_says_where_a_separate_git_dir_primary_is_read():
    """#605: the knob's home moved with the fix, from "the first `git
    worktree list` entry, as for `worktree_root`" to that entry's work tree,
    with the two layouts that have none named."""
    text = _prose("deploy-command.md")
    assert "the work tree of the first `git worktree list` entry" in text
    assert "`git init --separate-git-dir`" in text
    assert "exits 2 and says to run from the primary itself" in text
    # CR 1999 and CR 1998: the git it needs, and the store it doesn't cover.
    assert "needs git 2.31 or later" in text
    # CR 2008: below about 2.25 the store is listed as bare, which is no
    # exit 2: the old claim that older git always "says so" was false.
    assert "below about 2.25 git lists such a store as bare" in text
    assert "and says so" not in text
    assert "A store whose path ends in `/.git` isn't covered." in text


def test_pr_modes_exit_2_is_not_only_an_unusable_file():
    """CR 1905's note on #605: from a linked worktree of a --separate-git-dir
    primary, merge-mode.sh's exit 2 means "run from the primary", not
    "the file is unusable"."""
    text = _prose("pr-mode.md")
    assert "One exit 2 is not about the file." in text
    assert "`git init --separate-git-dir`" in text
    assert "run from the primary checkout" in text


# CR 1999: below git 2.31, rev-parse echoes `--path-format=absolute` back as
# a line, so the fallback never fires and a --separate-git-dir primary is
# exit 2 even from itself. That fails safe, but the hint told someone already
# in the primary to run from the primary. A shim on PATH plays that git for
# that call and for --version; every other call is the real git.
OLD_GIT_SHIM = """\
#!/bin/sh
case " $* " in
  " --version ") echo "git version 2.30.2"; exit 0 ;;
  *" --path-format=absolute "*)
    echo --path-format=absolute
    for a do shift; [ "$a" = --path-format=absolute ] || set -- "$@" "$a"; done
    ;;
esac
exec "{real}" "$@"
"""


def _old_git_env(tmp_path: Path) -> dict:
    real = subprocess.run(
        ["sh", "-c", "command -v git"],
        capture_output=True,
        text=True,
        check=True,
        env=_env(),
    ).stdout.strip()
    bin_dir = tmp_path / "old-git"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(OLD_GIT_SHIM.replace("{real}", real))
    (bin_dir / "git").chmod(0o755)
    return _env(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.parametrize("where", ["primary", "linked"])
@pytest.mark.parametrize("script", SCRIPT_NAMES)
def test_git_older_than_2_31_says_so_rather_than_run_from_the_primary(
    tmp_path, script, where
):
    text = _knob_text(script, tmp_path)
    primary, linked = layouts.separate_git_dir(tmp_path / "l", text, name=KNOBS[script])
    checkout = primary if where == "primary" else linked
    _pushed(checkout)
    record = tmp_path / "record"
    result = _run_with(script, checkout, record, env=_old_git_env(tmp_path))
    _assert_nothing_read(script, result, record)
    # The core phrase and its tail, through "run from the primary
    # checkout)", are shared word for word with worktree-create.sh,
    # resolve-worktree-root.sh and resolve-plans-dir.sh (CR 2010d): from a
    # linked worktree, upgrading git alone still leaves exit 2. The two
    # resolvers then add their own escape, ", or set WORKTREE_ROOT" and
    # ", or set PLANS_DIR"; these readers have none.
    assert (
        "git 2.30.2 predates 2.31, which this layout needs to tell its primary"
        " from a linked worktree: upgrade git (from a linked worktree, then run"
        " from the primary checkout)"
    ) in result.stderr, result.stderr
    assert layouts.OLD_GIT_HINT in result.stderr, result.stderr
    assert "run this from the primary checkout" not in result.stderr, result.stderr


@pytest.mark.parametrize("script", SCRIPT_NAMES)
def test_each_help_names_the_run_from_the_primary_exit_2(script):
    """CR 2000: every script on this reader says, under exit 2, what a
    linked worktree of a --separate-git-dir primary should do."""
    result = subprocess.run(
        ["bash", str(SCRIPTS / script), "--help"],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    text = " ".join(result.stdout.split())
    assert (
        "From a linked worktree of a --separate-git-dir primary: run from the"
        " primary checkout"
    ) in text, text


# CR 2009, CR 2011 and CR 2012 (#587): `git clone --bare` sets no upstream,
# and a plain one no fetch refspec, so after the post-merge pass's pull the
# deployed branch has no @{u}. "push it first (Step 4)" alone is the wrong
# remedy when the code is pushed and only the tracking is missing. Deciding
# by branch name failed too: a plain bare clone has no origin/HEAD, so a
# `trunk` default read as `main` (CR 2011). The message is now one that is
# right on any branch, with the refspec step first and only when it's unset
# (CR 2012). These fixtures skip _pushed on purpose: it sets the tracking by
# hand, which hides the case.

REFSPEC_STEP = "git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'"


def _bare_clone_home(
    tmp_path: Path, branch: str, *, refspec: bool = False, mode: str | None = None
) -> Path:
    """A plain `git clone --bare` of a repo whose one branch is `branch`, and
    a worktree on it that has never been given an upstream."""
    text = _knob_text("run-deploy-command.sh", tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    layouts.git(src, "init", "-q", "-b", branch)
    layouts.git(src, "config", "user.email", "test@example.com")
    layouts.git(src, "config", "user.name", "test")
    layouts.knob(src, text, "deploy_command")
    layouts.git(src, "add", "-A")
    layouts.git(src, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "knob")
    bare = tmp_path / "repo.git"
    layouts.git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    if refspec:
        layouts.git(
            bare, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"
        )
    home = tmp_path / "home"
    layouts.git(bare, "worktree", "add", "-q", str(home), branch)
    if mode is not None:
        layouts.knob(home, f"{mode}\n")
        layouts.knob(home, f"{branch}\n", "default_branch")
    return home


def _deploy(home: Path, record: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / "run-deploy-command.sh"), *args],
        cwd=home,
        capture_output=True,
        text=True,
        env={**_env(), "STUB_RECORD": str(record)},
        timeout=60,
    )


def _printed_remedy(stderr: str) -> str:
    """The command line the message prints, between "set it: " and ", then
    re-run"."""
    assert "set it: " in stderr, stderr
    return stderr.split("set it: ", 1)[1].split(", then re-run", 1)[0]


@pytest.mark.parametrize("branch", ["main", "trunk"])
@pytest.mark.parametrize("mode", [None, "pr"], ids=["direct", "pr"])
@pytest.mark.parametrize("check", [False, True], ids=["run", "check"])
def test_a_bare_clones_branch_gets_the_set_upstream_remedy_first_step_first(
    tmp_path, branch, mode, check
):
    home = _bare_clone_home(tmp_path, branch, mode=mode)
    record = tmp_path / "record"
    result = _deploy(home, record, *(["--check"] if check else []))
    _assert_nothing_read("run-deploy-command.sh", result, record)
    assert _printed_remedy(result.stderr) == (
        f"{REFSPEC_STEP} && git fetch origin"
        f" && git branch --set-upstream-to=origin/{branch}"
    ), result.stderr
    assert "otherwise push it first (Step 4)" in result.stderr, result.stderr
    assert "bare clone never" not in result.stderr, result.stderr


@pytest.mark.parametrize("refspec", [False, True], ids=["plain", "refspec-set"])
def test_the_remedy_runs_exactly_as_printed(tmp_path, refspec):
    """CR 2012: run the printed command line as it stands, on a `trunk`
    default, and the deploy accepts the checkout. With the refspec already
    set, the message leaves its step out."""
    home = _bare_clone_home(tmp_path, "trunk", refspec=refspec)
    record = tmp_path / "record"
    remedy = _printed_remedy(_deploy(home, record, "--check").stderr)
    assert (REFSPEC_STEP in remedy) is not refspec, remedy
    ran = subprocess.run(
        ["bash", "-c", remedy], cwd=home, capture_output=True, text=True, env=_env()
    )
    assert ran.returncode == 0, ran.stderr
    result = _run_with("run-deploy-command.sh", home, record)
    _assert_read_from("run-deploy-command.sh", result, record, home)


def test_a_branch_not_on_origin_is_still_told_to_push(tmp_path):
    """The same message on a branch nobody pushed: its last clause."""
    home = _bare_clone_home(tmp_path, "main")
    layouts.git(home, "switch", "-q", "-c", "feature/y")
    record = tmp_path / "record"
    result = _run_with("run-deploy-command.sh", home, record)
    _assert_nothing_read("run-deploy-command.sh", result, record)
    assert "HEAD (feature/y) has no upstream" in result.stderr, result.stderr
    assert "otherwise push it first (Step 4)" in result.stderr, result.stderr


# CR 2010a: pr-mode.md's post-merge step 1 finds the main checkout with
# `git -C <first row> rev-parse --show-toplevel`. Held here against each
# layout: it names the main checkout for a plain primary and a submodule's
# row, and fails for a bare primary and a --separate-git-dir store, the two
# cases the step then tells apart by the `(bare)` marker.


def _first_row(checkout: Path) -> str:
    return layouts.git(checkout, "worktree", "list").splitlines()[0]


def _ask(row_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", row_path, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        env=layouts.env(),
    )


def test_step_1s_question_names_a_plain_primary(tmp_path):
    primary = layouts.seed(tmp_path / "p", "direct\n")
    wt = tmp_path / "wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    answer = _ask(_first_row(wt).split()[0])
    assert answer.returncode == 0, answer.stderr
    assert Path(answer.stdout.strip()).resolve() == primary.resolve()


def test_step_1s_question_names_a_submodules_work_tree(tmp_path):
    wt = layouts.submodule_linked(tmp_path, "direct\n")
    row = _first_row(wt).split()[0]
    assert "/.git/modules/" in row, row
    answer = _ask(row)
    assert answer.returncode == 0, answer.stderr
    assert (
        Path(answer.stdout.strip()).resolve() == (tmp_path / "super" / "sub").resolve()
    )


def test_step_1s_question_fails_for_a_bare_row_marked_bare(tmp_path):
    home = layouts.bare_home(tmp_path, "direct\n")
    row = _first_row(home)
    assert row.endswith("(bare)"), row
    assert _ask(row.split()[0]).returncode != 0


def test_step_1s_question_fails_for_an_unmarked_store(tmp_path):
    _, linked = layouts.separate_git_dir(tmp_path, None)
    row = _first_row(linked)
    assert "(bare)" not in row, row
    assert _ask(row.split()[0]).returncode != 0
