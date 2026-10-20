#!/usr/bin/env python3
"""stale-issue-prose.sh — rank verify-facts.sh's issue rows by how likely their prose is stale.

usage: stale-issue-prose.sh [TSV] [--repo SLUG] [--threshold P] [--dry-run]

An optional, advisory pass over `verify-facts.sh --issues` output
(gregoryfoster/skills#438). The verifier stops at the reference: a closed one
comes back TRUE with "check whether the prose still describes it as pending".
This pass finds each reference again in its file, takes the sentence or list
item holding it, and asks TypeSafe one yes-or-no question about it:

  closed (or merged)  does the sentence still call it open, pending, planned,
                      in progress, or blocking something?   (still_open)
  open                does the sentence call it done, fixed, shipped, merged
                      or closed?                            (already_done)

It judges; it never edits, and it never changes a verdict. Every row stays
TRUE. A stale sentence is a class-C rewrite, and only FALSE is ever eligible
for deletion.

  TSV          the verifier's output; `-` or absent reads stdin
  --repo SLUG  owner/repo for bare #N references, as passed to the verifier.
               Default: gh's inference for the current directory, which is
               the verifier's own default
  --threshold  flag a row `stale?` when its probability is at least P
               (default 0.2, chosen from the #438 measurement; ranking
               is the point, and the flag is where to stop reading)
  --dry-run    print what would be sent, one JSONL case per line in
               scripts/typesafe-eval.py's set format (without `expected`),
               and send nothing. It still asks gh for each issue's metadata

Run it from the checkout the verifier ran in: the TSV's paths are relative to
that checkout's root.

OUTPUT is TSV on stdout, one row per occurrence, no header. The verifier's five
columns come first, unchanged, so a reader of its TSV still parses each row:

  verdict class file ref evidence line kind state question p flag status sentence

  line       where this occurrence is, 1-based (the verifier records none)
  kind       issue | pull request, from the pass's own lookup
  state      open | closed | merged, as of this run
  question   still_open | already_done
  p          TypeSafe's probability that the answer is yes, 3 places
  flag       `stale?` when p is at least the threshold, else empty
  status     judged, or why the occurrence wasn't judged:
               code        inside a fenced block or a code span: not a claim
               short-repo  `watcher#278`: the verifier resolved #278 against
                           this repo, which may be the wrong issue
               unverifiable  the verifier's own row; nothing to judge against
               not-found   the reference is no longer in the file
               unresolved  gh couldn't resolve it now
               skipped | failed | not-asked   TypeSafe skipped, failed, or
                           wasn't reached after a failure
               dry-run
  sentence   the sentence or list item, tabs and newlines as spaces

Judged rows come first, most likely stale first; the rest follow in file
order. A one-line summary goes to stderr, with how many occurrences were in
code, so a reference that appears only in code doesn't silently vanish.

The splitter is `_sentences.py` beside this file; its docstring says what a
sentence is. One TypeSafe request per occurrence, the shape #438 measured:
about 273 input tokens of overhead plus the sentence. Issue metadata comes
from one `gh api graphql` call per repo per 50 references.

SENDING follows the TypeSafe client beside this file (`python3 _typesafe.py
--help`): nothing leaves the machine until the repo opts in, with
TYPESAFE_OPT_IN=on or `.skills/typesafe`. Each request carries exactly: the
sentence, its heading, the reference as written, and the item's kind, title,
state, close reason and close date. Nothing else from the file or the repo.

exit codes:
  0  every occurrence that could be judged was judged
  1  usage error, or a TSV that isn't the verifier's (nothing was sent)
  2  a TypeSafe or gh failure (its message on stderr). The rows are still
     printed, the unjudged ones marked
  4  skipped: not opted in, or no key (the client's line on stderr). The rows
     are still printed, unjudged
  Exits 2 and 4 are advisory: carry on with the verifier's TSV as if this
  pass hadn't run. verify-facts.sh's own exit code is never touched.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` drops it
import _sentences  # noqa: E402
import _typesafe  # noqa: E402

# Chosen from the #438 measurement: the highest threshold that kept recall at
# 0.9 or more on both questions (still_open 14/15, already_done 3/3).
DEFAULT_THRESHOLD = 0.2
BATCH = 50

EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_SKIPPED = 4

_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

STILL_OPEN = (
    "The reference in `sentence` points at the GitHub item described in "
    "`issue`, which is closed. Does `sentence` still describe that item as "
    "open, pending, planned, in progress, or as blocking or holding up "
    "something? Answer no when the sentence cites it as history: where a rule "
    "came from, what it fixed, or a decision it recorded."
)
ALREADY_DONE = (
    "The reference in `sentence` points at the GitHub item described in "
    "`issue`, which is still open. Does `sentence` describe that item as done, "
    "fixed, shipped, merged, or closed? Answer no when the sentence describes "
    "it as open, pending or planned, or only cites it."
)


class UsageError(Exception):
    pass


class GhError(Exception):
    pass


@dataclass
class Row:
    verdict: str
    klass: str
    file: str
    ref: str
    evidence: str
    line: int | None = None
    kind: str = ""
    state: str = ""
    question: str = ""
    p: float | None = None
    status: str = ""
    sentence: str = ""
    heading: str | None = None
    meta: dict = field(default_factory=dict)


# --- input -------------------------------------------------------------------


def read_tsv(lines) -> list[tuple[str, ...]]:
    """The verifier's issue rows. Raises UsageError on a line that isn't the verifier's.

    Only an issue row must be exactly five columns. A backticked path holding
    a tab comes out as a six-column path row, which is still the verifier's
    output and isn't read here, so it mustn't refuse the run (CR 422).
    """
    rows = []
    for n, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        if not line:
            continue
        cols = line.split("\t")
        if (
            cols[0] not in ("TRUE", "FALSE", "UNVERIFIABLE")
            or len(cols) < 5
            or (cols[1] == "issue" and len(cols) != 5)
        ):
            raise UsageError(
                f"line {n} isn't a verify-facts.sh row (verdict, class, file, "
                f"claim, evidence): {line[:80]!r}"
            )
        if cols[1] == "issue":
            rows.append(tuple(cols))
    return rows


def split_ref(ref: str, default_slug: str | None) -> tuple[str | None, int]:
    slug, _, num = ref.rpartition("#")
    return (slug or default_slug), int(num)


# --- issue metadata ----------------------------------------------------------

_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
%s
  }
}"""
_FIELDS = (
    "{ __typename ... on Issue { title state stateReason closedAt } "
    "... on PullRequest { title state closedAt mergedAt } }"
)


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def default_repo(run=_run) -> str | None:
    try:
        r = run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
        )
    except OSError:
        return None
    slug = r.stdout.strip()
    return slug if r.returncode == 0 and _SLUG.match(slug) else None


