"""The review's changed-files list must cover the branch, not just the tree (#549).

Every `reviewing-code*/scripts/gather-context.sh` printed its "Changed files"
section from `git diff --name-only HEAD` plus `--staged HEAD`: the working tree
against HEAD. On a branch whose work is fully committed — the normal state when
a review runs before shipping — the section was empty, and nothing said so. A
call such as `gather-context.sh origin/main..HEAD` was accepted and the range
ignored without a word. Reported from CannObserv/wslcb-licensing-tracker#229.

The budget block had already solved this for itself (#389): a merge base,
`origin/HEAD` first, skipping a ref whose merge base is HEAD
(test_gather_context_budget_base.py). The list now runs from that same base,
resolved once, plus the working tree and untracked files; its header names the
base, or says the list is working tree only. An argument other than `--help`
is refused with exit 2 rather than ignored.

The scripts run end to end against fixture repositories, with a stub `uv` and
`php` first on PATH and HOME pointed at the fixture, so no variant reaches a
real toolchain or the user's own vendored skills.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO / "skills"

VARIANTS = [
    "reviewing-code",
    "reviewing-code-php",
    "reviewing-code-python-click",
    "reviewing-code-python-fastapi",
]

SECTION = "=== Changed files"


def _clean_env(home: Path | None = None) -> dict:
    # docs/STYLE.md: a hook-exported GIT_DIR would aim every fixture command
    # at this repository (#189).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.com",
    )
    if home is not None:
        env["HOME"] = str(home)
        env["PATH"] = f"{home / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    return r.stdout.strip()


def _commit(cwd: Path, name: str, text: str) -> str:
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A HOME with no vendored skills, and stub `uv` and `php` on PATH: the
    variants' own sections run, reach nothing real, and stay fast."""
    h = tmp_path / "home"
    (h / "bin").mkdir(parents=True)
    uv = h / "bin" / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n")
    uv.chmod(0o755)
    php = h / "bin" / "php"
    php.write_text('#!/bin/sh\necho "php-stub $*"\n')
    php.chmod(0o755)
    return h


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone of a bare origin whose main carries one commit. `clone` sets
    origin/HEAD, as a normal checkout has it."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    _commit(seed, "README.md", "seed\n")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(bare), str(work))
    return work


def _committed_branch(clone: Path, name: str = "feature.txt") -> str:
    """A feature branch one commit beyond the base, nothing uncommitted.
    Returns the fork point."""
    fork = git(clone, "rev-parse", "HEAD")
    git(clone, "checkout", "-q", "-b", "feature")
    _commit(clone, name, "the branch's work\n")
    assert git(clone, "status", "--porcelain") == ""
    return fork


def _run(variant: str, cwd: Path, home: Path, *args: str):
    script = SKILLS_DIR / variant / "scripts" / "gather-context.sh"
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(home),
    )


def _section(stdout: str) -> tuple[str, list[str]]:
    """The changed-files section's header line and its body lines."""
    lines = stdout.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith(SECTION)]
    assert len(starts) == 1, f"expected one {SECTION!r} header in:\n{stdout}"
    body = []
    for ln in lines[starts[0] + 1 :]:
        if ln.startswith("===") or ln == "":
            break
        body.append(ln)
    return lines[starts[0]], body


class TestTheIssueReproduction:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_issue_549_verbatim(self, variant, clone, home):
        """#549, Done when: "On a fully committed branch, `gather-context.sh`
        lists the branch's files, and a range argument is either honoured or
        refused." """
        _committed_branch(clone)

        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        _, body = _section(r.stdout)
        assert "feature.txt" in body, (
            f"{variant}: on a fully committed branch the changed-files section "
            f"listed {body!r}, not the branch's file. A review run before "
            "shipping saw an empty scope and nothing said so (#549)."
        )

        r = _run(variant, clone, home, "origin/main..HEAD")
        if r.returncode == 0:
            _, body = _section(r.stdout)
            assert "feature.txt" in body, (
                f"{variant}: `gather-context.sh origin/main..HEAD` exited 0 "
                "and did not list the range's file: the range was accepted "
                "and ignored (#549)."
            )
        else:
            assert r.returncode == 2, (
                f"{variant}: a range argument must be honoured or refused "
                f"with exit 2, not exit {r.returncode}.\n{r.stderr}"
            )


