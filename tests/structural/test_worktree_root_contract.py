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
   later change to the guard is deliberate. The script's *other* documented
   trap — that `--git-common-dir` is `$PWD`-relative outside a linked worktree
   — went unasserted here until #215, though the block ported into
   `resolve-plans-dir.sh` by #202 covered it from the start;
   `test_resolve_from_a_subdirectory_is_absolute_and_names_the_repo_root`
   closes that asymmetry.

3. Around the guard (#585, #605): a git failure on the primary, a
   `--separate-git-dir` primary and an inherited `GIT_DIR`, using
   merge_mode_layouts.py's builders. Only the main worktree, a bare primary
   and #203's submodule case take the current checkout; anything else is
   exit 2, never a fallback.

4. `TestGitignoreVenvRule` pins the untrailing-slash `.venv` rule that keeps a
   worktree's venv symlink ignored, and keeps its comment from re-acquiring
   the motivating example that #156 retired.

No API calls. Self-contained: each test builds a throwaway repo under tmp_path.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

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
    # worktree-create.sh refuses a root the repo does not ignore (#567).
    (repo / ".gitignore").write_text(".worktrees/\n")
    _git(repo, "add", "README.md", ".gitignore")
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
            '`WT=$(worktree-create.sh --new x); cd "$WT"` is the documented '
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
            [
                "bash",
                "-c",
                f'WT=$(bash "{CREATE}" --new feature/gamma 2>/dev/null); cd "$WT" && pwd',
            ],
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

    def test_resolve_from_linked_worktree_equals_primary(
        self, primary: Path, linked: Path
    ):
        from_primary = _run(RESOLVE, cwd=primary)
        from_linked = _run(RESOLVE, cwd=linked)
        assert from_primary.returncode == 0 and from_linked.returncode == 0
        assert from_linked.stdout.strip() == from_primary.stdout.strip(), (
            "the worktree root is a property of the repository, not of the "
            "checkout you happen to be standing in; --show-toplevel answers "
            "with the linked worktree and nests one level per generation"
        )
        assert Path(from_linked.stdout.strip()) == primary / ".worktrees"

    def test_resolve_from_a_subdirectory_is_absolute_and_names_the_repo_root(
        self, primary: Path
    ):
        """Trap one: --git-common-dir is RELATIVE outside a linked worktree.

        From the primary checkout's root it prints `.git`; from a subdirectory
        it prints `../../.git`. Absolutizing before taking the parent is what
        keeps the fallback root from being emitted as `../../.worktrees` — a
        path that resolves differently for every caller that reads it.

        No other vantage point produces the `../../` form. From a linked
        worktree the common dir is already absolute, so the tests above are
        blind to the trap by construction; from the primary checkout's own root
        it is `.git`, whose parent is `.`.

        What this test discriminates, verified by mutation (#221): taking
        `dirname` of the *un-absolutized* common dir while comparing absolutized
        values — the realistic "forgot to absolutize before taking the parent"
        slip. That accepts `../..` as the candidate and emits
        `../../.worktrees`, which `is_absolute()` names as a relative leak
        rather than reporting a bare path mismatch.

        What it does NOT discriminate, contrary to what this docstring claimed
        before #221: the naive `[[ "$CANDIDATE" == "." ]] && CANDIDATE="$PWD"`
        repair. Applied to today's script that patch passes this whole file.
        The candidate-validation guard below rejects the still-relative
        candidate, and resolution falls back to --show-toplevel, which from a
        subdirectory of the *primary* checkout is already the right answer. The
        naive repair was only load-bearing before that guard existed; do not
        read this test as the thing standing between the two.
        """
        deep = primary / "a" / "b"
        deep.mkdir(parents=True)
        r = _run(RESOLVE, cwd=deep)
        assert r.returncode == 0, f"resolve failed in a subdirectory: {r.stderr}"
        printed = r.stdout.strip()
        assert Path(printed).is_absolute(), (
            "the resolved root must be absolute wherever it is resolved from; "
            f"an un-absolutized --git-common-dir leaks $PWD-relative. Got {printed!r}"
        )
        assert Path(printed) == primary / ".worktrees", (
            "a relative --git-common-dir must be absolutized against $PWD "
            f"before its parent is taken. Got {printed!r}"
        )

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

    def test_config_file_is_read_from_the_primary_checkout(
        self, primary: Path, linked: Path
    ):
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
            ["bash", str(RESOLVE)],
            capture_output=True,
            text=True,
            cwd=str(linked),
            env=env,
        )
        assert r.stdout.strip() == "/tmp/override-root", (
            "WORKTREE_ROOT is first in the resolution order and must stay first"
        )

    def test_submodule_resolves_to_the_submodule_root(
        self, primary: Path, tmp_path: Path
    ):
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
    the cohort runs. #203 decided against it and documented the boundary
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


