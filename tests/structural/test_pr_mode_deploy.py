"""`run-deploy-command.sh` deploys the default branch in `pr` mode (#342).

#345's script deploys whatever HEAD was pushed: HEAD must equal its upstream,
and the branch is not checked (CR 1545, stet under `direct` mode, where Step
3 has already put the agent on the default branch). In `pr` mode nothing
does: the branch is pushed and a PR opened, so a pushed feature branch
passes the upstream check and would be deployed unreviewed. The post-merge
pass deploys the default branch at the merge commit instead, and the script
now refuses anything else there.

The default branch resolves as `worktree-destroy.sh` resolves it:
`.skills/default_branch`, then origin's HEAD, then `main`. Here the file is
read from the primary checkout, as every knob this script reads is.

Absent or `direct`: nothing changes, and a pushed feature branch still
deploys. That is pinned too, so the stet stays a decision.

Every test uses a stub command that records its arguments and exits 0. No
real deploy runs, no API calls; every git call scrubs `GIT_*` (#189).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SCRIPT = SKILLS_DIR / "shipping-work" / "scripts" / "run-deploy-command.sh"

STUB = """\
#!/usr/bin/env bash
for a in "$@"; do printf 'arg=%s\\n' "$a" >>"${STUB_RECORD:?}"; done
"""


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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The primary checkout on main, pushed, with the deploy knob set and a
    pushed feature branch checked out."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    stub = repo / "scripts" / "deploy.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    (repo / ".skills").mkdir()
    (repo / ".skills" / "deploy_command").write_text("scripts/deploy.sh\n")
    _git(repo, "switch", "-q", "-c", "feature/y")
    _commit(repo, "feature")
    _git(repo, "push", "-q", "-u", "origin", "feature/y")
    return repo


def _mode(repo: Path, text: str) -> None:
    (repo / ".skills" / "merge_mode").write_text(text)


def _run(cwd: Path, *args: str, record: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record)),
        timeout=60,
    )


def _merge_and_land_on_main(repo: Path) -> str:
    """GitHub merging the PR, then the post-merge pass's switch and pull."""
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge #7", "feature/y")
    _git(repo, "push", "-q", "origin", "main")
    return _git(repo, "rev-parse", "HEAD")


class TestDirectModeIsUnchanged:
    @pytest.mark.parametrize("mode", [None, "direct\n"], ids=["absent", "direct"])
    def test_a_pushed_feature_branch_still_deploys(self, repo, tmp_path, mode):
        if mode:
            _mode(repo, mode)
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 0, r.stdout + r.stderr
        assert record.read_text() == f"arg={_git(repo, 'rev-parse', 'HEAD')}\n"


class TestPrModeDeploysTheDefaultBranch:
    def test_a_pushed_feature_branch_is_exit_2_and_runs_nothing(self, repo, tmp_path):
        _mode(repo, "pr\n")
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 2, r.stdout + r.stderr
        assert not record.exists(), "the deploy must not have run"
        assert "feature/y" in r.stderr and "main" in r.stderr
        assert "git pull --ff-only" in r.stderr

    def test_check_refuses_it_too(self, repo, tmp_path):
        _mode(repo, "pr\n")
        r = _run(repo, "--check", record=tmp_path / "record")
        assert (r.returncode, r.stdout) == (2, "")

    def test_the_merge_commit_on_main_deploys(self, repo, tmp_path):
        _mode(repo, "pr\n")
        merge = _merge_and_land_on_main(repo)
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 0, r.stdout + r.stderr
        assert record.read_text() == f"arg={merge}\n"

    def test_main_ahead_of_origin_is_still_refused(self, repo, tmp_path):
        _mode(repo, "pr\n")
        _merge_and_land_on_main(repo)
        _commit(repo, "unpushed")
        r = _run(repo, record=tmp_path / "record")
        assert r.returncode == 2

    def test_a_detached_head_at_the_merge_is_refused(self, repo, tmp_path):
        _mode(repo, "pr\n")
        merge = _merge_and_land_on_main(repo)
        _git(repo, "switch", "-q", "--detach", merge)
        r = _run(repo, record=tmp_path / "record")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "detached" in r.stderr

    def test_from_a_worktree_on_the_branch_is_refused(self, repo, tmp_path):
        _mode(repo, "pr\n")
        _git(repo, "switch", "-q", "main")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "feature/y")
        r = _run(wt, record=tmp_path / "record")
        assert r.returncode == 2, r.stdout + r.stderr

    def test_the_default_branch_knob_is_honoured(self, repo, tmp_path):
        _mode(repo, "pr\n")
        (repo / ".skills" / "default_branch").write_text("trunk\n")
        merge = _merge_and_land_on_main(repo)
        r = _run(repo, record=tmp_path / "record")
        assert r.returncode == 2, "main is not the default branch here"
        _git(repo, "switch", "-q", "-c", "trunk")
        _git(repo, "push", "-q", "-u", "origin", "trunk")
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 0, r.stdout + r.stderr
        assert record.read_text() == f"arg={merge}\n"

    def test_origins_head_names_the_default_without_the_knob(self, repo, tmp_path):
        _mode(repo, "pr\n")
        merge = _merge_and_land_on_main(repo)
        _git(repo, "switch", "-q", "-c", "trunk")
        _git(repo, "push", "-q", "-u", "origin", "trunk")
        _git(
            repo,
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/trunk",
        )
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 0, r.stdout + r.stderr
        assert record.read_text() == f"arg={merge}\n"


class TestAnUnusableModeIsNeverDirect:
    def test_it_is_exit_2_and_runs_nothing(self, repo, tmp_path):
        _mode(repo, "PR\n")
        record = tmp_path / "record"
        r = _run(repo, record=record)
        assert r.returncode == 2
        assert not record.exists()
        assert ".skills/merge_mode" in r.stderr

    def test_check_too(self, repo, tmp_path):
        _mode(repo, "\n")
        r = _run(repo, "--check", record=tmp_path / "record")
        assert (r.returncode, r.stdout) == (2, "")

    def test_with_no_deploy_command_it_is_still_exit_3(self, repo, tmp_path):
        """Without the deploy knob there is nothing to deploy, whatever the
        merge mode says; Step 8 is the next-steps table."""
        _mode(repo, "PR\n")
        (repo / ".skills" / "deploy_command").unlink()
        r = _run(repo, record=tmp_path / "record")
        assert r.returncode == 3


def test_help_says_pr_mode_deploys_the_default_branch():
    out = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
    ).stdout
    assert "merge_mode" in out and "default branch" in out
