"""#304 — the ship gate runs the suite the project's own config defines.

Two ways a `uv`-based `pre-ship.sh` ran something else:

1. **`-m "not integration"` replaced the project's marker expression.** A
   command-line `-m` does not intersect with the one in `addopts`, it replaces
   it. CannObserv/power-map's `addopts` says `-m 'not integration and not
   browser'`; the gate's `-m` dropped `not browser` and requested a Playwright
   tier the project documents as run-alone. Power-map had a guard that refused
   (so every ship exited 2 with a message about playwright); without one the
   tier would have run as part of the "unit" suite. Power-map's workaround was
   the fork docs/STYLE.md tells projects not to write.
2. **A bare `uv run`.** A project whose own hook runs `uv run --group seed
   pytest` got a narrower suite from the gate, silently: the group's tests
   `importorskip` at module scope and register as skips.

The fix for (1) passes no `-m` at all. `shipping-work-python-fastapi` loads a
per-run plugin that deselects integration-marked items after pytest has applied
the project's own expression, so pytest itself resolves that expression — from
whichever config file wins its own precedence, and from `PYTEST_ADDOPTS` — and
the result is `not integration and (<project expr>)` with nothing re-parsed.
`shipping-work-python-click` never passed `-m`, so it had nothing to fix there.
The fix for (2) is `.skills/pre-ship-uv-args`, whose arguments go after `uv run`
in every uv call either gate makes.

Everything runs against a stub `uv` on `PATH` that records its argv. The marker
tests have it hand the pytest call to a REAL pytest in a throwaway project, so
what is asserted is which tests ran, not which flags were passed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# The two variants that run their suite through uv.
UV_VARIANTS = ["shipping-work-python-click", "shipping-work-python-fastapi"]
FASTAPI = "shipping-work-python-fastapi"

KNOB = ".skills/pre-ship-uv-args"
TOOLS = ("ruff", "python", "pytest")

# argv recorder and, on request, a hand-off to a real pytest. Written in Python
# so the hand-off can exec this interpreter, which has pytest installed; a
# two-line sh launcher runs it, since a shebang naming a deep venv path can
# outrun the kernel's shebang limit.
STUB_LAUNCHER = '#!/bin/sh\nexec "$STUB_PYTHON" "$0.py" "$@"\n'
STUB_UV = """import json, os, sys
argv = sys.argv[1:]
plugin = None
for d in filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)):
    p = os.path.join(d, "pre_ship_not_integration.py")
    if os.path.exists(p):
        plugin = open(p).read()
with open(os.environ["UV_LOG"], "a") as log:
    log.write(json.dumps({{"argv": argv, "plugin": plugin}}) + "\\n")
tool = next(i for i, a in enumerate(argv) if a in {tools!r})
if argv[tool] == "python" and "import pytest_cov" in argv:
    sys.exit(1)  # pytest-cov absent, so no --no-cov
if argv[tool] == "pytest" and os.environ.get("UV_STUB_REAL_PYTEST"):
    os.execv(sys.executable, [sys.executable, "-m", "pytest", *argv[tool + 1:]])
sys.exit(0)
"""

TIERS = """import os

import pytest


def _ran(name):
    with open(os.environ["RAN_LOG"], "a") as f:
        f.write(name + "\\n")


def test_plain():
    _ran("plain")


@pytest.mark.integration
def test_integration():
    _ran("integration")


@pytest.mark.browser
def test_browser():
    _ran("browser")


@pytest.mark.integration
class TestLive:
    def test_in_class(self):
        _ran("integration-class")