def fetch_meta(slug: str, numbers, run=_run) -> dict[int, dict | None]:
    """{number: metadata, or None when gh resolves no issue or PR}. Raises GhError."""
    owner, name = slug.split("/", 1)
    out: dict[int, dict | None] = {}
    numbers = sorted(set(numbers))
    for i in range(0, len(numbers), BATCH):
        chunk = numbers[i : i + BATCH]
        body = "\n".join(
            f"    n{n}: issueOrPullRequest(number: {n}) {_FIELDS}" for n in chunk
        )
        argv = ["gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}"]
        argv += ["-f", f"query={_QUERY % body}"]
        try:
            r = run(argv)
        except OSError as e:
            raise GhError(f"gh couldn't run: {e}") from None
        # An alias gh can't resolve is a NOT_FOUND error beside the others'
        # data, and gh exits 1 [measured 2026-10-20], so stdout is read first.
        try:
            reply = json.loads(r.stdout)
        except ValueError:
            reply = None
        data = reply.get("data") if isinstance(reply, dict) else None
        if not isinstance(data, dict):
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise GhError(
                f"gh api graphql for {slug}: {msg[-1] if msg else f'exit {r.returncode}'}"
            )
        repo = data.get("repository")
        if not isinstance(repo, dict):
            for n in chunk:
                out[n] = None
            continue
        for n in chunk:
            item = repo.get(f"n{n}")
            out[n] = item if isinstance(item, dict) and item.get("__typename") else None
    return out


def describe(meta: dict) -> dict:
    """The `issue` object sent: kind, title, state, and when and why it closed."""
    kind = "pull request" if meta.get("__typename") == "PullRequest" else "issue"
    state = str(meta.get("state", "")).lower()
    issue = {"kind": kind, "title": meta.get("title", ""), "state": state}
    if meta.get("stateReason") and state != "open":
        issue["closed_as"] = str(meta["stateReason"]).lower().replace("_", " ")
    when = meta.get("mergedAt") or meta.get("closedAt")
    if when and state != "open":
        issue["closed_on"] = str(when)[:10]
    return issue


