"""Every primary-checkout reader answers alike, in four more layouts (#612).

Eleven readers find the primary checkout, whose untracked `.skills/` knobs
they read. Nine read the first `git worktree list --porcelain` block, and
now share one function, `resolve_primary`, as one body between marker
comments, held byte-identical here as `test_typesafe_copies.py` holds
`_typesafe.py`. The two resolvers (`resolve-worktree-root.sh`,
`resolve-plans-dir.sh`) compare common dirs, and answer `.bare`'s `<dir>`
and #203's submodule worktree that way, so they stay their own pair.

#612 named four gaps, each reproduced below for every copy:

1. **A `--separate-git-dir` store whose path ends in `/.git`.** The listing
   names the store's parent, which git takes for a work tree, so every
   reader read `<T>/stores/proj/.skills/` [reproduced]. From the primary
   itself, whose git dir is the common dir, its own top level answers.
2. **Git before about 2.25 lists that store as `bare`,** so each reader's
   bare arm stood in the current checkout: from a linked worktree, the
   feature branch's knob [reproduced, git 2.17.1]. A `bare` line now counts
   once `rev-parse --is-bare-repository` agrees. From the primary such git
   answered right by accident, and still does.
3. **An inherited `GIT_COMMON_DIR`** answered for another repository.
4. **Git before 2.31** gets set U's old-git hint from every copy but the
   doctor's, which is silent by design.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

REPO = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO / "skills"
SW = SKILLS / "shipping-work" / "scripts"
UGW = SKILLS / "using-git-worktrees" / "scripts"
MS = SKILLS / "managing-skills" / "scripts"

COPIES = [
    SW / "merge-mode.sh",
    UGW / "merge-mode.sh",
    SW / "_command-knob.sh",
    SW / "read-next-steps.sh",
    SKILLS / "curating-context" / "scripts" / "install-cadence.sh",
    MS / "doctor.sh",
    MS / "skills-submodule-update.sh",
    UGW / "worktree-create.sh",
    UGW / "worktree-destroy.sh",
]
RESOLVERS = [
    UGW / "resolve-worktree-root.sh",
    SKILLS / "writing-plans" / "scripts" / "resolve-plans-dir.sh",
]
BLOCK = re.compile(r"^# >>> resolve_primary\b.*?^# <<< resolve_primary\n", re.M | re.S)
BASH = shutil.which("bash") or "bash"
ROW = "Data reload: data/*.csv changed -> run scripts/reload.sh"
CRON = "0 15 * * 1"


def _block(path: Path) -> str:
    found = BLOCK.findall(path.read_text())
    assert len(found) == 1, f"{path.relative_to(REPO)}: {len(found)} blocks"
    return found[0]


def _function(path: Path, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", path.read_text(), re.M | re.S)
    assert m, f"{path.name} has no {name}() at column 0"
    return m.group(0)


def _bash(script: str, cwd: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", script, "_", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# --- one body ---------------------------------------------------------------


@pytest.mark.parametrize("path", COPIES, ids=lambda p: str(p.relative_to(SKILLS)))
def test_each_reader_holds_the_block_once(path: Path):
    _block(path)


def test_the_copies_are_byte_identical():
    first = _block(COPIES[0])
    differ = [str(p.relative_to(REPO)) for p in COPIES[1:] if _block(p) != first]
    assert not differ, f"differ from {COPIES[0].relative_to(REPO)}: {differ}"


@pytest.mark.parametrize("path", COPIES, ids=lambda p: str(p.relative_to(SKILLS)))
def test_no_reader_keeps_its_own_porcelain_parse(path: Path):
    """The block is the one place the first block is parsed: a second parse
    outside it is a copy the identity test can't hold."""
    text = BLOCK.sub("", path.read_text())
    assert "%%$'\\n\\n'*}" not in text, path.name


# --- the block on its own ----------------------------------------------------


def _run_block() -> str:
    return (
        "set -euo pipefail\n"
        + _block(COPIES[0])
        + 'rc=0; resolve_primary "${1:-.}" || rc=$?\n'
        + 'printf "%s\\n%s\\n%s\\n%s\\n%s" "$rc" "$RP_TREE" "$RP_BARE" "$RP_ERR"'
        + ' "$RP_REASON"\n'
    )


