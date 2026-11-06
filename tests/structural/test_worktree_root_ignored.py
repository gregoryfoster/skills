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
