"""Behavioral tests for the two contracts using-git-worktrees' scripts publish (#188).

Both defects here are invisible to this repo's own orchestration, which uses
the Agent tool's `isolation: "worktree"` and never invokes these scripts. They
bite consuming repos that *do* drive worktrees through the skill, so every test
below constructs the failing shape explicitly rather than observing the live
checkout.

1. `worktree-create.sh` documents an absolute path on stdout (`--help`, exit
   code 0) and says so again where it routes its venv notes to stderr. But
   `git worktree add` prints `HEAD is now at <sha> <subject>` to **stdout**,
   so `WT=$(worktree-create.sh --new x)` captured two lines and `cd "$WT"`
   failed. `TestStdoutContract` pins one line.

2. `resolve-worktree-root.sh` asked `git rev-parse --show-toplevel`, which
   answers with the *current* worktree's root. Run from inside a linked
   worktree it returned `<worktree>/.worktrees`, so each generation of
   worktree nested one level deeper instead of landing beside its siblings.
   `--git-common-dir` is the shared `.git` from either vantage point and its
   parent is the primary checkout. `TestWorktreeRootDoesNotNest` pins that,
   including the submodule case where the parent of the common dir is
   `<super>/.git/modules` and is *not* a work tree. The one shape that guard
   does not rescue — a linked worktree *of* a submodule — still nests, by a
   decision recorded in #203; `TestSubmoduleWorktreeBoundary` pins it so a
   later change to the guard is deliberate.

3. `TestGitignoreVenvRule` pins the untrailing-slash `.venv` rule that keeps a
   worktree's venv symlink ignored, and keeps its comment from re-acquiring
   the motivating example that #156 retired.

No API calls. Self-contained: each test builds a throwaway repo under tmp_path.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "using-git-worktrees" / "scripts"
CREATE = SCRIPTS / "worktree-create.sh"
RESOLVE = SCRIPTS / "resolve-worktree-root.sh"
GITIGNORE = REPO_ROOT / ".gitignore"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars, and with a predictable locale.

    An inherited GIT_DIR beats both `-C` and cwd, and git exports it to every
    hook process — so a fixture that ran under pre-commit would otherwise
    initialise and commit into the *real* repo. Dropping every GIT_* var is
    the only reliable scrub. LC_ALL is pinned because two tests read git's
    own progress wording.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    # WORKTREE_ROOT wins over everything in the resolution order; these tests
    # exercise the fallback, so it must not leak in from the caller.
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
def linked(primary: Path) -> Path:
    """A linked worktree of `primary`, created by git directly (not by the script)."""
    wt = primary / ".worktrees" / "gen-one"
    _git(primary, "worktree", "add", "-q", "-b", "gen/one", str(wt))
    return wt.resolve()


class TestStdoutContract:
    """worktree-create.sh promises exactly the worktree path on stdout."""

    def test_new_branch_prints_only_the_path(self, primary: Path):
        r = _run(CREATE, "--new", "feature/alpha", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        lines = r.stdout.splitlines()
        assert len(lines) == 1, (
            "stdout must carry the worktree path and nothing else — "
            "`WT=$(worktree-create.sh --new x); cd \"$WT\"` is the documented "
            f"usage and breaks on any extra line. Got {len(lines)}: {lines!r}"
        )
        assert Path(lines[0]) == primary / ".worktrees" / "feature-alpha"
        assert Path(lines[0]).is_dir()

    def test_existing_branch_prints_only_the_path(self, primary: Path):
        """The non---new branch of the if/else is a separate `git worktree add` call."""
        _git(primary, "branch", "feature/beta")
        r = _run(CREATE, "feature/beta", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        lines = r.stdout.splitlines()
        assert len(lines) == 1, (
            "the existing-branch call site must be redirected too, not just "
            f"the --new one. Got {len(lines)}: {lines!r}"
        )
        assert Path(lines[0]) == primary / ".worktrees" / "feature-beta"

    def test_captured_path_is_usable_as_a_directory(self, primary: Path):
        """The failure mode in the issue, reproduced as the caller sees it."""
        captured = subprocess.run(
            ["bash", "-c", f'WT=$(bash "{CREATE}" --new feature/gamma 2>/dev/null); cd "$WT" && pwd'],
            capture_output=True,
            text=True,
            cwd=str(primary),
            env=_clean_env(),
        )
        assert captured.returncode == 0, (
            "cd into the captured stdout must succeed; it does not when git's "
            f"checkout notice is prepended. stderr: {captured.stderr}"
        )
        assert Path(captured.stdout.strip()) == primary / ".worktrees" / "feature-gamma"

    def test_checkout_notice_is_relocated_not_discarded(self, primary: Path):
        """`>&2`, not `-q`.

        `git worktree add -q` also empties stdout, but it silences the
        `Preparing worktree` line on stderr as well — the fix must move the
        diagnostic off the contract stream, not throw away the operator's
        only record of what was checked out.
        """
        r = _run(CREATE, "--new", "feature/delta", cwd=primary)
        assert "HEAD is now at" in r.stderr, (
            "git's checkout notice must survive on stderr; a `-q` fix would "
            f"pass the stdout tests and lose it. stderr was: {r.stderr!r}"
        )
        assert "HEAD is now at" not in r.stdout


class TestWorktreeRootDoesNotNest:
    """resolve-worktree-root.sh must name the project, not the current checkout."""

    def test_resolve_from_linked_worktree_equals_primary(self, primary: Path, linked: Path):
        from_primary = _run(RESOLVE, cwd=primary)
        from_linked = _run(RESOLVE, cwd=linked)
        assert from_primary.returncode == 0 and from_linked.returncode == 0
        assert from_linked.stdout.strip() == from_primary.stdout.strip(), (
            "the worktree root is a property of the repository, not of the "
            "checkout you happen to be standing in; --show-toplevel answers "
            "with the linked worktree and nests one level per generation"
        )
        assert Path(from_linked.stdout.strip()) == primary / ".worktrees"

    def test_second_generation_worktree_is_a_sibling(self, primary: Path, linked: Path):
        """Create a worktree from inside a worktree: it lands beside, not below."""
        r = _run(CREATE, "--new", "gen/two", cwd=linked)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        created = Path(r.stdout.strip())
        assert created == primary / ".worktrees" / "gen-two", (
            f"expected a sibling of the first-generation worktree, got {created}"
        )
        assert linked not in created.parents, (
            f"{created} is nested inside {linked}; each generation would sink deeper"
        )

    def test_config_file_is_read_from_the_primary_checkout(self, primary: Path, linked: Path):
        """`.skills/worktree_root` is a machine-local knob, so it is untracked.

        An untracked file in the primary checkout does not exist in a linked
        worktree at all, so resolving against the current checkout does not
        merely nest — it silently ignores the configured root.
        """
        (primary / ".skills").mkdir()
        (primary / ".skills" / "worktree_root").write_text(
            "# configured\n" + str(primary / "elsewhere") + "\n"
        )
        assert not (linked / ".skills" / "worktree_root").exists(), (
            "fixture precondition: the knob is untracked and thus absent here"
        )
        r = _run(RESOLVE, cwd=linked)
        assert r.stdout.strip() == str(primary / "elsewhere"), (
            f"configured root must be honored from a linked worktree, got {r.stdout!r}"
        )

    def test_env_var_still_wins(self, primary: Path, linked: Path):
        env = _clean_env()
        env["WORKTREE_ROOT"] = "/tmp/override-root"
        r = subprocess.run(
            ["bash", str(RESOLVE)], capture_output=True, text=True, cwd=str(linked), env=env
        )
        assert r.stdout.strip() == "/tmp/override-root", (
            "WORKTREE_ROOT is first in the resolution order and must stay first"
        )

    def test_submodule_resolves_to_the_submodule_root(self, primary: Path, tmp_path: Path):
        """--git-common-dir's parent is NOT a work tree inside a submodule.

        There it is `<super>/.git/modules`, and taking it unconditionally would
        put worktrees inside `.git`. The submodule's own --show-toplevel is
        already correct, so the fix must fall back to it.
        """
        vendor = _add_submodule(primary, tmp_path)
        r = _run(RESOLVE, cwd=vendor)
        assert r.returncode == 0, f"resolve failed inside a submodule: {r.stderr}"
        assert Path(r.stdout.strip()) == vendor / ".worktrees", (
            "inside a submodule the root must be the submodule's own work tree, "
            f"never anything under .git/modules. Got {r.stdout.strip()!r}"
        )

    def test_outside_a_repo_exits_2(self, tmp_path: Path):
        outside = (tmp_path / "not-a-repo").resolve()
        outside.mkdir()
        r = _run(RESOLVE, cwd=outside)
        assert r.returncode == 2, f"expected exit 2, got {r.returncode}"
        assert "not inside a git repository" in r.stderr


class TestSubmoduleWorktreeBoundary:
    """#203: the one shape the guard does not rescue, pinned on purpose.

    In a linked worktree *of* a submodule, `--git-common-dir` is the same
    `<super>/.git/modules/<name>` the guard exists to refuse, so resolution
    falls back to `--show-toplevel` — which names the linked worktree. The
    root nests, exactly as it did everywhere before #188.

    Fixing it means walking `<super>/.git/modules/<name>/worktrees/<id>/gitdir`
    back to the registering checkout: real parsing for a combination nobody in
    the cohort runs. #213 decided against it and documented the boundary
    instead. These tests hold the decision in place — the behavioural one so a
    later change to the guard is noticed, the comment one so the next reader of
    the script is not left assuming the guard covers this.
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
        assert Path(from_vendor.stdout.strip()) == vendor / ".worktrees", (
            "precondition: the submodule's own checkout still resolves correctly"
        )
        assert Path(from_subwt.stdout.strip()) == subwt / ".worktrees", (
            "known and accepted (#203): from a linked worktree of a submodule "
            "the root nests under the worktree instead of naming the "
            "submodule's primary checkout. If this assertion fails the guard "
            "was changed — confirm the change was intended, then update this "
            f"test and the boundary note in the script. Got {from_subwt.stdout.strip()!r}"
        )

    def test_the_script_comment_names_this_boundary(self):
        """The comment must not read as though the submodule case is fully handled."""
        text = RESOLVE.read_text()
        parts = text.split("Two traps, both load-bearing", 1)
        assert len(parts) == 2, "resolve-worktree-root.sh lost its 'Two traps' comment"
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


