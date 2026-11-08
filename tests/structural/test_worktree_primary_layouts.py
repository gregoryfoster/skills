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

import os
import shutil
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
        """The message is merge-mode.sh's (CR 2029): it runs first, on the
        same rule, and refuses before destroy's own read is reached."""
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
        """Never the fallback: "dubious ownership" is git's reason alone.
        The message is merge-mode.sh's, as above (CR 2029)."""
        primary, linked = layouts.separate_git_dir(
            tmp_path / "l", "trunk\n", name="default_branch"
        )
        _destroyable(primary, tmp_path / "wts")
        dubious = layouts.different_owner({}, linked)
        r = _destroy(linked, tmp_path / "wts", **dubious)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "dubious ownership" in r.stderr, r.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT not in r.stderr, r.stderr

    def test_a_registered_worktree_needs_no_root(self, tmp_path: Path):
        """CR 1989: the root feeds only the constructed path, for a branch
        with no registered worktree. Resolved up front, the resolver's exit 2
        from this linked worktree refused a `--descoped` destroy that worked
        before #585."""
        primary, linked = layouts.separate_git_dir(tmp_path / "l", None)
        layouts.git(primary, "worktree", "add", "-q", "-b", "l2", str(tmp_path / "l2"))
        r = _run(DESTROY, "l2", "--descoped", "x", "--dry-run", cwd=linked)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (tmp_path / "l2").is_dir(), "a dry run removes nothing"

    def test_an_unregistered_branch_still_needs_the_root(self, tmp_path: Path):
        """The constructed path does need it: the resolver's exit 2 shows."""
        primary, linked = layouts.separate_git_dir(tmp_path / "l", None)
        layouts.git(primary, "branch", "l3")
        r = _run(DESTROY, "l3", "--descoped", "x", "--dry-run", cwd=linked)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "no registered worktree" in r.stderr, r.stderr
        assert "run this from the primary checkout" in r.stderr, r.stderr


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

    def test_below_git_2_31_it_says_git_is_too_old(self, tmp_path: Path):
        """CR 1990's case in create: git before 2.31 echoes
        `--path-format=absolute` back at exit 0, so from the primary itself
        "run this from the primary checkout" would be false. A `git` shim
        plays 2.30 over the real one."""
        real = shutil.which("git")
        assert real, "git is on PATH"
        shims = tmp_path / "shims"
        shims.mkdir()
        shim = shims / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = --version ]; then echo "git version 2.30.6"; exit 0; fi\n'
            "args=()\n"
            "for a; do\n"
            '  if [ "$a" = --path-format=absolute ]; then echo "$a"; '
            'else args+=("$a"); fi\n'
            "done\n"
            f'exec {real} "${{args[@]}}"\n'
        )
        shim.chmod(0o755)
        primary, _ = layouts.separate_git_dir(tmp_path / "l", None)
        before = _worktrees(primary)
        r = _run(
            CREATE,
            "--new",
            "feature/y",
            cwd=primary,
            WORKTREE_ROOT=str(tmp_path / "out"),
            PATH=f"{shims}{os.pathsep}{os.environ['PATH']}",
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert (
            "git 2.30.6 predates 2.31, which this layout needs to tell its "
            "primary from a linked worktree: upgrade git (from a linked "
            "worktree, then run from the primary checkout)"
        ) in r.stderr, r.stderr
        assert "run this from the primary checkout" not in r.stderr, r.stderr
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


class TestCreatesVenvKnobFromThePrimary:
    """CR 1992a: worktree_venv_mode had its own copy of the old lookup, with
    `2>/dev/null` fallbacks and no GIT_DIR scrub. It now reads
    primary_checkout's answer, so `.skills/worktree_venv` is found where the
    ignore check found the primary."""

    @staticmethod
    def _venv(checkout: Path) -> None:
        (checkout / ".venv" / "bin").mkdir(parents=True)
        (checkout / ".venv" / "bin" / "activate").write_text("")

    def _create(self, cwd: Path, tmp_path: Path, **extra: str):
        out = tmp_path / "out"
        r = _run(CREATE, "--new", "feature/y", cwd=cwd, WORKTREE_ROOT=str(out), **extra)
        assert r.returncode == 0, r.stdout + r.stderr
        return r, Path(r.stdout.strip())

    @pytest.mark.parametrize("kind", INHERITED)
    def test_a_submodules_own_checkout_under_an_inherited_variable(
        self, tmp_path: Path, kind: str
    ):
        """The reviewer's case: the knob says none, and the hook's GIT_DIR
        made the lookup miss it, so `.venv` was linked anyway."""
        layouts.submodule_linked(tmp_path / "l", "direct\n")
        sub = tmp_path / "l" / "super" / "sub"
        layouts.knob(sub, "none\n", name="worktree_venv")
        self._venv(sub)
        r, wt = self._create(sub, tmp_path, **_inherited(kind, sub))
        assert not (wt / ".venv").exists() and not (wt / ".venv").is_symlink()
        assert "worktree_venv=none" in r.stderr, r.stderr

    def test_a_submodules_linked_worktree_reads_its_primarys_knob(self, tmp_path: Path):
        """Before, #203's gap was inherited here: the knob, untracked in the
        submodule's primary, was looked for in this linked worktree."""
        wt = layouts.submodule_linked(tmp_path / "l", "direct\n")
        sub = tmp_path / "l" / "super" / "sub"
        layouts.knob(sub, "none\n", name="worktree_venv")
        self._venv(wt)
        r, new = self._create(wt, tmp_path)
        assert not (new / ".venv").exists() and not (new / ".venv").is_symlink()
        assert "worktree_venv=none" in r.stderr, r.stderr

    def test_a_bare_primary_reads_the_current_checkouts_knob(self, tmp_path: Path):
        home = layouts.bare_home(tmp_path / "l", "none\n", name="worktree_venv")
        self._venv(home)
        r, new = self._create(home, tmp_path)
        assert not (new / ".venv").is_symlink()
        assert "worktree_venv=none" in r.stderr, r.stderr

    def test_a_dot_bare_layout_reads_the_directory_holding_it(self, tmp_path: Path):
        """CR 2028: `<dir>/.bare` with a `<dir>/.git` gitfile naming it is a
        bare primary too, but every checkout is a linked worktree, and the
        knob lives in `<dir>`, where the resolver reads `worktree_root`.
        Read from the current checkout, `none` was missed and the venv
        linked: #201's hazard, at exit 0."""
        src = layouts.seed(tmp_path / "seed", "direct\n")
        top = tmp_path / "dx"
        top.mkdir()
        layouts.git(tmp_path, "clone", "-q", "--bare", str(src), str(top / ".bare"))
        (top / ".git").write_text("gitdir: ./.bare\n")
        layouts.git(top, "worktree", "add", "-q", str(top / "main"), "main")
        layouts.knob(top, "none\n", name="worktree_venv")
        self._venv(top / "main")
        r, new = self._create(top / "main", tmp_path)
        assert not (new / ".venv").exists() and not (new / ".venv").is_symlink()
        assert "worktree_venv=none" in r.stderr, r.stderr

    def test_a_dot_bare_gitfile_git_rejects_links_nothing(self, tmp_path: Path):
        """CR 2033: `gitdir:./.bare` (no space) is no gitfile to git. The
        resolver took the bare case, `--project-root` named this checkout,
        and the venv linked past `<dir>`'s `none`: #201's hazard."""
        src = layouts.seed(tmp_path / "seed", "direct\n")
        top = tmp_path / "dx"
        top.mkdir()
        layouts.git(tmp_path, "clone", "-q", "--bare", str(src), str(top / ".bare"))
        (top / ".git").write_text("gitdir: ./.bare\n")
        main = top / "main"
        layouts.git(top, "worktree", "add", "-q", str(main), "main")
        layouts.knob(top, "none\n", name="worktree_venv")
        (top / ".git").write_text("gitdir:./.bare\n")
        self._venv(main)
        r, new = self._create(main, tmp_path)
        assert not (new / ".venv").exists() and not (new / ".venv").is_symlink()
        assert "could not resolve where .skills/worktree_venv lives" in r.stderr

    def test_a_dot_bare_directory_git_refuses_links_nothing(self, tmp_path: Path):
        """The knob's home unknown is no `link`: git refusing `<dir>` makes
        the resolver exit 2, and the venv is left unlinked, saying why."""
        src = layouts.seed(tmp_path / "seed", "direct\n")
        top = tmp_path / "dx"
        top.mkdir()
        layouts.git(tmp_path, "clone", "-q", "--bare", str(src), str(top / ".bare"))
        (top / ".git").write_text("gitdir: ./.bare\n")
        main = top / "main"
        layouts.git(top, "worktree", "add", "-q", str(main), "main")
        self._venv(main)
        r, new = self._create(main, tmp_path, **layouts.different_owner({}, main))
        assert not (new / ".venv").exists() and not (new / ".venv").is_symlink()
        assert "dubious ownership" in r.stderr, r.stderr
        assert "could not resolve where .skills/worktree_venv lives" in r.stderr


def test_pr_modes_exit_2_is_not_only_an_unusable_file():
    """CR 1905's note on #605: from a linked worktree of a --separate-git-dir
    primary, merge-mode.sh's exit 2 means "run from the primary", not "the
    file is unusable". shipping-work's pr-mode.md says the same."""
    doc = SCRIPTS.parent / "references" / "pr-mode.md"
    text = " ".join(doc.read_text().split())
    assert "One exit 2 is not about the file." in text
    assert "`git init --separate-git-dir`" in text
    assert "run from the primary checkout" in text


@pytest.mark.parametrize(
    ("script", "phrases"),
    [
        (CREATE, ["primary checkout", "--separate-git-dir", "git < 2.31"]),
        (DESTROY, ["primary checkout", "no registered", "worktree root"]),
    ],
    ids=["create", "destroy"],
)
def test_help_names_the_new_exit_2s(script: Path, phrases: list[str]):
    """CR 2030: each --help's exit-2 list names what #585 and #605 added."""
    r = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True)
    codes = r.stdout[r.stdout.index("Exit codes:") :]
    exit_2 = " ".join(codes[codes.index("  2  ") :].split())
    for phrase in phrases:
        assert phrase in exit_2, (phrase, exit_2)