class TestTheReviewBase:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_the_header_names_the_merge_base_and_its_ref(self, variant, clone, home):
        fork = _committed_branch(clone)
        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        header, _ = _section(r.stdout)
        assert fork[:12] in header and "origin/HEAD" in header, (
            f"{variant}: the header must name the base the list runs from, so "
            f"the reviewer sees the scope. Got {header!r}; base {fork[:12]} "
            "from origin/HEAD."
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_the_working_tree_and_untracked_files_still_count(
        self, variant, clone, home
    ):
        """The branch's commits plus the tree: an edit not yet committed and
        a new file not yet added are both in review, and a file both
        committed and edited is listed once."""
        _committed_branch(clone)
        (clone / "README.md").write_text("edited, uncommitted\n")
        (clone / "feature.txt").write_text("edited again\n")
        (clone / "new.txt").write_text("untracked\n")
        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        _, body = _section(r.stdout)
        assert sorted(body) == ["README.md", "feature.txt", "new.txt"], body

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_no_base_says_the_list_is_working_tree_only(self, variant, tmp_path, home):
        """No remote and a default branch with neither common name: the list
        falls back to the working tree, and the header says so."""
        repo = tmp_path / "solo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "trunk")
        _commit(repo, "a.txt", "a\n")
        (repo / "a.txt").write_text("dirty\n")
        r = _run(variant, repo, home)
        assert r.returncode == 0, r.stderr
        header, body = _section(r.stdout)
        assert "working tree" in header and "only" in header, header
        assert body == ["a.txt"], body

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_an_empty_list_is_never_silent(self, variant, clone, home):
        """On main with everything pushed, every candidate's merge base is
        HEAD, so no base qualifies and the tree is clean. The section must
        say it is empty, and why, rather than print nothing."""
        assert git(clone, "status", "--porcelain") == ""
        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        header, body = _section(r.stdout)
        assert "only" in header, header
        assert len(body) == 1 and body[0].startswith("(none"), (
            f"{variant}: an empty changed-files list must say so. Got {body!r}"
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_on_main_everything_pushed_does_not_claim_no_merge_base(
        self, variant, clone, home
    ):
        """CR 1788. The fallback's commonest case: a merge base exists and
        is HEAD itself, which the loop skips by design. A header or empty
        line saying "no merge base" asserts something false there, and on a
        repo whose default branch has another name it reads as no common
        history at all."""
        assert git(clone, "merge-base", "HEAD", "origin/HEAD") == git(
            clone, "rev-parse", "HEAD"
        )
        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        header, body = _section(r.stdout)
        assert "only" in header, header
        for line in [header, *body]:
            assert "no merge base" not in line, (
                f"{variant}: {line!r} says there is no merge base; there is "
                "one, and it is HEAD."
            )
        assert "other than HEAD" in header, header

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_an_empty_list_against_a_base_is_never_silent(self, variant, clone, home):
        """Two unpushed commits on main that cancel out, and a clean tree:
        origin/HEAD qualifies as the base, and nothing differs from it."""
        _commit(clone, "x.txt", "x\n")
        git(clone, "rm", "-q", "x.txt")
        git(clone, "commit", "-q", "-m", "revert x")
        r = _run(variant, clone, home)
        assert r.returncode == 0, r.stderr
        header, body = _section(r.stdout)
        assert "origin/HEAD" in header, header
        assert len(body) == 1 and body[0].startswith("(none"), body

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_a_failed_git_is_incomplete_not_none(self, variant, tmp_path, home):
        """A repo with no commit yet: `git diff HEAD` fails. The list must
        say it is incomplete and leave git's error on stderr, not read the
        failure as an empty answer — the silent-empty class #549 is."""
        repo = tmp_path / "unborn"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("untracked\n")
        r = _run(variant, repo, home)
        assert r.returncode == 0, r.stderr
        _, body = _section(r.stdout)
        assert body and body[-1].startswith("(incomplete"), body
        assert "a.txt" in body, body
        assert "HEAD" in r.stderr, r.stderr


class TestArguments:
    @pytest.mark.parametrize("variant", VARIANTS)
    @pytest.mark.parametrize("arg", ["origin/main..HEAD", "main", "-h", "--base"])
    def test_an_unknown_argument_is_refused_with_exit_2(
        self, variant, arg, clone, home
    ):
        r = _run(variant, clone, home, arg)
        assert r.returncode == 2, (
            f"{variant}: `{arg}` exited {r.returncode}; an argument the script "
            "does not take must be refused, not ignored (#549)."
        )
        assert "--help" in r.stderr and arg in r.stderr, r.stderr
        assert r.stdout == "", "refused before printing any context"

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_help_exits_0_and_names_the_contract(self, variant, clone, home):
        r = _run(variant, clone, home, "--help")
        assert r.returncode == 0, r.stderr
        assert "merge base" in r.stdout and "2 =" in r.stdout, r.stdout


def test_php_lints_the_branchs_committed_php_files(clone, home):
    """The PHP variant's `php -l` reads the same list, so a committed
    branch's PHP file is linted, not skipped as unchanged."""
    _committed_branch(clone, "src/thing.php")
    r = _run("reviewing-code-php", clone, home)
    assert r.returncode == 0, r.stderr
    assert "php-stub -l src/thing.php" in r.stdout, r.stdout


class TestOneBaseInLockstep:
    """The base is resolved once and feeds both the list and the budget
    block; the two blocks are the same text in all four copies until #536
    folds them."""

    @staticmethod
    def _block(variant: str, first: str) -> str:
        lines = (
            (SKILLS_DIR / variant / "scripts" / "gather-context.sh")
            .read_text()
            .splitlines()
        )
        starts = [i for i, ln in enumerate(lines) if ln.startswith(first)]
        assert len(starts) == 1, f"{variant}: expected one line starting {first!r}"
        out = []
        for ln in lines[starts[0] :]:
            if ln == "":
                break
            out.append(ln)
        return "\n".join(out)

    @pytest.mark.parametrize("first", ["# --- Review base", "# Changed files:"])
    def test_the_blocks_match_across_variants(self, first):
        blocks = {v: self._block(v, first) for v in VARIANTS}
        assert len(set(blocks.values())) == 1, (
            f"the block starting {first!r} differs across variants: "
            + ", ".join(v for v in VARIANTS if blocks[v] != blocks[VARIANTS[0]])
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_one_resolver(self, variant):
        text = (SKILLS_DIR / variant / "scripts" / "gather-context.sh").read_text()
        assert text.count("git merge-base") == 1, (
            f"{variant}: the review base must be resolved once and shared by "
            "the changed-files list and the budget block."
        )
        assert '--base "$_cd_base"' in text
