"""A bare clone's default branch is its own HEAD (#615).

`git clone --bare` creates no `refs/remotes/origin/HEAD`, so without
`.skills/default_branch` the default-branch lookup fell back to `main`, and
a bare clone whose default branch is `trunk` read as being on a feature
branch. The bare repository's own HEAD is what `clone --bare` keeps of the
remote's default, so in a bare layout it answers before `main`.

The order, for all three copies: `.skills/default_branch` (doc-check reads
no knob), then `origin/HEAD`, then, in a bare layout, the bare repository's
HEAD, then `main`. A layout that has `origin/HEAD` answers as before.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

REPO = Path(__file__).resolve().parent.parent.parent
SW = REPO / "skills" / "shipping-work" / "scripts"
DEPLOY = SW / "run-deploy-command.sh"
DOC_CHECK = SW / "doc-check.sh"
DESTROY = REPO / "skills" / "using-git-worktrees" / "scripts" / "worktree-destroy.sh"

STUB = """\
#!/usr/bin/env bash
pwd -P >"${STUB_RECORD:?}"
"""


def _run(script: Path, *args: str, cwd: Path, **extra: str):
    env = layouts.env()
    env.pop("WORKTREE_ROOT", None)
    env.update(extra)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )


def _bare_trunk(tmp_path: Path, *, tracked: bool = True) -> Path:
    """A bare clone of a repo whose default branch is `trunk`, and its
    linked worktree on trunk. With `tracked`, trunk has an upstream as
    set U's remedy sets it, and still no origin/HEAD."""
    src = tmp_path / "src"
    src.mkdir()
    layouts.git(src, "init", "-q", "-b", "trunk")
    layouts.git(src, "config", "user.email", "test@example.com")
    layouts.git(src, "config", "user.name", "test")
    (src / "README.md").write_text("x\n")
    layouts.git(src, "add", "-A")
    layouts.git(src, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    bare = tmp_path / "repo.git"
    layouts.git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    assert layouts.git(bare, "symbolic-ref", "HEAD") == "refs/heads/trunk"
    home = tmp_path / "home"
    layouts.git(bare, "worktree", "add", "-q", str(home), "trunk")
    if tracked:
        layouts.git(
            home, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"
        )
        # git 2.48+ fetch would create origin/HEAD itself, which is the
        # answer this bare clone lacks.
        layouts.git(home, "config", "remote.origin.followRemoteHEAD", "never")
        layouts.git(home, "fetch", "-q", "origin")
        layouts.git(home, "branch", "--set-upstream-to=origin/trunk")
    probe = subprocess.run(
        [
            "git",
            "-C",
            str(home),
            "rev-parse",
            "--verify",
            "-q",
            "refs/remotes/origin/HEAD",
        ],
        capture_output=True,
        env=layouts.env(),
    )
    assert probe.returncode != 0, "fixture: origin/HEAD exists"
    return home


def _deploy_knobs(home: Path, tmp_path: Path) -> Path:
    stub = tmp_path / "bin" / "stub.sh"
    stub.parent.mkdir(parents=True)
    stub.write_text(STUB)
    stub.chmod(0o755)
    layouts.knob(home, f"{stub}\n", "deploy_command")
    layouts.knob(home, "pr\n", "merge_mode")
    return tmp_path / "record"


class TestRunDeployCommand:
    def test_a_bare_clone_on_its_trunk_default_deploys(self, tmp_path):
        """#615's reproduction: pr mode refused with "HEAD is on trunk; ...
        only the default branch (main)"."""
        home = _bare_trunk(tmp_path)
        record = _deploy_knobs(home, tmp_path)
        r = _run(DEPLOY, cwd=home, STUB_RECORD=str(record))
        assert "only the default branch (main)" not in r.stderr, r.stderr
        assert r.returncode == 0, r.stdout + r.stderr
        assert record.read_text().strip() == str(home.resolve())

    def test_a_bare_clones_feature_branch_is_still_refused(self, tmp_path):
        home = _bare_trunk(tmp_path)
        record = _deploy_knobs(home, tmp_path)
        layouts.git(home, "switch", "-q", "-c", "feature/x")
        r = _run(DEPLOY, cwd=home, STUB_RECORD=str(record))
        assert r.returncode == 2, r.stdout + r.stderr
        assert "only the default branch (trunk)" in r.stderr, r.stderr
        assert not record.exists()

    def test_the_knob_still_comes_first(self, tmp_path):
        home = _bare_trunk(tmp_path)
        record = _deploy_knobs(home, tmp_path)
        layouts.knob(home, "release\n", "default_branch")
        r = _run(DEPLOY, cwd=home, STUB_RECORD=str(record))
        assert r.returncode == 2, r.stdout + r.stderr
        assert "only the default branch (release)" in r.stderr, r.stderr

    def test_a_plain_clone_without_origin_head_still_reads_main(self, tmp_path):
        """Not bare: the fallback stays `main`, as before."""
        home = _bare_trunk(tmp_path)
        plain = tmp_path / "plain"
        layouts.git(tmp_path, "clone", "-q", str(tmp_path / "src"), str(plain))
        layouts.git(plain, "remote", "set-head", "origin", "-d")
        record = _deploy_knobs(plain, tmp_path / "p")
        r = _run(DEPLOY, cwd=plain, STUB_RECORD=str(record))
        assert r.returncode == 2, r.stdout + r.stderr
        assert "only the default branch (main)" in r.stderr, r.stderr
        del home


class TestWorktreeDestroy:
    def test_a_bare_clones_branch_is_checked_against_trunk(self, tmp_path):
        """The copy at worktree-destroy.sh's default-branch lookup: a branch
        merged into trunk read as unmerged against `main`, which a bare clone
        of a trunk repo doesn't have."""
        home = _bare_trunk(tmp_path)
        layouts.git(home, "branch", "feature/y", "HEAD")
        wts = tmp_path / "wts"
        layouts.git(home, "worktree", "add", "-q", str(wts / "feature-y"), "feature/y")
        r = _run(DESTROY, "feature/y", "--dry-run", cwd=home, WORKTREE_ROOT=str(wts))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ancestor of 'origin/trunk'" in r.stdout, r.stdout

    def test_untracked_it_uses_the_local_trunk(self, tmp_path):
        home = _bare_trunk(tmp_path, tracked=False)
        layouts.git(home, "branch", "feature/y", "HEAD")
        wts = tmp_path / "wts"
        layouts.git(home, "worktree", "add", "-q", str(wts / "feature-y"), "feature/y")
        r = _run(DESTROY, "feature/y", "--dry-run", cwd=home, WORKTREE_ROOT=str(wts))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ancestor of 'trunk'" in r.stdout, r.stdout


class TestDocCheck:
    @pytest.mark.parametrize("tracked", [True, False], ids=["tracked", "untracked"])
    def test_a_bare_clone_diffs_against_its_trunk(self, tmp_path, tracked):
        """The third copy, which the issue didn't name: doc-check fell from
        origin/HEAD to origin/main to main, and a bare trunk clone has none
        of them, so it was exit 2."""
        home = _bare_trunk(tmp_path, tracked=tracked)
        layouts.git(home, "switch", "-q", "-c", "feature/z")
        (home / "AGENTS.md").write_text("changed\n")
        layouts.git(home, "add", "-A")
        layouts.git(home, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "doc")
        r = _run(DOC_CHECK, cwd=home)
        assert "could not resolve a base ref" not in r.stderr, r.stderr
        assert r.returncode == 1, r.stdout + r.stderr
        assert "AGENTS.md" in r.stdout, r.stdout


class TestAnUnbornBareHeadIsNoAnswer:
    """CR 2264: `git init --bare` names `master` (or init.defaultBranch) in
    HEAD whether or not it exists, and a bare repository filled by push or
    fetch keeps that name. Taken unchecked, it refused a deploy and a destroy
    that resolved `main` before #615."""

    def _home(self, tmp_path: Path) -> Path:
        home = _bare_trunk(tmp_path)
        bare = tmp_path / "repo.git"
        layouts.git(bare, "branch", "main", "trunk")
        layouts.git(bare, "symbolic-ref", "HEAD", "refs/heads/never-made")
        layouts.git(home, "switch", "-q", "main")
        layouts.git(home, "fetch", "-q", "origin")
        layouts.git(home, "branch", "-q", "--set-upstream-to=origin/trunk")
        return home

    def test_deploy_falls_through_to_main(self, tmp_path):
        home = self._home(tmp_path)
        record = _deploy_knobs(home, tmp_path)
        r = _run(DEPLOY, cwd=home, STUB_RECORD=str(record))
        assert "never-made" not in r.stderr, r.stderr
        assert "only the default branch" not in r.stderr, r.stderr

    def test_destroy_falls_through_to_main(self, tmp_path):
        home = self._home(tmp_path)
        layouts.git(home, "branch", "feature/y", "HEAD")
        wts = tmp_path / "wts"
        layouts.git(home, "worktree", "add", "-q", str(wts / "feature-y"), "feature/y")
        r = _run(DESTROY, "feature/y", "--dry-run", cwd=home, WORKTREE_ROOT=str(wts))
        assert "never-made" not in r.stderr, r.stderr
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ancestor of 'main'" in r.stdout, r.stdout
