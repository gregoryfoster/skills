"""worktree-create.sh refuses a worktree root that git would commit (#567).

A worktree created inside a directory git does not ignore is one `git add -A`
away from being committed: git adds the nested checkout as an embedded
repository (a mode-160000 gitlink, with only a warning). So the root must be
outside every work tree that contains it, or ignored there. `git check-ignore`
alone cannot decide it, because it exits non-zero for ANY path it does not
match, a path outside the repo included, so the inside-the-work-tree test
comes first, on canonical paths.

Two traps the tests pin:

* `git check-ignore` matches a dir-only pattern only when it knows the path
  is a directory, and the worktree's directory does not exist yet on the
  first create. A rule on a parent (`.worktrees/`) still matches
  `.worktrees/x`, because a parent is a directory by construction; a rule on
  the worktree's own level (`.worktrees/*/`) matches only when asked about
  `.worktrees/x/`, with the slash. Without it, every first worktree under such
  a rule is falsely refused (CR 1843).
* Paths are compared canonically. macOS resolves /var to /private/var, and a
  root may be reached through a symlink or a `..`; a raw string compare calls
  such a root "outside" and lets it through.

Also #562's leftover, built here: a relative `.skills/worktree_root` resolves
against the primary checkout, not against the caller's directory.

No API calls. Each test builds a throwaway repo under tmp_path, with every
GIT_* variable scrubbed (docs/STYLE.md).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "using-git-worktrees" / "scripts"
CREATE = SCRIPTS / "worktree-create.sh"
RESOLVE = SCRIPTS / "resolve-worktree-root.sh"


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.pop("WORKTREE_ROOT", None)
    env["LC_ALL"] = "C"
    env.update(extra)
    return env


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=check,
        env=_clean_env(),
    )


def _run(
    script: Path, *args: str, cwd: Path, **env: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=_clean_env(**env),
    )


def _worktrees(repo: Path) -> list[str]:
    out = _git(repo, "worktree", "list", "--porcelain").stdout
    return [
        ln[len("worktree ") :] for ln in out.splitlines() if ln.startswith("worktree ")
    ]


def _make_repo(path: Path, gitignore: str | None) -> Path:
    path.mkdir(parents=True)
    _git(path.parent, "init", "-q", "-b", "main", str(path))
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "test")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("x = 1\n")
    if gitignore is not None:
        (path / ".gitignore").write_text(gitignore)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "initial")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The cohort's common form: `.gitignore` carries `.worktrees/`."""
    return _make_repo(tmp_path.resolve() / "repo", ".worktrees/\n")


def _assert_refused(r: subprocess.CompletedProcess, repo: Path) -> None:
    assert r.returncode == 2, (
        f"expected exit 2, got {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert ".gitignore" in r.stderr, f"the refusal must name the remedy: {r.stderr}"
    assert r.stdout == "", f"a refusal prints no path: {r.stdout!r}"
    assert len(_worktrees(repo)) == 1, "no worktree may be created"


class TestTheIssuesCase:
    """#567's own reproduction: WORKTREE_ROOT names a tracked directory."""

    def test_a_root_in_a_tracked_directory_is_refused(self, repo: Path):
        r = _run(
            CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(repo / "src")
        )
        _assert_refused(r, repo)
        assert sorted(p.name for p in (repo / "src").iterdir()) == ["app.py"]
        assert "'src/'" in r.stderr, f"the remedy names the path to ignore: {r.stderr}"

    def test_without_the_guard_add_all_commits_a_gitlink(self, repo: Path):
        """What the refusal prevents, shown with git directly."""
        wt = repo / "src" / "feature-x"
        _git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        _git(repo, "add", "-A")
        staged = _git(repo, "ls-files", "-s", "--", "src/feature-x").stdout
        assert staged.startswith("160000 "), staged

    def test_a_configured_root_inside_the_repo_is_refused(self, repo: Path):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "worktree_root").write_text(str(repo / "wt") + "\n")
        r = _run(CREATE, "--new", "feature/x", cwd=repo)
        _assert_refused(r, repo)
        assert not (repo / "wt").exists(), "nothing is created before the refusal"

    def test_the_root_being_the_repo_itself_is_refused(self, repo: Path):
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(repo))
        _assert_refused(r, repo)

    def test_the_default_root_is_not_exempt(self, tmp_path: Path):
        bare = _make_repo(tmp_path.resolve() / "noignore", None)
        r = _run(CREATE, "--new", "feature/x", cwd=bare)
        _assert_refused(r, bare)
        assert "'.worktrees/'" in r.stderr, r.stderr