"""

MARKERS_TOML = 'markers = ["integration: live services", "browser: playwright"]\n'
MARKERS_INI = "markers =\n    integration: live services\n    browser: playwright\n"


def _clean_env(project: Path, **extra: str) -> dict:
    """No `GIT_*` (docs/STYLE.md) and no inherited PYTEST_ADDOPTS; the stub
    `uv` first on PATH."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k != "PYTEST_ADDOPTS"
    }
    env["PATH"] = f"{project.parent / 'fakebin'}{os.pathsep}{env.get('PATH', '')}"
    env["UV_LOG"] = str(project.parent / "uv.log")
    env["RAN_LOG"] = str(project.parent / "ran.log")
    env["STUB_PYTHON"] = sys.executable
    env.update(extra)
    return env


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        check=True,
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    # No commit: HEAD does not resolve, so the gate runs pytest unconditionally
    # and writes no per-SHA stamp into /tmp.
    (root / "tests").mkdir()
    (root / "tests" / "test_tiers.py").write_text(TIERS)
    # Click's import check reads this instead of asking uv for [project] name.
    (root / ".skills").mkdir()
    (root / ".skills" / "import-targets").write_text("mypkg\n")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    uv = fakebin / "uv"
    uv.write_text(STUB_LAUNCHER)
    uv.chmod(0o755)
    (fakebin / "uv.py").write_text(STUB_UV.format(tools=TOOLS))
    return root


def _run(variant: str, project: Path, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / "pre-ship.sh")],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=180,
        env=_clean_env(project, **extra),
    )


def _calls(project: Path) -> list[dict]:
    log = project.parent / "uv.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _ran(project: Path) -> set[str]:
    log = project.parent / "ran.log"
    return set(log.read_text().split()) if log.exists() else set()


def _uv_args(argv: list[str]) -> list[str]:
    """What sat between `run` and the tool."""
    assert argv[0] == "run", argv
    tool = next(i for i, a in enumerate(argv) if a in TOOLS)
    return argv[1:tool]


# ---------------------------------------------------------------------------
# The marker: the project's expression survives, integration stays excluded
# ---------------------------------------------------------------------------

# Every place pytest reads addopts from, each carrying the project's own
# `not browser`. pytest picks the file; the gate never reads any of them.
CONFIGS = {
    "pyproject-string": (
        "pyproject.toml",
        "[tool.pytest.ini_options]\n"
        "addopts = \"-v -m 'not integration and not browser'\"\n" + MARKERS_TOML,
    ),
    "pyproject-list": (
        "pyproject.toml",
        "[tool.pytest.ini_options]\n"
        'addopts = ["-v", "-m", "not integration and not browser"]\n' + MARKERS_TOML,
    ),
    "pytest.ini": (
        "pytest.ini",
        "[pytest]\naddopts = -m 'not integration and not browser'\n" + MARKERS_INI,
    ),
    "tox.ini": (
        "tox.ini",
        "[pytest]\naddopts = -m 'not integration and not browser'\n" + MARKERS_INI,
    ),
    "setup.cfg": (
        "setup.cfg",
        "[tool:pytest]\naddopts = -m 'not integration and not browser'\n" + MARKERS_INI,
    ),
}


