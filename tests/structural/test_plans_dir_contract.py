"""Behavioral tests for the project root `resolve-plans-dir.sh` names (#202).

Third instance of the defect #188 fixed in `resolve-worktree-root.sh` and
`worktree-create.sh`: `git rev-parse --show-toplevel` answers with the
*current* checkout, so a script that must talk about "the project" gets the
worktree it happens to be standing in.

Two consequences, and the second is the one that bites:

1. The fallback mis-roots — plans land in `<worktree>/docs/plans` rather than
   the project's.
2. `.skills/plans_dir` is untracked, as machine-local config should be, so it
   **does not exist in a linked worktree at all**. From a worktree the knob is
   not mis-read, it is absent, and resolution falls through to the default as
   though the project had never configured one. A wrong path is visible; a
   silently-ignored configuration is not.

`--git-common-dir` is the shared `.git` from either vantage point and its
parent is the primary checkout. Two traps that a naive version gets wrong are
pinned below: the path is *relative* from the primary checkout and absolute
from a linked worktree, and inside a submodule the common dir is
`<super>/.git/modules/<name>` whose parent is not a work tree — taking it
would resolve the plans directory inside `.git`. This repo vendors skills as
submodules, so that one is live.

These tests began as the port of `test_worktree_root_contract.py`'s
`TestWorktreeRootDoesNotNest` and `TestSubmoduleWorktreeBoundary` onto the
plans-dir script (#202); they duplicate that file's fixtures rather than share
them because `tests/structural/` has no conftest and each module here builds
its own throwaway repos.

The flow has since gone both ways — #215 back-ported the subdirectory trap into
that file, and #221 back-ported this file's absoluteness assertion after it,
so the two are peers rather than an original and a copy. The scripts they pin
are line-for-line the same resolution block; an edit to either half should be
checked against the other.

The relative knob (#590) and the primary lookup's failure layouts (#585,
#605) are held to that script by running both resolvers on the same layouts,
rather than by a copied expectation.

No API calls. Self-contained: each test builds a throwaway repo under tmp_path.
"""

import os
import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESOLVE = REPO_ROOT / "skills" / "writing-plans" / "scripts" / "resolve-plans-dir.sh"
# The twin whose rule the relative knob is held to (#590).
WORKTREES = REPO_ROOT / "skills" / "using-git-worktrees" / "scripts"
WORKTREE_RESOLVE = WORKTREES / "resolve-worktree-root.sh"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars, and with a predictable locale.

    An inherited GIT_DIR beats both `-C` and cwd, and git exports it to every
    hook process — so a fixture that ran under pre-commit would otherwise
    initialise and commit into the *real* repo. Dropping every GIT_* var is
    the only reliable scrub; see docs/STYLE.md, "A repo-creating git command
    must scrub `GIT_DIR`".
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    # PLANS_DIR wins over everything in the resolution order; these tests
    # exercise the config file and the fallback, so it must not leak in.
    env.pop("PLANS_DIR", None)
    env.pop("WORKTREE_ROOT", None)
    return env


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=check,
        env=_clean_env(),
    )


def _run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=_clean_env(),
    )


def _add_submodule(primary: Path, tmp_path: Path, name: str = "vendor") -> Path:
    """Add a fresh one-commit repo to `primary` as a submodule; return its work tree.

    `protocol.file.allow=always` is required because git 2.38 disabled the
    `file://` transport for submodules by default.
    """
    sub = (tmp_path / f"{name}-src").resolve()
    sub.mkdir()
    _git(tmp_path.resolve(), "init", "-q", "-b", "main", str(sub))
    _git(sub, "config", "user.email", "test@example.com")
    _git(sub, "config", "user.name", "test")
    (sub / "s.txt").write_text("s\n")
    _git(sub, "add", "s.txt")
    _git(sub, "commit", "-q", "-m", "sub initial")
    _git(
        primary,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(sub),
        name,
    )
    return primary / name


