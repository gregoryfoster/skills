"""doc-check.sh and pre-ship.sh run through a consumer's symlinks (CR 1865).

`managing-skills`' local-overrides.md recommends an override that symlinks
each script it does not change into the vendored submodule, so a link to
`doc-check.sh` or `pre-ship.sh` sits in a directory with no `detect-stack.sh`
beside it. Both took their directory from `dirname "$0"` without following
the link: doc-check.sh then lost detect-stack.sh, and with it the framework
watch list, silently (a FastAPI `alembic/versions/` change passed), and
pre-ship.sh exited 2. Both now follow the chain, as run-pre-restart.sh does
(CR 1841).

Two layouts, from a consumer that holds nothing beside the link:

- `per-script`: consumer/skills/shipping-work/scripts/<name> ->
  ../../../hop/<name> -> the real script, absolute. Two hops.
- `dir-link prefix`: run as consumer/.claude/skills/shipping-work/scripts/<name>,
  where .claude/skills/shipping-work -> ../../skills/shipping-work, and the
  per-script link -> ../../../skills-vendor/o-r/skills/shipping-work/scripts/
  <name>, a real file in the vendored tree. The link's `..` crosses the
  directory link. A logical `cd` resolves `..` by spelling, and bash falls
  back to the physical path only when the spelled one is missing, so a decoy
  directory sits at the spelled path: only `cd -P` lands beside the script.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.structural.gate_fakes import fake_env
from tests.utils.skill_loader import SKILLS_DIR

SKILL = SKILLS_DIR / "shipping-work"
LAYOUTS = ["per-script", "dir-link prefix"]


def _env() -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    )


def _linked(tmp_path: Path, name: str, layout: str) -> Path:
    """The path a consumer runs `name` by, in `layout`."""
    consumer = tmp_path / "consumer"
    scripts = consumer / "skills" / "shipping-work" / "scripts"
    scripts.mkdir(parents=True)
    link = scripts / name
    if layout == "per-script":
        hop = consumer / "hop"
        hop.mkdir()
        (hop / name).symlink_to(SKILL / "scripts" / name)
        link.symlink_to(Path("..", "..", "..", "hop", name))
        run = link
    else:
        vendored = consumer / "skills-vendor" / "o-r" / "skills"
        vendored.mkdir(parents=True)
        (vendored / "shipping-work").symlink_to(SKILL)
        link.symlink_to(
            Path("..", "..", "..", "skills-vendor", "o-r", "skills")
            / "shipping-work"
            / "scripts"
            / name
        )
        dot = consumer / ".claude" / "skills"
        dot.mkdir(parents=True)
        (dot / "shipping-work").symlink_to(Path("..", "..", "skills", "shipping-work"))
        decoy = consumer / ".claude" / "skills-vendor" / "o-r" / "skills"
        (decoy / "shipping-work" / "scripts").mkdir(parents=True)
        run = dot / "shipping-work" / "scripts" / name
    assert run.resolve() == (SKILL / "scripts" / name).resolve()
    assert not (run.parent / "detect-stack.sh").exists()
    return run


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    return repo


@pytest.mark.parametrize("layout", LAYOUTS)
def test_doc_check_keeps_the_framework_watch_list(tmp_path, layout):
    """The reviewer's case: a FastAPI service changes alembic/versions/,
    which only the fastapi watch list names. Through the link it passed."""
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("x\n")
    (repo / "README.md").write_text("x\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "svc"\ndependencies = ["fastapi>=0.110"]\n'
    )
    (repo / "uv.lock").write_text("version = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "checkout", "-q", "-b", "work")
    (repo / "alembic" / "versions").mkdir(parents=True)
    (repo / "alembic" / "versions" / "0001_init.py").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "migration")
    result = subprocess.run(
        ["bash", str(_linked(tmp_path, "doc-check.sh", layout)), "--base", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "alembic/versions/0001_init.py" in result.stdout
    assert "route table" in result.stdout


@pytest.mark.parametrize("layout", LAYOUTS)
def test_pre_ship_finds_its_helpers(tmp_path, layout):
    """detect-stack.sh, gate-workers.sh and gate-stamp.sh are found beside
    the link's target, so an npm repo's gate runs instead of exiting 2."""
    repo = _repo(tmp_path)
    (repo / "package.json").write_text('{"scripts": {"lint:js": "eslint ."}}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    env = fake_env(tmp_path / "fakebin", tmp_path / "tools.log", GATE_STAMP="off")
    result = subprocess.run(
        ["bash", str(_linked(tmp_path, "pre-ship.sh", layout))],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Detected: toolchain npm" in result.stdout
