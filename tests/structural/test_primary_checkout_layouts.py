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
