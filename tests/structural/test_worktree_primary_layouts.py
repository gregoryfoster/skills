"""worktree-create.sh and worktree-destroy.sh find the primary in every layout (#605).

Both read the primary checkout from the first `git worktree list
--porcelain` block, as `shipping-work`'s readers do: create to ask whether
the primary ignores the worktree root (#567), destroy to read its
untracked `.skills/default_branch` (#559). Set T taught them a bare
primary and a submodule (CR 1839, 1840); set R's rule (CR 1892, 1895, 1903)
covers two more, which merge_mode_layouts.py builds:

- **a `--separate-git-dir` primary,** whose block names its store: `-C
  <store>` names no work tree, so create refused every root and destroy
  every run, even from the primary itself. From the primary its own top
  level answers; from a linked worktree git knows no path to it, so exit 2
  says to run from the primary.
- **an inherited `GIT_DIR` or `GIT_WORK_TREE`,** as a hook exports, which
  beats `-C`: asked for a submodule's primary, git answered for this
  checkout or for the entry itself. Destroy read no knob and took `main`;
  create skipped the primary's ignore check and let a tracked root through.

Every fixture scrubs the inherited `GIT_*` variables and names its repo
explicitly (docs/STYLE.md, #189).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "using-git-worktrees"
    / "scripts"
)
CREATE = SCRIPTS / "worktree-create.sh"
DESTROY = SCRIPTS / "worktree-destroy.sh"


def _run(
    script: Path, *args: str, cwd: Path, **extra: str
) -> subprocess.CompletedProcess:
    env = layouts.env()
    env.pop("WORKTREE_ROOT", None)
    env.update(extra)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _worktrees(checkout: Path) -> int:
    return (
        layouts.git(checkout, "worktree", "list", "--porcelain").count("\nworktree ")
        + 1
    )


def _inherited(kind: str, checkout: Path) -> dict:
    """The variable a hook would hand the script, run from `checkout`."""
    if kind == "GIT_DIR":
        return {"GIT_DIR": layouts.git(checkout, "rev-parse", "--absolute-git-dir")}
    return {"GIT_WORK_TREE": str(checkout)}


INHERITED = ["GIT_DIR", "GIT_WORK_TREE"]


# --- worktree-destroy.sh: the primary's .skills/default_branch -------------


def _destroyable(checkout: Path, wts: Path) -> None:
    """`trunk` and `feature/y` at HEAD, and feature/y's worktree under `wts`.

    Merged into both trunk and main, so a dry run passes against either,
    and only the base it names says which knob was read.
    """
    layouts.git(checkout, "branch", "trunk", "HEAD")
    layouts.git(checkout, "branch", "feature/y", "HEAD")
    layouts.git(checkout, "worktree", "add", "-q", str(wts / "feature-y"), "feature/y")


def _destroy(checkout: Path, wts: Path, **extra: str) -> subprocess.CompletedProcess:
    return _run(
        DESTROY, "feature/y", "--dry-run", cwd=checkout, WORKTREE_ROOT=str(wts), **extra
    )


class TestDestroyFromASeparateGitDirPrimary:
    def test_the_primary_reads_its_own_knob(self, tmp_path: Path):
        primary, _ = layouts.separate_git_dir(
            tmp_path / "l", "trunk\n", name="default_branch"
        )
        _destroyable(primary, tmp_path / "wts")
        r = _destroy(primary, tmp_path / "wts")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ancestor of 'trunk'" in r.stdout, r.stdout

    def test_a_linked_worktree_is_exit_2_and_says_why(self, tmp_path: Path):
        primary, linked = layouts.separate_git_dir(
            tmp_path / "l", "trunk\n", name="default_branch"
        )
        _destroyable(primary, tmp_path / "wts")
        r = _destroy(linked, tmp_path / "wts")
        assert r.returncode == 2, r.stdout + r.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT in r.stderr, r.stderr
        assert "primary checkout" in r.stderr, r.stderr
        assert "ancestor of" not in r.stdout, "no verdict against a guessed base"

    def test_a_store_git_cannot_open_is_exit_2_without_the_hint(self, tmp_path: Path):
        """Never the fallback: "dubious ownership" is git's reason alone."""
        primary, linked = layouts.separate_git_dir(
            tmp_path / "l", "trunk\n", name="default_branch"
        )
        _destroyable(primary, tmp_path / "wts")
        dubious = layouts.different_owner({}, linked)
        r = _destroy(linked, tmp_path / "wts", **dubious)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "dubious ownership" in r.stderr, r.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT not in r.stderr, r.stderr