# --- the case ----------------------------------------------------------------


def build_case(
    sentence: str, heading: str | None, ref: str, issue: dict
) -> tuple[dict, dict]:
    """(state, questions) for one occurrence: exactly what is sent, and what #438 measured."""
    state = {"sentence": sentence, "reference": ref, "issue": issue}
    if heading:
        state["section"] = heading
    if issue["state"] == "open":
        questions = {"already_done": {"type": "noul", "instructions": ALREADY_DONE}}
    else:
        questions = {"still_open": {"type": "noul", "instructions": STILL_OPEN}}
    return state, questions


def locate(rows, root: Path, default_slug: str | None) -> list[Row]:
    """One Row per occurrence of each verifier row's reference in its file."""
    texts: dict[str, list | None] = {}
    out = []
    for verdict, klass, fname, ref, evidence in rows:
        base = dict(
            verdict=verdict, klass=klass, file=fname, ref=ref, evidence=evidence
        )
        if verdict != "TRUE":
            out.append(Row(**base, status="unverifiable"))
            continue
        if fname not in texts:
            path = Path(fname) if Path(fname).is_absolute() else root / fname
            try:
                # UTF-8, not the locale's encoding, or a non-UTF-8 locale
                # would send mojibake (CR 423).
                text = path.read_text(encoding="utf-8", errors="replace")
                texts[fname] = _sentences.occurrences(text)
            except OSError:
                texts[fname] = None
        found = [o for o in (texts[fname] or []) if o.ref == ref]
        if not found:
            out.append(Row(**base, status="not-found"))
            continue
        slug, _ = split_ref(ref, default_slug)
        repo_name = (slug or "").rpartition("/")[2].lower()
        for o in found:
            row = Row(**base, line=o.line, sentence=o.sentence, heading=o.heading)
            if o.in_code:
                row.status = "code"
            elif o.short_repo and o.short_repo.lower() != repo_name:
                row.status = "short-repo"
            elif slug is None:
                row.status = "unresolved"
            out.append(row)
    return out


# --- output ------------------------------------------------------------------


def _cell(v) -> str:
    return re.sub(r"[\t\r\n]+", " ", "" if v is None else str(v))


def render(rows: list[Row], threshold: float) -> str:
    judged = sorted((r for r in rows if r.p is not None), key=lambda r: -r.p)
    rest = sorted((r for r in rows if r.p is None), key=lambda r: (r.file, r.line or 0))
    lines = []
    for r in judged + rest:
        p = "" if r.p is None else f"{r.p:.3f}"
        flag = "stale?" if r.p is not None and r.p >= threshold else ""
        cols = [r.verdict, r.klass, r.file, r.ref, r.evidence, r.line, r.kind, r.state]
        cols += [r.question, p, flag, r.status, r.sentence]
        lines.append("\t".join(_cell(c) for c in cols))
    return "".join(f"{line}\n" for line in lines)


def summary(rows: list[Row], threshold: float) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    flagged = sum(1 for r in rows if r.p is not None and r.p >= threshold)
    refs = len({(r.file, r.ref) for r in rows})
    parts = [f"{counts.pop('judged', 0)} judged ({flagged} at or over {threshold:g})"]
    parts += [f"{n} {s}" for s, n in sorted(counts.items())]
    return (
        f"stale-issue-prose: {len(rows)} occurrences of {refs} references: "
        + ", ".join(parts)
    )


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
    opts = {"tsv": None, "repo": None, "threshold": DEFAULT_THRESHOLD, "dry_run": False}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            opts["help"] = True
            return opts
        if a in ("--repo", "--threshold"):
            v = next(it, None)
            if v is None:
                raise UsageError(f"{a} needs a value")
            if a == "--repo":
                if not _SLUG.match(v):
                    raise UsageError(f"--repo is owner/repo, not {v!r}")
                opts["repo"] = v
            else:
                opts["threshold"] = _threshold(v)
        elif a == "--dry-run":
            opts["dry_run"] = True
        elif a.startswith("-") and a != "-":
            raise UsageError(f"unknown option {a}")
        elif opts["tsv"] is not None:
            raise UsageError(f"one TSV only; got {opts['tsv']!r} and {a!r}")
        else:
            opts["tsv"] = a
    return opts


