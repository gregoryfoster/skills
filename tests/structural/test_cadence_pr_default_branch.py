"""A `pr` run off the default branch is refused (#683, finding 1).

Both `pr` steps took `BRANCH` from `GITHUB_REF_NAME`, and the workflow
declares `workflow_dispatch:`. A dispatch on `feature/x` found no PR into
`feature/x`, merged the measurement branch into the `feature/x` checkout, and
pushed a row whose parents carried `feature/x`'s commits: the open PR into the
default branch then held unreviewed code under a bot's title, and a second PR
into `feature/x` opened (CannObserv/watcher#445's review, traced). A `pr` run
now stops in its own step, after the mode is read and before the credential is
spent, unless it is on the default branch, read from `origin`. `direct` is not
held: its row lands on the dispatched branch itself, reviewed in that branch's
own PR.

Uses `test_cadence_merge_mode`'s rig: a bare origin, fresh runner clones and a
fake `gh`. No API calls.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from tests.structural.test_cadence_merge_mode import (
    GUARD_STEP,
    PR_BRANCH,
    READ_STEP,
    Rig,
    _env,
    _git,
    _init,
    _render,
    _steps,
)


def _feature_branch(rig: Rig, name: str = "feature/x") -> str:
    """A branch on origin with a commit the default branch doesn't have."""
    dev = rig.clone(f"dev-{name.replace('/', '-')}")
    _git(dev, "checkout", "-q", "-b", name)
    (dev / "feature.py").write_text("print('unreviewed')\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-qm", "feature work")
    _git(dev, "push", "-q", "origin", f"HEAD:{name}")
    return _git(dev, "rev-parse", "HEAD")


def _ancestor(rig: Rig, a: str, b: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(rig.origin), "merge-base", "--is-ancestor", a, b],
            env=_env(),
        ).returncode
        == 0
    )


def _creates(rig: Rig) -> int:
    return len([c for c in rig.calls() if c.startswith("pr create")])


class TestARunOffTheDefaultBranchIsRefused:
    def test_a_dispatch_on_a_feature_branch_carries_none_of_it_into_the_pr(
        self, tmp_path: Path
    ):
        """The issue's scenario: the measurement PR into main is open, and the
        workflow is dispatched on feature/x."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        pr_tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        feature = _feature_branch(rig)
        calls = len(rig.calls())

        r = rig.run("2026-10-15", ref="feature/x")
        assert r.returncode != 0, r.stdout
        assert rig.guard is not None and r is rig.guard, "refused in its own step"
        assert "::error::" in r.stdout
        assert "feature/x" in r.stdout and "main" in r.stdout
        assert "dispatch" in r.stdout.lower()
        assert _git(rig.origin, "rev-parse", PR_BRANCH) == pr_tip
        assert not _ancestor(rig, feature, PR_BRANCH)
        assert _git(rig.origin, "rev-parse", "feature/x") == feature
        assert len(rig.calls()) == calls, "gh was called after the refusal"
        assert _creates(rig) == 1, "a second PR was opened"

    def test_the_default_branch_proceeds(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        r = rig.run("2026-10-08")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.guard is not None and rig.guard.returncode == 0
        assert "main" in rig.guard.stdout
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08"]

    def test_a_default_branch_it_cannot_read_is_a_refusal(self, tmp_path: Path):
        """Unknown is never "allowed": no origin to ask."""
        repo = _init(tmp_path / "r")
        step = _steps(_render(tmp_path, "pr\n"))[GUARD_STEP]
        r = subprocess.run(
            ["bash", "-e", "-c", step],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_env(MERGE_MODE="pr", GITHUB_REF_NAME="main"),
            timeout=30,
        )
        assert r.returncode != 0, r.stdout
        assert "::error::" in r.stdout and "default branch" in r.stdout

    def test_a_run_the_knob_turned_direct_is_not_held(self, tmp_path: Path):
        """`direct` pushes the row to the dispatched branch itself, where its
        own PR reviews it; nothing crosses into another branch's PR."""
        repo = _init(tmp_path / "r")
        step = _steps(_render(tmp_path, "pr\n"))[GUARD_STEP]
        r = subprocess.run(
            ["bash", "-e", "-c", step],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_env(MERGE_MODE="direct", GITHUB_REF_NAME="feature/x"),
            timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr

    def test_it_runs_after_the_mode_is_read_and_before_the_credential(
        self, tmp_path: Path
    ):
        doc = yaml.safe_load(_render(tmp_path, "pr\n"))
        names = [s.get("name", "") for s in doc["jobs"]["measure"]["steps"]]
        assert names.index(READ_STEP) + 1 == names.index(GUARD_STEP)
        assert names.index(GUARD_STEP) < names.index("Preflight the credential")

    def test_the_direct_render_has_no_guard(self, tmp_path: Path):
        assert GUARD_STEP not in _render(tmp_path, None)
