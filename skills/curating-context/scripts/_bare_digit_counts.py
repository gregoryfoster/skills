#!/usr/bin/env python3
"""bare-digit-counts.sh — ask which bare digits check-counts.sh passed over are tallies.

usage: bare-digit-counts.sh [CANDIDATES] [--threshold P] [--dry-run]

An optional, advisory pass over `check-counts.sh --file <reference doc>
--candidates FILE` (gregoryfoster/skills#441). The gate leaves a bare digit
alone, because in a policy file one is nearly always a status code, a port, a
version or a limit, so "182 hx-get reveals" passes unbackticked. This pass
reads the clauses the gate passed over, drops the digits code can rule out,
and asks TypeSafe one yes-or-no question about each clause left:

  tally       does a number in the clause state how many of something the
              repo holds now, so it goes stale when that count changes?

REFERENCE DOCS ONLY. A clause from a policy file (any AGENTS.md or CLAUDE.md)
is never sent, and its row says `policy-file`. The cohort's 12 policy files
held 411 passed-over digits and one tally, so the pass would spend a call per
port and status code to find nothing; point the gate's --file at a doc.
Nor is a clause from an ARCHIVAL doc, a path with a component named in
CTX_ARCHIVAL (default: plans specs research audits archive), as
`_context-lib.sh` reads it: a dated plan's counts are records, which the
question already answers no for. Its row says `archival`.

It flags; it never writes. The gate, its warrants and
`.skills/context-counts-ok` are untouched: a flagged clause needs no entry,
and which of the gate's remedies fits stays the reader's call.

  CANDIDATES   check-counts.sh's --candidates JSONL; `-` or absent reads stdin
  --threshold  flag a clause `tally?` when its probability is at least P
               (default 0.8, chosen from the #441 measurement for
               precision: a pass that cries wolf defeats its purpose)
  --dry-run    print the tally cases that would be sent, one JSONL case per
               line in scripts/typesafe-eval.py's set format (without
               `expected`), and send nothing

PREFILTERS. A digit that code can rule out is masked before anything is sent:

  code      inside a code span
  link      in a link target, an autolink or a bare URL
  issue     an issue reference, `#12` or `owner/repo#12`
  date      an ISO date or year-month: 2026-10-21, 2026-10
  percent   12%, 72.3 %
  version   dotted: 1.13.0, v1.15, 0.2, 3.9+
  sha       a hex string of 7 or more holding a letter and a digit
  time      a clock time: 08:00, 15:27:00Z
  port      after a colon: localhost:8080
  marker    the clause is only a list marker, `1.` or `2)`
  word      fused to letters: H1, UTF-8, 5xx, 64k, 30s, x86_64

A clause with no digit left is `prefiltered`, and the masks that took its
digits are named. The rest are asked about, with the digits left listed as
`numbers`.

OUTPUT is TSV on stdout, one row per candidate, no header:

  file line status p flag numbers clause

  status      judged, prefiltered:<masks>, or why it wasn't judged:
                policy-file   from an AGENTS.md or CLAUDE.md: never sent
                archival      from an archival doc: never sent
                skipped | failed | not-asked   TypeSafe skipped, failed, or
                            wasn't reached after a failure
                would-ask   --dry-run: printed as a case, not sent
  p           the probability the clause states a tally, 3 places
  flag        `tally?` when p is at least the threshold
  numbers     the digits left after the prefilters, space-separated
  clause      as check-counts.sh split it, tabs and newlines as spaces

Judged rows come first, most likely a tally first, then the rest in file
order. A one-line summary goes to stderr.

SENDING follows the TypeSafe client beside this file (`python3 _typesafe.py
--help`): nothing leaves the machine until the repo opts in, with
TYPESAFE_OPT_IN=on or `.skills/typesafe`. A request carries the clause, its
numbers and its heading. Nothing else from the file or the repo.

exit codes:
  0  every candidate was prefiltered, a policy file's or an archival
     doc's, or judged (with --dry-run: printed)
  1  usage error, or input that isn't check-counts.sh's (nothing was sent)
  2  a TypeSafe failure (its message on stderr). The rows are still
     printed, the unjudged ones marked
  4  skipped: not opted in, or no key (the client's line on stderr). The rows
     are still printed, unjudged
  Exits 2 and 4 are advisory, and check-counts.sh's own exit code is never
  touched.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` drops it
import _sentences  # noqa: E402
import _typesafe  # noqa: E402
from _archival import archival_names, is_archival  # noqa: E402

DEFAULT_THRESHOLD = 0.8
# A policy file's clauses are never sent (#441): 1 tally in its 411 digits.
POLICY_FILES = frozenset({"AGENTS.md", "CLAUDE.md"})

EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_SKIPPED = 4

# The second wording measured (#441). The first lumped "a measurement" in with
# the limits, and Jev still called every dated graph yield and past dump a tally:
# no threshold reached precision 0.2. Naming a record as no took the Brier
# score from 0.065 to 0.037 on the 780-case set both were asked on (policy
# files included); on the committed docs-only set of 664 it is 0.041 (CR 465).
TALLY = (
    "Does a number in `numbers`, as `clause` uses it, state how many of something "
    "the repo or project holds right now (files, tests, tables, rules, call sites, "
    "seeded values and the like), so the sentence goes stale when that count "
    "changes? Answer no when the number is a status code, a port, a version, a "
    "date, a standard, an identifier, an ordinal or step number, or a configured "
    "limit, budget, threshold or duration. Answer no as well when the count is a "
    "record: the result of a past run, audit, measurement, migration or incident, "
    "dated or told in the past tense, which stays true as history after the repo "
    "changes."
)
# Applied in this order, each to what the earlier ones left.
_URL = re.compile(r"\]\([^)\s]*\)|<[a-z][a-z0-9+.-]*:[^>\s]*>|\bhttps?://\S+", re.I)
_PREFILTERS = (
    ("issue", _sentences.REF),
    ("date", re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")),
    ("percent", re.compile(r"\d+(?:\.\d+)?\s?%")),
    ("version", re.compile(r"\bv?\d+(?:\.\d+)+\+?")),
    ("sha", re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")),
    # Before `port`, which took ":00" and left the hour (CR 459).
    ("time", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?\b")),
    ("port", re.compile(r":\d{2,5}\b")),
    ("word", re.compile(r"\b[A-Za-z_]+[-_]?\d[\w-]*|\b\d+[A-Za-z_]\w*")),
)
_MARKER = re.compile(r"^\(?\d{1,3}[.)]$")
# Thousands separators only: `\d[\d,]*` took the comma after "port 8000," into
# the number, and 94 of the 788 cases first measured were asked about one (CR 458).
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+\+?|\d+\+?")


class UsageError(Exception):
    pass


@dataclass
class Row:
    file: str
    line: int
    clause: str
    heading: str | None
    numbers: list
    masks: list
    status: str = ""
    p: float | None = None


# --- input -------------------------------------------------------------------


def read_candidates(lines) -> list[dict]:
    """check-counts.sh's records. Raises UsageError on a line that isn't one."""
    out = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            rec = None
        if not (
            isinstance(rec, dict)
            and isinstance(rec.get("file"), str)
            and isinstance(rec.get("line"), int)
            and isinstance(rec.get("clause"), str)
            and "heading" in rec
            and (rec["heading"] is None or isinstance(rec["heading"], str))
        ):
            raise UsageError(
                f"line {n} isn't a check-counts.sh --candidates record (file, "
                f"line, clause, heading): {line.strip()[:80]!r}"
            )
        out.append(rec)
    return out


# --- prefilters --------------------------------------------------------------


def _mask(text: str, spans) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def prefilter(clause: str) -> tuple[list[str], list[str]]:
    """(numbers left, names of the masks that took a digit), for one clause."""
    if _MARKER.match(clause.strip()):
        return [], ["marker"]
    masks = []
    text = clause
    steps = [("code", _sentences._code_spans(text)), ("link", None)]
    steps += [(name, None) for name, _ in _PREFILTERS]
    patterns = dict(_PREFILTERS, link=_URL)
    for name, spans in steps:
        if spans is None:
            spans = [m.span() for m in patterns[name].finditer(text)]
        if any(re.search(r"\d", text[a:b]) for a, b in spans):
            masks.append(name)
        text = _mask(text, spans)
    return _NUMBER.findall(text), masks


def is_policy_file(path: str) -> bool:
    return Path(path).name in POLICY_FILES


def to_row(rec: dict, archival=None) -> Row:
    """One candidate, and why it won't be sent, if it won't.

    `archival` is the list of names; None reads CTX_ARCHIVAL as the library does.
    """
    numbers, masks = prefilter(rec["clause"])
    row = Row(rec["file"], rec["line"], rec["clause"], rec["heading"], numbers, masks)
    names = archival_names() if archival is None else archival
    if is_policy_file(row.file):
        row.status = "policy-file"
    elif is_archival(row.file, Path.cwd(), names):
        row.status = "archival"
    elif not numbers:
        row.status = "prefiltered:" + ",".join(masks)
    return row


# --- the cases ---------------------------------------------------------------


def build_tally_case(clause: str, numbers, heading: str | None) -> tuple[dict, dict]:
    """(state, questions) for one clause: exactly what is sent, and what #441 measured."""
    state = {"clause": clause, "numbers": list(numbers)}
    if heading:
        state["heading"] = heading
    return state, {"tally": {"type": "noul", "instructions": TALLY}}