def _root() -> Path:
    r = _run(["git", "rev-parse", "--show-toplevel"])
    return (
        Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path.cwd()
    )


def main(
    argv: list[str], stdin=None, stdout=None, stderr=None, run=_run, connect=None
) -> int:
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
        if opts["tsv"] in (None, "-"):
            tsv = read_tsv(stdin)
        else:
            try:
                with open(opts["tsv"], encoding="utf-8", errors="replace") as f:
                    tsv = read_tsv(f)
            except OSError as e:
                raise UsageError(f"can't read {opts['tsv']}: {e.strerror}") from None
    except UsageError as e:
        say(f"stale-issue-prose: {e}")
        say(
            "usage: stale-issue-prose.sh [TSV] [--repo SLUG] [--threshold P] [--dry-run]"
        )
        return EXIT_USAGE

    threshold = opts["threshold"]
    if not tsv:
        say(
            "stale-issue-prose: the TSV has no issue rows; run verify-facts.sh "
            "with --issues to resolve references"
        )

    # Connect before asking gh anything: a run that will skip has no use for
    # the default repo or the metadata (CR 424).
    client = None
    if not opts["dry_run"]:
        try:
            # The client's per-call lines go where this run's own do (CR 425).
            client = connect(stderr=stderr)
        except _typesafe.Skipped as s:
            say(s.line)
            rows = locate(tsv, _root(), opts["repo"])
            for r in rows:
                if r.status in ("", "unresolved"):
                    r.status = "skipped"
            stdout.write(render(rows, threshold))
            say(summary(rows, threshold))
            return EXIT_SKIPPED

    needs_default = any(r[0] == "TRUE" and not r[3].rpartition("#")[0] for r in tsv)
    slug = opts["repo"] or (default_repo(run) if needs_default else None)
    exit_code = 0
    if needs_default and slug is None:
        say(
            "stale-issue-prose: no --repo, and gh can't infer one: bare #N references go unjudged"
        )
        # A gh failure, so exit 2: exit 0 would call a ranking complete that
        # left most of a typical file's references out (CR 432).
        exit_code = EXIT_FAILED
    rows = locate(tsv, _root(), slug)

    # Metadata, one query per repo per BATCH references.
    wanted: dict[str, set] = {}
    for r in rows:
        if not r.status:
            s, n = split_ref(r.ref, slug)
            wanted.setdefault(s, set()).add(n)
    meta: dict[tuple[str, int], dict | None] = {}
    for s, nums in sorted(wanted.items()):
        try:
            for n, m in fetch_meta(s, nums, run).items():
                meta[(s, n)] = m
        except GhError as e:
            say(f"stale-issue-prose: {e}")
            exit_code = EXIT_FAILED
    for r in rows:
        if r.status:
            continue
        m = meta.get(split_ref(r.ref, slug))
        if m is None:
            r.status = "unresolved"
            continue
        r.meta = describe(m)
        r.kind, r.state = r.meta["kind"], r.meta["state"]
        r.question = "already_done" if r.state == "open" else "still_open"

    pending = [r for r in rows if not r.status]
    if opts["dry_run"]:
        for r in pending:
            state, questions = build_case(r.sentence, r.heading, r.ref, r.meta)
            case = {
                "id": f"{r.file}:{r.line}:{r.ref}",
                "state": state,
                "questions": questions,
            }
            stdout.write(json.dumps(case, ensure_ascii=False) + "\n")
            r.status = "dry-run"
        say(summary(rows, threshold))
        return exit_code

    failed = False
    for r in pending:
        if failed:
            r.status = "not-asked"
            continue
        state, questions = build_case(r.sentence, r.heading, r.ref, r.meta)
        try:
            reply = client.ask(state, questions)
            answer = reply["answers"][r.question]
            p = answer.get("noul") if isinstance(answer, dict) else None
            if (
                not isinstance(p, (int, float))
                or isinstance(p, bool)
                or not 0 <= p <= 1
            ):
                raise _typesafe.TypeSafeError(
                    200, f"answer has no noul probability: {answer!r}"
                )
        except _typesafe.TypeSafeError as e:
            say(str(e))
            r.status, failed, exit_code = "failed", True, EXIT_FAILED
            continue
        r.p, r.status = float(p), "judged"
    stdout.write(render(rows, threshold))
    say(summary(rows, threshold))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
