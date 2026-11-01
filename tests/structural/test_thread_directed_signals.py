"""A test signals its own thread, never its whole process (#547).

`os.kill(os.getpid(), sig)` is process-directed: the kernel hands the signal to
any thread that does not block it. Under pytest-xdist the worker also runs
execnet's IO thread, which blocks nothing, so a signal meant to wait behind
the test thread's `pthread_sigmask` was taken by that thread instead, and
Python ran the handler inside the very window the mask guards. That is how
`test_a_signal_between_mkdir_and_its_record_still_removes_staging` flaked
under the parallel suite and never serially: 33 of 160 runs of its file under
`-n 4 --dist loadfile` failed before the fix, and 0 of 160 after.

`signal.raise_signal(sig)` is C's `raise()`, which POSIX defines in a threaded
process as `pthread_kill(pthread_self(), sig)`: the calling thread's mask
holds it until the mask lifts. Measured with a second, unmasked thread
present: os.kill ran the handler inside the blocked window 1852 times in
2000; raise_signal and pthread_kill(get_ident()) never did.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
PROCESS_DIRECTED = re.compile(r"\bos\.kill\(\s*os\.getpid\(\)")


def test_no_test_sends_a_process_directed_signal_to_itself():
    hits = [
        f"{path.relative_to(TESTS.parent)}:{n}"
        for path in sorted(TESTS.rglob("*.py"))
        if path != Path(__file__).resolve()
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if PROCESS_DIRECTED.search(line)
    ]
    assert not hits, (
        "send it to this thread with signal.raise_signal(sig): " + ", ".join(hits)
    )
