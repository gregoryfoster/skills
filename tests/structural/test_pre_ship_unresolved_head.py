"""An unresolved HEAD must not become a stamp key.

Both `uv` variants of `pre-ship.sh` skip pytest when `/tmp/<basename>-tests-
clean-<sha>` exists and the tree is clean, and both meant to run pytest
unconditionally, with no stamp, when HEAD does not resolve — their WARN says
exactly that, and the comment above it names the shared-slot poisoning it is
there to prevent.

It did not. On a repository with no commits `git rev-parse HEAD` prints the
name it could not resolve — the literal word `HEAD` — to stdout before exiting
128 (git 2.39.3, measured). The capture kept it, so the WARN printed and the
very next branch read `/tmp/<basename>-tests-clean-HEAD`: the slot every
commit-less checkout of that basename shares. Found when #304's fixtures, all
named `proj`, stopped running pytest after the first one passed.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
UV_VARIANTS = ["shipping-work-python-click", "shipping-work-python-fastapi"]

# Records argv; reports pytest-cov absent so no --no-cov is added; passes
# everything else.
STUB_UV = """#!/bin/sh
printf '%s\\n' "$*" >>"$UV_LOG"
case "$*" in *"import pytest_cov"*) exit 1 ;; esac
exit 0
"""


@pytest.fixture
def project(tmp_path: Path):
    # A basename no other run shares, because the slot under test is /tmp/.
    root = tmp_path / f"proj-{uuid.uuid4().hex[:12]}"
    root.mkdir()
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        check=True,
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    (root / "tests").mkdir()
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "uv").write_text(STUB_UV)
    (fakebin / "uv").chmod(0o755)
    stamp = Path("/tmp") / f"{root.name}-tests-clean-HEAD"
    try:
        yield root, stamp
    finally:
        stamp.unlink(missing_ok=True)


def _run(variant: str, root: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = f"{root.parent / 'fakebin'}{os.pathsep}{env['PATH']}"
    env["UV_LOG"] = str(root.parent / "uv.log")
    return subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / "pre-ship.sh")],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _pytest_ran(root: Path) -> bool:
    log = root.parent / "uv.log"
    return log.exists() and any(
        "pytest" in line.split() for line in log.read_text().splitlines()
    )


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_a_stale_head_stamp_does_not_skip_pytest(variant: str, project) -> None:
    root, stamp = project
    stamp.touch()
    r = _run(variant, root)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "could not resolve HEAD" in r.stderr, r.stderr
    assert _pytest_ran(root), (
        f"{variant} warned it would run pytest unconditionally, then skipped "
        f"it on {stamp} — a stamp keyed on the word HEAD.\nstdout={r.stdout}"
    )


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_a_passing_run_writes_no_head_stamp(variant: str, project) -> None:
    root, stamp = project
    r = _run(variant, root)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _pytest_ran(root), r.stdout
    assert not stamp.exists(), (
        f"{variant} stamped a pass at {stamp}, a slot every commit-less "
        "checkout of this basename would then read as its own."
    )
