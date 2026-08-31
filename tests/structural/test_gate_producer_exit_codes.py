"""A gate's producers must fail loudly, not resolve to nothing (#255).

`shipping-work-python-click`'s `pre-ship.sh` delegates two questions to helper
scripts — which package to import-check, and which directories hold the tests —
and captures each helper's exit code carefully, because (its own comment) *"a
missing helper or a broken pyproject.toml must not silently degrade to 'no
tests, skip pytest'."*

Both helpers defeated that from the inside. Each ran `uv run python -c …` under
a `|| true` (one of them inside a `done < <(…)` besides), so a `uv` that could
not run at all — no venv, a resolution failure — produced an empty list and
exit 0. `pre-ship.sh` then printed *"No tests directory found … Skipping
pytest"* and shipped a commit having run none.

The text gate in `test_content_invariants.py` catches the process-substitution
spelling. This file pins the behaviour, because the second spelling (`… ||
true` straight to stdout) is invisible to it, and because the distinction that
matters is at runtime: **an empty answer and an unanswerable question must not
look the same to the caller.**

Everything here runs against a fake `uv` on `PATH`; no venv, no network, no
real resolver.
"""

import os
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Both copies are held byte-equal by TestPythonClickHelperByteEquality; the
# parametrization runs the behaviour against each so a future divergence
# cannot quietly relax the shipping-side one.
VARIANTS = ["shipping-work-python-click", "reviewing-code-python-click"]

# A resolver that cannot run, versus one that runs and answers nothing.
UV_BROKEN = '#!/bin/sh\necho "error: no interpreter found for the project" >&2\nexit 2\n'
UV_SILENT = "#!/bin/sh\nexit 0\n"


def _clean_env(project: Path, **extra: str) -> dict:
    """Strip `GIT_*` (docs/STYLE.md) and put the fake `uv` first on PATH."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = f"{project / 'fakebin'}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra)
    return env


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "fakebin").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        check=True, capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "my-pkg"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["integration"]\n'
    )
    return root


def _fake_uv(project: Path, body: str) -> None:
    uv = project / "fakebin" / "uv"
    uv.write_text(body)
    uv.chmod(0o755)


def _run(variant: str, script: str, project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / script)],
        cwd=str(project), capture_output=True, text=True, timeout=60,
        env=_clean_env(project),
    )


HELPERS = [
    ("detect-test-dirs.sh", "detect-test-dirs"),
    ("detect-import-targets.sh", "detect-import-targets"),
]


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("script,prefix", HELPERS, ids=[h[0] for h in HELPERS])
class TestAnUnanswerableQuestionIsNotAnEmptyAnswer:
    def test_a_resolver_that_cannot_run_exits_two(
        self, variant: str, script: str, prefix: str, project: Path
    ) -> None:
        _fake_uv(project, UV_BROKEN)
        r = _run(variant, script, project)
        assert r.returncode == 2, (
            f"{variant}/{script}: a `uv` that could not run was reported as a "
            f"clean empty answer (exit {r.returncode}). pre-ship.sh skips the "
            "check it feeds when the list is empty, so this ships a gate that "
            f"never ran.\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
        )
        assert r.stdout == "", (
            f"{variant}/{script}: a failed resolver must emit no list at all; "
            f"got {r.stdout!r}"
        )
        assert prefix in r.stderr, (
            f"{variant}/{script}: the failure must name the script that could "
            f"not resolve; got {r.stderr!r}"
        )

    def test_a_resolver_that_answers_nothing_exits_zero(
        self, variant: str, script: str, prefix: str, project: Path
    ) -> None:
        """The other half of the distinction. A project with no `[project]`
        name, or no `testpaths`, is a legitimate empty answer — turning that
        into an error would make the gate unusable on shared libraries."""
        _fake_uv(project, UV_SILENT)
        r = _run(variant, script, project)
        assert r.returncode == 0, (
            f"{variant}/{script}: an empty-but-successful resolution must not "
            f"fail the gate (exit {r.returncode}). stderr={r.stderr!r}"
        )
        assert r.stdout.strip() == "", r.stdout


@pytest.mark.parametrize("variant", VARIANTS)
class TestDetectTestDirsResolution:
    def test_tests_dir_wins_without_consulting_uv(
        self, variant: str, project: Path
    ) -> None:
        """`tests/` short-circuits before any resolver runs, so a broken `uv`
        is irrelevant on the common layout."""
        (project / "tests").mkdir()
        _fake_uv(project, UV_BROKEN)
        r = _run(variant, "detect-test-dirs.sh", project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "tests", r.stdout

    def test_a_testpath_that_is_not_on_disk_is_skipped_not_fatal(
        self, variant: str, project: Path
    ) -> None:
        """`testpaths = ["integration"]` with no `integration/` used to exit 1.

        The loop's status is its body's last command, and `[[ -d … ]] && echo`
        returns 1 when the directory is absent — so under `set -e` the script
        exited 1 and pre-ship.sh reported "detect-test-dirs.sh failed", a
        tooling error where the truth was "that directory is not there".
        """
        _fake_uv(project, '#!/bin/sh\necho integration\n')
        r = _run(variant, "detect-test-dirs.sh", project)
        assert r.returncode == 0, (
            f"{variant}: a testpaths entry that is not on disk was reported as "
            f"a resolver failure (exit {r.returncode}). stderr={r.stderr!r}"
        )
        assert r.stdout.strip() == "", r.stdout

        (project / "integration").mkdir()
        r = _run(variant, "detect-test-dirs.sh", project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "integration", r.stdout


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("script", [h[0] for h in HELPERS])
class TestTheExitCodeIsPublished:
    def test_help_names_the_infra_code(
        self, variant: str, script: str, project: Path
    ) -> None:
        r = subprocess.run(
            ["bash", str(SKILLS_DIR / variant / "scripts" / script), "--help"],
            cwd=str(project), capture_output=True, text=True, timeout=30,
            env=_clean_env(project),
        )
        assert r.returncode == 0, r.stderr
        assert "Exit codes:" in r.stdout and "2" in r.stdout, (
            f"{variant}/{script} --help must publish its exit codes — the "
            "caller branches on them, and 2 now means 'could not run' rather "
            f"than 'nothing found'. Got:\n{r.stdout}"
        )
