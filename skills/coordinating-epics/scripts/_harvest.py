#!/usr/bin/env python3
"""harvest-candidates.sh — rank which paragraphs of a closed child bear on which open child.

usage: harvest-candidates.sh --repo OWNER/REPO --epic N --source N
                             [--since TS] [--until TS] [--max-calls N]
                             [--dry-run]

An optional, advisory step for check-in §2 Harvest (gregoryfoster/skills#436).
It reads the source child's comments since its hand-off, splits them into
paragraphs the way GitHub renders them (`_epic_edit.paragraphs`), and pairs
every paragraph with every child of the epic that is still open. A pair is
settled without a call when the paragraph names the child:

  named   the paragraph sits under a `For #N` heading, bold lead or list
          item naming the child, or links `#N` itself. 68 of the 90
          harvested pairs #436 aligned in 4 public epics were named

Every other pair is the residue, and gets one TypeSafe question:

  bears_on  does the paragraph change or settle a fact, contract, interface,
            limit or step that the child's body relies on?

The residue is where a note reaches a child it never names. On the other 22
pairs the Noul put the target first among the open children 14 times and in
the top 3 16 times, against 3 and 12 for plain word matching. Over six whole
threads (1,732 residue rows), each thread's top 20 held 10 of its 16 such
notes, against 5 (#436's measurement, pinned by its fixture). It ranks; it doesn't decide. Read the named rows, then
the residue from the top, and verify each one before writing a "Changed since
filed" comment. Nothing here writes to GitHub.

  --repo       the epic's repository
  --epic       the epic's number. Its open children are the checklist items
               (`- [ ]` / `- [x]` lines carrying a ref) whose issue is open
  --source     the closed child whose thread is harvested
  --since      read comments created after TS (ISO 8601). Default: after the
               last hand-off brief on the source (a comment whose first line
               is a brief's heading), else the whole thread. A "Changed since
               filed" comment is never read: it is a harvest into the thread
  --until      read comments created before TS, for a replay
  --max-calls  refuse, sending nothing, when the residue needs more than N
               calls (default 2500; a thread here measured up to about 2,100)
  --dry-run    print the cases that would be sent, one JSONL case per line
               in scripts/typesafe-eval.py's set format (without `expected`),
               and send nothing. A case's id is `<comment id>:p<k>:<child>`

OUTPUT is TSV on stdout, one row per (paragraph, child), no header:

  status p child comment paragraph

  status     named, judged, or why it wasn't judged: skipped | failed |
             not-asked (TypeSafe skipped, failed, or wasn't reached after a
             failure) | would-ask (--dry-run)
  p          the Noul, 3 places; empty unless judged
  child      the open child, as `#N` or `owner/repo#N`
  comment    the source comment's URL
  paragraph  its text, tabs and newlines as spaces

Named rows come first in thread order, then judged rows, likeliest first,
then the rest in thread order. A summary goes to stderr, with the first of
the client's per-call lines and a count of the others.

SENDING follows the TypeSafe client beside this file (`python3 _typesafe.py
--help`): nothing leaves the machine until the checkout you run from opts in,
with TYPESAFE_OPT_IN=on or `.skills/typesafe`. Run it from the epic's own
repo, so a private repo decides for itself. A request carries one paragraph,
the source's ref, and one child's number, title and body (clipped to
MAX_BODY_CHARS). Nothing else.

exit codes:
  0  every pair was named or judged (with --dry-run: printed)
  1  usage error, or a residue over --max-calls (nothing was sent)
  2  gh failed (its stderr shown), or a TypeSafe failure (its message on
     stderr). After a TypeSafe failure the rows are still printed
  4  skipped: not opted in, or no key (the client's line on stderr). The rows
     are still printed, the residue unjudged
  Exits 2 and 4 are advisory: harvest by reading, as if the step hadn't run.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` drops it
import _typesafe  # noqa: E402
from _epic_edit import (  # noqa: E402
    Infra,
    box_state,
    gh_cause,
    gh_json,
    key,
    line_ref,
    paragraphs,
    refs_in,
)
from _scan import CAPPED, pages, utc_z  # noqa: E402

DEFAULT_MAX_CALLS = 2500
# About 16k tokens at the client's 3 bytes a token: half the 32k a question
# may carry. The largest child body in #436's four epics is 32,100 characters.
MAX_BODY_CHARS = 48_000

EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_SKIPPED = 4

# The wording #436 measured: 156 cases (22 unnamed pairs against their open
# children) and 1,732 whole-thread residue rows. A reworded question needs a
# re-measure on the committed set.
BEARS_ON = (
    "`paragraph` comes from a comment on a closed child issue of an epic: its "
    "close-out report, a review round, or notes it left. `child` is another "
    "child of the same epic, still open; an agent will implement it later from "
    "its title and body. Does `paragraph` change or settle a fact, contract, "
    "interface, limit or step that `child.body` relies on, so that the agent "
    "implementing `child` needs to read it? Answer no when the paragraph "
    "concerns only the closed issue's own work, or bears on the epic in general "
    "but not on this child's work."
)
QUESTIONS = {"bears_on": {"type": "noul", "instructions": BEARS_ON}}

# A hand-off brief's first line: "## Coordinator brief: #N", "## Brief
# (coordinator, …)", "## Hand-off brief: #N", or the bold forms.
BRIEF_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|\*\*)\s*(?:coordinator brief|hand-off brief|brief\b)", re.I
)
CHANGED_RE = re.compile(r"^\s*(?:#{1,6}\s+|\*\*)\s*changed since filed", re.I)
# "For #N:", "For #N, #M and owner/repo#K", "For `#N`" — the list after "For".
FOR_RE = re.compile(
    r"\b[Ff]or\s+((?:`?(?:[\w.-]+/[\w.-]+)?#\d+`?"
    r"(?:\s*,\s*(?:and\s+)?|\s*/\s*|\s+and\s+)?)+)"
)
REF_IN_FOR = re.compile(r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


class UsageError(Exception):
    pass


@dataclass
class Child:
    key: str  # _epic_edit.key form: owner/repo#N, lowercased
    label: str  # as printed: #N in the epic's repo, else owner/repo#N
    number: int
    title: str
    body: str


@dataclass
class Para:
    comment_id: int
    url: str
    k: int  # its index in the comment's paragraphs
    text: str
    named: set[str] = field(default_factory=set)  # child keys it names


@dataclass
class Row:
    para: Para
    child: Child
    status: str = ""
    p: float | None = None


# --- what a paragraph names ---------------------------------------------------


def for_keys(line: str, host: str) -> set[str]:
    """The refs a `For …` list on this line names."""
    out = set()
    for m in FOR_RE.finditer(line):
        for r in REF_IN_FOR.finditer(m.group(1)):
            out.add(key(r.group("repo"), r.group("num"), host))
    return out


def scope_names(texts: list[str], host: str) -> list[set[str]]:
    """For each paragraph of one comment, the children a `For #N` scope over it names.

    A scope opens at a heading, a bold lead (`**For #N:**`) or a list item
    whose first line names children in a `For …` list. A heading's scope runs
    to the next heading; a bold lead's over the list items under it, to the
    next plain paragraph; an item's over the items indented under it.
    """
    out: list[set[str]] = []
    scope: list[tuple[int, set[str], str]] = []  # (indent, keys, kind)
    for text in texts:
        first = text.split("\n", 1)[0]
        indent = len(first) - len(first.lstrip())
        head, item = HEADING_RE.match(first), ITEM_RE.match(first)
        if head:
            scope = []
        elif item:
            scope = [s for s in scope if s[2] != "item" or s[0] < indent]
        elif indent == 0:
            scope = [s for s in scope if s[2] == "head"]
        own = set()
        if head or item or first.lstrip().startswith("**"):
            own = for_keys(first[:120], host)
        out.append(set().union(own, *(s[1] for s in scope)))
        if own:
            kind = "head" if head else "item" if item else "lead"
            scope.append((indent, own, kind))
    return out


def comment_paras(comment: dict, host: str) -> list[Para]:
    """A comment's paragraphs and table rows, each with the children it names."""
    texts = [t for t, _ in paragraphs((comment.get("body") or "").splitlines())]
    scoped = scope_names(texts, host)
    out = []
    for k, (text, names) in enumerate(zip(texts, scoped)):
        if len(text.strip()) < 3:
            continue
        linked = refs_in(text.splitlines(), host)
        out.append(
            Para(
                comment_id=comment["id"],
                url=comment.get("html_url") or "",
                k=k,
                text=text,
                named=names | linked,
            )
        )
    return out