class TestRootsThatPass:
    def test_the_default_root_passes_before_it_exists(self, repo: Path):
        """The dir-only pattern `.worktrees/` against a path not yet created."""
        assert not (repo / ".worktrees").exists()
        r = _run(CREATE, "--new", "feature/x", cwd=repo)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == repo / ".worktrees" / "feature-x"

    def test_a_dir_only_rule_on_the_worktree_level_passes(self, tmp_path: Path):
        """`.worktrees/*/` matches the worktree's directory only as a directory.

        It does not exist yet, so git knows that only from the trailing slash
        on the question. A parent rule (`.worktrees/`) cannot pin the slash:
        it matches `.worktrees/x` with or without one (CR 1843).
        """
        r_ = _make_repo(tmp_path.resolve() / "r", ".worktrees/*/\n")
        assert not (r_ / ".worktrees").exists()
        r = _run(CREATE, "--new", "feature/x", cwd=r_)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == r_ / ".worktrees" / "feature-x"
        assert _git(r_, "status", "--porcelain").stdout == ""

    def test_a_root_under_an_ignored_parent_passes(self, tmp_path: Path):
        r_ = _make_repo(tmp_path.resolve() / "r", "build/\n")
        r = _run(
            CREATE, "--new", "feature/x", cwd=r_, WORKTREE_ROOT=str(r_ / "build" / "wt")
        )
        assert r.returncode == 0, r.stderr

    def test_a_root_whose_contents_are_ignored_passes(self, tmp_path: Path):
        """`.worktrees/*` ignores every worktree in the root, not the root.

        Asking about the root would refuse it; the worktree's own directory is
        what `git add -A` would stage, so that is what is asked about.
        """
        r_ = _make_repo(tmp_path.resolve() / "r", ".worktrees/*\n")
        r = _run(CREATE, "--new", "feature/x", cwd=r_)
        assert r.returncode == 0, r.stderr
        assert _git(r_, "status", "--porcelain").stdout == ""

    def test_a_root_outside_the_repo_passes(self, repo: Path, tmp_path: Path):
        """The `case` the issue explains: check-ignore would say NOT ignored."""
        outside = tmp_path.resolve() / "elsewhere"
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(outside))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == outside / "feature-x"

    def test_this_repos_default_root_is_ignored(self):
        """This repo's own `.worktrees/` passes the check worktree-create.sh runs."""
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", ".worktrees/"],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        assert r.returncode == 0, (
            "this repo's .gitignore must ignore .worktrees/, or Rule 1's "
            "worktree-create.sh orchestrate/<topic> is refused here"
        )


class TestCanonicalPaths:
    def test_a_symlinked_alias_of_the_repo_is_inside(self, repo: Path, tmp_path: Path):
        alias = tmp_path.resolve() / "alias"
        alias.symlink_to(repo)
        r = _run(
            CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(alias / "src")
        )
        _assert_refused(r, repo)

    def test_a_dotdot_root_into_a_tracked_directory_is_inside(self, repo: Path):
        root = f"{repo}/.worktrees/../src"
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=root)
        _assert_refused(r, repo)

    def test_a_dotdot_root_through_a_missing_directory(self, repo: Path):
        """`missing/..` cannot be resolved by cd; it must be applied lexically."""
        root = f"{repo}/missing/../wt"
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=root)
        _assert_refused(r, repo)

    def test_a_dotdot_root_out_of_the_repo_through_a_missing_directory(
        self, repo: Path, tmp_path: Path
    ):
        """`missing/../../outside` leaves the repo: applied lexically, it passes.

        Taken literally, the `..` keeps the path under the repo's prefix and
        check-ignore is asked about it (exit 128). The test above cannot tell
        the two apart, since there git normalises the `..` itself (CR 1843).
        """
        root = f"{repo}/missing/../../outside"
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=root)
        assert r.returncode == 0, r.stderr
        assert (tmp_path.resolve() / "outside" / "feature-x").is_dir()

    def test_a_dotdot_root_into_an_ignored_directory_passes(self, repo: Path):
        root = f"{repo}/src/../.worktrees"
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=root)
        assert r.returncode == 0, r.stderr

    def test_a_root_reached_through_a_symlink_out_of_the_repo_passes(
        self, repo: Path, tmp_path: Path
    ):
        """A link inside the repo whose target is outside: the target decides."""
        outside = tmp_path.resolve() / "out"
        outside.mkdir()
        (repo / "out-link").symlink_to(outside)
        # Commit the link so the check is about the root, not an untracked link.
        _git(repo, "add", "out-link")
        _git(repo, "commit", "-q", "-m", "link")
        r = _run(
            CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(repo / "out-link")
        )
        assert r.returncode == 0, r.stderr