@dataclass
class Answer:
    rc: int
    tree: str
    bare: str
    err: str
    reason: str


def _resolve(cwd: Path, env: dict | None = None, *args: str) -> Answer:
    r = _bash(_run_block(), cwd, layouts.env() if env is None else env, *args)
    assert r.returncode == 0, r.stderr
    assert r.stderr == "", f"the block prints nothing: {r.stderr!r}"
    rc, tree, bare, err, reason = r.stdout.split("\n", 4)
    return Answer(int(rc), tree, bare, err, reason)


def _root(cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RESOLVERS[0]), "--project-root"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=layouts.env() if env is None else env,
        timeout=60,
    )


def _plain(tmp_path: Path) -> tuple[Path, Path]:
    primary = layouts.seed(tmp_path / "plain", "direct\n")
    linked = tmp_path / "plain-wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(linked))
    return primary, linked


class TestTheBlock:
    def test_a_plain_primary_and_its_linked_worktree(self, tmp_path: Path):
        primary, linked = _plain(tmp_path)
        for where in (primary, linked, primary / ".skills"):
            a = _resolve(where)
            assert (a.rc, a.tree, a.bare) == (0, str(primary.resolve()), "0"), a

    def test_a_bare_primary_is_marked_and_stands_in_this_checkout(self, tmp_path):
        home = layouts.bare_home(tmp_path, "direct\n")
        a = _resolve(home)
        assert (a.rc, a.tree, a.bare) == (0, str(home.resolve()), "1"), a

    def test_the_bare_repository_itself_has_no_work_tree(self, tmp_path):
        layouts.bare_home(tmp_path, "direct\n")
        a = _resolve(tmp_path / "repo.git")
        assert (a.rc, a.tree, a.bare) == (0, "", "1"), a

    def test_a_submodules_linked_worktree_names_the_submodule(self, tmp_path):
        wt = layouts.submodule_linked(tmp_path, "direct\n")
        a = _resolve(wt)
        assert (a.rc, a.tree) == (0, str((tmp_path / "super" / "sub").resolve())), a

    def test_a_dir_argument_answers_for_that_repository(self, tmp_path):
        primary, _ = _plain(tmp_path)
        a = _resolve(tmp_path, None, str(primary / ".skills"))
        assert (a.rc, a.tree) == (0, str(primary.resolve())), a

    def test_dubious_ownership_is_a_refusal_with_gits_reason(self, tmp_path):
        primary, linked = _plain(tmp_path)
        a = _resolve(linked, layouts.different_owner(layouts.env(), linked))
        assert a.rc == 1 and a.tree == "", a
        assert str(primary.resolve()) in a.err or str(primary) in a.err, a
        # Git's reason whole, its safe.directory command included (CR 2265).
        assert "dubious ownership" in a.reason, a
        assert "safe.directory" in a.reason, a

    def test_gap_1_a_git_suffixed_store_from_its_primary(self, tmp_path):
        primary = layouts.git_suffixed_store(tmp_path, "pr\n")
        a = _resolve(primary)
        assert (a.rc, a.tree, a.bare) == (0, str(primary.resolve()), "0"), a

    def test_gap_2_an_old_git_bare_listing_from_a_linked_worktree(self, tmp_path):
        _, linked = layouts.separate_git_dir(tmp_path / "l", "pr\n")
        env = layouts.old_git_bare_env(layouts.env(), tmp_path / "bin")
        a = _resolve(linked, env)
        assert a.rc == 1 and a.tree == "", a
        assert layouts.OLD_GIT_HINT in a.err, a

    def test_gap_2_an_old_git_bare_listing_from_its_primary(self, tmp_path):
        """Git 2.17 answered this right by accident: the bare arm read the
        current checkout, which is the primary. It still answers."""
        primary, _ = layouts.separate_git_dir(tmp_path / "l", "pr\n")
        env = layouts.old_git_bare_env(layouts.env(), tmp_path / "bin")
        a = _resolve(primary, env)
        assert (a.rc, a.tree, a.bare) == (0, str(primary.resolve()), "0"), a

    def test_gap_3_an_inherited_git_common_dir(self, tmp_path):
        primary, _ = _plain(tmp_path)
        other = layouts.seed(tmp_path / "other", layouts.DECOY)
        env = {**layouts.env(), "GIT_COMMON_DIR": str(other / ".git")}
        a = _resolve(primary, env)
        assert (a.rc, a.tree) == (0, str(primary.resolve())), a

    @pytest.mark.parametrize("where", ["primary", "linked"])
    def test_gap_4_below_git_2_31(self, tmp_path, where):
        primary, linked = layouts.separate_git_dir(tmp_path / "l", "pr\n")
        env = layouts.old_git_env(layouts.env(), tmp_path / "bin")
        a = _resolve(primary if where == "primary" else linked, env)
        assert a.rc == 1, a
        assert "git 2.30.2 " + layouts.OLD_GIT_HINT in a.err, a

    def test_a_separate_git_dir_linked_worktree_says_run_from_the_primary(
        self, tmp_path
    ):
        _, linked = layouts.separate_git_dir(tmp_path / "l", "pr\n")
        a = _resolve(linked)
        assert a.rc == 1, a
        assert layouts.SEPARATE_GIT_DIR_HINT in a.err, a
        assert "run this from the primary checkout" in a.err, a