# --- output ------------------------------------------------------------------


def _cell(v) -> str:
    return re.sub(r"[\t\r\n]+", " ", "" if v is None else str(v))


def _p(v) -> str:
    return "" if v is None else f"{v:.3f}"


def render(rows: list[Row], threshold: float) -> str:
    judged = sorted((r for r in rows if r.p is not None), key=lambda r: -r.p)
    rest = sorted((r for r in rows if r.p is None), key=lambda r: (r.file, r.line))
    out = []
    for r in judged + rest:
        flag = "tally?" if r.p is not None and r.p >= threshold else ""
        cols = [r.file, r.line, r.status, _p(r.p), flag, " ".join(r.numbers), r.clause]
        out.append("\t".join(_cell(c) for c in cols) + "\n")
    return "".join(out)


def summary(rows: list[Row], threshold: float) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        key = "prefiltered" if r.status.startswith("prefiltered") else r.status
        counts[key] = counts.get(key, 0) + 1
    flagged = sum(1 for r in rows if r.p is not None and r.p >= threshold)
    parts = [f"{counts.pop('judged', 0)} judged ({flagged} at or over {threshold:g})"]
    parts += [f"{n} {s}" for s, n in sorted(counts.items())]
    return f"bare-digit-counts: {len(rows)} candidates: " + ", ".join(parts)


