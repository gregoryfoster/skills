"""The command-knob scripts run through a consumer's per-script symlink (CR 1841).

`managing-skills`' local-overrides.md recommends an override that symlinks
each script it doesn't change into the vendored submodule. A link to
`run-deploy-command.sh` or `run-pre-restart.sh` then sits in a directory
with no `_command-knob.sh` (or `merge-mode.sh`) beside it. Resolving the
script's directory from `${BASH_SOURCE[0]}` without following the link
looked there, and exited 2 ("_command-knob.sh not found") even for a project
with no knob, which used to be exit 3.

Each case runs the script through a two-hop chain, a relative link to an
absolute one, from a consumer directory holding nothing else.
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
echo ran >"${STUB_RECORD:?}"
"""

KNOBS = {
    "run-deploy-command.sh": "deploy_command",
    "run-pre-restart.sh": "pre_restart",
}


def _env(**extra: str) -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A primary checkout on main, pushed (deploy_command asks), with a stub."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    stub = repo / "scripts" / "stub.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _linked(tmp_path: Path, name: str) -> Path:
    """consumer/skills/shipping-work/scripts/<name> -> ../../../vendor/<name>
    -> the real script, absolute. Neither link's directory holds anything else."""
    vendor = tmp_path / "vendor"
    vendor.mkdir(exist_ok=True)
    (vendor / name).symlink_to(SCRIPTS / name)
    consumer = tmp_path / "consumer" / "skills" / "shipping-work" / "scripts"
    consumer.mkdir(parents=True, exist_ok=True)
    link = consumer / name
    link.symlink_to(Path("..", "..", "..", "..", "vendor", name))
    assert link.resolve() == (SCRIPTS / name).resolve()
    return link


def _run(link: Path, repo: Path, record: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(link)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record)),
        timeout=60,
    )


@pytest.mark.parametrize("name", sorted(KNOBS))
def test_no_knob_through_a_symlink_is_still_exit_3(repo, tmp_path, name):
    record = tmp_path / "record"
    result = _run(_linked(tmp_path, name), repo, record)
    assert result.returncode == 3, result.stdout + result.stderr
    assert not record.exists()


@pytest.mark.parametrize("name", sorted(KNOBS))
def test_a_valid_knob_through_a_symlink_runs_the_command(repo, tmp_path, name):
    (repo / ".skills").mkdir()
    (repo / ".skills" / KNOBS[name]).write_text("scripts/stub.sh\n")
    record = tmp_path / "record"
    result = _run(_linked(tmp_path, name), repo, record)
    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text() == "ran\n"