# The parity the resolver holds the block to, where both answer: the same
# primary, layout by layout (test_plans_dir_contract.py holds the two
# resolvers to each other). Two layouts answer apart, as before #612:
# - a bare primary, which the block marks and its callers stand in their
#   checkout, where the resolver names `<dir>` for a `.bare` store (#614);
# - a submodule's linked worktree, which the resolver keeps as its own root
#   (#203), where the readers name the submodule's checkout.
PARITY: dict[str, Callable[[Path], Path]] = {
    "plain_primary": lambda t: _plain(t)[0],
    "plain_linked": lambda t: _plain(t)[1],
    "submodule_primary": lambda t: (
        layouts.submodule_linked(t, "direct\n").parent / "super" / "sub"
    ),
    "separate_git_dir_primary": lambda t: layouts.separate_git_dir(t, None)[0],
    "git_suffixed_store_primary": lambda t: layouts.git_suffixed_store(t, "pr\n"),
}


@pytest.mark.parametrize("layout", sorted(PARITY))
def test_the_block_names_the_resolvers_primary(tmp_path, layout):
    checkout = PARITY[layout](tmp_path / "l")
    root = _root(checkout)
    assert root.returncode == 0, root.stderr
    a = _resolve(checkout)
    assert (a.rc, a.tree) == (0, root.stdout.strip()), (a, root.stdout)


# --- every copy, end to end ------------------------------------------------
#
# Each copy reads its own knob. The primary holds the true one; the place a
# gap read instead holds the DECOY (gap 1), the same text in the linked
# worktree (gap 2: the bare arm read this checkout), or the DECOY in another
# repository (gap 3).


@dataclass
class Copy:
    name: str
    knob: str
    text: str
    run: Callable[[Path, dict, Path], subprocess.CompletedProcess]
    reads: Callable[[subprocess.CompletedProcess, Path], bool]
    refused: Callable[[subprocess.CompletedProcess], bool]
    says: Callable[[subprocess.CompletedProcess], str]