# --- the run -----------------------------------------------------------------


def _threshold(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        v = -1.0
    if not 0.0 <= v <= 1.0:
        raise UsageError(f"--threshold is a probability 0-1, not {text!r}")
    return v


def parse_args(argv: list[str]) -> dict:
    opts = {"input": None, "threshold": DEFAULT_THRESHOLD, "dry_run": False}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            opts["help"] = True
            return opts
        if a == "--threshold":
            v = next(it, None)
            if v is None:
                raise UsageError(f"{a} needs a value")
            opts["threshold"] = _threshold(v)
        elif a == "--dry-run":
            opts["dry_run"] = True
        elif a.startswith("-") and a != "-":
            raise UsageError(f"unknown option {a}")
        elif opts["input"] is not None:
            raise UsageError(f"one input only; got {opts['input']!r} and {a!r}")
        else:
            opts["input"] = a
    return opts


def _noul(reply: dict, name: str) -> float:
    answer = reply["answers"][name]
    p = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0 <= p <= 1:
        # Its shape, never its text: server text reaches stderr only through
        # the client's redaction (#438's CR 404, 438, 444).
        shape = (
            f"an object with {len(answer)} key(s)"
            if isinstance(answer, dict)
            else f"a {type(answer).__name__}"
        )
        raise _typesafe.TypeSafeError(
            200, f"answer for {name} has no noul probability ({shape})"
        )
    return float(p)


def main(argv: list[str], stdin=None, stdout=None, stderr=None, connect=None) -> int:
    stdin, stdout, stderr = (
        stdin or sys.stdin,
        stdout or sys.stdout,
        stderr or sys.stderr,
    )
    connect = connect or _typesafe.connect

    def say(line: str) -> None:
        print(line, file=stderr)

    try:
        opts = parse_args(argv)
        if opts.get("help"):
            print(__doc__.strip(), file=stdout)
            return 0
        if opts["input"] in (None, "-"):
            recs = read_candidates(stdin)
        else:
            try:
                with open(opts["input"], encoding="utf-8", errors="replace") as f:
                    recs = read_candidates(f)
            except OSError as e:
                raise UsageError(f"can't read {opts['input']}: {e.strerror}") from None
    except UsageError as e:
        say(f"bare-digit-counts: {e}")
        say("usage: bare-digit-counts.sh [CANDIDATES] [--threshold P] [--dry-run]")
        return EXIT_USAGE

    threshold = opts["threshold"]
    names = archival_names()
    rows = [to_row(r, names) for r in recs]
    pending = [r for r in rows if not r.status]
    for status, what in (("policy-file", "a policy file"), ("archival", "archival")):
        files = sorted({r.file for r in rows if r.status == status})
        if files:
            say(
                f"bare-digit-counts: {', '.join(files)} is {what}, so nothing "
                "from it is sent (#441). Run check-counts.sh --file <live "
                "reference doc> --candidates FILE instead"
            )

    if opts["dry_run"]:
        for r in pending:
            r.status = "would-ask"
            state, questions = build_tally_case(r.clause, r.numbers, r.heading)
            case = {"id": f"{r.file}:{r.line}", "state": state, "questions": questions}
            stdout.write(json.dumps(case, ensure_ascii=False) + "\n")
        say(summary(rows, threshold))
        return 0

    if pending:
        try:
            # The client's per-call lines go where this run's own do.
            client = connect(stderr=stderr)
        except _typesafe.Skipped as s:
            say(s.line)
            for r in pending:
                r.status = "skipped"
            stdout.write(render(rows, threshold))
            say(summary(rows, threshold))
            return EXIT_SKIPPED

    exit_code = 0
    failed = False
    for r in pending:
        if failed:
            r.status = "not-asked"
            continue
        try:
            state, questions = build_tally_case(r.clause, r.numbers, r.heading)
            r.p = _noul(client.ask(state, questions), "tally")
            r.status = "judged"
        except _typesafe.TypeSafeError as e:
            say(str(e))
            r.status, failed, exit_code = "failed", True, EXIT_FAILED
    stdout.write(render(rows, threshold))
    say(summary(rows, threshold))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