# --- the case -----------------------------------------------------------------


def build_case(paragraph: str, repo: str, source: int, child: dict) -> tuple:
    """(state, questions) for one (paragraph, child) pair: the shape #436 measured."""
    state = {
        "paragraph": paragraph,
        "from": f"a comment on {repo}#{source}, a closed child of the epic",
        "child": {
            "number": child["number"],
            "title": child["title"],
            "body": child["body"][:MAX_BODY_CHARS],
        },
    }
    return state, QUESTIONS


# --- loading ------------------------------------------------------------------


def _ts(value: str, flag: str) -> str:
    try:
        return utc_z(value)
    except ValueError:
        raise UsageError(f"{flag} wants an ISO 8601 time with a zone, not {value!r}")


def open_children(repo: str, epic: int, source: int) -> list[Child]:
    """The epic's checklist items whose issue is open, in checklist order, less the source."""
    body = gh_json(["api", f"repos/{repo}/issues/{epic}"], "fetching the epic")
    host = repo.lower()
    out, seen = [], {key(None, epic, host), key(None, source, host)}
    for line in (body.get("body") or "").splitlines():
        if box_state(line) is None:
            continue
        ref = line_ref(line, host)
        if not ref or ref[1] in seen:
            continue
        seen.add(ref[1])
        r, num = ref[1].rsplit("#", 1)
        it = gh_json(["api", f"repos/{r}/issues/{num}"], f"fetching {ref[1]}")
        if it.get("state") != "open":
            continue
        out.append(
            Child(
                key=ref[1],
                label=f"#{num}" if r == host else ref[1],
                number=int(num),
                title=it.get("title") or "",
                body=it.get("body") or "",
            )
        )
    return out