def _run_env(script: Path, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


class TestAGitFailureOnThePrimaryIsExit2:
    """#585: the primary lookup hid git's failures behind `2>/dev/null`.

    git refusing the primary checkout ("dubious ownership", as on a
    service-owned checkout) read as "the candidate is not a checkout", and
    resolution fell back to the current linked worktree: the root nested and
    the primary's `.skills/worktree_root` went unread, in silence. Set T's
    rule (CR 1858) holds here too: only a bare primary takes the current
    checkout, and a git failure on any other is exit 2 with git's reason.
    """

    def test_dubious_ownership_of_the_primary_is_exit_2(
        self, primary: Path, linked: Path
    ):
        """The issue's own reproduction: only the linked worktree is safe."""
        (primary / ".skills").mkdir()
        (primary / ".skills" / "worktree_root").write_text(
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
        assert r.stdout == "", f"a refusal prints no root: {r.stdout!r}"

    def test_the_primary_itself_still_resolves_when_it_is_safe(self, primary: Path):
        """The refusal is about the primary git cannot open, not the variable."""
        r = _run_env(RESOLVE, primary, layouts.different_owner(_clean_env(), primary))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == primary / ".worktrees"

    def test_a_bare_primary_takes_the_current_checkout(self, tmp_path: Path):
        """The one layout that takes the current checkout (set T's rule)."""
        home = layouts.bare_home(tmp_path.resolve(), "direct\n").resolve()
        r = _run(RESOLVE, cwd=home)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == home / ".worktrees"

    @staticmethod
    def _dot_bare(tmp_path: Path, primary: Path) -> Path:
        """`<dir>/.bare`, a `<dir>/.git` gitfile naming it, `<dir>/main` linked."""
        top = tmp_path.resolve() / "dx"
        top.mkdir()
        _git(tmp_path, "clone", "-q", "--bare", str(primary), str(top / ".bare"))
        (top / ".git").write_text("gitdir: ./.bare\n")
        _git(top, "worktree", "add", "-q", str(top / "main"), "main")
        return top

    def test_a_dot_bare_layout_still_names_the_directory_holding_it(
        self, tmp_path: Path, primary: Path
    ):
        """`<dir>/.bare` plus a `<dir>/.git` file naming it: `<dir>` shares the
        common dir, so it is the project, as before #585."""
        top = self._dot_bare(tmp_path, primary)
        r = _run(RESOLVE, cwd=top / "main")
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == top / ".worktrees"

    def test_a_dot_bare_directory_git_refuses_is_exit_2(
        self, tmp_path: Path, primary: Path
    ):
        """CR 1988: the store is bare, but `<dir>` holds the knob, and git
        refusing `<dir>` had read as the bare case: the current checkout,
        with `<dir>/.skills/worktree_root` unread at exit 0."""
        top = self._dot_bare(tmp_path, primary)
        (top / ".skills").mkdir()
        (top / ".skills" / "worktree_root").write_text(str(top / "configured") + "\n")
        main = top / "main"
        r = _run_env(RESOLVE, main, layouts.different_owner(_clean_env(), main))
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "dubious ownership" in r.stderr, r.stderr
        assert f"'{top}'" in r.stderr, f"the error names <dir>: {r.stderr}"
        assert r.stdout == ""


class TestTheSeparateGitDirPrimary:
    """#605, case 1: a primary whose `.git` is a pointer file to a store.

    The parent of the common dir is the store's parent, which is no checkout.
    From the primary this checkout is the primary (its git dir is the common
    dir), so its own top level answers. From a linked worktree git knows no
    path to the primary: resolution fell back to the linked worktree, so the
    root nested and the primary's knob went unread. Set R's rule (CR 1892):
    that is exit 2, and the message says why.
    """

    def test_from_the_primary_it_names_the_primary(self, tmp_path: Path):
        primary, _ = layouts.separate_git_dir(tmp_path.resolve(), None)
        primary = primary.resolve()
        (primary / ".skills").mkdir()
        (primary / ".skills" / "worktree_root").write_text("wt\n")
        r = _run(RESOLVE, cwd=primary)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()) == primary / "wt"

    def test_from_a_linked_worktree_it_is_exit_2_and_says_why(self, tmp_path: Path):
        primary, linked = layouts.separate_git_dir(tmp_path.resolve(), None)
        r = _run(RESOLVE, cwd=linked)
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert layouts.SEPARATE_GIT_DIR_HINT in r.stderr, r.stderr
        assert "run this from the primary checkout" in r.stderr, r.stderr
        assert r.stdout == "", f"a refusal prints no root: {r.stdout!r}"

    @pytest.mark.parametrize("where", ["primary", "linked"])
    def test_below_git_2_31_it_says_git_is_too_old(self, tmp_path: Path, where: str):
        """CR 1990: git before 2.31 echoes `--path-format=absolute` back at
        exit 0, so the primary cannot be told from a linked worktree. "Run
        this from the primary checkout" was false from the primary itself.
        A `git` shim plays 2.30 over the real one."""
        real = shutil.which("git")
        assert real, "git is on PATH"
        shims = tmp_path.resolve() / "shims"
        shims.mkdir()
        shim = shims / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = --version ]; then echo "git version 2.30.6"; exit 0; fi\n'
            "args=()\n"
            "for a; do\n"
            '  if [ "$a" = --path-format=absolute ]; then echo "$a"; else args+=("$a"); fi\n'
            "done\n"
            f'exec {real} "${{args[@]}}"\n'
        )
        shim.chmod(0o755)
        primary, linked = layouts.separate_git_dir(tmp_path.resolve() / "l", None)
        env = _clean_env()
        env["PATH"] = f"{shims}{os.pathsep}{env['PATH']}"
        r = _run_env(RESOLVE, primary if where == "primary" else linked, env)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "git 2.30.6 predates 2.31, which this layout needs" in r.stderr, r.stderr
        assert "set WORKTREE_ROOT" in r.stderr, r.stderr
        assert "run this from the primary checkout" not in r.stderr, r.stderr