class TestLinkedWorktrees:
    @pytest.fixture
    def linked(self, repo: Path) -> Path:
        wt = repo / ".worktrees" / "orchestrate-t"
        _git(repo, "worktree", "add", "-q", "-b", "orchestrate/t", str(wt))
        return wt

    def test_a_root_inside_the_current_linked_worktree_is_refused(
        self, repo: Path, linked: Path
    ):
        """Ignored from the primary (under .worktrees/), not from the linked tree."""
        r = _run(
            CREATE,
            "--new",
            "feature/x",
            cwd=linked,
            WORKTREE_ROOT=str(linked / "nested"),
        )
        assert r.returncode == 2, r.stderr
        assert ".gitignore" in r.stderr
        assert len(_worktrees(repo)) == 2

    def test_the_default_root_from_a_linked_worktree_passes(
        self, repo: Path, linked: Path
    ):
        r = _run(CREATE, "--new", "feature/x", cwd=linked)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == repo / ".worktrees" / "feature-x"

    def test_a_primary_git_cannot_open_is_exit_2_not_skipped(
        self, repo: Path, linked: Path
    ):
        """CR 1858: a tree git cannot answer for fails closed.

        git refuses the primary alone ("dubious ownership"; the linked
        worktree is declared safe). Skipped, the root in the primary's
        tracked `src/` was outside the only tree left to ask, and passed.
        """
        r = _run(
            CREATE,
            "--new",
            "feature/x",
            cwd=linked,
            WORKTREE_ROOT=str(repo / "src"),
            GIT_TEST_ASSUME_DIFFERENT_OWNER="1",
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="safe.directory",
            GIT_CONFIG_VALUE_0=str(linked),
        )
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "dubious ownership" in r.stderr, "git's reason is let through"
        assert f"'{repo}'" in r.stderr, f"the error names the tree: {r.stderr}"
        assert r.stdout == ""
        assert len(_worktrees(repo)) == 2, "no worktree may be created"


class TestSubmodulePrimary:
    """Run from a submodule's checkout, the first list entry is its git dir.

    `<super>/.git/modules/<name>` is not a work tree; git names the
    submodule's checkout via core.worktree, and that checkout decides.
    """

    def test_a_root_the_submodule_tracks_is_refused(self, tmp_path: Path):
        src = _make_repo(tmp_path.resolve() / "src-repo", ".worktrees/\n")
        sup = _make_repo(tmp_path.resolve() / "sup", ".worktrees/\n")
        _git(
            sup,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(src),
            "sub",
        )
        sub = sup / "sub"
        assert "/.git/modules/" in _worktrees(sub)[0]
        r = _run(CREATE, "--new", "feature/x", cwd=sub, WORKTREE_ROOT=str(sub / "src"))
        assert r.returncode == 2, r.stderr
        assert f"{sub}/.gitignore" in r.stderr, r.stderr
        r = _run(CREATE, "--new", "feature/x", cwd=sub)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == sub / ".worktrees" / "feature-x"