@pytest.fixture
def primary(tmp_path: Path) -> Path:
    """A one-commit repo, resolved through any /var -> /private/var symlink.

    git reports physical paths, so the fixture must too or every comparison
    against script output is a false-unequal.
    """
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    _git(tmp_path.resolve(), "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def linked(primary: Path) -> Path:
    """A linked worktree of `primary`, created by git directly."""
    wt = primary / ".worktrees" / "gen-one"
    _git(primary, "worktree", "add", "-q", "-b", "gen/one", str(wt))
    return wt.resolve()


class TestPlansDirDoesNotNest:
    """resolve-plans-dir.sh must name the project, not the current checkout."""

    def test_resolve_from_linked_worktree_equals_primary(
        self, primary: Path, linked: Path
    ):
        from_primary = _run(RESOLVE, cwd=primary)
        from_linked = _run(RESOLVE, cwd=linked)
        assert from_primary.returncode == 0 and from_linked.returncode == 0
        assert from_linked.stdout.strip() == from_primary.stdout.strip(), (
            "the plans directory is a property of the repository, not of the "
            "checkout you happen to be standing in; --show-toplevel answers "
            "with the linked worktree and files the plan inside it"
        )
        assert Path(from_linked.stdout.strip()) == primary / "docs" / "plans"

    def test_resolve_from_a_subdirectory_is_absolute_and_names_the_repo_root(
        self, primary: Path
    ):
        """Trap one: --git-common-dir is RELATIVE outside a linked worktree.

        From the primary checkout's root it prints `.git`; from a subdirectory
        it prints `../../.git`. Absolutizing before taking the parent is what
        keeps this from resolving to a sibling of the subdirectory.

        Which mutants this discriminates — and the one it does not, despite a
        docstring that long claimed otherwise — is written once beside the twin
        of this test in test_worktree_root_contract.py. Deliberately not
        restated here, by the same rule the two scripts follow: two copies of
        one account drift into two accounts, and only the copy someone happens
        to edit gets corrected.
        """
        deep = primary / "a" / "b"
        deep.mkdir(parents=True)
        r = _run(RESOLVE, cwd=deep)
        assert r.returncode == 0, f"resolve failed in a subdirectory: {r.stderr}"
        printed = r.stdout.strip()
        assert Path(printed).is_absolute(), (
            "the resolved plans directory must be absolute wherever it is "
            "resolved from; an un-absolutized --git-common-dir leaks "
            f"$PWD-relative. Got {printed!r}"
        )
        assert Path(printed) == primary / "docs" / "plans", (
            "a relative --git-common-dir must be absolutized against $PWD "
            f"before its parent is taken. Got {printed!r}"
        )

    def test_config_file_is_read_from_the_primary_checkout(
        self, primary: Path, linked: Path
    ):
        """`.skills/plans_dir` is a machine-local knob, so it is untracked.

        An untracked file in the primary checkout does not exist in a linked
        worktree at all, so resolving against the current checkout does not
        merely mis-root — it silently ignores the configured directory, which
        is the invisible half of this defect.
        """
        (primary / ".skills").mkdir()
        (primary / ".skills" / "plans_dir").write_text(
            "# configured\n" + str(primary / "notes") + "\n"
        )
        assert not (linked / ".skills" / "plans_dir").exists(), (
            "fixture precondition: the knob is untracked and thus absent here"
        )
        r = _run(RESOLVE, cwd=linked)
        assert r.stdout.strip() == str(primary / "notes"), (
            f"configured plans dir must be honored from a linked worktree, got {r.stdout!r}"
        )

    def test_env_var_still_wins(self, primary: Path, linked: Path):
        env = _clean_env()
        env["PLANS_DIR"] = "/tmp/override-plans"
        r = subprocess.run(
            ["bash", str(RESOLVE)],
            capture_output=True,
            text=True,
            cwd=str(linked),
            env=env,
        )
        assert r.stdout.strip() == "/tmp/override-plans", (
            "PLANS_DIR is first in the resolution order and must stay first"
        )

    def test_submodule_resolves_to_the_submodule_root(
        self, primary: Path, tmp_path: Path
    ):
        """Trap two: --git-common-dir's parent is NOT a work tree in a submodule.

        There it is `<super>/.git/modules`, and taking it unconditionally would
        resolve the plans directory to `<super>/.git/modules/docs/plans`. The
        submodule's own --show-toplevel is already correct, so the guard must
        fall back to it. This repo vendors skills as submodules — live, not
        theoretical.
        """
        vendor = _add_submodule(primary, tmp_path)
        r = _run(RESOLVE, cwd=vendor)
        assert r.returncode == 0, f"resolve failed inside a submodule: {r.stderr}"
        resolved = Path(r.stdout.strip())
        assert ".git" not in resolved.parts, (
            f"the plans directory must never land inside .git. Got {resolved}"
        )
        assert resolved == vendor / "docs" / "plans", (
            "inside a submodule the plans dir must be the submodule's own work "
            f"tree. Got {resolved}"
        )

    def test_outside_a_repo_exits_2(self, tmp_path: Path):
        outside = (tmp_path / "not-a-repo").resolve()
        outside.mkdir()
        r = _run(RESOLVE, cwd=outside)
        assert r.returncode == 2, f"expected exit 2, got {r.returncode}"
        assert "not inside a git repository" in r.stderr


class TestRelativeConfiguredDir:
    """#590: a relative `.skills/plans_dir` is the primary checkout's.

    Echoed verbatim, it resolved against the caller's directory: from a
    subdirectory it named a directory under that subdirectory, and from a
    linked worktree one inside that worktree. #562 and #567 fixed the same
    defect in `resolve-worktree-root.sh`; this is its twin.
    """

    @pytest.fixture
    def knob(self, primary: Path) -> Path:
        (primary / ".skills").mkdir()
        (primary / ".skills" / "plans_dir").write_text("# configured\nnotes/plans\n")
        return primary

    def test_resolve_from_a_subdirectory_names_the_primary(self, knob: Path):
        deep = knob / "src" / "pkg"
        deep.mkdir(parents=True)
        r = _run(RESOLVE, cwd=deep)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(knob / "notes" / "plans"), (
            "a relative knob echoed verbatim resolves against the caller's "
            f"directory, here src/pkg/notes/plans; got {r.stdout.strip()!r}"
        )

    def test_resolve_from_a_linked_worktree_names_the_primary(
        self, knob: Path, linked: Path
    ):
        r = _run(RESOLVE, cwd=linked)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(knob / "notes" / "plans"), (
            "a relative knob echoed verbatim files the plan inside the linked "
            f"worktree; got {r.stdout.strip()!r}"
        )

    def test_a_relative_env_var_is_printed_as_given(self, knob: Path):
        """PLANS_DIR keeps its meaning: the reader's directory, as before."""
        env = _clean_env()
        env["PLANS_DIR"] = "elsewhere"
        r = subprocess.run(
            ["bash", str(RESOLVE)],
            capture_output=True,
            text=True,
            cwd=str(knob),
            env=env,
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "elsewhere"

    @pytest.mark.parametrize(
        "value",
        ["notes", "./notes", "notes/", "../shared-plans", "~/plans", "/abs/plans"],
        ids=["bare", "dot-slash", "trailing-slash", "dotdot", "tilde", "absolute"],
    )
    @pytest.mark.parametrize("vantage", ["subdirectory", "linked"])
    def test_the_rule_is_the_worktree_root_rule(
        self, primary: Path, linked: Path, value: str, vantage: str
    ):
        """One rule for both knobs, held by running both resolvers.

        An absolute value is kept; anything else, `~` and `..` included, is
        joined to the primary checkout with a leading `./` dropped. Neither
        script expands `~` or folds `..`: the knob file is not shell input.
        Compared by output, not by a restated expectation, so a change to
        either script's rule fails here until the other matches.
        """
        (primary / ".skills").mkdir()
        (primary / ".skills" / "plans_dir").write_text(value + "\n")
        (primary / ".skills" / "worktree_root").write_text(value + "\n")
        if vantage == "subdirectory":
            cwd = primary / "src"
            cwd.mkdir()
        else:
            cwd = linked
        plans = _run(RESOLVE, cwd=cwd)
        root = _run(WORKTREE_RESOLVE, cwd=cwd)
        assert plans.returncode == 0 and root.returncode == 0, (
            f"{plans.stderr!r} / {root.stderr!r}"
        )
        assert plans.stdout == root.stdout, (
            f"knob {value!r} from the {vantage}: plans_dir printed "
            f"{plans.stdout.strip()!r}, worktree_root {root.stdout.strip()!r}"
        )
        if not value.startswith("/"):
            assert plans.stdout.strip().startswith(str(primary) + "/")


class TestSubmoduleWorktreeBoundary:
    """#203's boundary, carried with the implementation it belongs to.

    In a linked worktree *of* a submodule, `--git-common-dir` is the same
    `<super>/.git/modules/<name>` the guard exists to refuse, so resolution
    falls back to `--show-toplevel` — which names the linked worktree. #213
    decided against walking
    `<super>/.git/modules/<name>/worktrees/<id>/gitdir` back to the
    registering checkout: real parsing for a combination nobody in the cohort
    runs. The port inherits the boundary along with the fix, so it inherits
    the tests that keep the boundary stated rather than silent.
    """

    def test_linked_worktree_of_a_submodule_nests_by_design(
        self, primary: Path, tmp_path: Path
    ):
        vendor = _add_submodule(primary, tmp_path)
        subwt = (tmp_path / "subwt").resolve()
        _git(vendor, "worktree", "add", "-q", "-b", "wt/one", str(subwt))

        from_vendor = _run(RESOLVE, cwd=vendor)
        from_subwt = _run(RESOLVE, cwd=subwt)
        assert from_vendor.returncode == 0 and from_subwt.returncode == 0, (
            f"resolve failed: {from_vendor.stderr!r} / {from_subwt.stderr!r}"
        )
        assert Path(from_vendor.stdout.strip()) == vendor / "docs" / "plans", (
            "precondition: the submodule's own checkout still resolves correctly"
        )
        assert Path(from_subwt.stdout.strip()) == subwt / "docs" / "plans", (
            "known and accepted (#203): from a linked worktree of a submodule "
            "the plans dir follows the worktree instead of naming the "
            "submodule's primary checkout. If this assertion fails the guard "
            "was changed — confirm the change was intended, then update this "
            f"test and the boundary note in the script. Got {from_subwt.stdout.strip()!r}"
        )

    def test_the_script_comment_names_this_boundary(self):
        """The comment must not read as though the submodule case is fully handled."""
        text = RESOLVE.read_text()
        parts = text.split("Two traps, both load-bearing", 1)
        assert len(parts) == 2, "resolve-plans-dir.sh lost its 'Two traps' comment"
        block = parts[1].split("COMMON_DIR=", 1)[0]
        assert "linked worktree of a submodule" in block.lower(), (
            "the traps comment explains the submodule guard but says nothing "
            "about the case the guard does not rescue, so it reads as complete; "
            "name the linked-worktree-of-a-submodule case there"
        )
        assert "#203" in block, (
            "cite #203 beside the boundary so the reader can find the decision "
            "not to implement the gitdir walk, rather than re-deriving it"
        )


def _run_env(script: Path, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


class TestAGitFailureOnThePrimaryIsExit2:
    """#585, ported: git refusing the primary is exit 2, never this checkout.

    `2>/dev/null` on the candidate probe read "dubious ownership" as "the
    candidate is not a checkout", and resolution fell back to the linked
    worktree: plans were filed inside it and the primary's
    `.skills/plans_dir` went unread, in silence. Why each layout answers as
    it does is written once, beside the twin in
    test_worktree_root_contract.py.
    """

    def test_dubious_ownership_of_the_primary_is_exit_2(
        self, primary: Path, linked: Path
    ):
        """The issue's own reproduction: only the linked worktree is safe."""
        (primary / ".skills").mkdir()
        (primary / ".skills" / "plans_dir").write_text(
            str(primary / "configured") + "\n"
        )
        r = _run_env(RESOLVE, linked, layouts.different_owner(_clean_env(), linked))
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "dubious ownership" in r.stderr, (
            f"git's reason is let through: {r.stderr}"
        )
        assert f"'{primary}'" in r.stderr, f"the error names the primary: {r.stderr}"
        assert r.stdout == "", f"a refusal prints no plans dir: {r.stdout!r}"

    def test_the_primary_itself_still_resolves_when_it_is_safe(self, primary: Path):
        r = _run_env(RESOLVE, primary, layouts.different_owner(_clean_env(), primary))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == primary / "docs" / "plans"


class TestTheSeparateGitDirPrimary:
    """#605, case 1, ported: a primary whose `.git` is a pointer file."""

    def test_from_the_primary_it_names_the_primary(self, tmp_path: Path):
        primary, _ = layouts.separate_git_dir(
            tmp_path.resolve(), "notes\n", "plans_dir"
        )
        primary = primary.resolve()
        r = _run(RESOLVE, cwd=primary)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == primary / "notes"

    def test_from_a_linked_worktree_it_is_exit_2_and_says_why(self, tmp_path: Path):
        _, linked = layouts.separate_git_dir(tmp_path.resolve(), "notes\n", "plans_dir")
        r = _run(RESOLVE, cwd=linked)
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert layouts.SEPARATE_GIT_DIR_HINT in r.stderr, r.stderr
        assert "run this from the primary checkout" in r.stderr, r.stderr
        assert r.stdout == "", f"a refusal prints no plans dir: {r.stdout!r}"


class TestAnInheritedGitDir:
    """#605, case 2, ported: git exports GIT_DIR to every hook.

    It beats cwd and `-C`, so `git -C <candidate>` answered for the current
    checkout. In a submodule that matched the common dir, and the plans dir
    became `<super>/.git/modules/docs/plans`.
    """

    @staticmethod
    def _with_git_dir(checkout: Path) -> dict:
        env = _clean_env()
        env["GIT_DIR"] = _git(
            checkout, "rev-parse", "--absolute-git-dir"
        ).stdout.strip()
        return env

    def _assert_same_answer(self, checkout: Path) -> str:
        plain = _run(RESOLVE, cwd=checkout)
        hooked = _run_env(RESOLVE, checkout, self._with_git_dir(checkout))
        assert plain.returncode == 0, plain.stderr
        assert hooked.returncode == 0, hooked.stderr
        assert "/.git/" not in hooked.stdout, (
            f"an inherited GIT_DIR put the plans dir inside .git: {hooked.stdout!r}"
        )
        assert hooked.stdout == plain.stdout, (hooked.stdout, plain.stdout)
        return plain.stdout.strip()

    def test_in_a_submodules_own_checkout(self, primary: Path, tmp_path: Path):
        """The reproduction: `<super>/.git/modules/docs/plans` before the port."""
        vendor = _add_submodule(primary, tmp_path)
        assert Path(self._assert_same_answer(vendor)) == vendor / "docs" / "plans"

    def test_in_a_submodules_linked_worktree(self, tmp_path: Path):
        wt = layouts.submodule_linked(tmp_path.resolve(), "direct\n").resolve()
        assert Path(self._assert_same_answer(wt)) == wt / "docs" / "plans"

    def test_in_a_linked_worktree(self, primary: Path, linked: Path):
        assert Path(self._assert_same_answer(linked)) == primary / "docs" / "plans"


def _layout(name: str, tmp_path: Path) -> tuple[Path, dict]:
    """Build one layout; return the checkout to run from and its env."""
    tmp = tmp_path.resolve()
    env = _clean_env()
    if name == "outside-a-repo":
        cwd = tmp / "plain"
        cwd.mkdir()
        return cwd, env
    if name == "bare-home":
        cwd = layouts.bare_home(tmp, "direct\n").resolve()
    elif name.startswith("submodule-linked"):
        cwd = layouts.submodule_linked(tmp, "direct\n").resolve()
    elif name.startswith("separate-"):
        primary, linked = layouts.separate_git_dir(tmp, None)
        cwd = (primary if name == "separate-primary" else linked).resolve()
    elif name == "dot-bare":
        src = layouts.seed(tmp / "seed", "direct\n")
        top = tmp / "dx"
        top.mkdir()
        layouts.git(tmp, "clone", "-q", "--bare", str(src), str(top / ".bare"))
        (top / ".git").write_text("gitdir: ./.bare\n")
        layouts.git(top, "worktree", "add", "-q", str(top / "main"), "main")
        cwd = top / "main"
    else:
        repo = layouts.seed(tmp / "repo", "direct\n")
        if name == "subdirectory":
            cwd = repo / "a" / "b"
            cwd.mkdir(parents=True)
        elif name.startswith(("linked", "dubious")):
            cwd = tmp / "wt"
            layouts.git(repo, "worktree", "add", "-q", "-b", "wt/one", str(cwd))
        elif name.startswith("submodule"):
            cwd = _add_submodule(repo, tmp)
        else:
            cwd = repo
    if name == "dubious-primary":
        env = layouts.different_owner(env, cwd)
    if name.endswith("-git-dir"):
        env["GIT_DIR"] = layouts.git(cwd, "rev-parse", "--absolute-git-dir")
    return cwd, env


PARITY_LAYOUTS = [
    "primary",
    "subdirectory",
    "linked",
    "submodule",
    "submodule-linked",
    "bare-home",
    "dot-bare",
    "separate-primary",
    "separate-linked",
    "dubious-primary",
    "linked-git-dir",
    "submodule-git-dir",
    "submodule-linked-git-dir",
    "outside-a-repo",
]


@pytest.mark.parametrize("name", PARITY_LAYOUTS)
def test_the_lookup_is_the_worktree_root_lookup(name: str, tmp_path: Path):
    """#585's port, held by output: both resolvers, one layout, one answer.

    The same exit code, the same stderr, and the same project root under
    `/docs/plans` where the worktree root has `/.worktrees`. A change to
    either script's lookup fails here until the other matches.
    """
    cwd, env = _layout(name, tmp_path)
    plans = _run_env(RESOLVE, cwd, env)
    root = _run_env(WORKTREE_RESOLVE, cwd, env)
    assert (plans.returncode, plans.stderr) == (root.returncode, root.stderr), (
        f"{name}: plans_dir exit {plans.returncode} {plans.stderr!r}; "
        f"worktree_root exit {root.returncode} {root.stderr!r}"
    )
    if root.returncode == 0:
        plans_root = plans.stdout.removesuffix("/docs/plans\n")
        tree_root = root.stdout.removesuffix("/.worktrees\n")
        assert plans_root != plans.stdout and tree_root != root.stdout, (
            plans.stdout,
            root.stdout,
        )
        assert plans_root == tree_root, (
            f"{name}: plans_dir {plans.stdout.strip()!r}, worktree_root "
            f"{root.stdout.strip()!r}"
        )
    else:
        assert plans.stdout == root.stdout == ""
