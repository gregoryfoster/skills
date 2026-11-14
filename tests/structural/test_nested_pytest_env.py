"""A pytest that a test starts keeps out of the outer run's way (#554).

Seven test files start a real pytest, directly or through a real
`pre-ship.sh`. Each such run inherits the outer gate's environment, and three
things in it belong to the outer run alone: its temp root, its `PYTEST_*`
variables (`PYTEST_ADDOPTS` among them), and its xdist workers.
`tests/utils/nested_pytest.py` builds the inner run's environment; each case
here runs a real nested pytest from it and checks one of the three.
"""

import getpass
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.utils.nested_pytest import nested_pytest_env

REPO = Path(__file__).resolve().parents[2]


def _git_free() -> dict[str, str]:
    """No inherited GIT_* (docs/STYLE.md, #189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _case(tmp_path: Path, body: str) -> Path:
    case = tmp_path / "case"
    case.mkdir()
    (case / "pytest.ini").write_text("[pytest]\n")
    (case / "test_case.py").write_text(textwrap.dedent(body))
    return case


def _pytest(case: Path, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(case),
            *extra,
            str(case),
        ],
        cwd=str(case),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def test_a_nested_run_never_sweeps_the_callers_temp_root(tmp_path):
    """The caller's root holds four finished runs' trees, unlocked, as a
    finished gate leaves them. A pytest that made its own numbered tree there
    would, at exit, delete every one but the newest three, its own included:
    so pytest-1 and pytest-2 would go. They must all survive, and the inner
    run's tmp_path must sit under the calling test's own."""
    shared = tmp_path / "callers-tmp"
    root = shared / f"pytest-of-{getpass.getuser()}"
    root.mkdir(parents=True, mode=0o700)
    finished = [root / f"pytest-{n}" for n in range(1, 5)]
    for tree in finished:
        tree.mkdir()
        (tree / "evidence").write_text("a failed test's files\n")
    where = tmp_path / "inner-tmp-path"
    case = _case(
        tmp_path,
        f"""\
        def test_uses_tmp_path(tmp_path):
            (tmp_path / "f").write_text("x")
            open({str(where)!r}, "w").write(str(tmp_path))
        """,
    )
    env = nested_pytest_env(tmp_path, {**_git_free(), "TMPDIR": str(shared)})
    r = _pytest(case, env)
    assert r.returncode == 0, r.stdout + r.stderr
    gone = [tree.name for tree in finished if not tree.exists()]
    assert not gone, (
        f"a nested pytest swept the caller's temp root and deleted {gone}: "
        "it made its numbered tree beside the caller's, not under the calling "
        "test's tmp_path"
    )
    inner = Path(where.read_text()).resolve()
    assert inner.is_relative_to(tmp_path.resolve()), inner
    assert not inner.is_relative_to(shared.resolve()), inner


def test_a_nested_run_never_writes_the_outer_runs_junit_file(tmp_path):
    """An outer run with `--junitxml=<f>` in PYTEST_ADDOPTS starts a nested
    pytest whose one test fails, as #554's set R report saw. `<f>` is the
    outer run's own until it exits: absent while it runs, and naming only the
    outer run's test after."""
    junit = tmp_path / "outer.xml"
    inner_case = tmp_path / "inner"
    inner_case.mkdir()
    (inner_case / "pytest.ini").write_text("[pytest]\n")
    (inner_case / "test_inner.py").write_text("def test_inner_fails():\n    assert 0\n")
    outer_case = _case(
        tmp_path,
        f"""\
        import os
        import subprocess
        import sys

        from tests.utils.nested_pytest import nested_pytest_env


        def test_outer(tmp_path):
            inner = {str(inner_case)!r}
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 "--rootdir", inner, inner],
                capture_output=True,
                text=True,
                env=nested_pytest_env(tmp_path),
            )
            assert r.returncode == 1, r.stdout + r.stderr
            assert not os.path.exists({str(junit)!r}), (
                "the nested run wrote the outer run's JUnit file mid-run"
            )
        """,
    )
    env = nested_pytest_env(tmp_path, _git_free())
    env["PYTEST_ADDOPTS"] = f"--junitxml={junit}"
    env["PYTHONPATH"] = str(REPO)
    r = _pytest(outer_case, env)
    assert r.returncode == 0, r.stdout + r.stderr
    report = junit.read_text()
    assert 'name="test_outer"' in report, report
    assert "test_inner_fails" not in report, report


def test_a_nested_run_takes_no_workers_and_no_outer_worker_identity(tmp_path):
    """The caller is an outer xdist worker: it carries PYTEST_XDIST_WORKER and
    a worker budget. An inner `-n auto` (or a gate that sizes its own pool from
    PYTEST_XDIST_AUTO_NUM_WORKERS) must run in-process, and nothing in it may
    believe it is the outer worker: tests/utils/gate_trace.py names its trace
    file from PYTEST_XDIST_WORKER."""
    seen = tmp_path / "seen"
    case = _case(
        tmp_path,
        f"""\
        import os


        def test_where_am_i():
            open({str(seen)!r}, "w").write(
                os.environ.get("PYTEST_XDIST_WORKER", "in-process")
            )
        """,
    )
    base = {
        **_git_free(),
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "3",
        "PYTEST_XDIST_WORKER": "gw7",
        "PYTEST_XDIST_WORKER_COUNT": "8",
    }
    r = _pytest(case, nested_pytest_env(tmp_path, base), "-n", "auto")
    assert r.returncode == 0, r.stdout + r.stderr
    assert seen.read_text() == "in-process", (
        f"the nested run's test ran as {seen.read_text()!r}: it took workers "
        "of its own, or inherited the outer worker's identity"
    )
