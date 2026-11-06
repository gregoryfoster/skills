"""The primary checkout is a working tree, in a bare or submodule layout too (CR 1839b).

`_command-knob.sh`'s `primary_checkout` and `read-next-steps.sh` took the
first `git worktree list --porcelain` entry as the primary checkout. That
entry is a git dir, not a working tree, in two layouts:

- **a bare primary,** whose linked worktrees are the only checkouts: the
  entry is `repo.git` itself;
- **a submodule,** whose entry is `<super>/.git/modules/<name>`.

Neither holds a `.skills/`, so a committed `.skills/next-steps` or
`.skills/pre_restart` read as absent (exit 3): the silent fallback #564
forbids. Both now normalise the entry with `git -C <entry> rev-parse
--show-toplevel`, and a bare one, which has no top level, falls back to the
current checkout's, as `using-git-worktrees` does.

Each fixture commits the knobs, so every checkout of the layout has them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SCRIPTS = SKILLS_DIR / "shipping-work" / "scripts"

STUB = """\
#!/usr/bin/env bash
pwd -P >"${STUB_RECORD:?}"
"""

ROW = "Data reload: data/*.csv changed -> run scripts/reload.sh"


def _env(**extra: str) -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    )


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A repo whose one commit carries the stub and both knobs."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    stub = src / "scripts" / "stub.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    (src / ".skills").mkdir()
    (src / ".skills" / "pre_restart").write_text("scripts/stub.sh\n")
    (src / ".skills" / "next-steps").write_text(f"# rows\n{ROW}\n")
    _git(src, "add", "-A")
    _git(
        src,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return src


@pytest.fixture
def bare_worktree(tmp_path: Path, src: Path) -> Path:
    """A linked worktree of a bare primary: the list's first entry is repo.git."""
    bare = tmp_path / "repo.git"
    _git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    wt = tmp_path / "wt"
    _git(bare, "worktree", "add", "-q", str(wt), "main")
    return wt


@pytest.fixture
def submodule(tmp_path: Path, src: Path) -> Path:
    """A submodule's checkout: the list's first entry is <super>/.git/modules/sub."""
    sup = tmp_path / "super"
    sup.mkdir()
    _git(sup, "init", "-q", "-b", "main")
    _git(
        sup,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "-q",
        "add",
        str(src),
        "sub",
    )
    return sup / "sub"


LAYOUTS = ["bare_worktree", "submodule"]


def _run(script: str, cwd: Path, record: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record)),
        timeout=60,
    )


@pytest.mark.parametrize("layout", LAYOUTS)
def test_read_next_steps_finds_the_committed_rows(request, tmp_path, layout):
    checkout = request.getfixturevalue(layout)
    result = _run("read-next-steps.sh", checkout, tmp_path / "record")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [ROW]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_pre_restart_runs_the_committed_check_from_the_checkout(
    request, tmp_path, layout
):
    checkout = request.getfixturevalue(layout)
    record = tmp_path / "record"
    result = _run("run-pre-restart.sh", checkout, record)
    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text().strip() == str(checkout.resolve())


# CR 1858: a primary git can't read is not a bare primary. The fallback above
# took *any* failure of `git -C <entry> rev-parse --show-toplevel` as "bare",
# so a primary under "dubious ownership" (safe.directory naming only the
# linked worktree) handed the feature branch's knobs to every script: its
# deploy command, its pre_restart check, its next-steps rows. Only a `bare`
# line in the first porcelain block means bare; any other failure exits 2,
# naming the path, with git's own reason shown.

BRANCH_ROW = "Branch row: read from the feature branch, not the primary"


@pytest.fixture
def unreadable_primary(tmp_path: Path, src: Path) -> tuple[Path, dict]:
    """A linked worktree on `feat` with its own rows, and an environment in
    which git refuses the primary as another user's but trusts the worktree."""
    (src / ".skills" / "deploy_command").write_text("scripts/stub.sh\n")
    _git(src, "add", "-A")
    _git(
        src,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "deploy knob",
    )
    wt = tmp_path / "wt"
    _git(src, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / ".skills" / "next-steps").write_text(f"{BRANCH_ROW}\n")
    # Its own upstream, so run-deploy-command.sh's pushed check would pass.
    _git(wt, "config", "branch.feat.remote", ".")
    _git(wt, "config", "branch.feat.merge", "refs/heads/feat")
    git_env = {
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(wt),
    }
    return wt, git_env


@pytest.mark.parametrize(
    "script", ["read-next-steps.sh", "run-pre-restart.sh", "run-deploy-command.sh"]
)
def test_an_unreadable_primary_exits_2_naming_it(
    unreadable_primary, src, tmp_path, script
):
    wt, git_env = unreadable_primary
    record = tmp_path / "record"
    result = subprocess.run(
        ["bash", str(SCRIPTS / script)],
        cwd=wt,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record), **git_env),
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert not record.exists(), "the branch's command ran"
    assert BRANCH_ROW not in result.stdout
    assert str(src) in result.stderr
    assert "dubious ownership" in result.stderr, result.stderr
