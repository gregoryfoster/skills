"""Fake uv, composer, php, node and npm for the ship-gate tests (#537).

One Python recorder behind a tiny `sh` launcher per tool name (the launcher
dodges the kernel's shebang-length limit). It logs each call to TOOL_LOG as a
JSON list `[tool, *argv]` (and, when TOOL_CWD_LOG is set, `[cwd, tool,
*argv]` there), and fails a call whose command line contains a FAKE_FAIL
substring. Other knobs: FAKE_PYTEST_RC, FAKE_COV, FAKE_XDIST,
FAKE_COMPOSER_TEST, FAKE_COMPOSER_LIST_FAIL, FAKE_VERSION[_<TOOL>],
FAKE_PYTHON_VERSION.

PATH is the fakes plus BASE_PATH only, so a real uv, composer or node on the
host can never answer for a fake that was withheld.

Shared by test_unified_pre_ship.py (the one gate, row by row) and
test_gate_parity.py (the old variant gates against it). Not a test module.
"""

import os
import sys
from pathlib import Path

LAUNCHER = '#!/bin/sh\nexec "$STUB_PYTHON" "$FAKE_DIR/fake.py" "${0##*/}" "$@"\n'

FAKE = r"""import json, os, sys
tool, argv = sys.argv[1], sys.argv[2:]
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write(json.dumps([tool, *argv]) + "\n")
if os.environ.get("TOOL_CWD_LOG"):
    with open(os.environ["TOOL_CWD_LOG"], "a") as log:
        log.write(json.dumps([os.getcwd(), tool, *argv]) + "\n")
line = " ".join([tool, *argv])
fails = [f for f in os.environ.get("FAKE_FAIL", "").split(",") if f]
if argv[:1] == ["--version"]:
    default = os.environ.get("FAKE_VERSION", "1.0")
    print(f"{tool} {os.environ.get('FAKE_VERSION_' + tool.upper(), default)}")
    sys.exit(0)
if tool == "uv":
    rest = argv[1:]
    i = next(i for i, a in enumerate(rest) if a in ("ruff", "python", "pytest"))
    t, targs = rest[i], rest[i + 1:]
    if t == "python" and targs[:1] == ["--version"]:
        print("Python " + os.environ.get("FAKE_PYTHON_VERSION", "3.12.0"))
        sys.exit(0)
    if t == "python" and targs[:1] == ["-c"]:
        code = targs[1]
        if code == "import pytest_cov":
            sys.exit(0 if os.environ.get("FAKE_COV") else 1)
        if code == "import xdist":
            sys.exit(0 if os.environ.get("FAKE_XDIST") else 1)
        if not code.startswith("import "):
            os.execv(sys.executable, [sys.executable, "-c", code])
    if t == "pytest" and not any(f in line for f in fails):
        sys.exit(int(os.environ.get("FAKE_PYTEST_RC", "0")))
if tool == "node":
    data = json.load(open("package.json"))
    if "process.env.SCRIPT" in argv[1]:
        sys.exit(0 if (data.get("scripts") or {}).get(os.environ["SCRIPT"]) else 1)
    sys.exit(0)
if tool == "composer" and argv[:1] == ["run-script"]:
    if os.environ.get("FAKE_COMPOSER_LIST_FAIL"):
        print("composer: could not read composer.json", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FAKE_COMPOSER_TEST"):
        print("  test   Runs the tests")
    sys.exit(0)
sys.exit(1 if any(f in line for f in fails) else 0)
"""

ALL_TOOLS = ("uv", "composer", "php", "node", "npm")

# What follows the fakes on PATH: enough for git, bash and coreutils, and
# nowhere a user-installed uv, composer or node usually lives.
BASE_PATH = "/usr/bin:/bin"


def fake_env(fake_dir: Path, log: Path, tools=ALL_TOOLS, **env: str) -> dict:
    """Install the fakes named in `tools` under `fake_dir`, and return an
    environment that runs them, logging to `log`."""
    fake_dir.mkdir(exist_ok=True)
    (fake_dir / "fake.py").write_text(FAKE)
    for tool in ALL_TOOLS:
        launcher = fake_dir / tool
        if tool in tools:
            launcher.write_text(LAUNCHER)
            launcher.chmod(0o755)
        elif launcher.exists():
            launcher.unlink()
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "GATE_STAMP", "PRE_SHIP_", "PYTEST_"))
        and k not in ("PRE_COMMIT", "PYTHONPATH")
    }
    base.update(
        PATH=f"{fake_dir}:{BASE_PATH}",
        STUB_PYTHON=sys.executable,
        FAKE_DIR=str(fake_dir),
        TOOL_LOG=str(log),
        PYTEST_XDIST_AUTO_NUM_WORKERS="0",
    )
    base.update(env)
    return base
