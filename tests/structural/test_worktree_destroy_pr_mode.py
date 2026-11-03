"""`worktree-destroy.sh` under `.skills/merge_mode` (#342).

The Iron Law's merge check is tip ancestry: the branch tip must be an ancestor
of `origin/<base>`. A GitHub **squash** or **rebase** merge writes new commits,
so a branch merged that way fails the check and destroy refuses without
`--descoped`. In `pr` mode two things change, and nothing else:

- **`git fetch origin` first,** so ancestry isn't read against a stale
  `origin/<base>`. In a `pr` repo, `origin/<base>` moves only on GitHub.
- **A merged PR is merge evidence** when ancestry fails, but only a PR into
  the base whose head *is* this branch's tip (or a descendant of it). `gh pr
  list --head <branch> --state merged` alone matches by branch name, so a
  branch reused after an earlier PR merged would read as merged with its new
  commits unmerged.

What this file pins, besides those:

- **Absent knob, byte for byte.** Output and exit codes are the literals the
  script printed before #342, and no network call happens: a fake `gh` that
  records every call is first on `PATH` and is never called, and a merge
  pushed to origin from elsewhere stays unseen (no fetch).
- **gh missing, unauthenticated or failing never reads as merged.** It is
  exit 2, the tooling code, with gh's own stderr shown: the verdict could not
  be reached, and exit 1's "merge it first" would be wrong advice for a
  branch that may already be squash-merged.
- **`--base <ref>` keeps its meaning:** ancestry against the ref as given.
  It names a local integration branch such as `batch/<x>`, which no PR
  targets, so pr mode asks gh nothing there.
- **`--dry-run`** reports the PR it found and exits with the real run's code.

The `gh` here is a fake that prints what a test tells it to. What real gh
prints was checked by hand against gh 2.102.0: `pr list --json … --jq …`
prints one line per PR and exits 0 with no output when none match, and an
unauthenticated call exits 4 with "To get started with GitHub CLI, please
run:  gh auth login" on stderr.

No API calls. Every git call scrubs the inherited `GIT_*` variables (#189).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SCRIPT = SKILLS_DIR / "using-git-worktrees" / "scripts" / "worktree-destroy.sh"

FAKE_GH = """\
#!/bin/sh
printf '%s\\n' "$*" >>"${FAKE_GH_LOG:?}"
[ -z "${FAKE_GH_ERR:-}" ] || printf '%s\\n' "$FAKE_GH_ERR" >&2
[ -z "${FAKE_GH_OUT:-}" ] || printf '%b\\n' "$FAKE_GH_OUT"
exit "${FAKE_GH_RC:-0}"
"""

# What the script and the git it runs need, for the PATH that has no gh.
TOOLS = (
    "bash sh git awk sed tr head tail realpath dirname basename cat pgrep ps "
    "xargs sleep lsof grep env mkdir rm ls uname wc cut sort kill"
).split()

AUTH_ERR = "To get started with GitHub CLI, please run:  gh auth login"


def _env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


class Rig:
    """origin.git (bare), repo (the primary checkout, on main), a worktree
    on feature/y with one commit pushed, and `other`: a second clone that
    stands in for GitHub merging the PR."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo = tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        _commit(self.repo, "README")
        _git(self.repo, "remote", "add", "origin", str(self.origin))
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        self.wt = self.repo / ".worktrees" / "feature-y"
        _git(self.repo, "worktree", "add", "-q", "-b", "feature/y", str(self.wt))
        self.tip = _commit(self.wt, "feature")
        _git(self.wt, "push", "-q", "-u", "origin", "feature/y")
        # The path exactly as the registry stores it, for the literal pins.
        self.wt_path = next(
            line[len("worktree ") :]
            for line in _git(self.repo, "worktree", "list", "--porcelain").split("\n")
            if line.startswith("worktree ") and line.endswith("feature-y")
        )
        self.other = tmp / "other"
        _git(tmp, "clone", "-q", str(self.origin), str(self.other))
        _git(self.other, "config", "user.email", "gh@example.com")
        _git(self.other, "config", "user.name", "github")
        self.bin = tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.gh_log = tmp / "gh.log"

    def knob(self, text: str) -> None:
        (self.repo / ".skills").mkdir(exist_ok=True)
        (self.repo / ".skills" / "merge_mode").write_text(text)

    def merge_on_origin(self, how: str) -> None:
        """`how`: 'squash' or 'merge', done in the other clone and pushed."""
        _git(self.other, "fetch", "-q", "origin")
        if how == "squash":
            _git(self.other, "merge", "-q", "--squash", "origin/feature/y")
            _git(self.other, "commit", "-q", "-m", "feature (#7)")
        else:
            _git(
                self.other,
                "merge",
                "-q",
                "--no-ff",
                "-m",
                "Merge #7",
                "origin/feature/y",
            )
        _git(self.other, "push", "-q", "origin", "main")

    def origin_main(self) -> str:
        return _git(self.repo, "rev-parse", "refs/remotes/origin/main")

    def gh_calls(self) -> list[str]:
        return self.gh_log.read_text().splitlines() if self.gh_log.exists() else []

    def destroy(
        self, *args: str, path: str | None = None, **gh
    ) -> subprocess.CompletedProcess:
        env = _env(
            WORKTREE_ROOT=str(self.repo / ".worktrees"),
            FAKE_GH_LOG=str(self.gh_log),
            PATH=path if path is not None else f"{self.bin}:{os.environ['PATH']}",
            **{f"FAKE_GH_{k.upper()}": v for k, v in gh.items()},
        )
        return subprocess.run(
            ["bash", str(SCRIPT), "feature/y", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def path_without_gh(self) -> str:
        farm = self.tmp / "nogh"
        farm.mkdir()
        for tool in TOOLS:
            found = shutil.which(tool)
            if found and tool != "gh":
                (farm / tool).symlink_to(found)
        # A local fetch runs git-upload-pack from PATH, and it lives in git's
        # exec-path, not beside a git that a symlink farm can name.
        exec_path = _git(self.repo, "--exec-path")
        return f"{farm}:{exec_path}"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


# ---------------------------------------------------------------------------
# Absent (and `direct`): today's behaviour, byte for byte, and no network
# ---------------------------------------------------------------------------


@pytest.fixture(params=["absent", "direct"])
def direct_rig(request, rig: Rig) -> Rig:
    if request.param == "direct":
        rig.knob("direct\n")
    return rig


class TestDirectModeIsUnchanged:
    def test_a_squash_merge_still_refuses_with_the_same_words(self, direct_rig):
        rig = direct_rig
        before = rig.origin_main()
        rig.merge_on_origin("squash")
        r = rig.destroy()
        assert r.returncode == 1
        assert r.stdout == ""
        assert r.stderr == (
            "ERROR: branch 'feature/y' is not merged into 'origin/main' "
            "(1 commit(s) ahead)\n"
            "Merge it first, or pass --descoped <reason> to acknowledge the "
            "descope.\n"
        )
        assert rig.wt.exists()
        assert rig.gh_calls() == [], "direct mode must never call gh"
        assert rig.origin_main() == before, "direct mode must never fetch"

    def test_a_merge_pushed_from_elsewhere_stays_unseen(self, direct_rig):
        """No fetch: the merge on origin is invisible, as it always was."""
        rig = direct_rig
        rig.merge_on_origin("merge")
        r = rig.destroy()
        assert r.returncode == 1
        assert rig.gh_calls() == []

    def test_a_merged_branch_is_removed_with_the_same_output(self, direct_rig):
        rig = direct_rig
        _git(rig.repo, "merge", "-q", "--ff-only", "feature/y")
        _git(rig.repo, "push", "-q", "origin", "main")
        r = rig.destroy()
        assert (r.returncode, r.stdout, r.stderr) == (
            0,
            f"Worktree removed: {rig.wt_path}\n",
            "",
        )
        assert rig.gh_calls() == []

    def test_the_dry_run_prints_the_same_lines(self, direct_rig):
        rig = direct_rig
        _git(rig.repo, "merge", "-q", "--ff-only", "feature/y")
        _git(rig.repo, "push", "-q", "origin", "main")
        r = rig.destroy("--dry-run")
        assert (r.returncode, r.stderr) == (0, "")
        assert r.stdout == (
            "DRY RUN — no changes made.\n"
            "  branch:    feature/y\n"
            f"  worktree:  {rig.wt_path}\n"
            "  resolved:  git worktree registry (by branch)\n"
            "  merge:     verified — 'feature/y' is an ancestor of 'origin/main'\n"
            "  locked:    no\n"
            "  port:      none recorded\n"
            f'  removal:   git worktree remove "{rig.wt_path}"\n'
        )
        assert rig.gh_calls() == []


# ---------------------------------------------------------------------------
# pr mode
# ---------------------------------------------------------------------------


@pytest.fixture
def pr_rig(rig: Rig) -> Rig:
    rig.knob("pr\n")
    return rig


class TestPrModeFetchesFirst:
    def test_a_merge_on_origin_is_seen_without_asking_gh(self, pr_rig):
        pr_rig.merge_on_origin("merge")
        r = pr_rig.destroy()
        assert r.returncode == 0, r.stdout + r.stderr
        assert not pr_rig.wt.exists()
        assert pr_rig.gh_calls() == [], "ancestry passed, so gh is not asked"

    def test_a_failed_fetch_warns_with_gits_words_and_checks_what_it_has(self, pr_rig):
        """A stale ref can only miss a merge, never invent one, so a branch
        already an ancestor of the last-fetched origin/main is still merged."""
        _git(pr_rig.repo, "merge", "-q", "--ff-only", "feature/y")
        _git(pr_rig.repo, "push", "-q", "origin", "main")
        _git(pr_rig.repo, "remote", "set-url", "origin", str(pr_rig.tmp / "gone.git"))
        r = pr_rig.destroy()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARN: git fetch origin failed" in r.stderr
        assert "gone.git" in r.stderr, "git's own stderr must be shown"


class TestAMergedPrIsEvidence:
    def test_a_squash_merged_pr_whose_head_is_the_tip_is_merged(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(out=f"7 {pr_rig.tip}")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not pr_rig.wt.exists()
        assert "PR #7" in r.stdout
        (call,) = pr_rig.gh_calls()
        assert call.startswith("pr list --head feature/y --base main --state merged"), (
            call
        )
        assert "headRefOid" in call

    def test_a_tip_behind_the_prs_head_is_merged(self, pr_rig):
        """A reviewer pushed a commit to the PR branch after this checkout
        last pulled; the PR's head descends from the local tip."""
        _git(pr_rig.other, "fetch", "-q", "origin")
        _git(pr_rig.other, "switch", "-q", "feature/y")
        head = _commit(pr_rig.other, "review-fixup")
        _git(pr_rig.other, "push", "-q", "origin", "feature/y")
        _git(pr_rig.other, "switch", "-q", "main")
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(out=f"7 {head}")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_commits_after_the_prs_head_are_not_merged(self, pr_rig):
        """The branch was reused after PR #7 merged: --head matches by name
        only, so the head must be checked against the tip."""
        merged_head = pr_rig.tip
        pr_rig.merge_on_origin("squash")
        _commit(pr_rig.wt, "after-the-merge")
        r = pr_rig.destroy(out=f"7 {merged_head}")
        assert r.returncode == 1, r.stdout + r.stderr
        assert pr_rig.wt.exists()
        assert "#7" in r.stderr

    def test_no_merged_pr_is_exit_1(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(out="")
        assert r.returncode == 1
        assert pr_rig.wt.exists()
        assert "no merged PR" in r.stderr
        assert "--descoped" in r.stderr

    def test_one_of_several_prs_matching_is_enough(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(out=f"3 {'0' * 40}\\n7 {pr_rig.tip}")
        assert r.returncode == 0, r.stdout + r.stderr


class TestNoGhNeverReadsAsMerged:
    def test_gh_missing_is_exit_2_and_destroys_nothing(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(path=pr_rig.path_without_gh())
        assert r.returncode == 2, r.stdout + r.stderr
        assert pr_rig.wt.exists()
        assert "gh" in r.stderr and "--descoped" in r.stderr

    def test_gh_unauthenticated_is_exit_2_with_ghs_own_words(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy(rc="4", err=AUTH_ERR)
        assert r.returncode == 2, r.stdout + r.stderr
        assert pr_rig.wt.exists()
        assert AUTH_ERR in r.stderr

    def test_gh_missing_with_ancestry_passing_needs_no_gh(self, pr_rig):
        pr_rig.merge_on_origin("merge")
        r = pr_rig.destroy(path=pr_rig.path_without_gh())
        assert r.returncode == 0, r.stdout + r.stderr


class TestTheFlagsInPrMode:
    def test_dry_run_names_the_pr_and_removes_nothing(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy("--dry-run", out=f"7 {pr_rig.tip}")
        assert r.returncode == 0, r.stdout + r.stderr
        assert pr_rig.wt.exists()
        assert "merged PR #7" in r.stdout
        assert pr_rig.tip in r.stdout

    def test_dry_run_with_gh_failing_exits_2_like_the_real_run(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy("--dry-run", rc="4", err=AUTH_ERR)
        assert r.returncode == 2
        assert pr_rig.wt.exists()

    def test_base_checks_ancestry_only_and_asks_gh_nothing(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy("--base", "origin/main", out=f"7 {pr_rig.tip}")
        assert r.returncode == 1, r.stdout + r.stderr
        assert pr_rig.gh_calls() == []
        assert "--base" in r.stderr

    def test_base_still_sees_a_fetched_merge(self, pr_rig):
        pr_rig.merge_on_origin("merge")
        r = pr_rig.destroy("--base", "origin/main")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_descoped_asks_gh_nothing(self, pr_rig):
        pr_rig.merge_on_origin("squash")
        r = pr_rig.destroy("--descoped", "abandoned")
        assert r.returncode == 0, r.stdout + r.stderr
        assert pr_rig.gh_calls() == []


def test_an_unusable_knob_is_exit_2_and_destroys_nothing(rig):
    rig.knob("PR\n")
    r = rig.destroy()
    assert r.returncode == 2
    assert rig.wt.exists()
    assert ".skills/merge_mode" in r.stderr
    assert rig.gh_calls() == []


def test_help_documents_pr_mode():
    out = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
    ).stdout
    for needle in (".skills/merge_mode", "gh pr list", "squash", "git fetch"):
        assert needle in out, needle
