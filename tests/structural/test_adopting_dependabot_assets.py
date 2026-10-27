"""adopting-dependabot's copyable guard tests, run inside fixture repos (#376).

A guard test that passes on a broken config is the failure it exists to
prevent, so each asset is copied into a throwaway repo, passes there as
shipped, and is then broken the ways the cohort broke it. Watcher mutated its
config seven ways and each failed a guard (CannObserv/watcher#283); the same
seven are here, plus the uv ones from notifier#33 and #103.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

ASSETS = SKILLS_DIR / "adopting-dependabot" / "assets"


def _env() -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def _pytest(root: Path, test: str) -> subprocess.CompletedProcess:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=_env())
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(root),
            test,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=120,
    )


def _adapt(text: str, **constants: str) -> str:
    """Rewrite one ADAPT constant's assignment, the edit an adopter makes."""
    for name, value in constants.items():
        # Up to the next top-level line that isn't a dict's closing brace.
        text, n = re.subn(
            rf"^{name}(:[^=]*)? = .*?(?=^(?!\}})\S)",
            f"{name}\\1 = {value}\n",
            text,
            count=1,
            flags=re.M | re.S,
        )
        assert n == 1, f"no {name} in the ADAPT block"
    return text


# --- test_dependabot.py ------------------------------------------------------------

ACTIONS_CONFIG = """\
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    commit-message:
      prefix: "chore"
"""

CI = """\
on: pull_request
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4.3.0
      - uses: astral-sh/setup-uv@08eba0b27e820071cde6df949e0beb9ba4906955 # v7.1.0
      - uses: ./.github/actions/setup
"""

UV_BLOCK = """\
  - package-ecosystem: "uv"
    directories:
      - "/"
      - "/clients/python"
    schedule:
      interval: "weekly"
    versioning-strategy: increase-if-necessary
    open-pull-requests-limit: 10
    commit-message:
      prefix: "chore"
    groups:
      dev-tools:
        dependency-type: "development"
    ignore:
      - dependency-name: "co-core"
"""


def _dependabot_repo(
    tmp_path: Path, config: str, *, uv: bool = False, sha_pins: bool = True
) -> Path:
    root = tmp_path / "repo"
    files = {
        ".github/dependabot.yml": config,
        ".github/workflows/ci.yml": CI,
        ".github/actions/setup/action.yml": "runs:\n  using: composite\n  steps: []\n",
    }
    if uv:
        files |= {
            "pyproject.toml": '[project]\nname = "x"\nversion = "0"\ndependencies = ["a", "b", "co-core==1"]\n',
            "uv.lock": "version = 1\n",
            "clients/python/pyproject.toml": '[project]\nname = "sdk"\nversion = "0"\ndependencies = ["c"]\n',
            "clients/python/uv.lock": "version = 1\n",
        }
    _write(root, files)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=_env())
    asset = (ASSETS / "test_dependabot.py").read_text()
    adapted = {"SHA_PINS": "True" if sha_pins else "False"}
    if uv:
        adapted |= {
            "ENABLED": '{"github-actions", "uv"}',
            "IGNORED": '{"co-core": "lockstep"}',
        }
    _write(root, {"tests/ci/test_dependabot.py": _adapt(asset, **adapted)})
    return root


ACTIONS_WITH_COMPOSITE = ACTIONS_CONFIG.replace(
    'directory: "/"', 'directories: ["/", "/.github/actions/setup"]'
)


def test_the_actions_guard_passes_as_adapted(tmp_path):
    root = _dependabot_repo(tmp_path, ACTIONS_WITH_COMPOSITE)
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_uv_guard_passes_as_adapted(tmp_path):
    root = _dependabot_repo(tmp_path, ACTIONS_WITH_COMPOSITE + UV_BLOCK, uv=True)
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


ACTIONS_MUTATIONS = {
    "deleted": None,
    "version-1": ACTIONS_WITH_COMPOSITE.replace("version: 2", "version: 1"),
    "mistyped-ecosystem": ACTIONS_WITH_COMPOSITE.replace(
        '"github-actions"', '"github_actions"'
    ),
    "workflows-directory": ACTIONS_WITH_COMPOSITE.replace(
        '["/", ', '["/.github/workflows", '
    ),
    "composite-unscanned": ACTIONS_CONFIG,
    "no-interval": ACTIONS_WITH_COMPOSITE.replace(
        '      interval: "weekly"\n', "      day: monday\n"
    ),
    "limit-fillable": ACTIONS_WITH_COMPOSITE.replace("limit: 10", "limit: 2"),
    "default-limit-fillable": ACTIONS_WITH_COMPOSITE.replace(
        "    open-pull-requests-limit: 10\n", ""
    ),
    "default-subject": ACTIONS_WITH_COMPOSITE.replace(
        '    commit-message:\n      prefix: "chore"\n', ""
    ),
    "unwanted-ecosystem": ACTIONS_WITH_COMPOSITE + UV_BLOCK,
}


@pytest.mark.parametrize("mutation", list(ACTIONS_MUTATIONS))
def test_each_way_the_actions_config_breaks_fails_a_guard(tmp_path, mutation):
    config = ACTIONS_MUTATIONS[mutation]
    root = _dependabot_repo(tmp_path, config or ACTIONS_WITH_COMPOSITE)
    if mutation == "default-limit-fillable":
        # Five distinct actions fill the default limit of 5.
        steps = "".join(
            f"      - uses: acme/a{n}@{'0' * 40} # v1.0.0\n" for n in range(5)
        )
        _write(
            root,
            {
                ".github/workflows/more.yml": f"on: push\njobs:\n  x:\n    runs-on: x\n    steps:\n{steps}"
            },
        )
    if config is None:
        (root / ".github/dependabot.yml").unlink()
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 1, f"{mutation} passed every guard:\n{proc.stdout}"


