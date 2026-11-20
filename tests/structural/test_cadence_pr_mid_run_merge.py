"""A PR merged mid-run is not reopened with its rows (#683, finding 2).

The take-in step merges the open PR's tip `T` into the checkout with
`--no-commit`, and the commit step records the row with parents `M0` and `T`.
A human squash-merging that PR in between (with or without
`delete_branch_on_merge`) left the commit step on its restart path: it pushed
the branch at the row, which still had `T` as a parent, and opened a new PR
whose merge base with the default branch was `M0`, not the squash, so its
diff showed the merged PR's rows again. Reproduced here before the fix
(raised as `[review]` on CannObserv/watcher#445). The take-in step now exports
what it took in, and the commit step refuses to push it once that PR has
ended: a re-run measures after the merged rows.

Uses `test_cadence_merge_mode`'s rig: a bare origin, fresh runner clones and a
fake `gh`. No API calls.
"""

from __future__ import annotations

from pathlib import Path

from tests.structural.test_cadence_merge_mode import LEDGER, PR_BRANCH, Rig, _git


def _creates(rig: Rig) -> int:
    return len([c for c in rig.calls() if c.startswith("pr create")])


def _squash_mid_run(rig: Rig, number: int, delete: bool):
    """A human squash-merges the open PR during the run; with `delete`, the
    branch goes with it, as delete_branch_on_merge does."""

    def act() -> None:
        human = rig.clone(f"squash{rig.runs}")
        _git(human, "fetch", "-q", "origin", PR_BRANCH)
        tip = _git(human, "rev-parse", "FETCH_HEAD")
        _git(human, "merge", "-q", "--squash", "FETCH_HEAD")
        _git(human, "commit", "-qm", f"chore: weekly context measurement (#{number})")
        _git(human, "push", "-q", "origin", "HEAD:main")
        if delete:
            _git(human, "push", "-q", "origin", f":refs/heads/{PR_BRANCH}")
        (rig.gh / "prs").write_text(f"{number} MERGED {tip}\n")

    return act


class TestAPrMergedMidRunIsNotReopened:
    def _two_runs(self, tmp_path: Path, delete: bool):
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        r = rig.run("2026-10-15", between=_squash_mid_run(rig, 7, delete))
        return rig, r

    def test_squashed_and_deleted_the_row_is_not_pushed(self, tmp_path: Path):
        rig, r = self._two_runs(tmp_path, delete=True)
        assert "measuring after the rows" in rig.take.stdout, "fixture: rows taken in"
        assert r.returncode != 0, r.stdout
        assert "::error::" in r.stdout and "#7" in r.stdout
        assert not rig.has_branch(PR_BRANCH), "the branch was recreated with #7's rows"
        assert _creates(rig) == 1, "a PR was opened over the merged rows"

    def test_squashed_and_kept_the_row_is_not_pushed(self, tmp_path: Path):
        rig, r = self._two_runs(tmp_path, delete=False)
        assert r.returncode != 0, r.stdout
        assert "::error::" in r.stdout and "#7" in r.stdout
        assert _creates(rig) == 1

    def test_the_refusal_names_a_dispatch_not_a_re_run(self, tmp_path: Path):
        """CR 2564: GitHub's "Re-run jobs" reuses the run's GITHUB_SHA, and
        checkout gives it the commit before the merge, so a re-run measures
        before the merged rows again. A dispatch, or the next scheduled run,
        checks out the default branch's tip."""
        rig, r = self._two_runs(tmp_path, delete=True)
        assert r.returncode != 0, r.stdout
        assert "gh workflow run context-cadence.yml" in r.stdout
        assert "not Re-run" in r.stdout, "the error must steer off Re-run jobs"
        assert "re-run this workflow" not in r.stdout

    def test_the_next_run_measures_after_the_merged_rows(self, tmp_path: Path):
        rig, _ = self._two_runs(tmp_path, delete=True)
        r = rig.run("2026-10-16")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-16"]
        assert _git(rig.origin, "rev-parse", f"{PR_BRANCH}~1") == _git(
            rig.origin, "rev-parse", "main"
        ), "the branch restarts at the default branch plus this row"

    def test_an_open_pr_still_takes_the_row(self, tmp_path: Path):
        """The guard reads only an ended PR: an open one is updated."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        (rig.gh / "prs").write_text(f"7 OPEN {tip}\n")
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "updated PR #7" in r.stdout


def _merge_commit_mid_run(rig: Rig, number: int):
    """The same PR merged with a merge commit, its branch deleted: its tip
    is now in the default branch's history."""

    def act() -> None:
        human = rig.clone(f"merge{rig.runs}")
        _git(human, "fetch", "-q", "origin", PR_BRANCH)
        tip = _git(human, "rev-parse", "FETCH_HEAD")
        _git(human, "merge", "-q", "--no-ff", "-m", f"Merge PR #{number}", "FETCH_HEAD")
        _git(human, "push", "-q", "origin", "HEAD:main")
        _git(human, "push", "-q", "origin", f":refs/heads/{PR_BRANCH}")
        (rig.gh / "prs").write_text(f"{number} MERGED {tip}\n")

    return act


class TestAMergeCommitKeepsTheRow:
    """CR 2567: the refusal fired whenever the taken-in PR ended, so a PR
    merged with a real merge commit lost the week's row for nothing: its tip
    is in the default branch's history, and restarting at the row is right.
    The squash merge above still refuses."""

    def test_merged_with_a_merge_commit_the_row_restarts_the_branch(
        self, tmp_path: Path
    ):
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        r = rig.run("2026-10-15", between=_merge_commit_mid_run(rig, 7))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "::error::" not in r.stdout
        assert "merged into main during this run" in r.stdout
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]
        added = [
            ln
            for ln in _git(
                rig.origin, "diff", f"main...{PR_BRANCH}", "--", LEDGER
            ).splitlines()
            if ln.startswith("+{")
        ]
        assert len(added) == 1 and "2026-10-15" in added[0], added
        assert _creates(rig) == 2, "the restarted branch gets its PR"

    def test_with_the_default_branch_moved_the_pr_shows_the_row_alone(
        self, tmp_path: Path
    ):
        """CR 2571: the normal week. A commit lands on main between the runs,
        so this run's checkout G isn't in the taken-in tip; after a merge
        commit mid-run, a row with parents G and the tip had two merge bases
        with main, and the new PR showed the merged row again. The default
        branch's new tip is merged into the row before it is pushed."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        human = rig.clone("weekly-work")
        (human / "NOTES.md").write_text("the week's ordinary work\n")
        _git(human, "add", "-A")
        _git(human, "commit", "-qm", "work")
        _git(human, "push", "-q", "origin", "HEAD:main")
        r = rig.run("2026-10-15", between=_merge_commit_mid_run(rig, 7))
        assert r.returncode == 0, r.stdout + r.stderr
        bases = _git(rig.origin, "merge-base", "--all", "main", PR_BRANCH).split()
        assert bases == [_git(rig.origin, "rev-parse", "main")], (
            "the PR's branch must contain main, one merge base"
        )
        diff = _git(rig.origin, "diff", f"main...{PR_BRANCH}")
        added = [
            ln
            for ln in diff.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        ]
        assert len(added) == 1 and "2026-10-15" in added[0], diff
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]

    def test_squashed_the_row_is_still_refused(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        r = rig.run("2026-10-15", between=_squash_mid_run(rig, 7, delete=True))
        assert r.returncode != 0, r.stdout
        assert "::error::" in r.stdout and "#7" in r.stdout
        assert _creates(rig) == 1
