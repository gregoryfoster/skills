"""#531 — a docs-only check runs on a host without Linux tools.

The ship gate runs on the operator's Mac, where a test that needs GNU
coreutils and tar skips (`maintaining_host_disk_rig.require_linux_tools`). A
module-wide `linux_tools` mark skipped the module's docs-only checks along with
the tests that drive the GC's scripts, so an edit dropping the advice they
guard would pass the gate.

This runs each such module on a PATH holding none of those tools, as on the
Mac: the docs-only class must pass while the script-driving tests skip. The
skip is the control that the PATH really hid the tools, so the check means the
same on a Linux runner as on the Mac.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

# Module, and the class in it that reads only docs.
DOCS_ONLY = [("test_maintaining_host_disk_bytecode.py", "TestTheDocsSayIt")]


@pytest.mark.parametrize("module, docs_class", DOCS_ONLY)
def test_the_docs_checks_run_without_linux_tools(tmp_path, module, docs_class):
    empty = tmp_path / "bin"
    empty.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = str(empty)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"tests/structural/{module}",
            "-v",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=300,
    )
    outcomes = re.findall(
        r"^(\S+::\S+) (PASSED|SKIPPED|FAILED|ERROR|XFAIL|XPASS)\b", result.stdout, re.M
    )
    docs = [o for nodeid, o in outcomes if f"::{docs_class}::" in nodeid]
    others = [o for nodeid, o in outcomes if f"::{docs_class}::" not in nodeid]
    assert docs and set(docs) == {"PASSED"}, result.stdout[-3000:]
    assert others and set(others) == {"SKIPPED"}, (
        "with no Linux tools on PATH the script-driving tests must skip, or "
        "this proves nothing about a Mac\n" + result.stdout[-3000:]
    )