def select(comments: list, since: str | None, until: str | None) -> list:
    """The comments to harvest: before UNTIL; after SINCE, else after the last brief.

    A "Changed since filed" comment is the coordinator's own harvest into this
    thread, so it is never read back out of it.
    """
    if until:
        comments = [c for c in comments if utc_z(c["created_at"]) < until]
    if since:
        comments = [c for c in comments if utc_z(c["created_at"]) > since]
    else:
        briefs = [
            i for i, c in enumerate(comments) if BRIEF_RE.match(c.get("body") or "")
        ]
        comments = comments[briefs[-1] + 1 :] if briefs else comments
    return [c for c in comments if not CHANGED_RE.match(c.get("body") or "")]


def thread(repo: str, source: int, since: str | None, until: str | None) -> list:
    path = f"repos/{repo}/issues/{source}/comments"
    return select(list(pages(path, f"reading #{source}'s comments")), since, until)


def to_rows(comments: list, children: list[Child], host: str) -> list[Row]:
    rows = []
    for c in comments:
        for para in comment_paras(c, host):
            for ch in children:
                rows.append(
                    Row(para, ch, status="named" if ch.key in para.named else "")
                )
    return rows


# --- output -------------------------------------------------------------------

_WS = re.compile(r"[\t\r\n]+")


def render(rows: list[Row]) -> str:
    named = [r for r in rows if r.status == "named"]
    judged = sorted(
        (r for r in rows if r.status == "judged"), key=lambda r: -(r.p or 0.0)
    )
    rest = [r for r in rows if r.status not in ("named", "judged")]
    out = []
    for r in named + judged + rest:
        p = f"{r.p:.3f}" if r.p is not None else ""
        text = _WS.sub(" ", r.para.text).strip()
        out.append(f"{r.status}\t{p}\t{r.child.label}\t{r.para.url}\t{text}\n")
    return "".join(out)


def summary(rows: list[Row], children: list[Child], paras: int) -> str:
    by = {}
    for r in rows:
        by[r.status] = by.get(r.status, 0) + 1
    parts = ", ".join(f"{n} {s}" for s, n in sorted(by.items()))
    return (
        f"harvest-candidates: {paras} paragraph(s) x {len(children)} open "
        f"child(ren) = {len(rows)} row(s): {parts or 'none'}"
    )


class _CallLines:
    """Keeps the client's first per-call line and counts the rest; anything else passes.

    Buffered by line: `print` writes the text and its newline separately, so
    a dropped line's newline would otherwise get through as a blank line.
    """

    def __init__(self, stderr):
        self._stderr, self.seen, self.more, self._buf = stderr, False, 0, ""

    def write(self, text: str) -> int:
        self._buf += text
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            if line.startswith("typesafe: answered by"):
                if self.seen:
                    self.more += 1
                    continue
                self.seen = True
            self._stderr.write(line + "\n")
        return len(text)

    def flush(self) -> None:
        if self._buf:
            self._stderr.write(self._buf)
            self._buf = ""
        self._stderr.flush()


def _noul(reply: dict) -> float:
    answer = reply["answers"]["bears_on"]
    p = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0 <= p <= 1:
        # Its shape, never its text: server text reaches stderr only through
        # the client's redaction (#438's CR 404).
        shape = (
            f"an object with {len(answer)} key(s)"
            if isinstance(answer, dict)
            else f"a {type(answer).__name__}"
        )
        raise _typesafe.TypeSafeError(
            200, f"answer for bears_on has no noul probability ({shape})"
        )
    return float(p)