# Where each layout keeps its primary, and so the knob.
PRIMARY_OF = {
    "bare_home": lambda tmp_path, checkout: checkout,
    "submodule_linked": lambda tmp_path, checkout: tmp_path / "super" / "sub",
}


class TestDestroyUnderAnInheritedGitEnvironment:
    @pytest.mark.parametrize("kind", INHERITED)
    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_the_primarys_knob_is_still_read(self, tmp_path, layout, kind):
        base = tmp_path / "l"
        checkout = layouts.LAYOUTS[layout](base, "trunk\n", name="default_branch")
        _destroyable(checkout, tmp_path / "wts")
        r = _destroy(checkout, tmp_path / "wts", **_inherited(kind, checkout))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ancestor of 'trunk'" in r.stdout, (
            f"the knob in {PRIMARY_OF[layout](base, checkout)} went unread: {r.stdout}"
        )


# --- worktree-create.sh: does the primary ignore the root? ------------------


class TestCreateFromASeparateGitDirPrimary:
    def test_a_root_outside_the_repo_passes_from_the_primary(self, tmp_path: Path):
        primary, _ = layouts.separate_git_dir(tmp_path / "l", None)
        out = tmp_path / "out"
        r = _run(CREATE, "--new", "feature/y", cwd=primary, WORKTREE_ROOT=str(out))
        assert r.returncode == 0, r.stdout + r.stderr
        assert Path(r.stdout.strip()) == (out / "feature-y").resolve()

    def test_the_primarys_own_rules_are_asked(self, tmp_path: Path):
        """Not skipped: a root in the primary that it does not ignore is refused."""
        primary, _ = layouts.separate_git_dir(tmp_path / "l", None)
        before = _worktrees(primary)
        r = _run(
            CREATE, "--new", "feature/y", cwd=primary, WORKTREE_ROOT=str(primary / "wt")
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert ".gitignore" in r.stderr, r.stderr
        assert _worktrees(primary) == before

    def test_a_linked_worktree_is_exit_2_and_says_why(self, tmp_path: Path):
        primary, linked = layouts.separate_git_dir(tmp_path / "l", None)
        before = _worktrees(primary)
        r = _run(
            CREATE,
            "--new",
            "feature/y",
            cwd=linked,
            WORKTREE_ROOT=str(tmp_path / "out"),
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT in r.stderr, r.stderr
        assert "primary checkout" in r.stderr, r.stderr
        assert r.stdout == ""
        assert _worktrees(primary) == before


class TestCreateUnderAnInheritedGitEnvironment:
    @pytest.mark.parametrize("kind", INHERITED)
    def test_a_root_the_submodules_primary_tracks_is_still_refused(
        self, tmp_path: Path, kind: str
    ):
        """`.skills/` is tracked in the submodule's primary and not ignored.

        Asked under the hook's variable, `-C <entry>` named this checkout or
        the entry, so the primary's check was skipped and the root passed.
        """
        wt = layouts.submodule_linked(tmp_path / "l", "direct\n")
        sub = tmp_path / "l" / "super" / "sub"
        root = sub / ".skills" / "wt"
        before = _worktrees(wt)
        plain = _run(CREATE, "--new", "feature/y", cwd=wt, WORKTREE_ROOT=str(root))
        assert plain.returncode == 2 and ".gitignore" in plain.stderr, (
            "precondition: without the variable the primary refuses the root\n"
            + plain.stdout
            + plain.stderr
        )
        r = _run(
            CREATE,
            "--new",
            "feature/y",
            cwd=wt,
            WORKTREE_ROOT=str(root),
            **_inherited(kind, wt),
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert ".gitignore" in r.stderr, r.stderr
        assert _worktrees(wt) == before, "no worktree may be created"
        assert not (root / "feature-y").exists()