class TestGitignoreVenvRule:
    """#188 item 3: correct the stale motivating example, keep the rule."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = GITIGNORE.read_text()
        self.head = "\n".join(self.text.splitlines()[:6])

    def test_venv_pattern_has_no_trailing_slash(self):
        lines = [ln.strip() for ln in self.text.splitlines()]
        assert ".venv" in lines, ".gitignore must ignore .venv"
        assert ".venv/" not in lines, (
            "a trailing slash matches only a real directory, so a linked "
            "worktree's .venv *symlink* stays untracked-but-visible and one "
            "`git add -A` commits an absolute machine-local path"
        )

    def test_comment_explains_the_symlink_consequence(self):
        low = self.head.lower()
        assert "symlink" in low, (
            "the comment must say why the slash is omitted: the thing being "
            "ignored in a worktree is a symlink, not a directory"
        )
        assert "git add -a" in low, (
            "the comment must name the consequence — committing an absolute "
            "machine-local path — or a future edit 'tidies' the slash back in"
        )

    def test_comment_does_not_cite_the_self_healed_hook_failure(self):
        assert "source .venv/bin/activate" not in self.head, (
            "#156 made the pre-commit hook self-heal a missing venv, so "
            "'the hook's `source .venv/bin/activate` breaks' is no longer a "
            "consequence of the missing slash — cite a live failure instead"
        )