class TestRelativeConfiguredRoot:
    """#562's leftover: a relative `.skills/worktree_root` is the primary's."""

    @pytest.fixture
    def knob(self, repo: Path) -> Path:
        (repo / ".gitignore").write_text(".worktrees/\nwt/\n")
        _git(repo, "commit", "-q", "-am", "ignore wt/")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "worktree_root").write_text("wt\n")
        return repo

    def test_resolve_from_a_subdirectory_names_the_primary(self, knob: Path):
        r = _run(RESOLVE, cwd=knob / "src")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(knob / "wt"), (
            "a relative knob echoed verbatim resolves against the caller's "
            f"directory; got {r.stdout.strip()!r}"
        )

    def test_create_from_a_subdirectory_lands_under_the_primary(self, knob: Path):
        """The script cds to the top level first, so the worktree landed right.

        But it printed `wt/feature-x`, relative, which the caller standing in
        `src/` reads as `src/wt/feature-x`: the stdout contract is an absolute
        path.
        """
        r = _run(CREATE, "--new", "feature/x", cwd=knob / "src")
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == knob / "wt" / "feature-x"

    def test_create_from_a_linked_worktree_lands_under_the_primary(self, knob: Path):
        wt = knob / ".worktrees" / "orchestrate-t"
        _git(knob, "worktree", "add", "-q", "-b", "orchestrate/t", str(wt))
        r = _run(CREATE, "--new", "feature/x", cwd=wt)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == knob / "wt" / "feature-x", (
            "resolved against the linked worktree, the root nests inside it"
        )

    def test_a_relative_env_root_prints_an_absolute_path(self, knob: Path):
        """WORKTREE_ROOT keeps its meaning (the current top level), stated whole."""
        r = _run(CREATE, "--new", "feature/x", cwd=knob / "src", WORKTREE_ROOT="wt")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(knob / "wt" / "feature-x")

    def test_a_relative_knob_into_a_tracked_directory_is_refused(self, repo: Path):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "worktree_root").write_text("src\n")
        r = _run(CREATE, "--new", "feature/x", cwd=repo / "src")
        _assert_refused(r, repo)


def test_help_documents_the_refusal():
    r = _run(CREATE, "--help", cwd=REPO_ROOT)
    assert r.returncode == 0
    codes = r.stdout[r.stdout.index("Exit codes:") :]
    exit_2 = codes[codes.index("  2  ") :]
    assert "does not ignore it" in exit_2, (
        f"--help's exit 2 must name the refusal: {codes}"
    )


class TestBarePrimary:
    """CR 1840: `clone --bare` + `worktree add`, which worked at 227de51e.

    The first `git worktree list` entry is the bare directory, which has no
    work tree: nothing there can commit a worktree, so it is not a tree to
    ask. Treated as one, a root equal to it was refused as "the work tree
    itself", and a root below it failed check-ignore with exit 128.
    """

    @pytest.fixture
    def home(self, tmp_path: Path) -> Path:
        seed = _make_repo(tmp_path.resolve() / "seed", None)
        bare = tmp_path.resolve() / "repo.git"
        _git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
        home = bare / "main"
        _git(bare, "worktree", "add", "-q", str(home), "main")
        return home

    def test_the_bare_directory_as_the_root_passes(self, home: Path):
        bare = home.parent
        r = _run(CREATE, "--new", "feature/x", cwd=home, WORKTREE_ROOT=str(bare))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == bare / "feature-x"

    def test_a_root_below_the_bare_directory_passes(self, home: Path):
        bare = home.parent
        r = _run(CREATE, "--new", "feature/x", cwd=home, WORKTREE_ROOT=str(bare / "wt"))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == bare / "wt" / "feature-x"

    def test_a_root_inside_the_current_checkout_is_still_refused(self, home: Path):
        r = _run(
            CREATE, "--new", "feature/x", cwd=home, WORKTREE_ROOT=str(home / "src")
        )
        assert r.returncode == 2, r.stderr
        assert ".gitignore" in r.stderr, r.stderr


class TestCaseInsensitiveVolume:
    """CR 1842: containment is decided by inode, not by spelling.

    On a case-insensitive volume (macOS's default) `pwd -P` keeps the caller's
    spelling, so `.../caserepo/src` names a directory inside `.../CaseRepo`
    while sharing no string prefix with it.
    """

    def test_a_case_flipped_root_into_a_tracked_directory_is_refused(
        self, tmp_path: Path
    ):
        repo = _make_repo(tmp_path.resolve() / "CaseRepo", ".worktrees/\n")
        flipped = tmp_path.resolve() / "caserepo"
        if not flipped.exists():
            pytest.skip("the filesystem is case-sensitive")
        r = _run(
            CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(flipped / "src")
        )
        _assert_refused(r, repo)
        assert "'src/'" in r.stderr, f"the remedy names the path to ignore: {r.stderr}"


