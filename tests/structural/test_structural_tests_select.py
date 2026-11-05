"""Under the pre-commit hook, `structural-tests.sh` runs only the impacted tests (#537).

Step 10 of the gate-topology plan, wired:

- a full run that passes (no map yet, a shared change, GATE_SELECT=off, or
  any run outside the hook) is traced, and builds the map under the git
  common dir;
- under PRE_COMMIT=1 with a map, the staged paths decide which test files
  run, through `scripts/gate_select.py`;
- a selected run records no stamp, so pre-ship on the same tree still runs
  the full suite, and logs one line to gate-select.log instead;
- a change the selector cannot map, or a selector that fails, runs the full
  suite, saying why.

pytest is faked: it logs its arguments, and writes a trace record when the
script asks it to trace. No API calls; each test gets a fresh repo.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COPIED = (
    "scripts/structural-tests.sh",
    "scripts/gate_select.py",
    "skills/shipping-work/scripts/gate-stamp.sh",
    "skills/shipping-work/scripts/gate-workers.sh",
)

# Logs argv; under GATE_TRACE, records that test_a depends on skills/a and
# test_b on skills/b, the way the real tracer would.
FAKE_PYTEST = """#!/bin/sh
echo "$*" >> "$FAKE_PYTEST_LOG"
if [ -n "${GATE_TRACE:-}" ]; then
  printf '%s\\n' \\
    '{"file": "tests/structural/test_a.py", "open": ["skills/a/SKILL.md"]}' \\
    '{"file": "tests/structural/test_b.py", "open": ["skills/b/SKILL.md"]}' \\
    > "$GATE_TRACE.main.jsonl"
fi
exit "${FAKE_PYTEST_RC:-0}"
"""


def _env(**extra: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "GATE_", "PRE_COMMIT", "PYTEST_"))
    }
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel in COPIED:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, repo / rel)
    (repo / "tests" / "utils").mkdir(parents=True)
    (repo / "tests" / "utils" / "gate_trace.py").write_text("# stand-in\n")
    for name in ("a", "b"):
        (repo / "skills" / name).mkdir(parents=True)
        (repo / "skills" / name / "SKILL.md").write_text(f"# {name}\n")
        (repo / "tests" / "structural" / f"test_{name}.py").parent.mkdir(
            parents=True, exist_ok=True
        )
        (repo / "tests" / "structural" / f"test_{name}.py").write_text(
            "def test(): pass\n"
        )
    (repo / ".gitignore").write_text(".venv\n")
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text(f'export PATH="{venv_bin}:$PATH"\n')
    (venv_bin / "pytest").write_text(FAKE_PYTEST)
    (venv_bin / "pytest").chmod(0o755)
    (venv_bin / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (venv_bin / "python").chmod(0o755)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _suite(repo: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/structural-tests.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        env=_env(
            FAKE_PYTEST_LOG=str(repo.parent / "pytest.log"),
            PYTEST_XDIST_AUTO_NUM_WORKERS="1",
            **env,
        ),
    )


def _calls(repo: Path) -> list[str]:
    log = repo.parent / "pytest.log"
    return log.read_text().splitlines() if log.exists() else []


def _common(repo: Path) -> Path:
    return repo / ".git"


def _with_map(repo: Path) -> None:
    """A passing full run outside the hook: traced, so it builds the map."""
    r = _suite(repo, GATE_STAMP="off")
    assert r.returncode == 0, r.stderr
    assert (_common(repo) / "gate-map.json").exists(), r.stdout + r.stderr


def _stage(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.read_text() + "x\n" if path.exists() else "x\n")
    _git(repo, "add", rel)


def test_a_full_run_is_traced_and_builds_the_map(repo):
    r = _suite(repo, GATE_STAMP="off")
    assert r.returncode == 0, r.stderr
    (call,) = _calls(repo)
    assert "tests.utils.gate_trace" in call and "tests/structural/" in call
    doc = json.loads((_common(repo) / "gate-map.json").read_text())
    assert doc["tests"]["tests/structural/test_a.py"] == ["skills/a"]


def test_under_the_hook_a_skill_change_runs_its_tests_only(repo):
    _with_map(repo)
    _stage(repo, "skills/a/SKILL.md")
    r = _suite(repo, PRE_COMMIT="1")
    assert r.returncode == 0, r.stderr
    call = _calls(repo)[-1]
    assert "tests/structural/test_a.py" in call
    assert "test_b.py" not in call and "tests/structural/ " not in call + " "
    assert "gate_trace" not in call, "a selected run builds no map"
    assert "selected 1/2" in r.stdout, r.stdout


def test_a_selected_run_records_no_stamp_but_logs_a_line(repo):
    _with_map(repo)
    _stage(repo, "skills/a/SKILL.md")
    assert _suite(repo, PRE_COMMIT="1").returncode == 0
    _git(repo, "commit", "-q", "-m", "change a")
    r = _suite(repo)
    assert "already passed" not in r.stdout, "pre-ship reused a selected run"
    assert "tests/structural/" in _calls(repo)[-1].split()
    log = (_common(repo) / "gate-select.log").read_text().splitlines()
    assert len(log) == 1 and log[0].split("\t")[2:4] == ["1", "2"], log


def test_gate_select_off_runs_everything(repo):
    _with_map(repo)
    _stage(repo, "skills/a/SKILL.md")
    _suite(repo, PRE_COMMIT="1", GATE_SELECT="off")
    assert "tests/structural/" in _calls(repo)[-1].split()


def test_a_shared_change_runs_everything_and_says_why(repo):
    _with_map(repo)
    _stage(repo, "tests/utils/gate_trace.py")
    r = _suite(repo, PRE_COMMIT="1")
    assert "tests/structural/" in _calls(repo)[-1].split()
    assert "full suite" in r.stdout and "tests/utils/gate_trace.py" in r.stdout


def test_an_unreadable_map_runs_everything(repo):
    _with_map(repo)
    (_common(repo) / "gate-map.json").write_text("{not json")
    _stage(repo, "skills/a/SKILL.md")
    r = _suite(repo, PRE_COMMIT="1")
    assert "tests/structural/" in _calls(repo)[-1].split()
    assert "gate_select.py failed" in r.stderr, r.stderr


def test_outside_the_hook_nothing_is_selected(repo):
    _with_map(repo)
    _stage(repo, "skills/a/SKILL.md")
    _git(repo, "commit", "-q", "-m", "change a")
    _suite(repo, GATE_STAMP="off")
    assert "tests/structural/" in _calls(repo)[-1].split()


def test_a_failing_full_run_builds_no_map(repo):
    r = _suite(repo, GATE_STAMP="off", FAKE_PYTEST_RC="1")
    assert r.returncode == 1
    assert not (_common(repo) / "gate-map.json").exists()
