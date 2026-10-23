#!/usr/bin/env python3
"""tightened-rules.sh — ask which tightened sentences may have lost their rule.

usage: tightened-rules.sh [CANDIDATES] [--threshold P] [--dry-run]

An optional, advisory pass over `prove-no-loss.sh --claims --candidates FILE`
(gregoryfoster/skills#442). A class-C tightening rewrites a section in place,
and the gate's two matchers can't see what such a rewrite most often drops:
whole-line matching calls every rewritten line lost, and `tighten` warrants
it; `--claims` checks the atoms, so a rewrite can keep every backticked span
and link and still lose the "never", the "only when", the exception or the
reason between them. This pass reads the lines a `tighten` entry accounted
for, rebuilds their sentences, and asks TypeSafe one yes-or-no question about
each sentence, against the section the rewrite left:

  dropped     did the rewrite drop or weaken a rule this sentence states?

It never moves the verdict. `prove-no-loss.sh`'s report, its exit code, the
`no_loss` and `claims_*` fields and both warrant files are what they were. A
high p means "re-read this sentence against the rewrite before you commit":
not a loss, and a low one is not a pass either.

  CANDIDATES   prove-no-loss.sh's --candidates JSONL; `-` or absent reads
               stdin
  --threshold  flag a sentence `dropped?` when its probability is at least P
               (default 0.3, chosen from the #442 measurement for recall: a
               missed loss costs more than a re-read. On 421 hand-labelled
               sentences it caught 52 of 61 losses and flagged 180; 0.5
               caught 46 and flagged 111)
  --dry-run    print the cases that would be sent, one JSONL case per line in
               scripts/typesafe-eval.py's set format (without `expected`),
               and send nothing. A case's id is `file:line#k`, the k-th
               sentence starting on that base line

SENTENCES. A record is one base LINE, and in a hard-wrapped file a sentence
spans several, so each record's base section is cut into sentences the way
`_sentences.py` cuts every file this skill reads. A sentence is asked about
when any of its lines is one a `tighten` entry accounted for. Two kinds are
settled without a call:

  kept          the sentence is in the successor word for word, whitespace
                aside (a re-wrap moves line breaks and nothing else)
  no-successor  prove-no-loss.sh found no section the rewrite left: no
                heading of the same name, and none of the line's atoms
                survived. Re-read it by hand

Nor is a sentence from an ARCHIVAL doc sent, a path with a component named
in CTX_ARCHIVAL (default: plans specs research audits archive), as
`_context-lib.sh` reads it: a dated plan is a record. Its row says
`archival`.

OUTPUT is TSV on stdout, one row per sentence, no header:

  file line status p flag sentence

  line        where the sentence starts at --base
  status      judged, kept, no-successor, archival, or why it wasn't judged:
                skipped | failed | not-asked   TypeSafe skipped, failed, or
                            wasn't reached after a failure
                would-ask   --dry-run: printed as a case, not sent
  p           the probability the rewrite dropped a rule, 3 places
  flag        `dropped?` when p is at least the threshold
  sentence    as it read at --base, tabs and newlines as spaces

Judged rows come first, most likely dropped first, then the rest in file
order. A one-line summary goes to stderr.

SENDING follows the TypeSafe client beside this file (`python3 _typesafe.py
--help`): nothing leaves the machine until the repo opts in, with
TYPESAFE_OPT_IN=on or `.skills/typesafe`. A request carries the sentence, its
base heading and the successor section (clipped to MAX_AFTER_CHARS around
the sentence's words). Nothing else from the file or the repo.

exit codes:
  0  every sentence was judged, kept, a successor-less one or an archival
     doc's (with --dry-run: printed)
  1  usage error, or input that isn't prove-no-loss.sh's (nothing was sent)
  2  a TypeSafe failure (its message on stderr). The rows are still
     printed, the unjudged ones marked
  4  skipped: not opted in, or no key (the client's line on stderr). The rows
     are still printed, unjudged
  Exits 2 and 4 are advisory, and prove-no-loss.sh's own exit code is never
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

DEFAULT_THRESHOLD = 0.3
# About 16k tokens at the client's 3 bytes a token: half the 32k a question
# may carry. The largest successor in the #442 corpus is 27,546 characters.
MAX_AFTER_CHARS = 48_000

EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_SKIPPED = 4

# The first of two wordings measured (#442). The second named the weakening
# shapes ("must" become "is", "only X" become "X") and an index entry as a no;
# it raised every probability rather than separating them: Brier 0.181 against
# this one's 0.139 on the committed 421-case set, more false alarms at every
# threshold, and the subtle weakenings it named still scored under 0.2.
DROPPED = (
    "`sentence` is from a section of a Markdown file of instructions for coding "
    "agents, as it read before an edit meant to make the section shorter without "
    "changing what it tells the reader to do. `after_section` is the section after "
    "that edit. Did the edit drop or weaken a rule `sentence` states? A rule is a "
    "requirement, a prohibition (never, don't, must not), a condition or scope "
    "(only when, unless, if), an exception, a boundary, or the stated reason for "
    "one of these. Answer yes when `after_section` no longer states it, or states "
    "it more weakly or more broadly, whatever words it uses. Answer no when "
    "`after_section` states the same rule in other words, or when `sentence` "
    "states no rule: a dated example, a changelog or issue reference, the story "
    "of a past incident or run, or a pointer to another document."
)

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{4,}")


class UsageError(Exception):
    pass


@dataclass
class Row:
    file: str
    line: int  # where the sentence starts at --base
    end_line: int  # where it ends
    sentence: str
    heading: str | None
    successor: dict | None
    status: str = ""
    p: float | None = None


# --- input -------------------------------------------------------------------


def _is_successor(s) -> bool:
    return s is None or (
        isinstance(s, dict)
        and isinstance(s.get("file"), str)
        and isinstance(s.get("text"), str)
    )


def read_candidates(lines) -> list[dict]:
    """prove-no-loss.sh's records. Raises UsageError on a line that isn't one."""
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
            and isinstance(rec.get("section_line"), int)
            and isinstance(rec.get("section"), str)
            and "heading" in rec
            and (rec["heading"] is None or isinstance(rec["heading"], str))
            and "successor" in rec
            and _is_successor(rec["successor"])
        ):
            raise UsageError(
                f"line {n} isn't a prove-no-loss.sh --candidates record (file, "
                f"line, section_line, section, heading, successor): "
                f"{line.strip()[:80]!r}"
            )
        out.append(rec)
    return out


# --- sentences ---------------------------------------------------------------


def _flat(text: str) -> str:
    return _WS.sub(" ", text).strip()


def to_rows(recs: list[dict], archival=None) -> list[Row]:
    """One row per base sentence touching a tightened line, and why it won't be sent, if it won't.

    `archival` is the list of names; None reads CTX_ARCHIVAL as the library does.
    """
    names = archival_names() if archival is None else archival
    sections: dict[tuple, list[dict]] = {}
    for rec in recs:
        sections.setdefault((rec["file"], rec["section_line"]), []).append(rec)
    rows = []
    for (file, start), group in sections.items():
        by_line = {rec["line"]: rec for rec in group}
        for s in _sentences.sentences(group[0]["section"]):
            first, last = s.line + start - 1, s.end_line + start - 1
            touched = [by_line[n] for n in range(first, last + 1) if n in by_line]
            if not touched:
                continue
            successor = next(
                (r["successor"] for r in touched if r["successor"] is not None), None
            )
            row = Row(file, first, last, s.text, group[0]["heading"], successor)
            if is_archival(file, Path.cwd(), names):
                row.status = "archival"
            elif successor is None:
                row.status = "no-successor"
            elif _flat(s.text) in _flat(successor["text"]):
                row.status = "kept"
            rows.append(row)
    return rows


# --- the cases ---------------------------------------------------------------


def clip(after: str, sentence: str, limit: int = MAX_AFTER_CHARS) -> str:
    """`after` cut to `limit` characters around where the sentence's words are."""
    if len(after) <= limit:
        return after
    low = after.lower()
    hits = sorted(
        i for i in (low.find(w.lower()) for w in _WORD.findall(sentence)) if i >= 0
    )
    centre = hits[len(hits) // 2] if hits else 0
    a = min(max(0, centre - limit // 2), len(after) - limit)
    return (
        ("…" if a else "")
        + after[a : a + limit]
        + ("…" if a + limit < len(after) else "")
    )


def case_ids(rows: list[Row]) -> dict[int, str]:
    """`file:line#k` for each row, k counting the sentences that start on that line."""
    seen: dict = {}
    out = {}
    for r in rows:
        k = seen[(r.file, r.line)] = seen.get((r.file, r.line), 0) + 1
        out[id(r)] = f"{r.file}:{r.line}#{k}"
    return out


def build_case(sentence: str, heading: str | None, after: str) -> tuple[dict, dict]:
    """(state, questions) for one sentence: exactly what is sent, and what #442 measured."""
    state = {"sentence": sentence}
    if heading:
        state["heading"] = heading
    state["after_section"] = clip(after, sentence)
    return state, {"dropped": {"type": "noul", "instructions": DROPPED}}


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
        flag = "dropped?" if r.p is not None and r.p >= threshold else ""
        cols = [r.file, r.line, r.status, _p(r.p), flag, r.sentence]
        out.append("\t".join(_cell(c) for c in cols) + "\n")
    return "".join(out)


def summary(rows: list[Row], threshold: float) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    flagged = sum(1 for r in rows if r.p is not None and r.p >= threshold)
    parts = [f"{counts.pop('judged', 0)} judged ({flagged} at or over {threshold:g})"]
    parts += [f"{n} {s}" for s, n in sorted(counts.items())]
    return f"tightened-rules: {len(rows)} sentences: " + ", ".join(parts)


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
        say(f"tightened-rules: {e}")
        say("usage: tightened-rules.sh [CANDIDATES] [--threshold P] [--dry-run]")
        return EXIT_USAGE

    threshold = opts["threshold"]
    rows = to_rows(recs, archival_names())
    pending = [r for r in rows if not r.status]
    files = sorted({r.file for r in rows if r.status == "archival"})
    if files:
        say(
            f"tightened-rules: {', '.join(files)} is archival, so nothing from it "
            "is sent (#442)"
        )

    if opts["dry_run"]:
        ids = case_ids(rows)
        for r in pending:
            r.status = "would-ask"
            state, questions = build_case(r.sentence, r.heading, r.successor["text"])
            case = {"id": ids[id(r)], "state": state, "questions": questions}
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
            state, questions = build_case(r.sentence, r.heading, r.successor["text"])
            r.p = _noul(client.ask(state, questions), "dropped")
            r.status = "judged"
        except _typesafe.TypeSafeError as e:
            say(str(e))
            r.status, failed, exit_code = "failed", True, EXIT_FAILED
    stdout.write(render(rows, threshold))
    say(summary(rows, threshold))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