def _script(path: Path, *args: str) -> Callable[..., subprocess.CompletedProcess]:
    def run(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(path), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    return run


def _command_knob(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
    return _bash(
        'set -euo pipefail\ndie() { printf "%s\\n" "$*" >&2; exit 2; }\n'
        '. "$1"\nprimary_checkout\nprintf "%s" "$PRIMARY"\n',
        cwd,
        env,
        str(SW / "_command-knob.sh"),
    )


def _hook(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
    hook = MS / "skills-submodule-update.sh"
    return _bash(
        "set -euo pipefail\n"
        + _function(hook, "resolve_primary")
        + _function(hook, "_read_merge_mode")
        + '_read_merge_mode\nprintf "%s\\n%s\\n%s" "$MERGE_MODE" '
        + '"$MERGE_MODE_PRIMARY" "$MERGE_MODE_ERR"\n',
        cwd,
        env,
    )


NO_GH = "gh is not on this shell's PATH"


def _is_shim(path: Path) -> bool:
    return path.is_file() and path.read_text().startswith('#!/bin/sh\nreal="')


def _doctor(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
    """The doctor's token check, with gh off PATH: it speaks only when it
    read `pr` from the primary."""
    doctor = MS / "doctor.sh"
    hooks = cwd / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "skills-submodule-update.sh").write_text("#!/bin/sh\n")
    tools = tmp / "tools-without-gh"
    tools.mkdir(exist_ok=True)
    for tool in ("git", "env", "awk"):
        link = tools / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool, path=layouts.env()["PATH"]))
    # An old-git shim stays first: it is git, for the doctor too.
    first = Path(env["PATH"].split(os.pathsep)[0], "git")
    shim = [str(first.parent)] if _is_shim(first) else []
    on_path = {**env, "PATH": os.pathsep.join([*shim, str(tools)])}
    return _bash(
        "set -euo pipefail\n"
        + _function(doctor, "resolve_primary")
        + _function(doctor, "env_value")
        + _function(doctor, "check_pr_mode_gh_token")
        + "check_pr_mode_gh_token\n",
        cwd,
        on_path,
    )


def _create(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
    """Create reads .skills/worktree_venv only where there is a venv to link,
    so this checkout gets one; the primary's `none` is then said."""
    activate = cwd / ".venv" / "bin" / "activate"
    activate.parent.mkdir(parents=True, exist_ok=True)
    activate.write_text("")
    env = {**env, "WORKTREE_ROOT": str(tmp / "out")}
    env.pop("GIT_COMMON_DIR", None)
    return _script(UGW / "worktree-create.sh", "--new", "feature/y")(cwd, env, tmp)


def _destroy(cwd: Path, env: dict, tmp: Path) -> subprocess.CompletedProcess:
    wts = tmp / "wts"
    layouts.git(cwd, "branch", "trunk", "HEAD")
    layouts.git(cwd, "branch", "feature/y", "HEAD")
    layouts.git(cwd, "worktree", "add", str(wts / "feature-y"), "feature/y")
    env = {**env, "WORKTREE_ROOT": str(wts)}
    run = _script(UGW / "worktree-destroy.sh", "feature/y", "--dry-run")
    return run(cwd, env, tmp)


def _rc0(r: subprocess.CompletedProcess) -> bool:
    return r.returncode == 0


def _said(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


def _is(path: str, primary: Path) -> bool:
    return bool(path) and Path(path).resolve() == primary.resolve()


COPY_LIST = [
    Copy(
        "shipping-work/merge-mode.sh",
        "merge_mode",
        "pr\n",
        _script(SW / "merge-mode.sh"),
        lambda r, p: _rc0(r) and r.stdout == "pr\n",
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
    Copy(
        "using-git-worktrees/merge-mode.sh",
        "merge_mode",
        "pr\n",
        _script(UGW / "merge-mode.sh"),
        lambda r, p: _rc0(r) and r.stdout == "pr\n",
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
    Copy(
        "_command-knob.sh",
        "deploy_command",
        "true\n",
        _command_knob,
        lambda r, p: _rc0(r) and _is(r.stdout, p),
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
    Copy(
        "read-next-steps.sh",
        "next-steps",
        f"# rows\n{ROW}\n",
        _script(SW / "read-next-steps.sh"),
        lambda r, p: _rc0(r) and r.stdout.splitlines() == [ROW],
        lambda r: r.returncode == 2 and ROW not in r.stdout,
        _said,
    ),
    Copy(
        "install-cadence.sh",
        "merge_mode",
        "pr\n",
        _script(
            SKILLS / "curating-context" / "scripts" / "install-cadence.sh",
            "--print",
            "--cron",
            CRON,
        ),
        lambda r, p: _rc0(r) and "Read the merge mode" in r.stdout,
        lambda r: r.returncode == 5 and r.stdout == "",
        _said,
    ),
    Copy(
        "doctor.sh",
        "merge_mode",
        "pr\n",
        _doctor,
        lambda r, p: _rc0(r) and NO_GH in r.stderr,
        lambda r: _rc0(r) and r.stderr == "",
        lambda r: "",
    ),
    Copy(
        "skills-submodule-update.sh",
        "merge_mode",
        "pr\n",
        _hook,
        lambda r, p: (
            _rc0(r)
            and r.stdout.split("\n")[:1] == ["pr"]
            and _is(r.stdout.split("\n")[1], p)
        ),
        lambda r: _rc0(r) and r.stdout.startswith("unusable\n\n"),
        lambda r: r.stdout.split("\n", 2)[-1],
    ),
    Copy(
        "worktree-create.sh",
        "worktree_venv",
        "none\n",
        _create,
        lambda r, p: _rc0(r) and "worktree_venv=none" in r.stderr,
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
    Copy(
        "worktree-destroy.sh",
        "default_branch",
        "trunk\n",
        _destroy,
        lambda r, p: _rc0(r) and "ancestor of 'trunk'" in r.stdout,
        lambda r: r.returncode == 2,
        _said,
    ),
    Copy(
        "resolve-worktree-root.sh",
        "worktree_root",
        "wt\n",
        _script(RESOLVERS[0], "--project-root"),
        lambda r, p: _rc0(r) and _is(r.stdout.strip(), p),
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
    Copy(
        "resolve-plans-dir.sh",
        "plans_dir",
        "notes\n",
        _script(RESOLVERS[1]),
        lambda r, p: _rc0(r) and _is(r.stdout.strip(), p / "notes"),
        lambda r: r.returncode == 2 and r.stdout == "",
        _said,
    ),
]
BY_NAME = {c.name: c for c in COPY_LIST}
NAMES = sorted(BY_NAME)


def _env_for(c: Copy) -> dict:
    env = layouts.env()
    env.pop("WORKTREE_ROOT", None)
    env.pop("PLANS_DIR", None)
    return env


@pytest.mark.parametrize("name", NAMES)
def test_gap_1_a_git_suffixed_store_is_read_from_its_primary(tmp_path, name):
    """#612's reproduction: `git init --separate-git-dir
    <T>/stores/proj/.git <T>/proj` read `<T>/stores/proj/.skills/`."""
    c = BY_NAME[name]
    primary = layouts.git_suffixed_store(tmp_path / "l", c.text, c.knob)
    r = c.run(primary, _env_for(c), tmp_path)
    assert c.reads(r, primary), _said(r)


def _old_git_linked(tmp_path: Path, c: Copy) -> tuple[Path, Path]:
    """CR 2008's layout: a --separate-git-dir primary holding the knob, and
    a linked worktree on a feature branch holding the same text, which the
    bare arm read."""
    primary, linked = layouts.separate_git_dir(tmp_path / "l", c.text, c.knob)
    layouts.knob(linked, c.text, c.knob)
    return primary, linked


@pytest.mark.parametrize("name", NAMES)
def test_gap_2_old_git_listing_the_store_bare_refuses_from_a_linked_worktree(
    tmp_path, name
):
    """#612's reproduction (CR 2008): on git 2.17.1, from a linked worktree,
    run-deploy-command.sh ran the feature branch's deploy command. The shim
    plays 2.17's listing; the real git answers everything else."""
    c = BY_NAME[name]
    _, linked = _old_git_linked(tmp_path, c)
    env = layouts.old_git_bare_env(_env_for(c), tmp_path / "bin")
    r = c.run(linked, env, tmp_path)
    assert c.refused(r), _said(r)
    if c.says(r):
        assert layouts.OLD_GIT_HINT in c.says(r), _said(r)


@pytest.mark.parametrize("name", NAMES)
def test_gap_2_old_git_listing_the_store_bare_still_answers_from_its_primary(
    tmp_path, name
):
    """The answer such git gave from the primary was right, and is kept."""
    c = BY_NAME[name]
    primary, _ = _old_git_linked(tmp_path, c)
    env = layouts.old_git_bare_env(_env_for(c), tmp_path / "bin")
    r = c.run(primary, env, tmp_path)
    assert c.reads(r, primary), _said(r)


def _old_git_pair(tmp: Path, text: str | None, name: str) -> tuple[Path, Path]:
    """separate_git_dir's layout, built with what git 2.17 has: no `init
    -b`, no `worktree add -q`. The knob, when given, is in both checkouts."""
    tmp.mkdir(parents=True, exist_ok=True)
    primary, linked = tmp / "work", tmp / "wt"
    layouts.git(
        tmp, "init", "-q", "--separate-git-dir", str(tmp / "store.git"), str(primary)
    )
    layouts.git(primary, "symbolic-ref", "HEAD", "refs/heads/main")
    layouts.git(primary, "config", "user.email", "test@example.com")
    layouts.git(primary, "config", "user.name", "test")
    (primary / "README.md").write_text("x\n")
    layouts.git(primary, "add", "-A")
    layouts.git(primary, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    layouts.git(primary, "worktree", "add", "-b", "feature/x", str(linked))
    if text is not None:
        layouts.knob(primary, text, name)
        layouts.knob(linked, text, name)
    return primary, linked


def _real_git_lists_the_store_bare(tmp_path: Path) -> bool:
    _, linked = _old_git_pair(tmp_path / "probe", None, "merge_mode")
    first = layouts.git(linked, "worktree", "list", "--porcelain").split("\n\n")[0]
    return "\nbare" in first


@pytest.mark.parametrize("name", NAMES)
def test_gap_2_on_a_real_git_that_lists_the_store_bare(tmp_path, name):
    """The shim's claim, checked against the git that made it: run under
    ubuntu:18.04 (git 2.17.1) with a Python of 3.10 or later (uv's), since
    the suite's modules don't import on bionic's own 3.6 or its 3.8."""
    if not _real_git_lists_the_store_bare(tmp_path):
        pytest.skip(
            "needs git before 2.25, which lists a --separate-git-dir store as"
            " bare (#612 gap 2); run in ubuntu:18.04 (git 2.17.1). The shim"
            " tests above cover it everywhere."
        )
    c = BY_NAME[name]
    primary, linked = _old_git_pair(tmp_path / "l", c.text, c.knob)
    r = c.run(linked, _env_for(c), tmp_path)
    assert c.refused(r), _said(r)


# Create and destroy act on the repository git names, so an inherited
# GIT_COMMON_DIR moves their worktree add and branch checks too: the
# resolution is held by the block's own test above.
GAP_3 = [n for n in NAMES if n not in ("worktree-create.sh", "worktree-destroy.sh")]


@pytest.mark.parametrize("name", GAP_3)
def test_gap_3_an_inherited_git_common_dir_does_not_answer(tmp_path, name):
    """#612's reproduction (R4-3): `GIT_COMMON_DIR=<other>/.git` resolved
    to `<other>`."""
    c = BY_NAME[name]
    primary = layouts.seed(tmp_path / "primary", c.text, c.knob)
    other = layouts.seed(tmp_path / "other", layouts.DECOY, c.knob)
    env = {**_env_for(c), "GIT_COMMON_DIR": str(other / ".git")}
    r = c.run(primary, env, tmp_path)
    assert c.reads(r, primary), _said(r)


@pytest.mark.parametrize("where", ["primary", "linked"])
@pytest.mark.parametrize("name", NAMES)
def test_gap_4_below_git_2_31_every_copy_says_git_is_too_old(tmp_path, name, where):
    """#612's reproduction: below 2.31, from a --separate-git-dir primary,
    set R's merge-mode.sh copies said "run this from the primary checkout",
    to someone already there."""
    c = BY_NAME[name]
    primary, linked = layouts.separate_git_dir(tmp_path / "l", c.text, c.knob)
    env = layouts.old_git_env(_env_for(c), tmp_path / "bin")
    r = c.run(primary if where == "primary" else linked, env, tmp_path)
    assert c.refused(r), _said(r)
    if c.says(r):
        assert layouts.OLD_GIT_HINT in c.says(r), _said(r)
        assert "run this from the primary checkout" not in c.says(r), _said(r)


# The hook keeps git's first line in MERGE_MODE_ERR, as it did before
# #612, and the doctor says nothing; every other copy says it all.
ALOUD = [n for n in NAMES if n not in ("doctor.sh", "skills-submodule-update.sh")]


@pytest.mark.parametrize("name", ALOUD)
def test_a_refused_primary_keeps_gits_whole_reason(tmp_path, name):
    """CR 2265: git's refusal is several lines, the last of them the
    `git config --global --add safe.directory` command to run. #612 kept
    the first line only, so the refusal no longer said what to run."""
    c = BY_NAME[name]
    primary = layouts.seed(tmp_path / "p", c.text, c.knob)
    linked = tmp_path / "wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(linked))
    env = layouts.different_owner(_env_for(c), linked)
    r = c.run(linked, env, tmp_path)
    assert c.refused(r), _said(r)
    assert "dubious ownership" in _said(r), _said(r)
    assert "safe.directory" in _said(r), _said(r)