class TestAnInheritedGitDir:
    """#605, case 2: git exports GIT_DIR to every hook.

    It beats both cwd and `-C`, so `git -C <candidate>` answered for the
    current checkout. In a submodule, where the candidate is
    `<super>/.git/modules`, that matched the common dir and the root became
    `<super>/.git/modules/.worktrees`: worktrees inside `.git`. Each answer
    under an inherited GIT_DIR must equal the answer without it.
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
            f"an inherited GIT_DIR put the root inside .git: {hooked.stdout!r}"
        )
        assert hooked.stdout == plain.stdout, (hooked.stdout, plain.stdout)
        return plain.stdout.strip()

    def test_in_a_submodules_linked_worktree(self, tmp_path: Path):
        """The issue's layout. Its answer is #203's, nested, with or without."""
        wt = layouts.submodule_linked(tmp_path.resolve(), "direct\n").resolve()
        assert Path(self._assert_same_answer(wt)) == wt / ".worktrees"

    def test_in_a_submodules_own_checkout(self, primary: Path, tmp_path: Path):
        vendor = _add_submodule(primary, tmp_path)
        assert Path(self._assert_same_answer(vendor)) == vendor / ".worktrees"

    def test_in_a_linked_worktree(self, primary: Path, linked: Path):
        assert Path(self._assert_same_answer(linked)) == primary / ".worktrees"