def test_a_tag_pin_fails_only_when_sha_pins_is_on(tmp_path):
    root = _dependabot_repo(tmp_path, ACTIONS_WITH_COMPOSITE)
    _write(
        root,
        {
            ".github/workflows/ci.yml": CI.replace(
                "@08eba0b27e820071cde6df949e0beb9ba4906955 # v7.1.0", "@v7"
            )
        },
    )
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 1 and "setup-uv@v7" in proc.stdout
    off = _dependabot_repo(tmp_path / "off", ACTIONS_WITH_COMPOSITE, sha_pins=False)
    _write(
        off,
        {
            ".github/workflows/ci.yml": CI.replace(
                "@08eba0b27e820071cde6df949e0beb9ba4906955 # v7.1.0", "@v7"
            )
        },
    )
    assert _pytest(off, "tests/ci/test_dependabot.py").returncode == 0


UV_MUTATIONS = {
    "table-uncovered": UV_BLOCK.replace('      - "/clients/python"\n', ""),
    "default-strategy": UV_BLOCK.replace(
        "    versioning-strategy: increase-if-necessary\n", ""
    ),
    "no-dev-group": UV_BLOCK.replace(
        '        dependency-type: "development"', '        patterns: ["*"]'
    ),
    "lockstep-unignored": UV_BLOCK.replace(
        '      - dependency-name: "co-core"', '      - dependency-name: "other"'
    ),
    # 3 + 1 runtime and one group in each of two directories: 6 can be open at once.
    "limit-fillable": UV_BLOCK.replace("limit: 10", "limit: 6"),
}


@pytest.mark.parametrize("mutation", list(UV_MUTATIONS))
def test_each_way_the_uv_config_breaks_fails_a_guard(tmp_path, mutation):
    root = _dependabot_repo(
        tmp_path, ACTIONS_WITH_COMPOSITE + UV_MUTATIONS[mutation], uv=True
    )
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 1, f"{mutation} passed every guard:\n{proc.stdout}"


def test_a_held_back_ecosystem_fails_with_its_reason(tmp_path):
    root = _dependabot_repo(tmp_path, ACTIONS_WITH_COMPOSITE + UV_BLOCK)
    test = root / "tests/ci/test_dependabot.py"
    test.write_text(
        _adapt(test.read_text(), HELD_BACK='{"uv": "the private wheelhouse (#358)"}')
    )
    proc = _pytest(root, "tests/ci/test_dependabot.py")
    assert proc.returncode == 1 and "the private wheelhouse (#358)" in proc.stdout


# --- test_dependency_imports.py -------------------------------------------------------

# Distributions this suite's own environment has installed, so the sweep can
# read their file lists: pyyaml and packaging are imported, pytest is reached
# by name only, and iniconfig (a pytest dependency) is the stale declaration.
IMPORTS_PYPROJECT = '[project]\nname = "x"\nversion = "0"\ndependencies = [{deps}]\n'
DEPS = '"PyYAML>=6", "packaging", "pytest"'
WITNESSED = '{"pytest": ("deploy/*.service", "pytest -q", "The unit runs the suite.")}'


def _imports_repo(tmp_path: Path, deps: str = DEPS, *, witness: bool = True) -> Path:
    root = tmp_path / "repo"
    _write(
        root,
        {
            "pyproject.toml": IMPORTS_PYPROJECT.format(deps=deps),
            "src/app/__init__.py": "import yaml\nfrom packaging.version import Version\nfrom app import util\n",
            "src/app/util.py": "import json\n",
            "deploy/app.service": "ExecStart=pytest -q\n"
            if witness
            else "ExecStart=app\n",
            "tests/ci/test_dependency_imports.py": _adapt(
                (ASSETS / "test_dependency_imports.py").read_text(),
                NEEDED_WITHOUT_IMPORT=WITNESSED,
            ),
        },
    )
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=_env())
    return root


def test_the_sweep_passes_on_a_clean_manifest(tmp_path):
    proc = _pytest(_imports_repo(tmp_path), "tests/ci/test_dependency_imports.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_declaration_nothing_imports_fails(tmp_path):
    proc = _pytest(
        _imports_repo(tmp_path, DEPS + ', "iniconfig"'),
        "tests/ci/test_dependency_imports.py",
    )
    assert proc.returncode == 1 and "iniconfig" in proc.stdout


def test_an_allowlist_entry_without_its_witness_fails(tmp_path):
    proc = _pytest(
        _imports_repo(tmp_path, witness=False), "tests/ci/test_dependency_imports.py"
    )
    assert proc.returncode == 1 and "pytest -q" in proc.stdout


def test_an_allowlist_entry_no_longer_declared_fails(tmp_path):
    proc = _pytest(
        _imports_repo(tmp_path, '"PyYAML>=6", "packaging"'),
        "tests/ci/test_dependency_imports.py",
    )
    assert proc.returncode == 1 and "no longer declared" in proc.stdout


def test_assets_are_copied_not_imported():
    """Neither asset is collected here: each is a template for another repo."""
    assert shutil.which("git")
    for asset in ASSETS.glob("*.py"):
        assert "ADAPT" in asset.read_text(), f"{asset.name} has no ADAPT block"
