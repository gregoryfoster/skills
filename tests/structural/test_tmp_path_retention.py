"""A passing run leaves no `tmp_path` tree behind (#554).

At `8f2dbfae` one full gate left 1,171,144 KB and 404,097 entries in its
`$TMPDIR/pytest-of-<user>/pytest-N`. pytest kept it until some later pytest,
any pytest on the host, swept it at exit, inside whatever test that pytest was
running. Under `tmp_path_retention_policy = "failed"` each passing test's
`tmp_path` goes at its own teardown, in the worker that ran it, and a passing
session removes its whole tree at the end; a failing test's tree stays for
inspection. The count stays at pytest's default of 3, because several gates
share one host's root: a lower count would sweep a sibling gate's failures
sooner. `-o tmp_path_retention_policy=all` keeps everything for one run, so
this reads the file, not the session.
"""

from pathlib import Path

import tomllib

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_suite_keeps_only_failed_tests_tmp_paths():
    options = tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"]["ini_options"]
    policy = options.get("tmp_path_retention_policy", "all")
    assert policy == "failed", (
        f"tmp_path_retention_policy is {policy!r}: a green gate leaves its "
        "whole tmp_path tree for a later pytest to sweep (#554)"
    )
    assert "tmp_path_retention_count" not in options, (
        "keep pytest's default count of 3: gates share the host's root"
    )
