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

The fix for (1) passes no `-m` at all. The gate (first in
`shipping-work-python-fastapi`, now in the unified `shipping-work`) loads a
per-run plugin that deselects integration-marked items after pytest has applied
the project's own expression, so pytest itself resolves that expression — from
whichever config file wins its own precedence, and from `PYTEST_ADDOPTS` — and
the result is `not integration and (<project expr>)` with nothing re-parsed.
`shipping-work-python-click` never passed `-m`, so it had nothing to fix there.
The fix for (2) is `.skills/pre-ship-uv-args`, whose arguments go after `uv run`
in every uv call either gate makes in the project. The one call outside it, the
`[project]`-name probe, runs `--no-project` and syncs nothing (#553).

Everything runs against a stub `uv` on `PATH` that records its argv. The marker
tests have it hand the pytest call to a REAL pytest in a throwaway project, so
what is asserted is which tests ran, not which flags were passed.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# The gates that run their suite through uv. The click and fastapi variants
# were two more until #537's release 2 deleted them; the unified gate held
# every property they did before they went.
UV_VARIANTS = ["shipping-work"]
# The gates that run the project's suite with integration tests deselected
# by plugin.
DESELECTING = ["shipping-work"]

KNOB = ".skills/pre-ship-uv-args"
TOOLS = ("ruff", "python", "pytest")

# argv recorder and, on request, a hand-off to a real pytest. Written in Python
# so the hand-off can exec this interpreter, which has pytest installed; a
# two-line sh launcher runs it, since a shebang naming a deep venv path can
# outrun the kernel's shebang limit.
STUB_LAUNCHER = '#!/bin/sh\nexec "$STUB_PYTHON" "$0.py" "$@"\n'
STUB_UV = """import json, os, sys
argv = sys.argv[1:]
if argv == ["--version"]:  # the unified gate's stamp key asks; not a uv run
    print("uv 0.0.0-stub")
    sys.exit(0)
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
    # The unified gate runs uv's checks only in a repo uv manages: a
    # pyproject.toml with a uv.lock. This one has no pytest table, so it is
    # no config candidate, and a test that writes its own replaces it.
    (root / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
    (root / "uv.lock").write_text("version = 1\n")
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


@pytest.mark.parametrize("gate", DESELECTING)
@pytest.mark.parametrize("config", sorted(CONFIGS))
def test_the_projects_own_marker_expression_survives(
    config: str, gate: str, project: Path
) -> None:
    """The power-map repro. Under `-m "not integration"` the browser tier ran."""
    name, body = CONFIGS[config]
    (project / name).write_text(body)
    r = _run(gate, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, (
        f"{config}: the project's addopts excludes the browser tier, and the "
        f"gate ran {sorted(_ran(project))}. A command-line -m replaces the "
        "project's marker expression; it must be intersected with instead "
        "(#304)."
    )


@pytest.mark.parametrize("gate", DESELECTING)
def test_the_first_config_pytest_finds_is_the_one_honoured(
    gate: str, project: Path
) -> None:
    """pytest.ini outranks pyproject.toml in pytest's own precedence. The gate
    defers to that rather than re-implementing it."""
    (project / "pytest.ini").write_text(
        "[pytest]\naddopts = -m 'not integration and not browser'\n" + MARKERS_INI
    )
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-v"\n' + MARKERS_TOML
    )
    r = _run(gate, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, sorted(_ran(project))


@pytest.mark.parametrize(
    "addopts",
    ["", "-m 'not browser'"],
    ids=["no-project-marker", "marker-that-never-names-integration"],
)
@pytest.mark.parametrize("gate", DESELECTING)
def test_integration_tests_stay_excluded(
    addopts: str, gate: str, project: Path
) -> None:
    """What `-m "not integration"` was for, kept: with no project marker, and
    with one that does not mention integration at all."""
    (project / "pyproject.toml").write_text(
        f'[tool.pytest.ini_options]\naddopts = "{addopts}"\n' + MARKERS_TOML
    )
    r = _run(gate, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    ran = _ran(project)
    assert not {"integration", "integration-class"} & ran, (
        f"integration-marked tests ran under the ship gate: {sorted(ran)}"
    )
    assert "plain" in ran
    if not addopts:
        assert "browser" in ran, "nothing asked for the browser tier to go"


@pytest.mark.parametrize("gate", DESELECTING)
def test_pytest_addopts_is_honoured_too(gate: str, project: Path) -> None:
    """PYTEST_ADDOPTS carries a marker the config file does not; pytest applies
    it, and the gate still removes integration on top."""
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = ""\n' + MARKERS_TOML
    )
    r = _run(
        gate,
        project,
        UV_STUB_REAL_PYTEST="1",
        PYTEST_ADDOPTS="-m 'not browser'",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert _ran(project) == {"plain"}, sorted(_ran(project))


@pytest.mark.parametrize("gate", DESELECTING)
def test_a_config_pytest_cannot_read_fails_the_gate(gate: str, project: Path) -> None:
    """The gate reads no config, so it cannot silently drop a marker it failed
    to read: pytest reads it, and refuses (a usage error, exit 4) — which the
    gate passes through as a failure, having run nothing."""
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-m 'not browser'\n"
    )
    r = _run(gate, project, UV_STUB_REAL_PYTEST="1")
    assert r.returncode not in (0, 5), (
        f"an unparseable pytest config passed the gate (exit {r.returncode})"
    )
    assert _ran(project) == set(), sorted(_ran(project))
    assert "Pre-ship checks passed." not in r.stdout


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


@pytest.mark.parametrize("gate", DESELECTING)
def test_the_plugin_is_loaded_and_is_the_one_written(gate: str, project: Path) -> None:
    r = _run(gate, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    (call,) = [c for c in _calls(project) if "pytest" in c["argv"]]
    argv = call["argv"]
    assert argv[argv.index("-p") + 1] == "pre_ship_not_integration", argv
    assert call["plugin"] and 'get_closest_marker("integration")' in call["plugin"], (
        "pytest was told to load pre_ship_not_integration, but no such module "
        f"was on its PYTHONPATH: {call}"
    )
    assert "-x" not in argv, argv  # the unified gate drops -x (Step 5 row 10)


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
def test_a_crlf_knob_reaches_uv_without_its_carriage_returns(
    variant: str, project: Path
) -> None:
    """A knob saved with Windows line endings. `read -r -a` splits on IFS
    whitespace, which does not include `\\r`, so `--group seed\\r\\n` used to
    reach uv as `seed\\r` and a blank CRLF line as an argument of its own — a
    uv error about a group nobody wrote, with the cause invisible in the
    terminal."""
    (project / KNOB).write_bytes(
        b"# power-map's own hook\r\n\r\n--group   seed\r\n  # indented\r\n--extra dev\r"
    )
    r = _run(variant, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    calls = _calls(project)
    assert calls, f"{variant}: uv never ran"
    for call in calls:
        assert _uv_args(call["argv"]) == ["--group", "seed", "--extra", "dev"], (
            f"{variant}: a CRLF {KNOB} reached uv with its carriage returns: "
            f"{call['argv']}"
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


# A pytest command line that excludes a tier with its own `-m "… not …"`. That
# `-m` replaces the project's addopts expression rather than narrowing it, so
# advice to run one reintroduces #304 by hand — whether `not` leads the
# expression or sits inside it (`unit and not integration`, `(not integration)`).
# Selecting a tier on purpose (`-m integration`) is a different request and is
# not matched.
EXCLUDING_MARKER = re.compile(r"pytest[^`\n]*\s-m\s*[\"'][^\"'\n]*\bnot\b")

# The process log records commands as they were run, in sessions that predate
# #304; telling a record to "drop the -m" would falsify it (CR 57).
RECORDS = "references/process-log/"


@pytest.mark.parametrize(
    "line",
    [
        'uv run pytest -m "not integration" tests/x.py',
        "uv run pytest -m 'not integration'",
        'uv run pytest -m"not integration"',
        'python -m pytest -m "not integration"',
        'uv run pytest -m "unit and not integration"',
        'uv run pytest -m "(not integration)"',
    ],
)
def test_the_pattern_catches_every_tier_exclusion(line: str) -> None:
    assert EXCLUDING_MARKER.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        "uv run pytest -m integration",
        'uv run pytest -m "integration or smoke"',
        "uv run pytest tests/ -x",
        "python -m pytest --markers",
    ],
)
def test_the_pattern_leaves_selection_alone(line: str) -> None:
    assert not EXCLUDING_MARKER.search(line), line


def test_no_skill_tells_the_reader_to_replace_the_projects_marker() -> None:
    """reviewing-code-python-fastapi advised `uv run pytest -m "not
    integration" <specific-test>` for a targeted run during review. On
    CannObserv/power-map, pointed at a directory, that runs the browser tier
    the project's `not integration and not browser` excludes. Measured with
    pytest here: addopts `-m 'not integration and not browser'` plus a
    command-line `-m "not integration"` ran the browser-marked test."""
    offenders = [
        f"{p.relative_to(SKILLS_DIR)}:{n}: {m.group(0)}…"
        for p in sorted(SKILLS_DIR.glob("**/*.md"))
        if RECORDS not in p.relative_to(SKILLS_DIR).as_posix()
        for n, line in enumerate(p.read_text().splitlines(), 1)
        for m in EXCLUDING_MARKER.finditer(line)
    ]
    assert not offenders, (
        "these recommend a pytest command line whose -m replaces the "
        "project's own marker expression (#304); drop the -m, since the "
        "project's addopts already excludes what it excludes:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# #553: the [project]-name probe, the one uv call that is not uv_run
# ---------------------------------------------------------------------------
#
# With no `.skills/import-targets`, `detect-import-targets.sh` asks uv for the
# `[project]` name. It is shared byte for byte with reviewing-code-python-click,
# which has no args file, so it cannot call `uv_run`. It runs `uv run
# --no-project` instead: the probe parses pyproject.toml with stdlib tomllib and
# needs no project environment, and with no project there is no sync and no
# group set to disagree with the rest of the gate's. Measured on uv 0.11.8:
# `--group seed` beside `--no-project` warns that it "has no effect", and the
# probe leaves no `.venv` or `uv.lock` behind.

# The words that keep a `uv run` from syncing the project, so it may skip the
# args file.
NO_PROJECT = "--no-project"


@pytest.mark.parametrize("variant", UV_VARIANTS)
def test_without_import_targets_every_uv_call_carries_the_knob_or_no_project(
    variant: str, project: Path
) -> None:
    """#553's reproduction, CannObserv/power-map#739's consumer test
    (`tests/sh/pre_ship.bats`, "our uv args reach every uv call"): the args file
    says `--group seed`, and no `uv run` the gate makes may lack it. That repo
    commits `.skills/import-targets`, which is what kept the bare probe from
    running there; without it, the probe was a `uv run` with neither the args
    nor `--no-project`, a project sync against a different group set.

    Green is the call carrying the args, or `--no-project` and nothing else: a
    call that syncs no project has no group set to disagree with. power-map's
    test as written admits only the first, so it would still flag the probe if
    that repo dropped its import-targets file."""
    (project / ".skills" / "import-targets").unlink()
    (project / KNOB).write_text("--group seed\n")
    r = _run(variant, project)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    calls = _calls(project)
    probes = [c for c in calls if any("tomllib" in a for a in c["argv"])]
    assert probes, f"{variant}: the [project]-name probe never ran: {calls}"
    tools = {t for c in calls for t in TOOLS if t in c["argv"]}
    assert {"ruff", "python", "pytest"} <= tools, calls
    for call in calls:
        assert _uv_args(call["argv"]) in (["--group", "seed"], [NO_PROJECT]), (
            f"{variant}: a uv call with neither {KNOB}'s words nor "
            f"{NO_PROJECT}: {call['argv']}"
        )
    for call in probes:
        assert _uv_args(call["argv"]) == [NO_PROJECT], call["argv"]


# The copies of the resolver: the gate's and the click review skill's, held
# byte-equal by test_content_invariants.py.
RESOLVERS = ["shipping-work", "reviewing-code-python-click"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
@pytest.mark.parametrize("variant", RESOLVERS)
def test_the_probe_syncs_no_project(variant: str, tmp_path: Path) -> None:
    """Against the real uv. The project's one dependency does not exist, so any
    resolve or sync fails, and offline it fails without the network: a bare
    `uv run` exits non-zero there, and the resolver exits 2. With
    `--no-project` the probe never resolves, reads the name, and leaves no
    `.venv` or `uv.lock` behind. The interpreter is pinned to this one (3.11+,
    so tomllib) so the test does not depend on what else is installed."""
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        check=True,
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "my-pkg"\nversion = "0"\n'
        'dependencies = ["no-such-package-skills-553"]\n\n'
        '[dependency-groups]\nseed = ["no-such-package-skills-553-seed"]\n'
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "UV_", "VIRTUAL_ENV", "CONDA_"))
    }
    env.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", UV_PYTHON=sys.executable)
    r = subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / "detect-import-targets.sh")],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert r.stdout == "my_pkg\n", f"stdout={r.stdout!r}\nstderr={r.stderr}"
    left = sorted(p.name for p in root.iterdir() if p.name != ".git")
    assert left == ["pyproject.toml"], f"the probe synced the project: {left}"


# ---------------------------------------------------------------------------
# No gate script runs `uv run` around uv_run, unless it syncs no project
# ---------------------------------------------------------------------------
#
# "The gate's scripts" is every `*.sh` in shipping-work's scripts directory:
# pre-ship.sh and every helper it can run, since a skill's scripts reach no
# other skill's (test_skill_scripts_stay_in_their_skill.py). That includes
# detect-import-targets.sh, and so, by byte-equality, the click review skill's
# copy. Not reviewing-code-python-click's gather-context.sh or detect-test-dirs.sh:
# review context, run informationally, and no args file applies to them. Not
# the repo-root scripts/: this repo's own gate, which reads no args file and
# runs no `uv run`.

GATE_SCRIPTS_DIR = SKILLS_DIR / "shipping-work" / "scripts"

UV_RUN_WRAPPER = re.compile(r"uv_run\b")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
UV_RUN_DEFINITION = re.compile(r"^\s*uv_run\(\)\s*\{")

# uv's global options that take a value as the next word, so `uv --directory
# run sync` is `uv sync`. `--python` is not global on uv 0.11.8, which refuses
# it before `run`, but a newer uv that takes it must not hide a `run`.
UV_VALUE_OPTIONS = frozenset(
    {
        "--directory",
        "--project",
        "--python",
        "--config-file",
        "--cache-dir",
        "--color",
        "--allow-insecure-host",
    }
)
# A variable that holds uv: `UV=uv`, `UV=/path/to/uv`, `UV=$(command -v uv)`
# with or without a redirection after it, `UV=${UV:-uv}`, optionally declared
# `local`, `readonly` and the like. An unquoted value ends where bash ends a
# word, so `UV=uv;` and `then UV=uv; fi` hold `uv` (CR 1869).
UV_VAR_ASSIGNMENT = re.compile(
    r"(?:^|[\s;&|(])(?:(?:local|declare|typeset|readonly|export)\s+(?:-\w+\s+)*)?"
    r"([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|\$\([^)]*\)|[^\s;&|()<>`]+)"
)
# `command -v uv`, `which uv` or `type -P uv` in a substitution, anything
# after the name inside it (`2>/dev/null`) allowed, never `uvx`.
UV_LOOKUP = r"\$\(\s*(?:command\s+-v|which|type\s+-P)\s+uv(?:\s[^)]*)?\)"
UV_VALUE = re.compile(rf"(?:\S*/)?uv|{UV_LOOKUP}|\$\{{[A-Za-z_]\w*:?[-=](?:\S*/)?uv\}}")
# The lookup itself as the command word: `"$(command -v uv)" run x`.
UV_LOOKUP_WORD = re.compile(rf"(\"?){UV_LOOKUP}\1(?=[\s;&|()<>`]|$)")
VAR_WORD = re.compile(r"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})")
WORD_END = " \t;&|()<>`"


def _word(line: str, j: int) -> tuple[str, str, int] | None:
    """The shell word at `j`: `(as written, quotes removed, end)`, or None at
    an operator or the end of the line."""
    start, value = j, []
    while j < len(line) and line[j] not in WORD_END:
        c = line[j]
        if c in "\"'":
            close = line.find(c, j + 1)
            if close < 0:
                return None
            value.append(line[j + 1 : close])
            j = close + 1
        elif c == "\\":
            value.append(line[j + 1 : j + 2])
            j += 2
        else:
            value.append(c)
            j += 1
    if j == start:
        return None
    return line[start:j], "".join(value), j


def _uv_vars(text: str) -> set[str]:
    """The names this file assigns uv to."""
    out = set()
    for m in UV_VAR_ASSIGNMENT.finditer(text):
        value = m.group(2)
        if value[:1] in "\"'" and value[-1:] == value[:1]:
            value = value[1:-1]
        if UV_VALUE.fullmatch(value):
            out.add(m.group(1))
    return out


def _uv_run_at(line: str, j: int, uv_vars: set[str]) -> int | None:
    """Where `uv … run` ends, when one starts at `j`: `uv` bare, quoted, by
    path or through a variable holding it, then global options (consuming the
    values of UV_VALUE_OPTIONS), then `run`. `uv` may also be `\\uv` or a
    lookup that prints its path, `$(command -v uv)`."""
    lookup = UV_LOOKUP_WORD.match(line, j)
    if lookup:
        j = lookup.end()
    else:
        first = _word(line, j)
        if first is None:
            return None
        raw, value, j = first
        var = VAR_WORD.fullmatch(raw.strip('"'))
        if not (value == "uv" or (var and (var.group(1) or var.group(2)) in uv_vars)):
            return None
    takes_value = False
    while True:
        while j < len(line) and line[j] in " \t":
            j += 1
        word = _word(line, j)
        if word is None:
            return None
        _, value, j = word
        if takes_value:
            takes_value = False
        elif value.startswith("-"):
            takes_value = value in UV_VALUE_OPTIONS
        else:
            return j if value == "run" else None


def _code_uv_runs(
    text: str, pattern: re.Pattern | None = None
) -> list[tuple[int, str]]:
    """Every `uv run` (or `pattern`) bash would execute: `(line number, rest of
    the line)`.

    A small quote-aware scan. It skips comments, single- and double-quoted
    strings (so `--help` text and error messages), and heredoc bodies, and it
    descends into `$(…)` wherever that appears, quoted or not, since a command
    substitution runs. A `\\` that ends a line outside a comment or a
    single-quoted string joins the next line, as bash does, and the joined
    line is scanned again from the state it started in; the number is the
    first line's. `uv run` is matched by _uv_run_at."""
    found: list[tuple[int, str]] = []
    lines = text.splitlines()
    uv_vars = _uv_vars(text)
    stack = ["code"]  # code | sub (inside $(…)) | paren | dq | sq | ansi
    heredoc: list[tuple[str, bool]] = []  # (delimiter, strip tabs)
    i = 0
    while i < len(lines):
        line, extra = lines[i], 0
        saved = (list(stack), len(found), list(heredoc))
        j = 0
        while j < len(line):
            top = stack[-1]
            c = line[j]
            if top in ("sq", "ansi"):
                if top == "ansi" and c == "\\":
                    j += 2
                    continue
                if c == "'":
                    stack.pop()
                j += 1
                continue
            if c == "\\" and j == len(line) - 1 and i + extra + 1 < len(lines):
                # A continuation: join, and scan the whole line again.
                extra += 1
                line = line[:j] + lines[i + extra]
                stack, heredoc = list(saved[0]), list(saved[2])
                del found[saved[1] :]
                j = 0
                continue
            # Outside "…", a word starts here: bash would run it. Checked
            # before `\` and `$(` are stepped over, so `\uv run` and
            # `$(command -v uv) run` are seen (CR 1869). A `#` is no word.
            if (
                top != "dq"
                and c != "#"
                and (j == 0 or not (line[j - 1].isalnum() or line[j - 1] in "_-"))
            ):
                if pattern is None:
                    end = _uv_run_at(line, j, uv_vars)
                else:
                    m = pattern.match(line, j)
                    end = m.end() if m else None
                if end is not None:
                    found.append((i + 1, line[end:]))
                    j = end
                    continue
            if c == "\\":
                j += 2
                continue
            if line.startswith("$(", j):
                stack.append("sub")
                j += 2
                continue
            if top == "dq":
                if c == '"':
                    stack.pop()
                j += 1
                continue
            # code, sub or paren: bash would run what is here.
            if c == "#" and (j == 0 or line[j - 1] in " \t;&|("):
                break
            if line.startswith("$'", j):
                stack.append("ansi")
                j += 2
                continue
            if c == "'":
                stack.append("sq")
            elif c == '"':
                stack.append("dq")
            elif c == "(" and top in ("sub", "paren"):
                stack.append("paren")
            elif c == ")" and top in ("sub", "paren"):
                stack.pop()
            elif line.startswith("<<", j) and not line.startswith("<<<", j):
                m = HEREDOC.match(line, j)
                if m:
                    heredoc.append((m.group(2), line.startswith("<<-", j)))
                    j = m.end()
                    continue
            j += 1
        i += 1 + extra
        for delimiter, strip in heredoc:
            while i < len(lines):
                body = lines[i].lstrip("\t") if strip else lines[i]
                i += 1
                if body == delimiter:
                    break
        heredoc = []
    return found


def _carries_no_project(rest: str) -> bool:
    """`--no-project` among the options between `uv run` and the command."""
    for word in rest.split():
        if not word.startswith("-"):
            return False
        if word == NO_PROJECT:
            return True
    return False


@pytest.mark.parametrize(
    "src,expected",
    [
        ("uv run ruff check .\n", [1]),
        ('x=$(uv run python -c "print(1)")\n', [1]),
        ('x="$(uv run python --version)"\n', [1]),
        ("foo && uv run pytest\n", [1]),
        ("if ! uv run pytest; then :; fi\n", [1]),
        ('echo "run uv run ruff"\n', []),
        ("echo 'uv run ruff'\n", []),
        ("# uv run ruff\n", []),
        ("x=1 # uv run ruff\n", []),
        ("cat <<'PY'\nuv run ruff\nit's\nPY\nuv run pytest\n", [5]),
        ('echo "a\nuv run b\n"\nuv run c\n', [4]),
        ('echo "${x#y} uv run"\n', []),
        ("my_uv run\n", []),
        # CR 1845: global options before `run`, a continuation, a quoted uv,
        # and a variable holding it all still run `uv run`.
        ("uv -q run pytest\n", [1]),
        ("uv --quiet run pytest\n", [1]),
        ("uv --directory sub run pytest\n", [1]),
        ("uv --directory=sub run pytest\n", [1]),
        ('uv --project "my dir" -v run pytest\n', [1]),
        ("uv --config-file u.toml --cache-dir c --color never run x\n", [1]),
        ("uv \\\n  run pytest\n", [1]),
        ("uv -q \\\n  --directory sub \\\n  run pytest\nuv run x\n", [1, 4]),
        ("foo && \\\n  uv run pytest\n", [1]),
        ('"uv" run pytest\n', [1]),
        ("'uv' run pytest\n", [1]),
        ("command uv run pytest\n", [1]),
        ("/usr/local/bin/uv run pytest\n", [1]),
        ('UV=uv\n"$UV" run pytest\n', [2]),
        ("UV=$(command -v uv)\n${UV} -q run pytest\n", [2]),
        ('local uv_bin="/opt/uv"\n"${uv_bin}" run x\n', [2]),
        # CR 1869: an assignment a `;` ends, one inside `then … fi`, a lookup
        # with a redirection (patching-hosts' probe.sh idiom), a default
        # expansion, the lookup as the command word, and an escaped uv.
        ('UV=uv; "$UV" run x\n', [1]),
        ('if true; then UV=uv; fi\n"$UV" run x\n', [2]),
        ('UV=$(command -v uv 2>/dev/null)\n"$UV" run x\n', [2]),
        (
            '[ -n "$uvb" ] || uvb=$(command -v uv 2>/dev/null) || uvb=""\n'
            '"$uvb" run x\n',
            [2],
        ),
        ('UV=${UV:-uv}\n"$UV" run x\n', [2]),
        ("UV=${UV:=/opt/bin/uv}\n$UV -q run x\n", [2]),
        ('"$(command -v uv)" run x\n', [1]),
        ("$(command -v uv 2>/dev/null) run x\n", [1]),
        ('x=1; "$(which uv)" --quiet run x\n', [1]),
        ("\\uv run x\n", [1]),
        ("foo && \\uv run x\n", [1]),
        # ... and these do not.
        ('UV=${UV:-uvx}\n"$UV" run x\n', []),
        ('"$(command -v uvx)" run x\n', []),
        ('UV=uv;\n"$OTHER" run x\n', []),
        ('echo "$(command -v uv) run x"\n', []),
        ("uv --directory run sync\n", []),
        ("uv tool run ruff\n", []),
        ("uv sync --frozen\n", []),
        ('"uv run" x\n', []),
        ('echo "uv \\\n run"\n', []),
        ("# uv \\\nuv run x\n", [2]),
        ('UV=1\n"$UV" run x\n', []),
        ('"$NPM" run lint:js\n', []),
    ],
)
def test_the_scan_finds_what_bash_would_run(src: str, expected: list[int]) -> None:
    assert [n for n, _ in _code_uv_runs(src)] == expected


def test_no_gate_uv_run_bypasses_uv_run() -> None:
    """#553: every `uv run` the gate makes goes through `uv_run`, which inserts
    `.skills/pre-ship-uv-args`, or carries `--no-project`, which syncs no
    project and so has no group set to disagree with. The probe at
    detect-import-targets.sh:76 was a bare `uv run`."""
    scripts = sorted(GATE_SCRIPTS_DIR.glob("*.sh"))
    assert GATE_SCRIPTS_DIR / "pre-ship.sh" in scripts, scripts
    definitions, wrapped, unwrapped, offenders = [], [], [], []
    for path in scripts:
        text = path.read_text()
        lines = text.splitlines()
        wrapped += [
            f"{path.name}:{n}"
            for n, _ in _code_uv_runs(text, UV_RUN_WRAPPER)
            if not UV_RUN_DEFINITION.match(lines[n - 1])
        ]
        for n, rest in _code_uv_runs(text):
            where = f"{path.relative_to(SKILLS_DIR)}:{n}"
            if UV_RUN_DEFINITION.match(lines[n - 1]):
                definitions.append(where)
            elif _carries_no_project(rest):
                unwrapped.append(where)
            else:
                offenders.append(f"{where}: uv run{rest}")
    # Not vacuous: the scan has to see the wrapper, the calls through it, and
    # the probe that carries --no-project.
    assert len(definitions) == 1, definitions
    assert definitions[0].startswith("shipping-work/scripts/pre-ship.sh:"), (
        f"uv_run is defined outside pre-ship.sh: {definitions}"
    )
    assert len(wrapped) >= 7, f"too few uv_run call sites found: {wrapped}"
    assert not offenders, (
        "these `uv run` calls bypass uv_run, so .skills/pre-ship-uv-args never "
        "reaches them, and they sync the project (#553). Call uv_run, or add "
        f"{NO_PROJECT} if the call needs no project environment:\n  "
        + "\n  ".join(offenders)
    )
    assert "shipping-work/scripts/detect-import-targets.sh" in " ".join(unwrapped), (
        f"the [project]-name probe's --no-project call was not found: {unwrapped}"
    )
