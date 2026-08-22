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

These tests are the port of `test_worktree_root_contract.py`'s
`TestWorktreeRootDoesNotNest` and `TestSubmoduleWorktreeBoundary` onto the
plans-dir script; they duplicate that file's fixtures rather than share them
because `tests/structural/` has no conftest and each module here builds its
own throwaway repos.

No API calls. Self-contained: each test builds a throwaway repo under tmp_path.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESOLVE = REPO_ROOT / "skills" / "writing-plans" / "scripts" / "resolve-plans-dir.sh"


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
        primary, "-c", "protocol.file.allow=always",
        "submodule", "add", "-q", str(sub), name,
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

    def test_resolve_from_linked_worktree_equals_primary(self, primary: Path, linked: Path):
        from_primary = _run(RESOLVE, cwd=primary)
        from_linked = _run(RESOLVE, cwd=linked)
        assert from_primary.returncode == 0 and from_linked.returncode == 0
        assert from_linked.stdout.strip() == from_primary.stdout.strip(), (
            "the plans directory is a property of the repository, not of the "
            "checkout you happen to be standing in; --show-toplevel answers "
            "with the linked worktree and files the plan inside it"
        )
        assert Path(from_linked.stdout.strip()) == primary / "docs" / "plans"

    def test_resolve_from_a_subdirectory_uses_the_repo_root(self, primary: Path):
        """Trap one: --git-common-dir is RELATIVE outside a linked worktree.

        From the primary checkout's root it prints `.git`; from a subdirectory
        it prints `../../.git`. Absolutizing before taking the parent is what
        keeps this from resolving to a sibling of the subdirectory.
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

    def test_config_file_is_read_from_the_primary_checkout(self, primary: Path, linked: Path):
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
            ["bash", str(RESOLVE)], capture_output=True, text=True, cwd=str(linked), env=env
        )
        assert r.stdout.strip() == "/tmp/override-plans", (
            "PLANS_DIR is first in the resolution order and must stay first"
        )

    def test_submodule_resolves_to_the_submodule_root(self, primary: Path, tmp_path: Path):
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
