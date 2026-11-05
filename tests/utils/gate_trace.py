"""A pytest plugin that records what each test file touches in the repo (#537).

Loaded by `scripts/structural-tests.sh` with `-p tests.utils.gate_trace` on a
full run, when `GATE_TRACE=<prefix>` is set. Each process (the xdist
controller and every worker) writes `<prefix>.<worker>.jsonl` at session end:
one JSON object per test file, listing the repo paths it

- opened (`open` audit event: reads, writes, and imports through
  `io.open_code`) or linked to (`os.symlink`'s target),
- checked for (`stat`: `os.stat`, behind `Path.exists`, `is_file`, `is_dir`
  and `os.path.exists`; it raises no audit event, so it is wrapped),
- listed (`os.listdir`, `os.scandir` — what `Path.glob` and `iterdir` use —
  and `glob.glob`),
- executed or passed to a subprocess (`subprocess.Popen` argv, `exec`), and
- started a subprocess from inside the repo (`proc`: the working directory
  and the first argv words, a path outside the repo shown as `<outside>`).

`scripts/gate_select.py build` turns those raw events into the dependency map
the pre-commit hook selects from. The policy lives there, not here: this file
only reports, so what counts as "the whole tree" can change without a re-trace.

Reads are attributed to the test file that was running — or being collected,
for module-level reads — when they happened. A session-scoped fixture's reads
land on the first file that used it; the selector's full-suite rule for any
change under `tests/` covers that gap.

Paths are kept repo-relative and resolved through symlinks, so
`.claude/skills/<x>` and `skills/<x>` are one path. Paths outside the repo
(tmp fixtures, site-packages) and inside `.git`, `.venv`, `.worktrees` and
`__pycache__` are dropped.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO = os.path.realpath(Path(__file__).resolve().parents[2])
_PREFIX = REPO + os.sep
IGNORED = {".git", ".venv", ".worktrees", "__pycache__", ".pytest_cache", ".ruff_cache"}

_out = os.environ.get("GATE_TRACE", "")
_current = ""
_os_stat = os.stat
_in_stat = False
_events: dict[str, dict[str, set[str]]] = {}
_real: dict[str, str] = {}


def _rel(path, base: str | None = None) -> str:
    """The repo-relative real path of `path`, or "" when it is not ours."""
    if isinstance(path, int) or path is None:
        return ""
    try:
        path = os.fsdecode(path)
    except TypeError:
        return ""
    if not os.path.isabs(path):
        path = os.path.join(base or os.getcwd(), path)
    real = _real.get(path)
    if real is None:
        real = os.path.realpath(path)
        _real[path] = real
    if real == REPO:
        return "."
    if not real.startswith(_PREFIX):
        return ""
    rel = real[len(_PREFIX) :]
    parts = rel.split(os.sep)
    if parts[0] in IGNORED or "__pycache__" in parts:
        return ""
    return rel


def _record(kind: str, rel: str) -> None:
    if rel and _current:
        _events.setdefault(_current, {}).setdefault(kind, set()).add(rel)


def _argv(args) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.fsdecode(args)]
    try:
        return [
            os.fsdecode(a) for a in args if isinstance(a, (str, bytes, os.PathLike))
        ]
    except TypeError:
        return []


def _marked(word: str, base: str) -> str:
    """A path argument outside the repo becomes `<outside>`, so the builder can
    tell `git -C <tmp>` from `git -C <repo>` without knowing tmp's name."""
    if os.sep in word and not word.startswith("-") and not _rel(word, base):
        return "<outside>"
    return word


def _audit(event: str, args) -> None:
    if not _current:
        return
    if event == "open":
        _record("open", _rel(args[0]))
    elif event == "os.symlink":
        # A fixture that links into the repo and then works through the link
        # reads what it points at, under a path outside the repo.
        _record("open", _rel(args[0], os.path.dirname(os.fsdecode(args[1]))))
    elif event in ("os.listdir", "os.scandir"):
        _record("list", _rel(args[0] if args and args[0] is not None else "."))
    elif event == "glob.glob":
        pattern = os.fsdecode(args[0])
        head = pattern.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0]
        _record("list", _rel(os.path.dirname(head) or "."))
    elif event == "subprocess.Popen":
        executable, argv, cwd = args[0], args[1], args[2]
        base = os.fsdecode(cwd) if cwd is not None else os.getcwd()
        words = _argv(argv)
        for item in words + _argv(executable or []):
            if os.sep in item or item.endswith((".sh", ".py", ".md")):
                _record("exec", _rel(item, base))
        where = _rel(base)
        if where:
            # Run from inside the repo: the builder decides whether the
            # command could read the tree from there (a `git -C <tmp>` or a
            # `--help` cannot). JSON-encoded so the record stays a set.
            _record("proc", json.dumps([where] + [_marked(w, base) for w in words[:8]]))


def _traced_stat(path, *args, **kwargs):
    """os.stat, recording the repo path it was asked about, found or not."""
    global _in_stat
    if _current and not _in_stat and kwargs.get("dir_fd") is None:
        _in_stat = True
        try:
            _record("stat", _rel(path))
        except Exception:  # noqa: BLE001 — tracing must never fail a stat
            pass
        finally:
            _in_stat = False
    return _os_stat(path, *args, **kwargs)


def _set_current(nodeid: str) -> None:
    global _current
    _current = nodeid.split("::", 1)[0]


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    if isinstance(collector, pytest.Module):
        _set_current(collector.nodeid)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _set_current(item.nodeid)
    yield


def pytest_configure(config):
    if _out:
        sys.addaudithook(_audit)
        # pathlib and os.path look os.stat up at call time; the import
        # system binds its own, so module lookups are not recorded.
        os.stat = _traced_stat


def pytest_sessionfinish(session):
    if not _out:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    path = f"{_out}.{worker}.jsonl"
    lines = [
        json.dumps({"file": f, **{k: sorted(v) for k, v in kinds.items()}})
        for f, kinds in sorted(_events.items())
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
