"""`scripts/pre-ship.sh` normalizes its delegates' exit codes, and does not lie.

This repo's ship gate wraps three scripts that disagree about what a code
means: `structural-tests.sh` exits 1 for both "no usable .venv" and "pytest
failed", `python-lint.sh` reserves 3 for a ruff-version mismatch, and
`measure-context.sh --gate` uses 4 for over-budget. Propagating that union
would make the gate's own `--help` block unwritable
([#318](https://github.com/gregoryfoster/skills/issues/318)), so it collapses
them: **1 = a gate found something, 2 = a gate could not run**.

A mapping is exactly the kind of thing that reads correct and behaves wrong, so
it is pinned by execution against fake delegates rather than by grepping the
`case` arms.

The one worth naming is pytest's **5**. "Collected no tests" is how a broken
conftest, a bad rootdir or a renamed directory reports success while verifying
nothing; `structural-tests.sh` passes 5 through unchanged for that reason, and
a wrapper that folded it into 0 — or into 1, where it would read as an ordinary
test failure — would undo the care taken one level down. It must surface as 2.

No API calls; every delegate here is a three-line stub.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "pre-ship.sh"

_FAKE = """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--check" ]]; then exit "${FAKE_PREFLIGHT:-0}"; fi
exit "${%s:-0}"
"""


def _project(tmp_path: Path) -> Path:
    """A throwaway repo holding the real gate and fake delegates.

    GIT_DIR is scrubbed: git exports it to every hook process, and from a
    linked worktree it is absolute, so `git -C <tmp> init` under a pre-commit
    hook would otherwise address the real repository (docs/STYLE.md).
    """
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "pre-ship.sh").write_text(GATE.read_text())
    (scripts / "structural-tests.sh").write_text(_FAKE % "FAKE_SUITE")
    (scripts / "python-lint.sh").write_text(_FAKE % "FAKE_LINT")
    measure = tmp_path / "skills" / "curating-context" / "scripts"
    measure.mkdir(parents=True)
    (measure / "measure-context.sh").write_text(_FAKE % "FAKE_BUDGET")
    for p in list(scripts.glob("*.sh")) + list(measure.glob("*.sh")):
        p.chmod(0o755)
    return tmp_path


def _run(project: Path, **fakes: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    env.update(fakes)
    return subprocess.run(
        ["bash", "scripts/pre-ship.sh"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_all_green_is_zero(tmp_path):
    r = _run(_project(tmp_path))
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "all gates passed" in r.stdout


@pytest.mark.parametrize(
    ("fakes", "expected", "why"),
    [
        ({"FAKE_BUDGET": "4"}, 1, "AGENTS.md over budget is a finding"),
        ({"FAKE_LINT": "1"}, 1, "ruff findings are a finding"),
        ({"FAKE_SUITE": "1"}, 1, "test failures are a finding"),
        ({"FAKE_PREFLIGHT": "1"}, 2, "no usable .venv: nothing was verified"),
        ({"FAKE_PREFLIGHT": "2"}, 2, "preflight tooling failure"),
        ({"FAKE_LINT": "3"}, 2, "ruff version mismatch: the gate did not run"),
        ({"FAKE_LINT": "2"}, 2, "lint tooling failure"),
        ({"FAKE_SUITE": "5"}, 2, "pytest collected NO tests — never a pass"),
        ({"FAKE_SUITE": "127"}, 2, "pytest missing from the venv"),
        ({"FAKE_BUDGET": "2"}, 2, "budget gate could not run"),
    ],
)
def test_delegate_codes_are_normalized(tmp_path, fakes, expected, why):
    r = _run(_project(tmp_path), **fakes)
    assert r.returncode == expected, (
        f"{fakes} should normalize to {expected} ({why}); got {r.returncode}.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_nothing_collected_is_not_reported_as_a_test_failure(tmp_path):
    """5 must not be flattened into 1 either.

    A 1 reads as "the suite ran and something failed", which sends the operator
    to look for a broken test. The actual state is that nothing ran at all, and
    the message has to say so or the diagnosis is confidently wrong — the same
    failure shape #252 found in doc-check.sh's empty path list.
    """
    r = _run(_project(tmp_path), FAKE_SUITE="5")
    assert r.returncode == 2
    assert "collected NO tests" in r.stderr, r.stderr
    assert "not a pass" in r.stderr.lower(), r.stderr


def test_a_missing_delegate_is_infra_not_a_pass(tmp_path):
    project = _project(tmp_path)
    (project / "scripts" / "python-lint.sh").unlink()
    r = _run(project)
    assert r.returncode == 2, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "missing delegate" in r.stderr, r.stderr


def test_the_first_failing_gate_stops_the_run(tmp_path):
    """Fail-fast, matching .pre-commit-config.yaml: a later gate must not run."""
    r = _run(_project(tmp_path), FAKE_BUDGET="4", FAKE_SUITE="1")
    assert r.returncode == 1
    assert "Gate 3/3" not in r.stdout, (
        "the suite ran although the budget gate had already failed:\n" + r.stdout
    )
