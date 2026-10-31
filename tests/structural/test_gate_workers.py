"""`gate-workers.sh` decides how many xdist workers a gate may use (#537, D2).

Resolution, first match wins: PYTEST_XDIST_AUTO_NUM_WORKERS (a coordinator's
per-agent figure), then `.skills/test-workers` (off | auto | a number), then
auto — serial on 2 cores or fewer (every exe.dev VM), otherwise
min(8, cores / (active gates + 1)), with a result under 2 meaning serial.

The core count is faked by a `getconf` earlier on PATH, so these run the same
on a 2-vCPU VM and a 14-core Mac. No API calls; each test gets a fresh repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "gate-workers.sh"


def _clean_env(**extra: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k != "PYTEST_XDIST_AUTO_NUM_WORKERS"
    }
    env.update(extra)
    return env


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_clean_env())
    return repo


def _fake_cores(tmp_path: Path, cores: int) -> str:
    """A PATH whose `getconf` reports `cores`, ahead of the real one."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    getconf = bin_dir / "getconf"
    getconf.write_text(f"#!/bin/sh\necho {cores}\n")
    getconf.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def _run(repo: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(**env),
    )


def _answer(repo: Path, **env: str) -> int:
    result = _run(repo, "--explain", **env)
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


class TestTheCoordinatorsFigureWins:
    def test_it_beats_the_knob(self, repo, tmp_path):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-workers").write_text("off\n")
        assert _answer(repo, PYTEST_XDIST_AUTO_NUM_WORKERS="3") == 3

    def test_a_non_number_is_refused(self, repo):
        result = _run(repo, PYTEST_XDIST_AUTO_NUM_WORKERS="lots")
        assert result.returncode == 2
        assert "not a number" in result.stderr
        assert result.stdout == ""


class TestTheKnob:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("off\n", 0), ("5\n", 5), ("# a comment\n\n  4  \n", 4)],
    )
    def test_it_is_read(self, repo, tmp_path, text, expected):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-workers").write_text(text)
        assert _answer(repo, PATH=_fake_cores(tmp_path, 14)) == expected

    def test_auto_falls_through_to_the_core_count(self, repo, tmp_path):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-workers").write_text("auto\n")
        assert _answer(repo, PATH=_fake_cores(tmp_path, 14)) == 8

    def test_garbage_is_refused_by_name(self, repo):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-workers").write_text("several\n")
        result = _run(repo)
        assert result.returncode == 2
        assert ".skills/test-workers" in result.stderr


class TestAuto:
    @pytest.mark.parametrize(("cores", "expected"), [(1, 0), (2, 0), (3, 3), (14, 8)])
    def test_the_core_count_decides(self, repo, tmp_path, cores, expected):
        assert _answer(repo, PATH=_fake_cores(tmp_path, cores)) == expected

    def test_a_live_gate_takes_its_share(self, repo, tmp_path):
        path = _fake_cores(tmp_path, 14)
        slots = Path(_run(repo, "--slot-dir").stdout.strip())
        (slots / str(os.getpid())).touch()
        assert _answer(repo, PATH=path) == 7

    def test_a_share_under_two_is_serial(self, repo, tmp_path):
        path = _fake_cores(tmp_path, 3)
        slots = Path(_run(repo, "--slot-dir").stdout.strip())
        (slots / str(os.getpid())).touch()
        assert _answer(repo, PATH=path) == 0

    def test_a_dead_gates_slot_is_cleared_not_counted(self, repo, tmp_path):
        path = _fake_cores(tmp_path, 14)
        slots = Path(_run(repo, "--slot-dir").stdout.strip())
        dead = subprocess.Popen(["true"])
        dead.wait()
        stale = slots / str(dead.pid)
        stale.touch()
        assert _answer(repo, PATH=path) == 8
        assert not stale.exists()

    def test_the_reason_is_on_stderr_only(self, repo, tmp_path):
        result = _run(repo, "--explain", PATH=_fake_cores(tmp_path, 2))
        assert result.stdout.strip() == "0"
        assert "serial" in result.stderr


def test_slots_live_in_the_common_dir_shared_by_worktrees(repo):
    slots = Path(_run(repo, "--slot-dir").stdout.strip())
    assert slots == (repo / ".git" / "gate-slots").resolve()