# --- the run ------------------------------------------------------------------


def _int(flag: str, value: str | None) -> int:
    if value is None or not value.isdigit() or int(value) < 1:
        raise UsageError(f"{flag} wants a positive integer, not {value!r}")
    return int(value)


def parse_args(argv: list[str]) -> dict:
    opts = {
        "repo": None,
        "epic": None,
        "source": None,
        "since": None,
        "until": None,
        "max_calls": DEFAULT_MAX_CALLS,
        "dry_run": False,
    }
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            return {"help": True}
        if a == "--dry-run":
            opts["dry_run"] = True
        elif a in ("--repo", "--epic", "--source", "--since", "--until", "--max-calls"):
            v = next(it, None)
            if v is None:
                raise UsageError(f"{a} needs a value")
            name = a[2:].replace("-", "_")
            if name in ("epic", "source", "max_calls"):
                opts[name] = _int(a, v)
            elif name in ("since", "until"):
                opts[name] = _ts(v, a)
            else:
                if not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
                    raise UsageError(f"--repo wants OWNER/REPO, not {v!r}")
                opts[name] = v
        else:
            raise UsageError(f"unknown argument {a}")
    for need in ("repo", "epic", "source"):
        if opts[need] is None:
            raise UsageError(f"--{need} is required")
    return opts


USAGE = (
    "usage: harvest-candidates.sh --repo OWNER/REPO --epic N --source N "
    "[--since TS] [--until TS] [--max-calls N] [--dry-run]"
)


def main(argv: list[str], stdout=None, stderr=None, connect=None, load=None) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    connect = connect or _typesafe.connect

    def say(line: str) -> None:
        print(line, file=stderr)

    try:
        opts = parse_args(argv)
    except UsageError as e:
        say(f"harvest-candidates: {e}")
        say(USAGE)
        return EXIT_USAGE
    if opts.get("help"):
        print(__doc__.strip(), file=stdout)
        return 0

    repo, host = opts["repo"], opts["repo"].lower()
    try:
        if load:
            children, comments = load(opts)
        else:
            children = open_children(repo, opts["epic"], opts["source"])
            comments = thread(repo, opts["source"], opts["since"], opts["until"])
    except Infra as e:
        say(f"harvest-candidates: {gh_cause(e)}")
        return EXIT_FAILED
    for what in CAPPED:
        say(f"harvest-candidates: WARNING {what} stopped at the page cap")

    rows = to_rows(comments, children, host)
    paras = len({(r.para.comment_id, r.para.k) for r in rows})
    pending = [r for r in rows if not r.status]

    def case(r: Row) -> tuple:
        ch = {"number": r.child.number, "title": r.child.title, "body": r.child.body}
        return build_case(r.para.text, repo, opts["source"], ch)

    if opts["dry_run"]:
        for r in pending:
            r.status = "would-ask"
            state, questions = case(r)
            cid = f"{r.para.comment_id}:p{r.para.k}:{r.child.label}"
            stdout.write(
                json.dumps(
                    {"id": cid, "state": state, "questions": questions},
                    ensure_ascii=False,
                )
                + "\n"
            )
        say(summary(rows, children, paras))
        return 0

    lines = _CallLines(stderr)
    client = None
    if pending:
        try:
            # The opt-in first: a repo that never opted in skips (exit 4),
            # however long its thread, rather than hearing about the cap.
            client = connect(stderr=lines)
        except _typesafe.Skipped as s:
            say(s.line)
            for r in pending:
                r.status = "skipped"
            stdout.write(render(rows))
            say(summary(rows, children, paras))
            return EXIT_SKIPPED

    if len(pending) > opts["max_calls"]:
        say(
            f"harvest-candidates: the residue needs {len(pending)} calls, over "
            f"--max-calls {opts['max_calls']}; nothing was sent. Narrow it with "
            "--since / --until, or raise the cap"
        )
        return EXIT_USAGE

    exit_code, failed = 0, False
    for r in pending:
        if failed:
            r.status = "not-asked"
            continue
        try:
            state, questions = case(r)
            r.p = _noul(client.ask(state, questions))
            r.status = "judged"
        except _typesafe.TypeSafeError as e:
            say(str(e))
            r.status, failed, exit_code = "failed", True, EXIT_FAILED
    lines.flush()
    stdout.write(render(rows))
    if lines.more:
        say(f"harvest-candidates: and {lines.more} more answered-by line(s)")
    say(summary(rows, children, paras))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