@pytest.mark.parametrize("config", sorted(CONFIGS))
def test_the_projects_own_marker_expression_survives(
    config: str, project: Path
) -> None:
    """The power-map repro. Under `-m "not integration"` the browser tier ran."""
    name, body = CONFIGS[config]
    (project / name).write_text(body)
    r = _run(FASTAPI, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, (
        f"{config}: the project's addopts excludes the browser tier, and the "
        f"gate ran {sorted(_ran(project))}. A command-line -m replaces the "
        "project's marker expression; it must be intersected with instead "
        "(#304)."
    )


def test_the_first_config_pytest_finds_is_the_one_honoured(project: Path) -> None:
    """pytest.ini outranks pyproject.toml in pytest's own precedence. The gate
    defers to that rather than re-implementing it."""
    (project / "pytest.ini").write_text(
        "[pytest]\naddopts = -m 'not integration and not browser'\n" + MARKERS_INI
    )
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-v"\n' + MARKERS_TOML
    )
    r = _run(FASTAPI, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, sorted(_ran(project))


@pytest.mark.parametrize(
    "addopts",
    ["", "-m 'not browser'"],
    ids=["no-project-marker", "marker-that-never-names-integration"],
)
def test_integration_tests_stay_excluded(addopts: str, project: Path) -> None:
    """What `-m "not integration"` was for, kept: with no project marker, and
    with one that does not mention integration at all."""
    (project / "pyproject.toml").write_text(
        f'[tool.pytest.ini_options]\naddopts = "{addopts}"\n' + MARKERS_TOML
    )
    r = _run(FASTAPI, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    ran = _ran(project)
    assert not {"integration", "integration-class"} & ran, (
        f"integration-marked tests ran under the ship gate: {sorted(ran)}"
    )
    assert "plain" in ran
    if not addopts:
        assert "browser" in ran, "nothing asked for the browser tier to go"


def test_pytest_addopts_is_honoured_too(project: Path) -> None:
    """PYTEST_ADDOPTS carries a marker the config file does not; pytest applies
    it, and the gate still removes integration on top."""
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = ""\n' + MARKERS_TOML
    )
    r = _run(
        FASTAPI,
        project,
        UV_STUB_REAL_PYTEST="1",
        PYTEST_ADDOPTS="-m 'not browser'",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, sorted(_ran(project))


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_no_marker_expression_reaches_the_command_line(
    variant: str, project: Path
) -> None:
    r = _run(variant, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    pytest_calls = [c for c in _calls(project) if "pytest" in c["argv"]]
    assert pytest_calls, f"{variant}: pytest never ran: {_calls(project)}"
    for call in pytest_calls:
        assert "-m" not in call["argv"], (
            f"{variant} passed -m to pytest ({call['argv']}), which replaces "
            "the project's own marker expression (#304)."
        )


def test_the_plugin_is_loaded_and_is_the_one_written(project: Path) -> None:
    r = _run(FASTAPI, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    (call,) = [c for c in _calls(project) if "pytest" in c["argv"]]
    argv = call["argv"]
    assert argv[argv.index("-p") + 1] == "pre_ship_not_integration", argv
    assert call["plugin"] and 'get_closest_marker("integration")' in call["plugin"], (
        "pytest was told to load pre_ship_not_integration, but no such module "
        f"was on its PYTHONPATH: {call}"
    )
    assert "-x" in argv, argv


# ---------------------------------------------------------------------------
# .skills/pre-ship-uv-args
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_no_knob_means_a_bare_uv_run(variant: str, project: Path) -> None:
    r = _run(variant, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    calls = _calls(project)
    assert {c["argv"][1] for c in calls} >= {"ruff", "pytest"}, calls
    for call in calls:
        assert _uv_args(call["argv"]) == [], call["argv"]


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_the_knob_reaches_every_uv_call(variant: str, project: Path) -> None:
    """Comments, blank and whitespace-only lines skipped; several arguments to
    a line; order kept. Every call, so the pytest-cov probe (fastapi) and the
    import check (click) see the environment pytest will run in."""
    (project / KNOB).write_text(
        "# power-map's own hook: uv run --group seed pytest\n"
        "\n"
        "   \n"
        "--group   seed\n"
        "  # indented comment\n"
        "--extra dev"
    )
    r = _run(variant, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    calls = _calls(project)
    tools = {t for c in calls for t in TOOLS if t in c["argv"]}
    assert {"ruff", "python", "pytest"} <= tools, (
        f"{variant}: expected ruff, a python check and pytest; saw {calls}"
    )
    for call in calls:
        assert _uv_args(call["argv"]) == ["--group", "seed", "--extra", "dev"], (
            f"{variant}: {KNOB} did not reach this uv call: {call['argv']}"
        )


@pytest.mark.parametrize("variant", UV_VARIANTS)
@pytest.mark.parametrize("shape", ["directory", "dangling-symlink"])
def test_an_unusable_knob_stops_the_gate(
    variant: str, shape: str, project: Path
) -> None:
    """Present but unusable is exit 2 — the gate's infra code — never a quiet
    fall back to a bare `uv run`, which is the narrower suite #304 is about."""
    knob = project / KNOB
    if shape == "directory":
        knob.mkdir()
    else:
        knob.symlink_to(project / "no-such-target")
    r = _run(variant, project)
    assert r.returncode == 2, (
        f"{variant}: an unusable {KNOB} ({shape}) gave exit {r.returncode}.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert KNOB in r.stderr, r.stderr
    assert _calls(project) == [], (
        f"{variant} ran uv before rejecting the knob: {_calls(project)}"
    )


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_help_documents_the_knob(variant: str) -> None:
    r = subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / "pre-ship.sh"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert KNOB in r.stdout, r.stdout
    assert '-m "not integration"' not in r.stdout, (
        f"{variant} --help still describes the -m that replaced the project's "
        "marker expression"
    )
