#!/usr/bin/env python3
"""Impacted-test selection for this repo's pre-commit hook (#537 Step 10).

Two subcommands, stdlib only:

  build   merge the traces a full run wrote (`tests/utils/gate_trace.py`)
          into the dependency map: each test file -> the units it depends on
  select  read changed paths on stdin and print the test files to run, one
          per line (exit 0), or `FULL<TAB><reason>` (exit 3)

A unit is one of:

  *               the whole tree: the file listed the repo root or skills/,
                  or ran an interpreter, a script by its path, or git not
                  aimed at a fixture from inside the repo, which can read
                  anything relative to it
  skills/<name>   anything under that skill: a skill's scripts reach only
                  their own directory, so the directory bounds what a bash
                  script under it can read
  <dir>/          anything under a directory the file listed
  <path>          one file it opened, checked for, or passed to a subprocess

Selection, for each changed path:

  tests/structural/test_*.py         that file
  skills/<name>/...                  every test depending on skills/<name>
  docs/plans/...                     nothing extra
  tests/..., scripts/..., hooks,     the full suite: shared helpers and the
  pyproject.toml, requirements*.txt, gate itself reach every test, and an
  .pre-commit-config.yaml, .github/  import is attributed to one file only
  anything else                      every test that opened or listed it

Plus, always: every test depending on `*`, and every test file on disk the
map has never seen. Exit codes: 0 selection printed, 3 full suite needed (the
reason follows FULL), 2 could not run (bad arguments, unreadable map).
"""

import argparse
import fnmatch
import glob
import json
import os
import re
import sys
import time

VERSION = 1
WHOLE = "*"
TEST_FILE = re.compile(r"tests/structural/test_[^/]+\.py")
FULL_PATTERNS = (
    "tests/*",
    "scripts/*",
    ".claude/hooks/*",
    ".github/*",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "requirements*.txt",
)
HELP_FLAGS = {"--help", "-h", "--version"}
INTERPRETERS = {
    "bash",
    "sh",
    "zsh",
    "dash",
    "env",
    "python",
    "python3",
    "node",
    "uv",
    "uvx",
    "perl",
    "ruby",
    "pytest",
    "make",
    "xargs",
    "timeout",
    "nice",
    "setsid",
}


def unit_of(rel: str, listed: bool = False) -> str:
    """The dependency unit a repo-relative path belongs to."""
    if rel in (".", "skills") and listed:
        return WHOLE
    parts = rel.split("/")
    if parts[0] == "skills" and len(parts) >= 2:
        return f"skills/{parts[1]}"
    return rel.rstrip("/") + "/" if listed else rel


def proc_reads_tree(record: list[str]) -> bool:
    """Whether a subprocess started from inside the repo could read the tree.

    record is [cwd, argv...], with a path outside the repo shown as
    `<outside>`. An interpreter, or any program named by a path (a script in
    the repo run directly, the venv's python), runs code that may read
    anything relative to the repo, so it counts, unless all it was asked for
    is `--help`. git counts unless it
    was pointed at a fixture outside the repo (`-C <outside>`, `init <outside>`,
    `clone ... <outside>`). Any other command reads only the paths in its
    argv, and the tracer already recorded those.
    """
    argv = record[1:]
    if not argv:
        return True
    if any(w in HELP_FLAGS for w in argv):
        return False
    prog = os.path.basename(argv[0])
    if prog == "git":
        return "<outside>" not in argv
    return prog in INTERPRETERS or "/" in argv[0] or argv[0] == "<outside>"


def build(prefix: str, out: str, tree: str) -> int:
    paths = sorted(glob.glob(f"{glob.escape(prefix)}.*.jsonl"))
    if not paths:
        print(f"ERROR: no trace files at {prefix}.*.jsonl", file=sys.stderr)
        return 2
    tests: dict[str, set[str]] = {}
    for path in paths:
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                units = tests.setdefault(rec["file"], set())
                for rel in (
                    rec.get("open", []) + rec.get("stat", []) + rec.get("exec", [])
                ):
                    units.add(unit_of(rel))
                for rel in rec.get("list", []):
                    units.add(unit_of(rel, listed=True))
                for raw in rec.get("proc", []):
                    if proc_reads_tree(json.loads(raw)):
                        units.add(WHOLE)
    doc = {
        "version": VERSION,
        "tree": tree,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tests": {f: sorted(u) for f, u in sorted(tests.items())},
    }
    tmp = f"{out}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, out)
    whole = sum(WHOLE in u for u in tests.values())
    print(
        f"gate map: {len(tests)} test files, {whole} depend on the whole tree -> {out}"
    )
    return 0


def _matches(path: str, unit: str) -> bool:
    if unit == WHOLE:
        return True
    if unit.endswith("/"):
        return path.startswith(unit)
    return path == unit


def select(
    map_path: str, changed: list[str], on_disk: list[str]
) -> tuple[int, list[str]]:
    with open(map_path) as fh:
        doc = json.load(fh)
    if doc.get("version") != VERSION:
        return 3, [f"the map is version {doc.get('version')}, not {VERSION}"]
    tests: dict[str, list[str]] = doc["tests"]
    chosen = {f for f, units in tests.items() if WHOLE in units}
    chosen |= {f for f in on_disk if f not in tests}
    for path in changed:
        if TEST_FILE.fullmatch(path):
            chosen.add(path)
        elif path.startswith("docs/plans/"):
            continue
        elif any(fnmatch.fnmatch(path, p) for p in FULL_PATTERNS):
            return 3, [f"{path} changed (shared by the whole suite)"]
        else:
            target = unit_of(path)
            for f, units in tests.items():
                if any(u == target or _matches(path, u) for u in units):
                    chosen.add(f)
    present = set(on_disk)
    return 0, sorted(f for f in chosen if f in present)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="merge a full run's traces into the map")
    b.add_argument("--trace", required=True, help="the GATE_TRACE prefix the run used")
    b.add_argument("--out", required=True, help="where to write the map")
    b.add_argument("--tree", default="", help="the tree the traced run passed on")
    s = sub.add_parser("select", help="changed paths on stdin -> test files to run")
    s.add_argument("--map", required=True)
    s.add_argument(
        "--root", default=".", help="the repo root, to list test files on disk"
    )
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.cmd == "build":
        try:
            return build(args.trace, args.out, args.tree)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(
                f"ERROR: cannot build the map from {args.trace}: {exc}", file=sys.stderr
            )
            return 2
    try:
        on_disk = sorted(
            os.path.relpath(p, args.root)
            for p in glob.glob(os.path.join(args.root, "tests/structural/test_*.py"))
        )
        rc, lines = select(
            args.map, [ln.strip() for ln in sys.stdin if ln.strip()], on_disk
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: cannot read the map {args.map}: {exc}", file=sys.stderr)
        return 2
    if rc == 3:
        print(f"FULL\t{lines[0]}")
    else:
        print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
