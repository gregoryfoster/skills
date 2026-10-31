"""The one gate against the variant gates it replaces, case by case (#537 step 7).

Each case builds a repo in one stack's shape, runs the variant's
`pre-ship.sh` and the unified `shipping-work/scripts/pre-ship.sh` under the
same fakes (tests/structural/gate_fakes.py), and reduces each run to its exit
class (0, 1, 2) and the set of checks it invoked. Every difference between
the two must be listed in EXPECTED with the row of the Step 5 table
(skills/shipping-work/references/gate-topology.md) that decided it — and
every listed difference must still occur, so the table cannot go stale.

This file goes when the variants do (release 2). Until then it is what makes
"the unified gate does what the variants did, except where we decided
otherwise" a checked claim rather than a hope.

No API calls; a fresh repo per case, named uniquely because the variants
keep their stamps in /tmp under the repo's basename.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.structural.gate_fakes import fake_env

SKILLS = Path(__file__).resolve().parents[2] / "skills"
UNIFIED = SKILLS / "shipping-work" / "scripts" / "pre-ship.sh"


def _git(repo: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _python(repo: Path, dep: str) -> None:
    _write(
        repo,
        "pyproject.toml",
        f'[project]\nname = "demo-app"\ndependencies = ["{dep}"]\n',
    )
    _write(repo, "uv.lock", "version = 1\n")
    _write(repo, "src/demo_app/__init__.py", "")
    _write(repo, "tests/test_x.py", "def test_x(): pass\n")


def _php(repo: Path) -> None:
    _write(repo, "composer.json", "{}\n")
    _write(repo, "index.php", "<?php echo 1;\n")
    _write(repo, "themes/site/composer.json", "{}\n")
    _write(repo, "themes/site/functions.php", "<?php\n")


def _npm(repo: Path) -> None:
    _write(
        repo,
        "package.json",
        json.dumps({"scripts": {"lint:js": "eslint", "test:js": "jest"}}),
    )


FIXTURES = {
    "fastapi": ("shipping-work-python-fastapi", lambda r: _python(r, "fastapi")),
    "click": ("shipping-work-python-click", lambda r: _python(r, "click")),
    "php": ("shipping-work-php", _php),
    "fastapi+npm": (
        "shipping-work-python-fastapi",
        lambda r: (_python(r, "fastapi"), _npm(r)),
    ),
    "php+npm": ("shipping-work-php", lambda r: (_php(r), _npm(r))),
}

PY_ENV = {"FAKE_COV": "1"}
SCENARIOS = {
    "pass": {"FAKE_COMPOSER_TEST": "1"},
    "ruff fails": {"FAKE_FAIL": "ruff check"},
    "pytest fails": {"FAKE_PYTEST_RC": "1"},
    "no tests": {"FAKE_PYTEST_RC": "5"},
    "php -l fails": {"FAKE_FAIL": "-l index.php", "FAKE_COMPOSER_TEST": "1"},
    "composer test fails": {"FAKE_FAIL": "composer test", "FAKE_COMPOSER_TEST": "1"},
    "npm lint fails": {"FAKE_FAIL": "lint:js", "FAKE_COMPOSER_TEST": "1"},
}

CASES = [
    ("fastapi", "pass"),
    ("fastapi", "ruff fails"),
    ("fastapi", "pytest fails"),
    ("fastapi", "no tests"),
    ("click", "pass"),
    ("click", "ruff fails"),
    ("click", "pytest fails"),
    ("php", "pass"),
    ("php", "php -l fails"),
    ("php", "composer test fails"),
    ("fastapi+npm", "pass"),
    ("fastapi+npm", "ruff fails"),
    ("fastapi+npm", "npm lint fails"),
    ("php+npm", "npm lint fails"),
]

# (case) -> {(side, event): Step 5 row}. "+" only the unified gate does it,
# "-" only the variant did; ("exit", "<old>-><new>") an exit class change.
# No case changes its exit class, and the PHP variant's behaviour survives
# whole: none of its cases appears here.

# Rows 7 and 10: the import check now runs in a FastAPI repo (its package is
# in the tree, so the guarded guess runs), and -x is gone.
_FASTAPI = {("+", "import demo_app"): "7", ("-", "pytest -x"): "10"}
# Rows 6, 8, 11, 12, 13: the click variant ran no format check, handed pytest
# its test dirs, ran -v, and neither deselected integration tests nor
# passed --no-cov.
_CLICK = {
    ("+", "ruff format"): "6",
    ("-", "pytest given test dirs"): "8",
    ("-", "pytest -v"): "11",
    ("+", "pytest deselects integration"): "12",
    ("+", "pytest --no-cov"): "13",
}
# Row 22: a Python variant stopped at its first failing check (set -e); the
# unified gate runs every check, then fails naming each.
_AFTER_RUFF = {
    ("+", e): "22"
    for e in (
        "ruff format",
        "import demo_app",
        "pytest",
        "pytest deselects integration",
        "pytest --no-cov",
    )
}

EXPECTED: dict[tuple[str, str], dict[tuple[str, str], str]] = {
    ("fastapi", "pass"): _FASTAPI,
    ("fastapi", "ruff fails"): _AFTER_RUFF,
    ("fastapi", "pytest fails"): _FASTAPI,
    ("fastapi", "no tests"): _FASTAPI,
    ("click", "pass"): _CLICK,
    ("click", "ruff fails"): _AFTER_RUFF,
    ("click", "pytest fails"): _CLICK,
    ("fastapi+npm", "pass"): _FASTAPI,
    ("fastapi+npm", "ruff fails"): {
        **_AFTER_RUFF,
        ("+", "npm lint:js"): "22",
        ("+", "npm test:js"): "22",
    },
    ("fastapi+npm", "npm lint fails"): {**_FASTAPI, ("+", "npm test:js"): "22"},
}


def _events(log: Path, repo: Path) -> set[str]:
    """What a run did, as checks: tool calls reduced to what they verify."""
    out = set()
    root = os.path.realpath(repo)
    if not log.exists():
        return out
    for line in log.read_text().splitlines():
        cwd, tool, *argv = json.loads(line)
        if argv[:1] == ["--version"]:
            continue
        if tool == "uv" and argv[:1] == ["run"]:
            rest = argv[1:]
            i = next(i for i, a in enumerate(rest) if a in ("ruff", "python", "pytest"))
            t, targs = rest[i], rest[i + 1 :]
            if t == "ruff":
                out.add(f"ruff {targs[0]}")
            elif t == "python" and targs[:1] == ["-c"]:
                code = targs[1]
                if code.startswith("import ") and code not in (
                    "import pytest_cov",
                    "import xdist",
                ):
                    out.add(code)
            elif t == "pytest":
                out.add("pytest")
                for flag in ("-x", "-v", "--no-cov"):
                    if flag in targs:
                        out.add(f"pytest {flag}")
                if "pre_ship_not_integration" in targs:
                    out.add("pytest deselects integration")
                if any(a.endswith("/") for a in targs):
                    out.add("pytest given test dirs")
        elif tool == "composer" and "validate" in argv:
            wd = next(
                (a.split("=", 1)[1] for a in argv if a.startswith("--working-dir=")),
                None,
            )
            if wd is None:
                rel = os.path.relpath(os.path.realpath(cwd), root)
                wd = rel
            out.add(f"composer validate {wd}")
        elif tool == "composer" and argv[:1] == ["test"]:
            out.add("composer test")
        elif tool == "php" and argv[:1] == ["-l"]:
            out.add(f"php -l {argv[1]}")
        elif tool == "npm" and argv[:1] == ["run"]:
            out.add(f"npm {argv[1]}")
    return out


def _exit_class(rc: int) -> int:
    return rc if rc in (0, 2) else 1


@pytest.fixture
def repo(tmp_path: Path):
    name = f"parity-{uuid.uuid4().hex[:12]}"
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    yield repo
    for stale in Path("/tmp").glob(f"{name}-tests-clean-*"):
        stale.unlink()


def _observe(gate: Path, repo: Path, env: dict, tag: str) -> tuple[int, set[str]]:
    log = repo.parent / f"{tag}.log"
    run_env = fake_env(
        repo.parent / "fakebin",
        repo.parent / f"{tag}-plain.log",
        TOOL_CWD_LOG=str(log),
        **env,
    )
    result = subprocess.run(
        ["bash", str(gate)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=run_env,
        timeout=120,
    )
    assert result.returncode != 2, f"{tag} gate hit a tooling failure:\n{result.stderr}"
    return _exit_class(result.returncode), _events(log, repo)


def observe_case(repo: Path, fixture: str, scenario: str):
    variant, build = FIXTURES[fixture]
    build(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    env = {**PY_ENV, **SCENARIOS[scenario]}
    old = _observe(SKILLS / variant / "scripts" / "pre-ship.sh", repo, env, "old")
    new = _observe(UNIFIED, repo, env, "new")
    diff: dict[tuple[str, str], str] = {}
    if old[0] != new[0]:
        diff[("exit", f"{old[0]}->{new[0]}")] = "?"
    for event in new[1] - old[1]:
        diff[("+", event)] = "?"
    for event in old[1] - new[1]:
        diff[("-", event)] = "?"
    return old, new, diff


@pytest.mark.parametrize(("fixture", "scenario"), CASES, ids=" / ".join)
def test_every_difference_is_a_decided_one(repo, fixture, scenario):
    old, new, diff = observe_case(repo, fixture, scenario)
    expected = EXPECTED.get((fixture, scenario), {})
    assert set(diff) == set(expected), (
        f"{fixture} / {scenario}: the unified gate differs from "
        f"{FIXTURES[fixture][0]} in ways the Step 5 table does not decide, or "
        "a listed difference no longer occurs.\n"
        f"  old: exit {old[0]}, {sorted(old[1])}\n"
        f"  new: exit {new[0]}, {sorted(new[1])}\n"
        f"  unexpected: {sorted(set(diff) - set(expected))}\n"
        f"  no longer occurring: {sorted(set(expected) - set(diff))}"
    )


def test_every_cited_row_is_a_row_of_the_table():
    """A difference is explained only by a row that exists."""
    table = (SKILLS / "shipping-work" / "references" / "gate-topology.md").read_text()
    cited = {row for diffs in EXPECTED.values() for row in diffs.values()}
    missing = sorted(r for r in cited if f"\n| {r} |" not in table)
    assert not missing, f"EXPECTED cites rows the table does not have: {missing}"


def test_every_expected_case_is_run():
    assert set(EXPECTED) <= set(CASES), sorted(set(EXPECTED) - set(CASES))
