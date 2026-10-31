"""A pytest plugin that prints where the structural suite's time goes (#537).

Loaded by `scripts/structural-tests.sh` with `-p tests.utils.gate_durations`,
so every gate run ends with the suite's wall clock and its slowest files. That
is reporting, not a gate: a timing threshold would fail on a loaded machine and
teach everyone to ignore it. What it buys is that growth stays visible at the
moment someone is waiting for it, which is when they are most likely to act.

Per FILE, not per test, because that is the unit a fix works on: the suite's
cost is diffuse (its slowest 100 tests were 15% of a serial run), but its
slowest files are a short list. Under pytest-xdist the controller receives every
report, so the totals are summed across workers — CPU-ish time, not wall clock.
"""

import time
from collections import defaultdict

TOP = 15

_per_file: dict[str, float] = defaultdict(float)
_started = time.monotonic()


def pytest_runtest_logreport(report):
    _per_file[report.nodeid.split("::", 1)[0]] += report.duration


def pytest_terminal_summary(terminalreporter):
    if not _per_file:
        return
    wall = time.monotonic() - _started
    total = sum(_per_file.values())
    tr = terminalreporter
    tr.section("where the time went (gate_durations)")
    tr.write_line(
        f"wall clock {wall:.0f}s; {total:.0f}s summed across {len(_per_file)} files"
    )
    for path, seconds in sorted(_per_file.items(), key=lambda kv: -kv[1])[:TOP]:
        tr.write_line(f"{seconds:7.1f}s  {100 * seconds / total:4.1f}%  {path}")
