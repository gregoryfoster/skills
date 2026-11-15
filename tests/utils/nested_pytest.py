"""The environment for a pytest that a test starts, directly or through a script (#554).

A nested pytest inherits the outer run's environment, and three things in it
belong to the outer run alone. `nested_pytest_env` takes them out:

- **Every `PYTEST_*` variable.** `PYTEST_ADDOPTS` carries the outer run's
  flags: a `--junitxml=<f>` there had each nested run rewrite `<f>` mid-gate
  with its own result, a `-q` cancels the `-v` a caller parses, a `-n` hands
  it workers. xdist's `PYTEST_XDIST_WORKER` would tell the inner run's plugins
  they are the outer worker: `tests/utils/gate_trace.py` names its trace file
  from it. A caller that wants one of them back sets it after this call.
- **Workers.** `PYTEST_XDIST_AUTO_NUM_WORKERS=0`, which xdist's `-n auto`
  reads and shipping-work's `gate-workers.sh` reads first. A real
  `pre-ship.sh` run inside the gate otherwise sized its own pool as if no gate
  were running (up to 8 workers, beside the outer gate's own).
- **The temp root.** A pytest that uses `tmp_path` makes a numbered
  `pytest-of-<user>/pytest-N` under its temp root and, at exit, deletes every
  unlocked one older than the newest three. Sharing the outer run's root,
  nested runs pushed a finished gate's tree out of the newest three, and
  whichever pytest exited next spent its own test deleting it.

The temp root moves with `PYTEST_DEBUG_TEMPROOT`, pytest's documented variable
for the root its `tmp_path` trees live under, not with `--basetemp` or
`TMPDIR`. `--basetemp` is a command-line flag, so it cannot reach a pytest a
script starts (the pre-ship gate's), and a caller whose argv is asserted on
would change shape. `TMPDIR` reaches it, but moves every other temp file the
script and its tools make too. `PYTEST_DEBUG_TEMPROOT` reaches every nested
pytest, script-started or not, and moves nothing else.

The root is a fresh directory under `temp_parent`, which the caller passes as
its own `tmp_path` (or a directory beneath it): the inner trees then go when
the calling test's tree does, and no two calls share one.

GIT_* is the caller's to scrub (docs/STYLE.md, #189): one caller sets
`GIT_CONFIG_GLOBAL` on purpose, so this keeps whatever `base` holds.

Reads nothing from the repo, at import or per call, and caches nothing
(`tests/utils/gate_trace.py`, on attribution).
"""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def nested_pytest_env(
    temp_parent: Path, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """`base` (default: this process's environment) for a nested pytest: no
    `PYTEST_*`, no xdist workers, and a temp root of its own in `temp_parent`."""
    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if not k.startswith("PYTEST_")
    }
    env["PYTEST_XDIST_AUTO_NUM_WORKERS"] = "0"
    env["PYTEST_DEBUG_TEMPROOT"] = tempfile.mkdtemp(prefix="nested-", dir=temp_parent)
    return env