class TestRootInASubmodule:
    """CR 1849: a root inside a submodule of the checkout.

    git cannot answer for the superproject (check-ignore exits 128: "Pathspec
    ... is in submodule"), and no `.gitignore` line there could change that.
    The superproject commits only the gitlink; the submodule's own checkout
    is what would commit a worktree, so its rules decide.
    """

    @pytest.fixture
    def sup(self, tmp_path: Path) -> Path:
        src = _make_repo(tmp_path.resolve() / "src-repo", "wt/\n")
        sup = _make_repo(tmp_path.resolve() / "sup", ".worktrees/\n")
        _git(
            sup,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(src),
            "vendor/sub",
        )
        _git(sup, "commit", "-q", "-m", "submodule")
        return sup

    def test_a_root_the_submodule_ignores_passes(self, sup: Path):
        root = sup / "vendor" / "sub" / "wt"
        r = _run(CREATE, "--new", "feature/x", cwd=sup, WORKTREE_ROOT=str(root))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == root / "feature-x"
        assert "fatal:" not in r.stderr, f"a settled question leaks git's: {r.stderr}"

    def test_a_root_the_submodule_tracks_is_refused_by_its_rules(self, sup: Path):
        sub = sup / "vendor" / "sub"
        r = _run(CREATE, "--new", "feature/x", cwd=sup, WORKTREE_ROOT=str(sub / "src"))
        assert r.returncode == 2, r.stderr
        assert "exit 128" not in r.stderr, r.stderr
        assert f"{sub}/.gitignore" in r.stderr, (
            f"the remedy names the submodule's .gitignore: {r.stderr}"
        )
        assert len(_worktrees(sup)) == 1

    @pytest.mark.parametrize("ignorecase", ["true", "false"])
    def test_a_case_flipped_root_is_still_the_submodules_to_decide(
        self, sup: Path, ignorecase: str
    ):
        """CR 1859: `Vendor/Sub/src` names `vendor/sub/src` on this volume.

        Asked of the superproject as spelled, git does not see the submodule
        (exit 1, not 128), so the superproject decided, and the remedy it
        printed, followed here, let through a root the submodule tracks.
        The existing part of the root is now spelled as on disk.
        """
        if not (sup / "Vendor").exists():
            pytest.skip("the filesystem is case-sensitive")
        _git(sup, "config", "core.ignorecase", ignorecase)
        (sup / ".gitignore").write_text(".worktrees/\nVendor/Sub/src/\n")
        _git(sup, "commit", "-q", "-am", "the superproject's remedy, followed")
        sub = sup / "vendor" / "sub"
        flipped = sup / "Vendor" / "Sub" / "src"
        r = _run(CREATE, "--new", "feature/x", cwd=sup, WORKTREE_ROOT=str(flipped))
        assert r.returncode == 2, r.stderr
        assert f"{sub}/.gitignore" in r.stderr, (
            f"the remedy names the submodule's .gitignore: {r.stderr}"
        )
        assert len(_worktrees(sup)) == 1

    def test_a_root_in_a_submodule_not_checked_out_is_refused(
        self, sup: Path, tmp_path: Path
    ):
        """CR 1870: an uninitialised submodule has no rules to read.

        Its directory is empty, so git names the superproject as its top
        level, which was skipped as already asked: the root passed, and the
        worktree in it then blocks `git submodule update --init`.
        """
        clone = tmp_path.resolve() / "clone"
        _git(tmp_path, "clone", "-q", str(sup), str(clone))
        sub = clone / "vendor" / "sub"
        assert sub.is_dir() and not (sub / ".git").exists()
        r = _run(CREATE, "--new", "feature/x", cwd=clone, WORKTREE_ROOT=str(sub / "wt"))
        assert r.returncode == 2, r.stderr
        assert f"submodule at {sub}, which is not checked out" in r.stderr, r.stderr
        assert "git submodule update --init" in r.stderr, r.stderr
        assert r.stdout == ""
        assert not (sub / "wt").exists()
        assert len(_worktrees(clone)) == 1


def test_a_root_that_cannot_be_created_exits_2_not_1(repo: Path, tmp_path: Path):
    """CR 1850: exit 1 is the Iron Law's code; a failed `mkdir -p` is not it."""
    blocker = tmp_path.resolve() / "afile"
    blocker.write_text("not a directory\n")
    r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=str(blocker / "wt"))
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}\nstderr: {r.stderr}"
    assert "could not create the worktree root" in r.stderr, r.stderr
    assert r.stdout == ""
    assert len(_worktrees(repo)) == 1


