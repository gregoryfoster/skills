"""The review's budget block must diff the branch, not nothing (#389).

Every `reviewing-code*/scripts/gather-context.sh` picks `context-delta.sh
--base` from the first ref that has a merge base with HEAD. `@{upstream}` came
first, and on a branch pushed with `-u` the upstream IS HEAD, so the merge base
was HEAD and the block printed nothing. Seen on CannObserv/provisioner PR #45:
+569 tokens to AGENTS.md and a new 2,000-token reference doc, an empty budget
block across five CR rounds.

The base is now the first of the default branch (`main`, `master`,
`origin/HEAD`) and then `@{upstream}` whose merge base is not HEAD itself. The
block is identical in all four variants, so it is lifted out of each and run
against fixture repositories; one end-to-end run of the baseline script shows
the block printing on a pushed branch.
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

START = '_cd_base=""'
END = '[ -n "$_cd_base" ] || _cd_base=HEAD'


def _clean_env() -> dict:
    # docs/STYLE.md: a hook-exported GIT_DIR would aim every fixture command
    # at this repository (#189).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.com",
    )
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


def _block(variant: str) -> str:
    script = SKILLS_DIR / variant / "scripts" / "gather-context.sh"
    lines = script.read_text().splitlines()
    starts = [i for i, ln in enumerate(lines) if ln == START]
    ends = [i for i, ln in enumerate(lines) if ln == END]
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (
        f"{variant}/scripts/gather-context.sh: expected one budget-base block "
        f"from `{START}` to `{END}`; this test lifts it and runs it."
    )
    return "\n".join(lines[starts[0] : ends[0] + 1])


def _base(variant: str, cwd: Path) -> str:
    r = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _block(variant) + '\necho "$_cd_base"'],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(),
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _commit(cwd: Path, name: str, text: str) -> str:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare origin whose main carries one commit."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    _commit(seed, "AGENTS.md", "# Agents\n")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


@pytest.fixture
def clone(tmp_path: Path, remote: Path) -> Path:
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    return work


def _pushed_branch(clone: Path) -> str:
    """A feature branch with commits, pushed with -u. Returns its fork point."""
    fork = git(clone, "rev-parse", "HEAD")
    git(clone, "checkout", "-q", "-b", "feature")
    _commit(clone, "AGENTS.md", "# Agents\n\n" + "More guidance. " * 200 + "\n")
    git(clone, "push", "-q", "-u", "origin", "feature")
    assert git(clone, "rev-parse", "@{upstream}") == git(clone, "rev-parse", "HEAD")
    return fork


class TestTheBudgetBase:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_a_pushed_branch_diffs_from_its_fork_point(self, variant, clone):
        """The #389 regression: upstream == HEAD must not become the base."""
        fork = _pushed_branch(clone)
        base = _base(variant, clone)
        assert base == fork, (
            f"{variant}: on a branch pushed with -u the budget base was {base}, "
            f"not the fork point {fork}. @{{upstream}} is HEAD there, so "
            "context-delta.sh saw no change and the budget block printed "
            "nothing on exactly the PR branches it exists for."
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_unpushed_commits_on_a_pushed_branch_count_from_the_fork(
        self, variant, clone
    ):
        """The default branch comes first: the upstream would show only the
        commits since the last push, not the branch a reviewer is reviewing."""
        fork = _pushed_branch(clone)
        _commit(clone, "notes.md", "unpushed\n")
        assert _base(variant, clone) == fork

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_no_local_main_falls_back_to_origin_head(self, variant, clone):
        """A clone checked out on its branch, its local main deleted — the shape
        of a cloud session. origin/HEAD still names the default branch."""
        fork = _pushed_branch(clone)
        git(clone, "branch", "-q", "-D", "main")
        assert _base(variant, clone) == fork

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_unpushed_commits_on_main_diff_from_the_upstream(self, variant, clone):
        """On main itself, main's merge base is HEAD and is skipped; the
        upstream is then the last pushed main."""
        pushed = git(clone, "rev-parse", "HEAD")
        _commit(clone, "notes.md", "unpushed\n")
        assert _base(variant, clone) == pushed

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_nothing_to_diff_against_falls_back_to_head(self, variant, tmp_path):
        """No remote, and a default branch with neither common name: HEAD, the
        old behaviour, still right for reviewing a dirty tree."""
        repo = tmp_path / "solo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "trunk")
        _commit(repo, "AGENTS.md", "# Agents\n")
        assert _base(variant, repo) == "HEAD"


def test_the_budget_block_prints_on_a_pushed_branch(clone):
    """End to end through the baseline script and the real context-delta.sh."""
    _pushed_branch(clone)
    (clone / "skills").mkdir()
    (clone / "skills" / "curating-context").symlink_to(SKILLS_DIR / "curating-context")
    r = subprocess.run(
        ["bash", str(SKILLS_DIR / "reviewing-code" / "scripts" / "gather-context.sh")],
        cwd=str(clone),
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(),
    )
    assert r.returncode == 0, r.stderr
    tail = r.stdout.split("=== Changed files (working tree vs HEAD) ===", 1)[1]
    assert "AGENTS.md" in tail, (
        "gather-context.sh printed no budget block on a branch pushed with -u "
        f"that grew AGENTS.md (#389). Output after the changed-files section:\n"
        f"{tail}"
    )