def test_skill_md_states_what_a_bare_primary_gets():
    """CR 1871: SKILL.md still called bare repositories out of scope.

    The scripts support one: its knobs are read from the current checkout,
    and the `.gitignore` check skips it (CR 1839, CR 1840).
    """
    doc = (SCRIPTS.parent / "SKILL.md").read_text()
    notes = doc[doc.index("## Notes") :]
    notes = notes[: notes.index("\n## ", 1)]
    line = next(ln for ln in notes.splitlines() if "bare" in ln.lower())
    assert "out of scope" not in line, line
    assert "current checkout" in line and "skips it" in line, line


def test_conventions_say_where_the_knob_is_read():
    """CR 1838: CONVENTIONS.md said the file sits "under the repo root".

    From a linked worktree that is the wrong checkout: the knob is read from
    the primary one, and a relative path resolves against it (#562, #567).
    """
    doc = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text()
    start = doc.index("## Worktree root convention")
    section = doc[start : doc.index("\n## ", start + 1)]
    step = next(ln for ln in section.splitlines() if ln.startswith("2. "))
    assert "under the repo root" not in step, step
    assert "primary checkout" in step, step
    assert "relative" in step, step
    assert "#567" in step or "/issues/567" in step, step


def _long_root(base: Path, length: int = 1548) -> str:
    """#586's root: `<base>/out/d1/d2/...`, exactly `length` characters."""
    root = str(base / "out")
    i = 0
    while len(root) < length - 6:
        i += 1
        root += f"/d{i}"
    return root + "/" + "x" * (length - len(root) - 1)


class TestARootCanonicalPathCannotWalk:
    """#586: canonical_path walks up to the deepest existing ancestor with
    `dirname`. Where `dirname` fails, as macOS's does past PATH_MAX (1,024),
    `p` emptied, the walk ended at `.`, and the root became `$PWD/<last
    component>`: a root outside the repo was refused as inside it. A failing
    step is exit 2 naming the root, never a fallback to `$PWD`.
    """

    def test_the_issues_root_is_never_refused_as_inside_the_repo(
        self, repo: Path, tmp_path: Path
    ):
        """The issue's reproduction, with the platform's own dirname: where
        it fails (macOS) the run is exit 2 naming the root; where it does not
        (GNU), the root is outside the repo and passes."""
        root = _long_root(tmp_path.resolve())
        assert len(root) == 1548
        r = _run(CREATE, "--new", "feature/x", cwd=repo, WORKTREE_ROOT=root)
        assert ".gitignore" not in r.stderr, (
            f"a root outside the repo was refused as inside it: {r.stderr[-400:]}"
        )
        if r.returncode == 2:
            assert f"'{root}'" in r.stderr, f"the error names the root: {r.stderr}"
            assert r.stdout == ""
            assert len(_worktrees(repo)) == 1, "no worktree may be created"
        else:
            assert r.returncode == 0, r.stderr
            assert r.stdout.strip() == f"{root}/feature-x"

    def test_a_dirname_that_fails_is_exit_2_naming_the_root(
        self, repo: Path, tmp_path: Path
    ):
        """macOS's failure, on every platform: a `dirname` that refuses any
        argument over 1,024 characters, as dirname(3) does there."""
        real = shutil.which("dirname")
        assert real, "dirname is on PATH"
        shims = tmp_path.resolve() / "shims"
        shims.mkdir()
        shim = shims / "dirname"
        shim.write_text(
            "#!/bin/sh\n"
            'for a in "$@"; do\n'
            '  if [ "${#a}" -gt 1024 ]; then\n'
            '    echo "dirname: $a: File name too long" >&2\n'
            "    exit 1\n"
            "  fi\n"
            "done\n"
            f'exec {real} "$@"\n'
        )
        shim.chmod(0o755)
        root = _long_root(tmp_path.resolve())
        r = _run(
            CREATE,
            "--new",
            "feature/x",
            cwd=repo,
            WORKTREE_ROOT=root,
            PATH=f"{shims}{os.pathsep}{os.environ['PATH']}",
        )
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\nstderr: {r.stderr[-600:]}"
        )
        assert ".gitignore" not in r.stderr, (
            f"refused as inside the repo, from $PWD: {r.stderr[-400:]}"
        )
        assert f"could not resolve the worktree root '{root}'" in r.stderr, r.stderr[
            -600:
        ]
        assert r.stdout == ""
        assert len(_worktrees(repo)) == 1, "no worktree may be created"
        assert not (repo / "feature-x").exists()
