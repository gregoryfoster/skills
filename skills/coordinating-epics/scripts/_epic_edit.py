#!/usr/bin/env python3
"""Edit a coordinating-epics epic body: fetch, check, transform, lint, write, read back.

The engine behind epic-edit.sh; run that, not this. Stdlib only, Python 3.9+.

Every check here exists because a coordinator thread once skipped it and
damaged an epic (gregoryfoster/skills#348):

- the transform runs on the body fetched live, in memory, so no stale or empty
  output file can be uploaded (archiver#300 finding 2, watcher#348 F43);
- the live body must equal the last body this tool wrote, or differ only by
  box ticks the caller has verified (address-validator#272 finding 47, the
  seventh run's finding 102). It is fetched again just before the PATCH, and
  any change refuses the write, which leaves a window of one round trip, not
  the whole run, in which a concurrent edit could still be lost (CR 258);
- each operation's anchor must exist, and is found by its ref, never by the
  line's exact old text, so a tick made elsewhere can't break the match
  (the third run's finding 34, broker#80 finding 147);
- checkbox counts are derived from the old body, never typed (seventh 92);
- new lines are linted for refs, placeholders, unexpanded variables, escaped
  backticks, unresolvable comment links and secrets (watcher F61,
  processor F129/F134, broker 120);
- `{now}`, `{today}`, and the scan's `{checked}` and `{last_seen}`, are
  injected, never typed (processor F91/F127, CR 248);
- the write is read back, because an exit code alone proves nothing
  (address-validator 48).
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import html.entities
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

EXIT_OK, EXIT_USAGE, EXIT_INFRA, EXIT_REFUSED, EXIT_READBACK = 0, 1, 2, 3, 4
EXIT_COMMENT = 5

USAGE_EXTRA = """\
operations (a JSON array, from --ops FILE or --ops - for stdin):
  {"op": "tick", "ref": "#12"}                set #12's box to [x]
  {"op": "untick", "ref": "#12"}              set #12's box to [ ]
  {"op": "note", "ref": "#12", "text": "..."} add text as #12's last " · "
                                              field, once; a table row's goes
                                              inside its last cell
  {"op": "set-line", "ref": "#12", "line": "- [x] #12 ..."}
                                              replace #12's line; the new line
                                              must lead with the same ref
  {"op": "add-line", "line": "- [ ] #44 ...", "after_ref": "#43"}
  {"op": "add-line", "line": "- [ ] #44 ...", "section": "Tier 2"}
                                              insert, once; refuses a second
                                              line for a ref that has one.
                                              section is a heading, or the
                                              start of exactly one, up to a
                                              space or a colon: "Tier 2" for
                                              "Tier 2 — bugs". Every other op
                                              takes a heading in full
  {"op": "header", "field": "Last check-in", "value": "{checked}"}
                                              set a "- **Field:** value" line
  {"op": "log", "text": "{today}: #12 closed. No new issues. Next: #13."}
                                              append "- text" to the Log section;
                                              a text's own leading "- " is taken
                                              off, so it isn't doubled, unless
                                              a ref or a box follows it
  {"op": "log-comment", "text": "{today}: #12 closed. Next: #13."}
                                              post the text as a comment on the
                                              epic, first line "**Check-in log,
                                              <date>**" ("date", default
                                              {today}), once the body is
                                              confirmed (#654)
  {"op": "compact", "ref": "#12", "link": "https://github.com/o/r/issues/12#issuecomment-1"}
                                              cut #12's ticked line to "- [x]
                                              **#12** <title> · [verified](link)",
                                              its sub-block dropped (refused
                                              while it holds an open box), a
                                              disposition field kept; "label":
                                              "record" for a comment that holds
                                              the line, not evidence; the title
                                              is the issue's unless "title" is
                                              given (#654)
  {"op": "replace-section", "heading": "Measured state", "text": "..."}
                                              replace a section's body; refused
                                              when it holds a deeper heading,
                                              unless "scope": "tree" takes the
                                              whole subtree (#408)
  {"op": "rename-section", "heading": "Tier 2", "to": "Tier 2 — bugs"}
                                              rename a heading, same level;
                                              refuses a name already a heading
  {"op": "set-preamble", "text": "..."}       replace the text between the title
                                              (if any) and the header's first
                                              "**Field:**" line or the first
                                              section; "" removes it (#413)
  {"op": "set-subline", "ref": "#12", "match": "Open:", "line": "  - Done: ..."}
                                              replace the one sub-bullet under
                                              #12's line whose text (after its
                                              marker, or its box) starts with
                                              match; "line": "" removes it with
                                              its own sub-block (#429)
  {"op": "add-section", "heading": "Log", "text": "...", "before": "Notes"}
                                              add a section, once: before
                                              "before" at its level, else at
                                              the end at the sections' level

  A header op adds a line only for a cursor field the body lacks (Last
  check-in, Last probe, Last issue seen, Last issue seen (owner/repo), Last
  verified SHA, Next); any other field must already be there. It reads unindented lines only, as scan.sh
  does: an indented "**Field:**" line, a checklist item's sub-note or a header
  list set in 1-3 spaces, is skipped, and the summary's notes name it. The
  line joins the top-level "- **Field:**" list holding the cursor lines, else
  the one above the first section, else goes just before that section (a "#"
  title stays above). With add-section, that brings an adopted epic onto the
  template without a hand edit.

  Every header op first turns each paragraph holding a cursor line, such as
  "**Last check-in:** ...", into "- **Field:** value" items, so the header
  converges on one list. A paragraph with a line that isn't an unindented
  field line, or with a setext underline below it, stays as it is, the
  summary's notes say why, and a new line goes below it. After the last op,
  each field a header op set must still be there once, with the value set, or
  the call is refused: run section ops before header ops. Converted lines are
  linted like any changed line, so a legacy value in one (a short ref, say) is
  fixed by a header op on its field in the same call.

  A ref is "#N" for this repo or "owner/repo#N". A ref's line is the checklist
  item, bullet or table row whose first token is that ref, after an optional
  ordinal ("- [x] 12. #447"); a task item's marker may be ordered ("1. [ ]").
  A ref in a code span leads nothing. Outside code, an HTML entity is read as
  the character GitHub renders, before any ref: "&#x23;49" is #49, and the
  "·" spelled "&#183;" names no #183 (#671). The summary's counts read a ticked
  item with a " · not planned" or " · out of epic" field as "disposed", apart
  from "done"; GitHub's [x] tally is the two together. In any text,
  {now} becomes the UTC time (2026-10-14T18:03Z) and {today} the UTC date.
  With --scan FILE (scan.sh's report), {checked} becomes the report's own time
  and {last_seen} its highest number (#58). Write those two into the header's
  Last check-in and Last issue seen: the next scan's window then starts where
  this one looked, not where the write happened. With scan.sh --also,
  {last_seen:owner/repo} is that repo's highest number as owner/repo#N, for
  its "Last issue seen (owner/repo)" line, and each such repo's new issues
  must be mentioned by owner/repo#N, as the host's are by #N (#400).

edit history:
  Each run with a baseline reads the body's edit history (GraphQL) and lists,
  in the summary's foreign_edits, every entry later than the baseline whose
  body no write of this tool produced. Every thread may write as one account,
  so an entry is matched by its body's hash and its time, never by its editor.
  The list is a warning, not a refusal: read those edits before trusting a
  clean diff. An unread history is a warning too (summary "edit_history").

tokens (#520):
  --token-for OWNER/REPO=VAR, repeatable, reads that repo with the token in
  $VAR: the epic's own repo, or the repo of a comment link the lint resolves.
  gh gets it as GH_TOKEN for that repo's calls only; every other call uses the
  ambient token. A mapped variable unset or empty is exit 1, before anything
  is fetched. No token's value is printed: one in gh's stderr shows as <$VAR>.
  A comment link on an unmapped repo that doesn't resolve names any set
  GH_TOKEN_<REPO> or GH_TOKEN_<OWNER>_<REPO> that would read it.

lint:
  Every line the edit adds or changes is linted whole, so ticking a line that
  already holds a short ref or an unexpanded variable is refused with it. That
  is deliberate: legacy text is fixed the first time it is touched. Rewrite the
  line with set-line, then tick. A fenced code block renders as written, so its
  lines are checked for secrets only; a code span skips every check but SUBn
  and secrets. Spans are found as CommonMark finds them, a table row cell by
  cell, so \\`make\\` (the escaped backticks an unquoted heredoc leaves) is
  refused and `App\\Tests\\` is code.

subjects (#662):
  A line's subject is the run of refs it leads with, joined by "+", ",", "&"
  or "and": "- [x] #46 + #47 ..." has two, and refs later in it are mentions.
  With --account, a ticked line whose subject is still open is a WARNING and
  a summary ticked_open entry, never a refusal; ticked_unchecked lists ticked
  subjects in another repo, which the open list can't speak for. That list
  holds issues only, so an open PR as a subject passes unseen. A new or
  changed checkbox line with two or more subjects is a WARNING too
  (multi_subject): a line each lets each box follow its own issue.

exit codes:
  0  written and read back, or nothing to write (every operation already held),
     and each log comment posted, or found already posted
  1  usage error: a bad flag, or a malformed ops or --scan file. Nothing was
     fetched or written.
  2  infrastructure failure (gh or python3 failed; gh's own stderr is shown).
     Nothing was written, including a PATCH gh reported failed when the body
     read afterwards is unchanged.
  3  refused: a foreign edit, a baseline no write or adoption of this tool
     saved (its hash is recorded beside it, in writes.jsonl), a missing
     anchor, a count or lint failure, a new body that grows past
     --body-limit or a log comment past GitHub's 65,536 characters, a header
     line a later op removed or changed, an open issue the epic doesn't list (--account [FROM]), a new
     issue in the --scan report that the body doesn't mention, or a closed
     epic without --closed-ok (the message names who closed it and when; a
     dry run notes it). Nothing was written.
  4  not confirmed. Either written (summary "written": true) but the body read
     back differs from the body sent, the read-back failed, or the baseline
     couldn't be saved; or the PATCH failed and whether it landed is unknown
     ("written": "unknown"). The summary says which. Read the epic, then take
     it with --adopt-live before the next edit. Or not applied ("written":
     false, "readback": "unchanged"): the PATCH returned success, but the body
     read back is the one from before the edit, so nothing landed and the
     baseline still holds. Near --body-limit, the host's size cap is the likely
     cause (#653): make the body smaller, then re-run.
  5  a log comment wasn't posted: gh failed after every check passed. The
     summary says whether the body was written ("readback": "matches" is a
     confirmed write). Re-run the same call: the body ops then hold, and a
     comment already posted is found, not posted twice.

log comments (#658):
  Each call that posts log comments is recorded beside the baseline, in
  comments.jsonl, before its first POST: each comment's hash, in order, and
  the time to search from. Each part posted, or found, is recorded with its
  URL. A re-run of the same comments, in order, resumes the latest call not
  finished: a part it posted is "posted": "already", and a part gh called
  failed but GitHub stored is found among the epic's comments since. A
  finished call is never matched, so two check-ins that log identical text
  post twice. The record is the state dir's (--state-dir): re-run with the
  same one. A state dir from before these records has none, so its first
  call matches by body, as before, and the records start there. A part
  whose POST truly failed, re-run after another state dir posted identical
  text, reads that one as "already".

body size:
  Every summary that built a new body gives its size as GitHub keeps it,
  "body": {"chars", "limit", "share"}, and a WARNING past 85% of the limit.
  Past its cap the host keeps the old body and still reports success (#653),
  so a new body that grows past --body-limit is refused before anything is
  sent. One that shrinks goes through, so room can always be made.
"""

# A task item's marker is a bullet or an ordered one, "1." or "1)", up to
# CommonMark's nine digits: GitHub renders "1. [ ] #348" as a task item (#403).
MARKER = r"(?:[-*+]|[0-9]{1,9}[.)])"
BOX_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>" + MARKER + r") \[(?P<mark>[ xX])\] ")
# GitHub links "pre-#348" and "ver.#3" as this repo's #348 and #3, so a "-" or
# "." before the "#" is prose (#401). A "/" isn't: ref_text turns only GitHub
# issue URLs into refs, and "https://example.com/a/#7" renders as a plain link.
# GitHub's classes are ASCII (#417): an owner is letters, digits and inner
# hyphens, so "v.o/r#5" and "-o/r#5" link o/r#5; a name stops at "é", so
# "o/ré#5" links this repo's #5, as "é#5" does; "#٥" links nothing. The
# closing \b stays Unicode: "#5é" links nothing either.
NOT_IN_WORD = r"(?<![A-Za-z0-9_/])"
OWNER_REPO = r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+"
REF_PAT = NOT_IN_WORD + r"(?:(?P<repo>" + OWNER_REPO + r"))?#(?P<num>[0-9]+)\b"
REF_RE = re.compile(REF_PAT)
# What may stand before a line's leading ref: markup, and an ordinal an epic
# numbers its order with, "- [x] 12. #447" (#403). The ordinal needs whitespace
# after it, as a list marker does, so "1.#5" leads with nothing. A backtick
# isn't markup here: GitHub links no ref in code, and a ref only in code lists
# nothing (#415), so a code-led line is no item, bullet or row (#403).
MARKUP = r"(?:~~|\*\*|\[)*"
LEAD = MARKUP + r"(?:[0-9]{1,9}[.)]\s+)?" + MARKUP
# A lead is a line's structure, then its ref. The structure is read on the
# line as written and only what follows is decoded: a marker, a box or a pipe
# that an entity spells is text on GitHub, never markup (CR 2414).
LEAD_STARTS = (
    ("item", re.compile(r"^\s*" + MARKER + r" \[[ xX]\] ")),
    ("bullet", re.compile(r"^\s*[-*+] ")),
    ("row", re.compile(r"^\|\s*")),
)
LEAD_REF_RE = re.compile(LEAD + REF_PAT)
UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
# A closing #-sequence needs whitespace before it, as in CommonMark, so
# "## Notes on C#" keeps its "#" (CR 255).
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)(?:[ \t]+#+)?[ \t]*$")
FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
FIELD_RE = re.compile(
    r"^(?P<lead>\s*(?:[-*+]\s+)?\*\*(?P<field>[^*]+?):\*\*)(?P<value>.*)$"
)

SHELL_VAR_RE = re.compile(r"\$\{[A-Za-z_]\w*\}|\$[A-Z_][A-Z0-9_]+\b")
# (pattern, what, read inside code spans too). A code span shows `${{ x }}`
# as written, so those two skip spans (CR 290). A SUBn in a span is still a
# leftover. The \` an unquoted heredoc leaves opens no span, so it is read
# outside them, where a backslash escapes (#402); `App\Tests\` is code.
PLACEHOLDER_RES = [
    (re.compile(r"\bSUB\d+\b"), "an unfilled SUBn placeholder", True),
    (re.compile(r"\{\{[^}]*\}\}"), "an unfilled {{...}} placeholder", False),
    (
        re.compile(r"\{(?:now|today|checked|last_seen(?::[^{}\s]*)?)\}"),
        "an uninjected {now}/{today}/{checked}/{last_seen}",
        False,
    ),
    (re.compile(r"(?<!\\)(?:\\\\)*\\`"), "an escaped backtick", False),
]
SECRET_RES = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# Its start is REF_PAT's: GitHub links "v.o/r#5, #6" as o/r#5 and this repo's
# #6 (#417).
BARE_AFTER_QUALIFIED_RE = re.compile(
    NOT_IN_WORD
    + r"(?P<repo>"
    + OWNER_REPO
    + r")#[0-9]+(?:\s*(?:,|/|;|&|\band\b|\bor\b)\s*)(?P<bare>#[0-9]+)\b"
)
# The name must end in a letter, digit or "_": GitHub reads a trailing "-" or
# "." as prose and links the #N after it (#401). "ésk#5" links nothing (#417).
SHORT_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_/.#-])(?P<ref>[A-Za-z](?:[\w.-]*[A-Za-z0-9_])?#\d+)\b"
)
# Link text may hold one level of brackets; the target may be <angled> or hold
# one level of parentheses; the title may be "…", '…' or (…) (CR 271).
LINK_MARK = "\ufffc"  # what a non-issue link reads as: no ref, no separator
MD_LINK_RE = re.compile(
    r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
    r"\((?P<target><[^>]*>|(?:[^()\s]|\([^()\s]*\))*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
# "https://github.com/v.o/r/issues/5" renders as a plain link, not o/r#5 (#417).
_ISSUE_URL = (
    r"https://github\.com/(?P<repo>"
    + OWNER_REPO
    + r")/(?:issues|pull)/(?P<num>[0-9]+)(?![\w/])"
)
GH_ISSUE_URL_RE = re.compile(_ISSUE_URL)
# GitHub renders a bare or <angled> issue URL as its ref, and "Fixes <url>"
# closes the issue (CR 288). A fragment (#issuecomment-…) stays a ref.
ANGLED_ISSUE_URL_RE = re.compile(r"<" + _ISSUE_URL + r"[^<>\s]*>")
# The fragment goes with it, as with the angled form, or "…#issuecomment-1, #6"
# would hide the bare #6 from the lint (CR 311).
BARE_ISSUE_URL_RE = re.compile(r"(?<![\w/<])" + _ISSUE_URL + r"(?:#[\w-]*)?")
# Wider than OWNER_REPO on purpose: it picks the links to resolve, and a
# ".../v.o/r/issues/5#issuecomment-N" that 404s is a finding (CR 335).
COMMENT_LINK_RE = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<num>\d+)#issuecomment-(?P<id>\d+)"
)


class Refused(Exception):
    """A check failed; nothing was written."""


class NotFound(Refused):
    """No line leads with the ref: the one refusal add-line's duplicate guard expects."""


class Infra(Exception):
    """A tool the check depends on failed.

    One raised by gh() also carries gh's own stderr and exit code, so a
    reader can quote the cause without parsing our header off the message,
    which can itself span lines (#410).
    """

    def __init__(self, msg: str, *, stderr: str | None = None, code: int | None = None):
        super().__init__(msg)
        self.stderr, self.code = stderr, code


def gh_cause(e: Infra) -> str:
    """gh's whole stderr, without our "<what>: gh <args> exited N:" header (#410).

    The header is skipped by the attributes gh() sets, not by its text. An
    Infra gh() didn't raise from a non-zero exit (gh not on PATH, non-JSON
    output) has no stderr of its own, and its message is the cause.
    """
    if e.code is None:
        return str(e)
    return e.stderr or f"gh exited {e.code} with no stderr"


def indented(text: str, by: str = "    ") -> str:
    """text with its continuation lines indented, so a multi-line cause reads as one."""
    return f"\n{by}".join(text.splitlines())


class Usage(Exception):
    """The invocation or the ops file is malformed; exit 1, nothing fetched or written."""


class Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; 2 means infrastructure here (CR 249)."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


ACCOUNT_LIMIT = 5000
# Characters, as #653 measured. The host's cap is inferred, not documented:
# 256 KiB, where a 260,219-character body plus 2,100 kept its old body.
BODY_LIMIT = 262_144
BODY_WARN = 0.85

OP_FIELDS = {
    "tick": ("ref",),
    "untick": ("ref",),
    "note": ("ref", "text"),
    "set-line": ("ref", "line"),
    "add-line": ("line",),
    "header": ("field", "value"),
    "log": ("text",),
    "replace-section": ("heading", "text"),
    "add-section": ("heading", "text"),
    "rename-section": ("heading", "to"),
    "set-preamble": ("text",),
    "set-subline": ("ref", "match", "line"),
    "log-comment": ("text",),
    "compact": ("ref", "link"),
}
OP_OPTIONAL = {
    "add-line": ("after_ref", "section"),
    "add-section": ("before",),
    "replace-section": ("scope",),
    "log-comment": ("date",),
    "compact": ("label", "title"),
}
COMPACT_LABELS = ("verified", "record")
# The first line of each comment the coordinator posts as its own (#654).
# scan.sh drops them by this line, never by author: every thread writes as
# one account. A log comment goes on the epic; a record, on a child.
LOG_MARK = "**Check-in log, {date}**"
LOG_MARK_RE = re.compile(r"^\*\*Check-in log, [^*\n]+\*\*\s*$")
RECORD_MARK_RE = re.compile(r"^\*\*Coordinator record, (?P<ref>[^*\n]+?)\*\*\s*$")
# GitHub refuses a longer comment body: "Body is too long" [stated: GitHub's
# own error text, not measured here]. comment.sh reads it from here.
COMMENT_LIMIT = 65_536


def check_ops(ops) -> None:
    """Reject a malformed ops file before anything is fetched."""
    if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
        raise Usage("--ops must be a JSON array of objects")
    for n, op in enumerate(ops, 1):
        kind = op.get("op")
        if (
            not isinstance(kind, str) or kind not in OP_FIELDS
        ):  # unhashable too (CR 270)
            raise Usage(f"op {n}: unknown op {kind!r}")
        allowed = {"op", *OP_FIELDS[kind], *OP_OPTIONAL.get(kind, ())}
        if set(op) - allowed:
            raise Usage(f"op {n} ({kind}): unknown fields {sorted(set(op) - allowed)}")
        for f in OP_FIELDS[kind] + OP_OPTIONAL.get(kind, ()):
            if f in op and not isinstance(op[f], str):
                raise Usage(f"op {n} ({kind}): {f} must be a string")
            if f in OP_FIELDS[kind] and f not in op:
                raise Usage(f"op {n} ({kind}): missing field {f!r}")
        if kind == "add-line" and ("after_ref" in op) == ("section" in op):
            raise Usage(f"op {n} (add-line): give exactly one of after_ref or section")
        # One opt-in, so a typo can't read as the default (#408).
        if "scope" in op and op["scope"] != "tree":
            raise Usage(f'op {n} ({kind}): scope must be "tree", not {op["scope"]!r}')
        if kind == "set-subline" and not op["match"].strip():
            raise Usage(f"op {n} (set-subline): match must be non-empty")
        if kind == "compact" and op.get("label", "verified") not in COMPACT_LABELS:
            raise Usage(
                f"op {n} (compact): label must be one of {COMPACT_LABELS}, not"
                f" {op['label']!r}"
            )
        if kind == "log-comment" and (
            "\n" in op.get("date", "") or "*" in op.get("date", "")
        ):
            raise Usage(f"op {n} (log-comment): date must be one line with no '*'")
        for f in ("ref", "after_ref"):  # a typo is usage, not a refusal (CR 293)
            if f in op and not re.fullmatch(r"\s*" + REF_PAT + r"\s*", op[f]):
                raise Usage(f"op {n} ({kind}): {f} {op[f]!r} is not #N or owner/repo#N")


# ---------------------------------------------------------------- body model


def normalize(body: str) -> list[str]:
    """Lines for comparison: CRLF folded, trailing whitespace and blank tail dropped.

    GitHub drops a body's final newline and may return CRLF, so a raw compare
    is never equal (address-validator#272 finding 47).
    """
    lines = [ln.rstrip() for ln in body.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def split_raw(body: str) -> list[str]:
    """Lines to edit: CRLF folded and the blank tail dropped, nothing else.

    Trailing spaces stay: two of them are a Markdown hard line break, and an
    edit must not rewrite lines its operations never touched.
    """
    lines = body.replace("\r\n", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


CURSOR_FIELDS = {
    f.lower(): f
    for f in (
        "Last check-in",
        "Last probe",
        "Last issue seen",
        "Last verified SHA",
        "Next",
    )
}


PER_REPO_CURSOR_RE = re.compile(
    r"last issue seen \((?P<repo>" + OWNER_REPO + r")\)", re.IGNORECASE
)
# {last_seen:owner/repo}: an --also repo's highest number, qualified (#400).
LAST_SEEN_FOR_RE = re.compile(r"\{last_seen:(?P<repo>[^{}\s]*)\}")


def per_repo_cursor(field: str) -> str | None:
    """The lowercased owner/repo of a "Last issue seen (owner/repo)" field, or
    None: an --also repo's own watermark (#400)."""
    m = PER_REPO_CURSOR_RE.fullmatch(field.strip())
    return m.group("repo").lower() if m else None


def is_cursor_line(line: str) -> bool:
    """A header cursor line, whose refs (Last issue seen, Next) track no issue.

    Only these: a tier line "- **#15:** …" or a log line "**2026-10-14:** #15 …"
    mentions #15 (CR 278). Top-level only, as #528 reads the header: an indented
    "  - **Next:** #14" is a checklist item's sub-note, and it names #14 (#535).
    """
    m = FIELD_RE.match(line)
    return (
        bool(m)
        and not line[:1].isspace()
        and (
            m.group("field").strip().lower() in CURSOR_FIELDS
            or per_repo_cursor(m.group("field")) is not None
        )
    )


def trailing(line: str) -> str:
    """A line's trailing whitespace: two spaces of it are a hard line break."""
    return line[len(line.rstrip()) :]


def field_end(text: str, row: bool) -> bool:
    """True where a note starts a field by itself, with no " · " before it.

    That is after a separator, or at the start of a row's empty last cell.
    """
    text = text.rstrip()
    return text.endswith("·") or (
        row and text.endswith("|") and not text.endswith("\\|")
    )


def fenced(lines: list[str]) -> list[bool]:
    """True for each line inside (or opening/closing) a fenced code block.

    CommonMark's rules (CR 246): a closing fence uses the opener's character,
    is at least as long, and carries no info string. So a ```` block can hold
    ``` examples, and ```python inside a block doesn't close it.
    """
    out: list[bool] = []
    opener = ""
    for ln in lines:
        m = FENCE_RE.match(ln)
        if not opener:
            fence = m.group("fence") if m else ""
            if m and not (fence[0] == "`" and "`" in m.group("info")):
                opener = fence
                out.append(True)
            else:
                out.append(False)
            continue
        out.append(True)
        if (
            m
            and m.group("fence")[0] == opener[0]
            and len(m.group("fence")) >= len(opener)
            and not m.group("info").strip()
        ):
            opener = ""
    return out


DELIM_CELL_RE = re.compile(r"\s*:?-+:?\s*")
# What ends a table besides a blank line: another block (measured: a list item).
TABLE_BREAK_RE = re.compile(r"^\s*(?:>|#{1,6}(?:\s|$)|[-*+]\s|\d{1,9}[.)]\s)")


def cells(line: str) -> list[str]:
    """A table row's cells, split on unescaped pipes; its outer pipes are no cell."""
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return UNESCAPED_PIPE_RE.split(s)


def tabled(lines: list[str]) -> list[bool]:
    """True for each line of a GFM table, where pipes split cells before code spans.

    A table is a header row, then a delimiter row with a pipe and as many cells,
    then every line up to a blank one or another block, with or without a
    leading pipe (CR 328). `x | #6 y` in a row is two cells, and #6 is linked.
    """
    fence = fenced(lines)
    out = [False] * len(lines)
    i = 0
    while i + 1 < len(lines):
        head, delim = lines[i], lines[i + 1]
        if (
            fence[i]
            or fence[i + 1]
            or "|" not in delim
            or TABLE_BREAK_RE.match(head)
            or not all(DELIM_CELL_RE.fullmatch(c) for c in cells(delim))
            or len(cells(head)) != len(cells(delim))
        ):
            i += 1
            continue
        j = i + 2
        while (
            j < len(lines)
            and lines[j].strip()
            and not fence[j]
            and not TABLE_BREAK_RE.match(lines[j])
        ):
            j += 1
        out[i:j] = [True] * (j - i)
        i = j
    return out


def key(repo: str | None, num: str | int, host: str) -> str:
    return f"{(repo or host).lower()}#{int(num)}"


def parse_ref(ref: str, host: str) -> str:
    m = re.fullmatch(r"\s*" + REF_PAT + r"\s*", ref)
    if not m:
        raise Refused(f"not a ref: {ref!r} (want #N or owner/repo#N)")
    return key(m.group("repo"), m.group("num"), host)


# GitHub decodes an HTML entity in Markdown text before it links refs (#671):
# "&#x23;49" links #49, the "#183" of "&#183;" (a "·") links nothing, and
# "#5&#52;" links #54. Its rules are not html.unescape's [each measured with
# gh api markdown, 2026-11-20]: the ";" is required ("&#35 58" links #35); a
# numeric entity has 1 to 8 digits, decimal or hex; a name is one of HTML5's;
# and an "&" that a backslash escapes starts none ("\&#35;51" links #35). The
# first alternative reads an escaped character past, so "\\&#35;88" is an
# escaped backslash and then an entity.
ENTITY_RE = re.compile(
    r"\\[!-/:-@\[-`{-~]"
    r"|&(?:#(?P<dec>[0-9]{1,8})|#[xX](?P<hex>[0-9A-Fa-f]{1,8})"
    r"|(?P<name>[A-Za-z][A-Za-z0-9]{1,31}));"
)


def decode_entities(text: str) -> str:
    """The text with each HTML entity as the character GitHub renders.

    One pass, as GitHub makes: "&amp;#183;" is the text "&#183;", whose #183
    it links. A code point that is 0, a surrogate or past U+10FFFF renders as
    U+FFFD. An unknown name is left as written.
    """

    def sub(m: re.Match) -> str:
        if m.group("name"):
            return html.entities.html5.get(m.group("name") + ";", m.group(0))
        if m.group("dec") or m.group("hex"):
            cp = int(m.group("dec") or m.group("hex"), 10 if m.group("dec") else 16)
            bad = cp == 0 or 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF
            return "\ufffd" if bad else chr(cp)
        return m.group(0)  # an escaped character, kept as written

    return ENTITY_RE.sub(sub, text) if "&" in text else text


def ref_text(line: str, entities: bool = True) -> str:
    """The line as refs read it: a link to an issue becomes its ref; any other, nothing.

    `[#400](https://github.com/o/r/issues/400)` is o/r#400, not this repo's #400,
    and `[plan](docs/plan.md#2-steps)` or `[s](#3-rescan)` holds no ref (CR 247).
    GitHub doesn't autolink inside link text, so `[see #5](doc)` holds none
    either (CR 271). Reference-style links (`[text][id]`) aren't resolved: their
    text reads as plain text. A bare or <angled> issue URL is its ref (CR 288).

    Entities are decoded last (#671). A decoded character is text, never
    markup: "&#91;#57&#93;(url)" makes no link, and #57 is linked. For the
    same reason line_subjects reads a line's marker before it decodes. A URL is
    read as written, since GitHub leaves an entity in a bare one alone. It
    does decode one inside a link target or an <angled> URL, which this
    doesn't: an under-read, accepted. entities=False is for text GitHub
    doesn't render as Markdown, a commit message: "&#183;" there references
    #183 [measured: 608c8094 on gregoryfoster/skills#183].
    """

    def sub(m: re.Match) -> str:
        u = GH_ISSUE_URL_RE.match(m.group("target").strip("<>"))
        # A neutral mark, not "": dropping the link could join a qualified ref
        # and a bare one into what reads as "a/b#5, #6" (CR 277).
        return f"{u.group('repo')}#{u.group('num')}" if u else LINK_MARK

    def as_ref(m: re.Match) -> str:
        return f"{m.group('repo')}#{m.group('num')}"

    line = MD_LINK_RE.sub(sub, line)
    line = BARE_ISSUE_URL_RE.sub(as_ref, ANGLED_ISSUE_URL_RE.sub(as_ref, line))
    return decode_entities(line) if entities else line


# Each ref after a line's lead that continues its subject (#662): a "+", ",",
# "&" or "and", with markup closing the ref before and opening the next, as in
# "**#46** + **#47**". Text of any other kind ends the run. What follows a
# line's marker is decoded first, so an entity is already its character:
# "&amp;" is the "&" joiner, and "&#183;" is a "·", which joins nothing
# (CR 2314, #671).
SUBJECT_NEXT_RE = re.compile(
    r"(?:~~|\*\*|\])*\s*(?:\+|,|&|\band\b)\s*" + MARKUP + REF_PAT
)


def line_subjects(line: str, host: str) -> tuple[str, list[str]] | None:
    """(kind, keys) when the line is an item, bullet or row led by a ref.

    The keys are its subject: the run of refs it leads with, so
    "- [x] #46 + #47 title" has two, and refs later in the line are mentions
    (#662, decided 2026-11-15). The first is the lead every op finds it by.
    """
    line = ref_text(line, entities=False)
    for kind, start in LEAD_STARTS:
        s = start.match(line)
        if not s:
            continue
        rest = decode_entities(line[s.end() :])
        m = LEAD_REF_RE.match(rest)
        if m:
            out = [key(m.group("repo"), m.group("num"), host)]
            pos = m.end()
            while n := SUBJECT_NEXT_RE.match(rest, pos):
                out.append(key(n.group("repo"), n.group("num"), host))
                pos = n.end()
            # "#46 + #47 + #46" names #46 once (CR 2317).
            return kind, list(dict.fromkeys(out))
    return None


def line_ref(line: str, host: str) -> tuple[str, str] | None:
    """(kind, key) when the line is an item, bullet or row led by a ref."""
    ls = line_subjects(line, host)
    return (ls[0], ls[1][0]) if ls else None


def show_key(ref_key: str, host: str) -> str:
    """A key as its ref is written: "#12" in this repo, "owner/repo#12" in another."""
    mine = host.lower() + "#"
    return "#" + ref_key[len(mine) :] if ref_key.startswith(mine) else ref_key


def unmarked_lead(line: str, host: str) -> str | None:
    """The key a line starts with while leading nothing: "#12 title" or
    "[ ] #12 title", a ref with no item, bullet or row to hold it
    (CannObserv/processor#84 F9, #670)."""
    if line_ref(line, host):
        return None
    lr = line_ref("- " + line.lstrip(), host)
    return lr[1] if lr else None


def why_no_lead(line: str, ref: str, host: str) -> str:
    """What a line that doesn't lead with ref is missing, for set-line's refusal."""
    lr = line_ref(line, host)
    if lr:
        return f"it leads with {show_key(lr[1], host)}"
    starts = unmarked_lead(line, host)
    if starts:
        return (
            f"it starts with {show_key(starts, host)}, but isn't a checklist item,"
            f' a bullet or a table row. Start it "- [ ] {ref}", "- [x] {ref}",'
            f' "- {ref}" or "| {ref}"'
        )
    return (
        "its first token isn't a ref. A ref leads when it comes first after the"
        " marker, with at most an ordinal and markup before it, and outside code"
    )


def ticked_subjects(
    lines: list[str], host: str, open_keys: set[str]
) -> tuple[list[dict], list[str]]:
    """Each ticked item outside fences whose subject is in open_keys, as
    {"line", "open"}, and the ticked subjects in another repo, which
    open_keys can't speak for (#662)."""
    fence = fenced(lines)
    mine = host.lower() + "#"
    found: list[dict] = []
    other: dict[str, None] = {}
    for i, ln in enumerate(lines):
        if fence[i] or box_state(ln) != "done":
            continue
        ls = line_subjects(ln, host)
        if not ls:
            continue
        other.update((s, None) for s in ls[1] if not s.startswith(mine))
        still = [s for s in ls[1] if s in open_keys]
        if still:
            found.append(
                {"line": ln.strip(), "open": ["#" + s[len(mine) :] for s in still]}
            )
    return found, list(other)


def find_ref_line(
    lines: list[str], ref_key: str, host: str, want_item: bool = False
) -> int:
    fence = fenced(lines)
    hits: dict[str, list[int]] = {"item": [], "bullet": [], "row": []}
    for i, ln in enumerate(lines):
        if fence[i]:
            continue
        lr = line_ref(ln, host)
        if lr and lr[1] == ref_key:
            hits[lr[0]].append(i)
    kinds = ["item"] if want_item else ["item", "bullet", "row"]
    for kind in kinds:
        if len(hits[kind]) == 1:
            return hits[kind][0]
        if len(hits[kind]) > 1:
            raise Refused(
                f"{ref_key}: {len(hits[kind])} {kind} lines lead with it; ambiguous"
            )
    what = "checklist item" if want_item else "item, bullet or table row"
    raise NotFound(f"{ref_key}: no {what} leads with it")


def lead_counts(lines: list[str], host: str) -> dict[tuple[str, str], int]:
    """How many lines each ref leads, by kind (item, bullet, row), outside fences."""
    fence = fenced(lines)
    out: dict[tuple[str, str], int] = {}
    for i, ln in enumerate(lines):
        lr = None if fence[i] else line_ref(ln, host)
        if lr:
            out[lr] = out.get(lr, 0) + 1
    return out


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    fence = fenced(lines)
    out = []
    for i, ln in enumerate(lines):
        if fence[i]:
            continue
        m = HEADING_RE.match(ln)
        if m:
            out.append((i, len(m.group("hashes")), m.group("text").strip()))
    return out


def section_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """headings() less a title: a first "#" heading with every other one deeper.

    Only "#": a "## Children" over "### Tier" headings is a section, and a
    new section beside it must be "##", not "###" inside it. A lone "#" is a
    title too, so adoption under it adds "##" sections, not "#" (CR 315).
    """
    hs = headings(lines)
    if hs and hs[0][1] == 1 and all(lvl > 1 for _, lvl, _ in hs[1:]):
        return hs[1:]
    return hs


def section_level(lines: list[str]) -> int:
    """The level a new last section takes: the shallowest the sections use.

    A title isn't a section, so "# Burn-down" over "##" sections gives 2
    (CR 305). No sections: 2.
    """
    return min((lvl for _, lvl, _ in section_headings(lines)), default=2)


def heading_by_prefix(lines: list[str], heading: str) -> str | None:
    """The one heading that starts with `heading` and goes on after white
    space or a colon, when no heading is `heading` itself: "Tier 2" finds
    "Tier 2 — bugs" or "Tier 2: bugs", never "Tier 20" or "Tier 2.5"
    (CR 2416), and "Log" never finds "Logistics".

    For add-line's section alone (CannObserv/processor#84 F10, #670): there a
    wrong guess adds one line. In section_span it would let the log op write
    into another section, and replace-section replace one the op didn't name.
    """
    want = heading.strip().lower()
    texts = [t for _, _, t in headings(lines)]
    if not want or any(t.lower() == want for t in texts):
        return None
    found = [
        t
        for t in texts
        if t.lower().startswith(want)
        and len(t) > len(want)
        and (t[len(want)].isspace() or t[len(want)] == ":")
    ]
    return found[0] if len(found) == 1 else None


def section_span(lines: list[str], heading: str) -> tuple[int, int]:
    """(index of the heading line, index one past the section's last line)."""
    hs = headings(lines)
    want = heading.strip().lower()
    found = [(i, lvl) for i, lvl, text in hs if text.lower() == want]
    if not found:
        # The refusal names what there is to choose from (F10): the headings
        # that start with the text given, or with none, all of them.
        texts = [t for _, _, t in hs]
        near = [t for t in texts if want and t.lower().startswith(want)]
        if near:
            hint = ". Headings that start with it: "
        elif texts:
            hint = ". The headings are: "
        else:
            hint = "; the body has no headings"
        raise Refused(
            f"no section headed {heading!r}"
            + hint
            + ", ".join(repr(t) for t in near or texts)
        )
    if len(found) > 1:
        raise Refused(f"{len(found)} sections headed {heading!r}; ambiguous")
    start, level = found[0]
    end = len(lines)
    for i, lvl, _ in hs:
        if i > start and lvl <= level:
            end = i
            break
    return start, end


LIST_MARK_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)")


def after_block(lines: list[str], i: int) -> int:
    """The index just past line i and the lines indented under it (CR 250).

    Inserting at i + 1 would put a new item between an item and its
    sub-bullets, and re-parent them under the new one. Blank lines inside
    the block don't end it while deeper lines follow (CR 266). After a blank
    line, a line belongs to the item only at the item's content column, as
    in CommonMark: a top-level paragraph indented one space doesn't (CR 283).
    """

    def indent(ln: str) -> int:
        return len(ln.expandtabs(4)) - len(ln.expandtabs(4).lstrip())

    base = indent(lines[i])
    m = LIST_MARK_RE.match(lines[i].expandtabs(4))
    content = len(m.group(0)) if m else base + 1
    end, j, after_blank = i + 1, i + 1, False
    while j < len(lines):
        if not lines[j].strip():
            after_blank = True
        elif indent(lines[j]) >= (content if after_blank else base + 1):
            end, after_blank = j + 1, False
        else:
            break
        j += 1
    return end


def indent_of(line: str) -> int:
    """A line's indent in columns, tabs at 4, as after_block reads it."""
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())


def sub_bullets(lines: list[str], i: int, match: str) -> list[int]:
    """The list items in line i's block whose text starts with match (#429).

    The text is read after the marker, and after a box too, so "Open:" finds
    "  - [ ] Open: …" and "[x] verify" finds "  - [x] verify …". Any depth.
    """
    fence, out = fenced(lines), []
    for j in range(i + 1, after_block(lines, i)):
        m = LIST_MARK_RE.match(lines[j])
        if fence[j] or not m:
            continue
        text = lines[j][m.end() :]
        unboxed = re.sub(r"^\[[ xX]\]\s+", "", text)
        if text.startswith(match) or unboxed.startswith(match):
            out.append(j)
    return out


def clean_title(title: str, child: str | None, host: str) -> str:
    """An issue's title, made safe to stand in a checklist line (#654).

    A "·" would start a field, so it becomes "-"; then no word of it is a
    field, and "not planned" in it disposes nothing. A bare name#N, which
    links nowhere, goes into a code span. In another repo's title a bare #N
    is that repo's, so it is qualified.
    """
    t = " ".join(title.split()).replace("·", "-")
    t = SHORT_REF_RE.sub(lambda m: f"`{m.group('ref')}`", t)
    if child and child.lower() != host.lower():
        t = REF_RE.sub(
            lambda m: m.group(0) if m.group("repo") else f"{child}#{m.group('num')}",
            t,
        )
    return t


def preamble_span(lines: list[str]) -> tuple[int, int]:
    """(start, end) of the text set-preamble owns (#413).

    From below a title, else the top, to the header's first top-level
    "**Field:**" line (list item or paragraph), else the first section. So
    the cursor lines, and any header field, stay out of its reach.
    """
    hs, secs = headings(lines), section_headings(lines)
    start = hs[0][0] + 1 if hs and secs != hs else 0
    fence = fenced(lines)
    stops = [i for i in range(start, len(lines)) if list_field(lines, fence, i)]
    stops += [s for s, _ in paragraph_headers(lines) if s >= start]
    stops += [i for i, _, _ in secs if i >= start]
    return start, min(stops, default=len(lines))


def list_field(lines: list[str], fence: list[bool], i: int) -> bool:
    """True for a top-level "- **Field:** value" item outside a fence.

    Top-level only: a "  - **Next:** ask alice" under a checklist item is that
    item's note, and a line after it would split the list. A tier line
    "- **#15:** …" is an item, not a header field (CR 316).
    """
    m = FIELD_RE.match(lines[i])
    return (
        bool(m)
        and not fence[i]
        and not lines[i][:1].isspace()
        and bool(LIST_MARK_RE.match(lines[i]))
        and not re.fullmatch(REF_PAT, m.group("field").strip())
    )


def field_list_end(lines: list[str], fence: list[bool], i: int) -> int:
    """One past the run of adjacent field items from line i, sub-bullets and all."""
    end = after_block(lines, i)
    while end < len(lines) and list_field(lines, fence, end):
        end = after_block(lines, end)
    return end


def paragraph_headers(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) of each paragraph holding a top-level cursor line (#399).

    "**Last check-in:** …" with no "- " is no list item, so it is no anchor for
    a new header line, and a header op used to leave it a paragraph.
    """
    return [
        (s, e)
        for s, e, kind in spans(lines)
        if kind == "para" and any(is_cursor_line(lines[j]) for j in range(s, e))
    ]


SETEXT_RE = re.compile(r"^\s{0,3}(?:=+|-+)[ \t]*$")


def converge(lines: list[str]) -> list[str]:
    """Turn each paragraph header into "- **Field:** value" items, in place (#399).

    Every line of the paragraph must be a field line, cursor or not: a plain
    line would become a lazy continuation of the item above it. A paragraph
    that can't converge is left as it is, and a note names the line, because
    no op can rewrite a paragraph above the first heading (#413), and refusing
    would block the Last check-in write every check-in makes. A hard break
    goes: two trailing spaces, or a "\\" that would show in an item as itself.
    Blank lines between it and a field list holding a cursor go too, or GitHub
    renders one loose list; an unrelated list keeps its gap [measured with
    gh api markdown]. Edits lines in place and returns notes on what it did.
    """
    notes = []
    for s, e in reversed(paragraph_headers(lines)):
        para = lines[s:e]
        bad = next(
            (ln for ln in para if ln[:1].isspace() or not FIELD_RE.match(ln)), None
        )
        why = f"{bad.strip()!r} can't become a list item" if bad is not None else ""
        if not why and e < len(lines) and SETEXT_RE.match(lines[e]):
            why = f"the {lines[e].strip()!r} under it makes it a heading"
        if why:
            # Named by its cursor field, not a line number: an earlier op can
            # move it, and a later header op would note it again (CR 939).
            lead = next(
                FIELD_RE.match(ln).group("lead") for ln in para if is_cursor_line(ln)
            )
            notes.append(f"the paragraph holding {lead!r} stays a paragraph: {why}")
            continue
        items = []
        for k, ln in enumerate(para):
            ln = ln.rstrip()
            # A "\" ends a hard break only before a line ending, and an escaped
            # "\\" is no break: an odd count of them is one.
            if k < len(para) - 1 and (len(ln) - len(ln.rstrip("\\"))) % 2:
                ln = ln[:-1].rstrip()
            items.append("- " + ln)
        lines[s:e] = items
        notes.append(f"the header paragraph at line {s + 1} became a list")
        fence = fenced(lines)
        below = e
        while below < len(lines) and not lines[below].strip():
            below += 1
        if (
            below > e
            and below < len(lines)
            and list_field(lines, fence, below)
            and holds_cursor(lines, below, field_list_end(lines, fence, below))
        ):
            del lines[e:below]
        above = s
        while above > 0 and not lines[above - 1].strip():
            above -= 1
        if above < s and any(
            end == above and holds_cursor(lines, start, end)
            for start, end in field_lists(lines)
        ):
            del lines[above:s]
    return notes


def holds_cursor(lines: list[str], start: int, end: int) -> bool:
    """True when a top-level line in the range is a cursor line, not a sub-note."""
    return any(is_cursor_line(ln) for ln in lines[start:end])


def field_lists(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) of each run of adjacent top-level field items."""
    fence, out, i = fenced(lines), [], 0
    while i < len(lines):
        if list_field(lines, fence, i):
            end = field_list_end(lines, fence, i)
            out.append((i, end))
            i = end
        else:
            i += 1
    return out


def header_end(lines: list[str]) -> tuple[int, bool]:
    """(where a new header line goes, whether it joins an existing field list).

    After the run of "- **Field:**" items holding the cursor lines, and after
    each one's sub-bullets (as add-line, CR 250). Else below a paragraph
    header converge() couldn't turn into a list, not in some other list
    (#399). Else after the list-item fields above the first section. A
    bold-led paragraph is no field list. Else just before the first section
    heading, a title kept above (CR 308).
    """
    fence = fenced(lines)
    secs = section_headings(lines)
    first = secs[0][0] if secs else len(lines)
    starts = [
        i
        for i in range(len(lines))
        if list_field(lines, fence, i) and is_cursor_line(lines[i])
    ]
    if not starts and (paras := paragraph_headers(lines)):
        end = paras[0][1]
        # A line between a setext heading and its underline unmakes the heading.
        if end < len(lines) and SETEXT_RE.match(lines[end]):
            end += 1
        return end, False
    starts = starts or [i for i in range(first) if list_field(lines, fence, i)]
    if starts:
        return field_list_end(lines, fence, starts[0]), True
    while first > 0 and not lines[first - 1].strip():
        first -= 1
    return first, False


def section_tail(lines: list[str], start: int, end: int) -> int:
    """Insertion point at a section's end, before its trailing blank lines."""
    pos = end
    while pos - 1 > start and not lines[pos - 1].strip():
        pos -= 1
    return pos


def counts(lines: list[str]) -> dict[str, int]:
    """Each item_state's count outside fences; GitHub's [x] tally is done + disposed."""
    fence = fenced(lines)
    out = {"open": 0, "done": 0, "disposed": 0}
    for i, ln in enumerate(lines):
        state = None if fence[i] else item_state(ln)
        if state:
            out[state] += 1
    return out


# A disposition closes an item without shipping it (F177, CannObserv/processor#24
# via #475): a field that is one of these phrases, or starts with one and then
# punctuation, as "not planned: superseded" or "out of epic (moved)". A phrase
# going on in words, "out of epic follow-up #20 filed", is text (CR 1489).
DISPOSITION_RE = re.compile(
    r"[*_]*(?:not planned|out of epic)[*_]*(?:$|\s*[:;,.)(—–-])", re.I
)
# A field starts after a " · ": a "·" with no space before it is text (CR 1488).
FIELD_SEP_RE = re.compile(r"\s+·\s*")


def item_state(line: str) -> str | None:
    """box_state, with a ticked disposition read apart as "disposed".

    A not-planned item could only be ticked, so it counted as done. Ticked
    with a " · " field that reads "not planned" or "out of epic", alone or
    before punctuation, it is disposed. An open one is open, and the words elsewhere are just text.
    """
    state = box_state(line)
    if state != "done":
        return state
    fields = FIELD_SEP_RE.split(line.rstrip())[1:]
    if any(DISPOSITION_RE.match(f) for f in fields):
        return "disposed"
    return state


def box_state(line: str) -> str | None:
    m = BOX_RE.match(line)
    if not m:
        return None
    return "done" if m.group("mark") in "xX" else "open"


def set_box(line: str, done: bool) -> str:
    m = BOX_RE.match(line)
    assert m
    mark = "x" if done else " "
    return f"{m.group('indent')}{m.group('marker')} [{mark}] " + line[m.end() :]


LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|(?P<num>\d{1,9})[.)])(?:[ \t]|$)")
QUOTE_RE = re.compile(r"^\s{0,3}>")
# A heading, a thematic break or a setext underline is a block of one line.
ONE_LINE_BLOCK_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}(?:[ \t]|$)|(?:[-*_][ \t]*){3,}$|=+[ \t]*$)"
)


def spans(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, kind) for each paragraph and table row outside a fenced block.

    A code span or link text can wrap within a paragraph, never past it, so a
    paragraph is read whole (CR 334). It ends at a blank line, a fence, a table,
    a heading, a thematic break, a list item, or a quote's start. An ordered
    item numbered other than 1 doesn't break a plain paragraph, but does end
    an item; a ">" line continues a quote; any other line continues the
    paragraph [each measured with gh api markdown]. kind is "row", "item",
    "quote", "line" (a one-line block) or "para".
    """
    fence, table = fenced(lines), tabled(lines)
    out: list[tuple[int, int, str]] = []
    start, kind = -1, ""

    def flush(end: int) -> None:
        nonlocal start
        if start >= 0:
            out.append((start, end, kind))
            start = -1

    for i, ln in enumerate(lines):
        if fence[i] or table[i] or not ln.strip():
            flush(i)
            if table[i] and not fence[i]:
                out.append((i, i + 1, "row"))
            continue
        item, quote = LIST_ITEM_RE.match(ln), QUOTE_RE.match(ln)
        one_line = ONE_LINE_BLOCK_RE.match(ln)
        starts = (
            one_line
            or (item and (not item.group("num") or int(item.group("num")) == 1))
            or (item and kind == "item")
            or (quote and kind != "quote")
        )
        if starts or start < 0:
            flush(i)
            start = i
            kind = (
                "line" if one_line else "item" if item else "quote" if quote else "para"
            )
        if one_line:
            flush(i + 1)
    flush(len(lines))
    return out


def paragraphs(lines: list[str]) -> list[tuple[str, bool]]:
    """(text, is_row) for each of spans(): what the lint reads as one unit."""
    return [("\n".join(lines[s:e]), kind == "row") for s, e, kind in spans(lines)]


def refs_in(lines: list[str], host: str) -> set[str]:
    """Every ref GitHub links in the lines.

    A ref only in a fenced block or a code span links nothing, so it doesn't
    list the issue (#415, decided 2026-10-15). Spans outrank links, a table
    row's cells are read apart (CR 328), and a paragraph is read whole, as a
    span or a link's text may wrap within it (CR 334).
    """
    out = set()
    for text, row in paragraphs(lines):
        for m in REF_RE.finditer(ref_text(outside_code(text, row))):
            out.add(key(m.group("repo"), m.group("num"), host))
    return out


# ---------------------------------------------------------------- operations


def inject(text: str, now: dt.datetime, scan: dict | None = None) -> str:
    def per_repo(m: re.Match) -> str:
        if not scan:
            raise Usage(f"{m.group(0)} needs --scan with scan.sh's report")
        hit = (scan.get("also") or {}).get(m.group("repo").lower())
        if hit is None:
            raise Usage(
                f"{m.group(0)}: the --scan report has no --also {m.group('repo')}"
            )
        return hit["last_seen"]

    text = LAST_SEEN_FOR_RE.sub(per_repo, text)
    for name in ("checked", "last_seen"):
        if "{" + name + "}" in text:
            if not scan:
                raise Usage(f"{{{name}}} needs --scan with scan.sh's report")
            text = text.replace("{" + name + "}", scan[name])
    return text.replace("{now}", now.strftime("%Y-%m-%dT%H:%MZ")).replace(
        "{today}", now.strftime("%Y-%m-%d")
    )


def _delta(before: str | None, after: str | None) -> dict[str, int]:
    d = {"open": 0, "done": 0, "disposed": 0}
    if before:
        d[before] -= 1
    if after:
        d[after] += 1
    return d


def _add(acc: dict[str, int], d: dict[str, int]) -> None:
    for k in acc:
        acc[k] += d[k]


def apply_ops(
    body_lines: list[str],
    ops: list[dict],
    host: str,
    now: dt.datetime,
    scan: dict | None = None,
) -> tuple[list[str], dict[str, int], list[str]]:
    """Apply ops in order. Returns (lines, expected count delta, notes)."""
    lines = list(body_lines)
    expect = {"open": 0, "done": 0, "disposed": 0}
    notes: list[str] = []
    converged: set[str] = set()
    # field -> (op, name, value) of the last header op that set it (#399).
    header_set: dict[str, tuple[str, str, str]] = {}
    for n, op in enumerate(ops, 1):
        kind = op.get("op")
        where = f"op {n} ({kind})"
        try:
            if kind in ("tick", "untick"):
                i = find_ref_line(
                    lines, parse_ref(op["ref"], host), host, want_item=True
                )
                want = kind == "tick"
                if (box_state(lines[i]) == "done") == want:
                    notes.append(
                        f"{where}: {op['ref']} already {'ticked' if want else 'unticked'}"
                    )
                    continue
                before = item_state(lines[i])
                lines[i] = set_box(lines[i], want)
                _add(expect, _delta(before, item_state(lines[i])))
            elif kind == "note":
                i = find_ref_line(lines, parse_ref(op["ref"], host), host)
                # The editor writes the " · " itself, so a text led by one, as
                # notes were before it did, doesn't get a second (#405).
                text = inject(op["text"], now, scan).strip()
                text = text.removeprefix("·").lstrip()
                if not text or "\n" in text:
                    raise Refused("note text must be one non-empty line")
                head, close = lines[i].rstrip(), ""
                # The line was found by its lead, so it has one (CR 2414).
                row = line_ref(head, host)[0] == "row"
                if row:
                    # Inside the last cell: GFM drops a cell past the header's
                    # count, so text after the closing pipe never shows (CR 286).
                    if UNESCAPED_PIPE_RE.search(text):
                        raise Refused(
                            "a note on a table row can't hold a bare |; write \\|"
                        )
                    if head.endswith("|") and not head.endswith("\\|"):
                        head, close = head[:-1].rstrip(), " |"
                # Already there when it is the line's last field. By the end,
                # not a substring: "second" on "#12 second thing" is a new note
                # (CR 253). A last " · " field that reads as the note is it.
                # A note joined by a bare space before #405 isn't a field, so
                # re-applied it goes on again (CR 342, an accepted limit).
                if head.endswith(text) and field_end(head[: -len(text)], row):
                    notes.append(f"{where}: note already on {op['ref']}'s line")
                    continue
                sep = " " if field_end(head, row) else " · "
                # The note goes before the line's own trailing break (CR 274).
                # A "not planned" note on a ticked item disposes it (F177).
                before = item_state(lines[i])
                lines[i] = head + sep + text + close + trailing(lines[i])
                _add(expect, _delta(before, item_state(lines[i])))
            elif kind == "set-line":
                ref_key = parse_ref(op["ref"], host)
                i = find_ref_line(lines, ref_key, host)
                new = inject(op["line"], now, scan).rstrip("\r\n")
                if "\n" in new:
                    raise Refused("set-line takes one line")
                lr = line_ref(new, host)
                if not lr or lr[1] != ref_key:
                    raise Refused(
                        f"the new line doesn't lead with {op['ref']}: "
                        + why_no_lead(new, op["ref"].strip(), host)
                    )
                if new == lines[i]:
                    notes.append(f"{where}: {op['ref']}'s line already reads so")
                    continue
                _add(expect, _delta(item_state(lines[i]), item_state(new)))
                lines[i] = new
            elif kind == "add-line":
                new = inject(op["line"], now, scan).rstrip("\r\n")
                if "\n" in new or not new.strip():
                    raise Refused("add-line takes one non-empty line")
                # Compared without trailing whitespace, so "note " finds "note";
                # the raw text, break and all, is what gets inserted (CR 280).
                if new.rstrip() in (ln.rstrip() for ln in lines):
                    notes.append(f"{where}: line already present")
                    continue
                lr = line_ref(new, host)
                if lr:
                    # Only "no such line" lets the add through; "ambiguous" must
                    # stop it, or a ref with two lines gets a third (CR 252).
                    try:
                        find_ref_line(lines, lr[1], host, want_item=lr[0] == "item")
                    except NotFound:
                        pass
                    else:
                        raise Refused(
                            f"{lr[1]} already has a line; use set-line or note"
                        )
                elif starts := unmarked_lead(new, host):
                    # Added as written, as it always was: a note, not a refusal.
                    notes.append(
                        f"{where}: the line starts with {show_key(starts, host)} but"
                        " isn't a checklist item, a bullet or a table row, so it is"
                        " added as text, and no op will find it by that ref"
                    )
                if "after_ref" in op:
                    anchor = find_ref_line(
                        lines, parse_ref(op["after_ref"], host), host
                    )
                    pos = after_block(lines, anchor)
                elif "section" in op:
                    section = op["section"]
                    took = heading_by_prefix(lines, section)
                    if took:
                        notes.append(
                            f"{where}: no section is headed {section!r}; the line"
                            f" goes under {took!r}, the one heading that starts"
                            " with it"
                        )
                        section = took
                    start, end = section_span(lines, section)
                    pos = section_tail(lines, start, end)
                else:
                    raise Refused("add-line needs after_ref or section")
                lines.insert(pos, new)
                _add(expect, _delta(None, item_state(new)))
            elif kind == "header":
                field = op["field"].strip()
                value = inject(op["value"], now, scan).strip()
                for note in converge(lines):
                    if note not in converged:
                        converged.add(note)
                        notes.append(f"{where}: {note}")
                header_set[field.lower()] = (where, field, value)
                hits = field_hits(lines, field)
                # A sub-note, or a header list indented 1-3 spaces, which
                # CommonMark allows: neither script reads it as the header's,
                # so a missing header line is added at the top level (#528).
                for i in field_hits(lines, field, nested=True):
                    notes.append(
                        f"{where}: skipped the indented '**{field}:**' line at line"
                        f" {i + 1}: neither this op nor scan.sh reads an indented"
                        " line as the header's"
                    )
                if not hits and (
                    field.lower() in CURSOR_FIELDS or per_repo_cursor(field)
                ):
                    # An adopted epic gets its cursors through here, not a
                    # hand edit (CR 292). Other fields aren't added: a typo
                    # would make a line no script reads.
                    pos, joins = header_end(lines)
                    name = CURSOR_FIELDS.get(field.lower(), field.strip())
                    new = [f"- **{name}:** {value}".rstrip()]
                    if pos < len(lines) and lines[pos].strip():
                        new.append("")
                    if not joins and pos and lines[pos - 1].strip():
                        new.insert(0, "")
                    lines[pos:pos] = new
                    continue
                if len(hits) != 1:
                    raise Refused(f"{len(hits)} '**{field}:**' lines; want exactly one")
                m = FIELD_RE.match(lines[hits[0]])
                assert m
                new = f"{m.group('lead')} {value}".rstrip() + trailing(lines[hits[0]])
                if new == lines[hits[0]]:
                    notes.append(f"{where}: {field} already reads so")
                    continue
                lines[hits[0]] = new
            elif kind == "log":
                text = inject(op["text"], now, scan).strip()
                # The op writes the "- " itself, so a text that brings its own,
                # as a line copied from the Log does, doesn't get a second
                # (CannObserv/processor#84 F8, #670). One is taken, no more.
                # Not where that would make the entry a line led by a ref, or
                # a checkbox: doubled, it was neither and was accepted, and
                # single, the lead and count guards may refuse it (CR 2415).
                bare = re.sub(r"^-\s+", "", text, count=1)
                if bare != text:
                    if line_ref("- " + bare, host) or box_state("- " + bare):
                        notes.append(
                            f'{where}: the text\'s own "- " is kept: without it'
                            " the entry would be a line led by a ref, or a checkbox"
                        )
                    else:
                        text = bare
                if not text or "\n" in text:
                    raise Refused("log text must be one non-empty line")
                start, end = section_span(lines, "Log")
                entry = f"- {text}"
                if entry in lines[start:end]:
                    notes.append(f"{where}: log entry already present")
                    continue
                lines.insert(section_tail(lines, start, end), entry)
            elif kind == "replace-section":
                start, end = section_span(lines, op["heading"])
                # Its span runs to the next heading as deep or shallower, so a
                # "##" takes its "###" subsections: once, a whole checklist (#408).
                inner = [t for i, _, t in headings(lines) if start < i < end]
                if inner and op.get("scope") != "tree":
                    raise Refused(
                        f"{op['heading']!r} holds subsections "
                        + ", ".join(repr(t) for t in inner)
                        + ", which replacing it would replace too. Replace a"
                        ' subsection by its own heading, or give "scope": "tree"'
                        " to replace the whole subtree"
                    )
                text = inject(op["text"], now, scan).strip("\n")
                new_body = [""] + [ln.rstrip("\r") for ln in text.split("\n")] + [""]
                if end == len(lines):
                    new_body.pop()
                old_body = lines[start + 1 : end]
                if normalize("\n".join(old_body)) == normalize("\n".join(new_body)):
                    notes.append(f"{where}: section already reads so")
                    continue
                before, after = counts(old_body), counts(new_body)
                _add(expect, {k: after[k] - before[k] for k in expect})
                lines[start + 1 : end] = new_body
            elif kind == "add-section":
                heading = op["heading"].strip()
                if not heading or "\n" in heading:
                    raise Refused("add-section takes a one-line heading")
                text = inject(op["text"], now, scan).strip("\n")
                new_body = [ln.rstrip("\r") for ln in text.split("\n")] if text else []
                if heading.lower() in (t.lower() for _, _, t in headings(lines)):
                    start, end = section_span(lines, heading)
                    old = normalize("\n".join(lines[start + 1 : end]).strip("\n"))
                    if old == normalize("\n".join(new_body)):
                        notes.append(f"{where}: section already present")
                        continue
                    raise Refused(
                        f"a section headed {heading!r} exists; use replace-section"
                    )
                # At its neighbours' level: a "##" before a "###" would end the
                # parent section, and a "##" after "#" sections would sit inside
                # the last one, where a replace-section deletes it (CR 305).
                if "before" in op:
                    start, _ = section_span(lines, op["before"])
                    level = next(lvl for i, lvl, _ in headings(lines) if i == start)
                    block = [f"{'#' * level} {heading}"]
                    lines[start:start] = (
                        block + ([""] + new_body if new_body else []) + [""]
                    )
                else:
                    block = [f"{'#' * section_level(lines)} {heading}"]
                    block += [""] + new_body if new_body else []
                    while lines and not lines[-1].strip():
                        lines.pop()
                    lines += [""] + block
                _add(expect, counts(new_body))
            elif kind == "rename-section":
                to = op["to"].strip()
                if not to or "\n" in to:
                    raise Refused("rename-section takes a one-line heading in to")
                taken = {t.lower(): i for i, _, t in headings(lines)}
                if op["heading"].strip().lower() not in taken and to.lower() in taken:
                    notes.append(f"{where}: already headed {to!r}")
                    continue
                start, _ = section_span(lines, op["heading"])
                if taken.get(to.lower(), start) != start:
                    # A heading is an anchor: two alike, and section ops refuse both.
                    raise Refused(f"{to!r} is already a heading")
                level = next(lvl for i, lvl, _ in headings(lines) if i == start)
                new = f"{'#' * level} {to}"
                if new == lines[start]:
                    notes.append(f"{where}: already headed {to!r}")
                    continue
                lines[start] = new
            elif kind == "set-preamble":
                text = inject(op["text"], now, scan).strip("\n")
                new_body = [ln.rstrip("\r") for ln in text.split("\n")] if text else []
                fence = fenced(new_body)
                for k, ln in enumerate(new_body):
                    if fence[k]:
                        continue
                    if is_cursor_line(ln) or list_field(new_body, fence, k):
                        raise Refused(
                            f"the text holds a header line, {ln.strip()!r}: the"
                            " header ops own each cursor line and header field"
                        )
                    if HEADING_RE.match(ln):
                        raise Refused(
                            f"the text holds a heading, {ln.strip()!r}: use add-section"
                        )
                start, end = preamble_span(lines)
                block = ([""] if start else []) + new_body
                if new_body and end < len(lines):
                    block.append("")
                if normalize("\n".join(lines[start:end])) == normalize(
                    "\n".join(block)
                ):
                    notes.append(f"{where}: preamble already reads so")
                    continue
                before, after = counts(lines[start:end]), counts(block)
                _add(expect, {k: after[k] - before[k] for k in expect})
                lines[start:end] = block
            elif kind == "set-subline":
                i = find_ref_line(lines, parse_ref(op["ref"], host), host)
                new = inject(op["line"], now, scan).rstrip("\r\n")
                if "\n" in new:
                    raise Refused("set-subline takes one line")
                hits = sub_bullets(lines, i, op["match"])
                if new.strip():
                    if not LIST_MARK_RE.match(new) or indent_of(new) <= indent_of(
                        lines[i]
                    ):
                        raise Refused(
                            f"the new line must be a sub-bullet indented under"
                            f" {op['ref']}'s line: {new.strip()!r}"
                        )
                    if not hits and new in lines[i + 1 : after_block(lines, i)]:
                        notes.append(
                            f"{where}: {op['ref']}'s sub-bullet already reads so"
                        )
                        continue
                if not hits:
                    raise Refused(
                        f"no sub-bullet under {op['ref']}'s line starts with"
                        f" {op['match']!r}"
                    )
                if len(hits) > 1:
                    raise Refused(
                        f"{len(hits)} sub-bullets under {op['ref']}'s line start with"
                        f" {op['match']!r}: "
                        + "; ".join(lines[j].strip() for j in hits)
                        + ". Make match longer"
                    )
                j = hits[0]
                if not new.strip():
                    # Its own sub-block goes with it, or it re-parents (CR 250).
                    gone = lines[j : after_block(lines, j)]
                    _add(expect, {k: -v for k, v in counts(gone).items()})
                    del lines[j : j + len(gone)]
                    continue
                if new == lines[j]:
                    notes.append(f"{where}: {op['ref']}'s sub-bullet already reads so")
                    continue
                _add(expect, _delta(item_state(lines[j]), item_state(new)))
                lines[j] = new
            elif kind == "compact":
                m = re.fullmatch(r"\s*" + REF_PAT + r"\s*", op["ref"])
                ref_key = parse_ref(op["ref"], host)
                i = find_ref_line(lines, ref_key, host, want_item=True)
                if box_state(lines[i]) != "done":
                    raise Refused(f"{op['ref']}'s line isn't ticked: tick it first")
                link = op["link"].strip()
                lm = COMMENT_LINK_RE.fullmatch(link)
                if not lm or key(lm.group("repo"), lm.group("num"), host) != ref_key:
                    raise Refused(
                        f"link must be a comment on {op['ref']} itself"
                        f" (…/issues/N#issuecomment-ID): {link}"
                    )
                child = m.group("repo") if m else None
                own = not child or child.lower() == host.lower()
                ref = f"#{m.group('num')}" if own else f"{child}#{m.group('num')}"
                title = clean_title(op.get("title", ""), child, host)
                if not title:
                    raise Refused(f"{op['ref']} has no title to keep")
                bm = BOX_RE.match(lines[i])
                assert bm
                rest = lines[i][bm.end() :]
                ordinal = re.match(r"(?:[0-9]{1,9}[.)]\s+)?", rest).group(0)
                fields = FIELD_SEP_RE.split(lines[i].rstrip())[1:]
                kept = next((f for f in fields if DISPOSITION_RE.match(f)), None)
                new = (
                    f"{bm.group('indent')}{bm.group('marker')} [x] {ordinal}**{ref}**"
                    f" {title}"
                    + (f" · {kept}" if kept else "")
                    + f" · [{op.get('label', 'verified')}]({link})"
                )
                end = after_block(lines, i)
                if new == lines[i] and end == i + 1:
                    notes.append(f"{where}: {op['ref']}'s line is already compact")
                    continue
                # The sub-block goes: the evidence lives in the linked comment.
                # Its boxes come off the derived counts too, so an open one
                # would vanish with every check green (CR 2208).
                gone = lines[i + 1 : end]
                still_open = [g.strip() for g in gone if box_state(g) == "open"]
                if still_open:
                    raise Refused(
                        f"{op['ref']}'s sub-block holds open items, which compact"
                        " would drop: "
                        + "; ".join(still_open)
                        + ". Give each a line of its own (add-line), or remove it"
                        " with set-subline, then compact"
                    )
                _add(expect, {k: -v for k, v in counts(gone).items()})
                _add(expect, _delta(item_state(lines[i]), item_state(new)))
                lines[i:end] = [new]
            elif kind == "log-comment":
                continue  # posted after the body write: build_comments()
            else:
                raise Usage(f"unknown op {kind!r}")
        except Usage as e:
            raise Usage(f"{where}: {e}") from None
        except KeyError as e:
            raise Usage(f"{where}: missing field {e}") from None
        except Refused as e:
            raise Refused(f"{where}: {e}") from None
    # add-line refuses a second line for a ref (CR 252); a section written
    # whole could still copy one in, and every later op on it is then
    # ambiguous. Moving a line within one call keeps its count (CR 307).
    before, after = lead_counts(body_lines, host), lead_counts(lines, host)
    doubled = sorted(
        f"{ref} ({after[k]} {kind} lines)"
        for k in after
        for kind, ref in [k]
        if after[k] > max(before.get(k, 0), 1)
    )
    if doubled:
        raise Refused(
            "these refs would lead more than one line: "
            + ", ".join(doubled)
            + ". Keep one line per ref, and move it rather than copy it"
        )
    # Ops apply in order, so a later section op can delete or copy a line a
    # header op just set, and the call used to report success (#399, shape D).
    for f, (where, name, value) in header_set.items():
        found = [
            FIELD_RE.match(lines[i]).group("value").strip()
            for i in field_hits(lines, f)
        ]
        if found != [value]:
            now_reads = (
                f"it reads {found[0]!r}"
                if len(found) == 1
                else f"{len(found)} '**{name}:**' lines remain"
            )
            raise Refused(
                f"{where} set {name} to {value!r}, but after every op {now_reads}."
                " Put section ops before header ops"
            )
    return lines, expect, notes


def field_hits(lines: list[str], field: str, nested: bool = False) -> list[int]:
    """Every unindented "**Field:**" line outside a fence, in either form.

    Top-level only, as list_field reads and scan.sh's header_fields does: an
    indented one is a checklist item's sub-note, which a header op once
    rewrote in place (#528). With nested, the indented ones instead, which
    the op skips and notes.
    """
    fence, want = fenced(lines), field.strip().lower()
    return [
        i
        for i, ln in enumerate(lines)
        if not fence[i]
        and ln[:1].isspace() == nested
        and (m := FIELD_RE.match(ln))
        and m.group("field").strip().lower() == want
    ]


# ---------------------------------------------------------------- gh

# The per-repo token map (#520): owner/repo, lowercased, to the variable
# --token-for named for it and that variable's value. One ambient token can't
# read a private sibling's refs, and a cohort keeps one PAT per repo. The value
# goes to gh only as GH_TOKEN, for that repo's calls, and is never shown.
TOKENS: dict[str, tuple[str, str]] = {}
REPO_FORM = r"[\w.-]+/[\w.-]+"
VAR_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
AMBIENT_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN")
TOKEN_FOR_HELP = (
    "read OWNER/REPO with the token held in environment variable VAR: its name,"
    " never its value. gh gets it as GH_TOKEN for that repo's calls only."
    " Repeatable. A cohort .env names them GH_TOKEN_<REPO>, e.g. --token-for"
    " CannObserv/provisioner=GH_TOKEN_PROVISIONER. A mapped variable unset or"
    " empty is a usage error, never a fall back to the ambient token"
)


def add_token_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--token-for",
        action="append",
        default=[],
        metavar="OWNER/REPO=VAR",
        help=TOKEN_FOR_HELP,
    )


def load_tokens(specs: list[str]) -> None:
    """Fill TOKENS from --token-for values, or raise Usage before any gh call.

    No message carries a value: a token pasted where its variable's name goes
    is named as that, and only a spec's OWNER/REPO, which holds a "/" no token
    does, is ever echoed.
    """
    TOKENS.clear()
    for spec in specs:
        repo, _, var = spec.partition("=")
        if not re.fullmatch(REPO_FORM, repo):
            raise Usage(
                "--token-for wants OWNER/REPO=VAR; one value isn't of that form"
            )
        if any(rx.search(var) for rx in SECRET_RES):
            raise Usage(
                f"--token-for {repo}: what follows '=' looks like a token's value."
                " Pass the name of the variable holding it, e.g. GH_TOKEN_<REPO>"
            )
        if not VAR_NAME_RE.fullmatch(var):
            raise Usage(
                f"--token-for {repo}: what follows '=' isn't an environment"
                " variable's name"
            )
        value = os.environ.get(var)
        if value is None:
            raise Usage(f"--token-for {repo}: {var} is not set")
        if not value.strip():
            raise Usage(f"--token-for {repo}: {var} is empty")
        had = TOKENS.get(repo.lower())
        if had and had[0] != var:
            raise Usage(f"--token-for maps {repo.lower()} to both {had[0]} and {var}")
        TOKENS[repo.lower()] = (var, value)


def repo_of(args: list[str]) -> str | None:
    """The repo a gh call reads: its repos/OWNER/REPO path, or its -R."""
    for i, a in enumerate(args):
        if a in ("-R", "--repo") and i + 1 < len(args):
            return args[i + 1]
        m = re.match(r"repos/([^/?#]+/[^/?#]+)", a)
        if m:
            return m.group(1)
    return None


def gh_env(repo: str | None) -> dict | None:
    """The environment for a call on repo: its mapped token as GH_TOKEN, else
    None, which inherits the ambient one."""
    hit = TOKENS.get((repo or "").lower())
    return {**os.environ, "GH_TOKEN": hit[1]} if hit else None


def scrub(text: str) -> str:
    """text with every token this run holds shown as <$VAR>.

    gh's whole stderr is surfaced (#410, #426), so a gh that ever printed its
    environment would put a token in a warning or the summary (#520).
    """
    known = list(TOKENS.values()) + [
        (v, os.environ.get(v) or "") for v in AMBIENT_TOKENS
    ]
    for var, value in sorted(known, key=lambda x: -len(x[1])):
        if len(value) >= 8:
            text = text.replace(value, f"<${var}>")
    return text


def token_hint(repo: str) -> str:
    """What to try when a read of repo failed, or "" when nothing is known.

    A mapped repo names its variable: no other token was tried. An unmapped
    one names each set variable the cohort's .env would hold its PAT in,
    GH_TOKEN_<REPO> or GH_TOKEN_<OWNER>_<REPO> with "." and "-" read as "_",
    unless it holds the ambient token that just failed (#520).
    """
    hit = TOKENS.get(repo.lower())
    if hit:
        return f"read with {hit[0]} (--token-for)"
    owner, _, name = repo.partition("/")

    def up(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "_", s).upper()

    ambient = {os.environ.get(v) for v in AMBIENT_TOKENS} - {None, ""}
    found = [
        var
        for var in (f"GH_TOKEN_{up(name)}", f"GH_TOKEN_{up(owner)}_{up(name)}")
        if (os.environ.get(var) or "").strip() and os.environ.get(var) not in ambient
    ]
    if not found:
        return ""
    also = f" ({', '.join(found[1:])} is set too)" if found[1:] else ""
    return f"{found[0]} is set: pass --token-for {repo}={found[0]}{also}"


def gh(args: list[str], what: str) -> str:
    try:
        r = subprocess.run(
            ["gh", *args], capture_output=True, text=True, env=gh_env(repo_of(args))
        )
    except FileNotFoundError:
        raise Infra("gh is not on PATH") from None
    if r.returncode != 0:
        err = scrub(r.stderr.strip())
        raise Infra(
            f"{what}: gh {' '.join(args)} exited {r.returncode}:\n{err}",
            stderr=err,
            code=r.returncode,
        )
    return r.stdout


def gh_json(args: list[str], what: str):
    out = gh(args, what)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise Infra(f"{what}: gh returned non-JSON: {scrub(out[:200])!r}") from None


def gh_graphql(query: str, variables: dict, what: str) -> tuple[dict, list[str]]:
    """GraphQL's data, and the message of each error that came with it.

    gh exits 1 on a GraphQL error but still prints the response, so one null
    node (a deleted issue's alias) leaves the rest readable. With no data at
    all (a 403, a bad query), it fails as gh() does. A query whose variables
    name an owner and a name runs with that repo's mapped token (#520).
    """
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    repo = (
        f"{variables['owner']}/{variables['name']}"
        if {"owner", "name"} <= set(variables)
        else None
    )
    try:
        r = subprocess.run(
            ["gh", *args], capture_output=True, text=True, env=gh_env(repo)
        )
    except FileNotFoundError:
        raise Infra("gh is not on PATH") from None
    try:
        resp = json.loads(r.stdout)
    except json.JSONDecodeError:
        resp = None
    data = resp.get("data") if isinstance(resp, dict) else None
    if r.returncode != 0 and not data:
        err = scrub(r.stderr.strip())
        raise Infra(
            f"{what}: gh api graphql exited {r.returncode}:\n{err}",
            stderr=err,
            code=r.returncode,
        )
    if not isinstance(data, dict):
        raise Infra(f"{what}: gh returned no data: {scrub(r.stdout[:200])!r}")
    return data, [scrub(str(e.get("message", e))) for e in resp.get("errors") or []]


def build_comments(ops: list[dict], now: dt.datetime, scan: dict | None) -> list[str]:
    """Each log-comment op's comment, in op order, checked before anything is
    written: non-empty, and under GitHub's comment cap (#654)."""
    out = []
    for n, op in enumerate(ops, 1):
        if op.get("op") != "log-comment":
            continue
        where = f"op {n} (log-comment)"
        text = inject(op["text"], now, scan).strip("\n").rstrip()
        date = inject(op.get("date", "{today}"), now, scan).strip()
        if not text.strip() or not date:
            raise Refused(f"{where}: log-comment takes non-empty text")
        body = LOG_MARK.format(date=date) + "\n\n" + text
        if len(body) > COMMENT_LIMIT:
            raise Refused(
                f"{where}: the comment is {len(body):,} characters; GitHub refuses"
                f" one over {COMMENT_LIMIT:,}. Split it into several log-comment ops"
            )
        out.append(body)
    return out


COMMENT_PAGES = 20


def comments_since(
    host: str, num: int, since: str
) -> tuple[list[tuple[str, str]], bool]:
    """The issue's comments updated at or after since, oldest first, as
    (normalized body, URL); and whether the read stopped at its page cap."""
    out = []
    for page in range(1, COMMENT_PAGES + 1):
        rows = gh_json(
            [
                "api",
                f"repos/{host}/issues/{num}/comments?since={since}&per_page=100&page={page}",
            ],
            "reading the epic's comments since the unfinished post",
        )
        out += [
            ("\n".join(normalize(c.get("body") or "")), str(c.get("html_url") or ""))
            for c in rows or []
            if isinstance(c, dict)
        ]
        if len(rows or []) < 100:
            return out, False
    return out, True


# ---------------------------------------------------------------- log comment attempts
#
# A re-run after an exit 5 must not post a log comment twice, and two
# check-ins that log identical text must post twice (#658). So each call that
# posts log comments is recorded beside the baseline before its first POST:
# a "call" record with each comment's hash, in order, and the time to search
# from, the epic's updated_at as that run fetched it (GitHub's clock) less a
# minute. Each comment posted, or found, adds a "posted" record with its URL.
# A re-run of the same comments, in order, resumes the latest call not yet
# finished: a part it posted is "already", and a part it may have stored
# though gh failed is looked for from the call's time (CR 2212). A finished
# call is never matched, so identical text from a later check-in posts.

ATTEMPTS = "comments.jsonl"
# GitHub's since is whole seconds, and a post can land in the second the epic
# was fetched (CR 2214).
SEARCH_SLACK = dt.timedelta(seconds=60)


def comment_key(body: str) -> str:
    return hashlib.sha256("\n".join(normalize(body)).encode()).hexdigest()


def read_calls(sd: Path) -> tuple[list[dict], set[str]] | None:
    """(unfinished calls, oldest first, each with its posted parts by
    position; every URL recorded as posted), or None when this state dir has
    no record file. A line that isn't a record is skipped, as read_writes
    skips one."""
    try:
        lines = (sd / ATTEMPTS).read_text().splitlines()
    except FileNotFoundError:
        return None
    calls: dict[str, dict] = {}
    urls: set[str] = set()
    for ln in lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("call"), str):
            continue
        if rec.get("state") == "pending" and isinstance(rec.get("keys"), list):
            calls[rec["call"]] = {
                "call": rec["call"],
                "keys": rec["keys"],
                "since": str(rec.get("since") or ""),
                "posted": {},
            }
        elif rec.get("state") == "posted" and rec["call"] in calls:
            calls[rec["call"]]["posted"][rec.get("seq")] = str(rec.get("url") or "")
            urls.add(str(rec.get("url") or ""))
    open_ = [
        c for c in calls.values() if len(c["posted"]) < len(c["keys"]) and c["since"]
    ]
    return open_, urls - {""}


def record_attempt(sd: Path, rec: dict) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    with open(sd / ATTEMPTS, "a") as f:
        f.write(json.dumps(rec) + "\n")


def post_comment(host: str, num: int, body: str) -> str:
    """Post a comment on the issue; its URL."""
    fd, payload = tempfile.mkstemp(prefix="epic-comment-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"body": body}, f)
        data = gh_json(
            [
                "api",
                "-X",
                "POST",
                f"repos/{host}/issues/{num}/comments",
                "--input",
                payload,
            ],
            "posting the log comment",
        )
    finally:
        os.unlink(payload)
    return str((data or {}).get("html_url", "")) if isinstance(data, dict) else ""


def fetch_issue(repo: str, num: int) -> dict:
    """The epic as REST returns it: body, updated_at, state and closer."""
    data = gh_json(["api", f"repos/{repo}/issues/{num}"], "fetching the epic")
    return data if isinstance(data, dict) else {}


def closed_state(issue: dict) -> dict | None:
    """Who closed the epic and when, or None while it is open."""
    if issue.get("state") != "closed":
        return None
    return {
        "closed_by": (issue.get("closed_by") or {}).get("login") or "someone unnamed",
        "closed_at": issue.get("closed_at") or "an unrecorded time",
    }


def fetch_body(repo: str, num: int) -> str:
    return fetch_issue(repo, num).get("body") or ""


# ---------------------------------------------------------------- lint


def introduced(
    old: list[str], new: list[str]
) -> tuple[list[str], list[bool], list[bool]]:
    """The lines new adds or changes, and whether each sits in a fenced block or a table."""
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    fence, table = fenced(new), tabled(new)
    out, code, row = [], [], []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(new[j1:j2])
            code.extend(fence[j1:j2])
            row.extend(table[j1:j2])
    return out, code, row


def absent(e: Infra) -> bool:
    """Whether gh's failure says the thing doesn't exist (404, or 410 deleted).

    Only that is a lint finding. A rate limit, an auth failure or a network
    error is infrastructure, exit 2, not a refusal of the line (CR 304).
    """
    return bool(re.search(r"\bHTTP 4(?:04|10)\b", str(e)))


ESCAPABLE = frozenset(string.punctuation)


def code_spans(line: str) -> list[tuple[int, int]]:
    """The line's code spans as (start, end), read the CommonMark way (#402).

    A backtick string opens a span only when no backslash escapes it, and the
    span closes on the next backtick string of the same length; one with no
    closer is text. Inside a span a backslash is literal, so `App\\Tests\\` is
    code, ``a\\`b`` is one span, and \\`make\\` holds none. The lint passes one
    line, though a span may wrap within a paragraph; refs_in passes the whole
    paragraph (CR 334).
    """
    spans, i, n = [], 0, len(line)
    while i < n:
        if line[i] == "\\" and i + 1 < n and line[i + 1] in ESCAPABLE:
            i += 2
            continue
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        k, close = j, None
        while k < n and close is None:
            if line[k] != "`":
                k += 1
                continue
            m = k
            while m < n and line[m] == "`":
                m += 1
            close, k = (m if m - k == j - i else None), m
        if close is None:
            i = j
        else:
            spans.append((i, close))
            i = close
    return spans


def outside_code(line: str, row: bool = False) -> str:
    """The line with each code span read as a neutral mark, so no text joins across it.

    In a table row, each cell is read on its own: GFM splits cells first (CR 328).
    """
    if row:
        return "|".join(outside_code(c) for c in UNESCAPED_PIPE_RE.split(line))
    out, last = [], 0
    for start, end in code_spans(line):
        out += [line[last:start], LINK_MARK]
        last = end
    return "".join(out) + line[last:]


def lint(
    new_lines: list[str],
    host: str,
    check_links: bool,
    in_fence: list[bool] | None = None,
    in_table: list[bool] | None = None,
    known: frozenset[int] = frozenset(),
) -> list[str]:
    """Each problem in new_lines, as the refusal names it.

    known holds numbers to take as existing though they are above the repo's
    highest: a body linted before its own issue is created names the number
    it predicts (comment.sh --lint-file --predicted, #395).
    """
    in_fence = in_fence or [False] * len(new_lines)
    in_table = in_table or [False] * len(new_lines)
    problems = []
    prose = []  # each line outside its code spans
    for raw, code, row in zip(new_lines, in_fence, in_table):
        for rx in SECRET_RES:
            if rx.search(raw):
                problems.append("what looks like a secret (line withheld)")
        # A fenced block renders as written: a command's $VAR, a CI
        # ${{ matrix.x }} or an example ref are its text (CR 290).
        if code:
            continue
        # Placeholders and variables are read in the whole line, link targets
        # included; refs are read the way GitHub renders them. GitHub links no
        # ref in a code span, and finds spans before links: a span outranks a
        # link (#402).
        text = outside_code(raw, row)
        prose.append(text)
        for rx, what, in_spans in PLACEHOLDER_RES:
            if rx.search(raw if in_spans else text):
                problems.append(f"{what}: {raw.strip()[:120]}")
        if SHELL_VAR_RE.search(text):
            problems.append(
                f"an unexpanded shell variable outside a code span: {raw.strip()[:120]}"
            )
        ln = ref_text(text)
        for m in SHORT_REF_RE.finditer(ln):
            problems.append(
                f"short ref {m.group('ref')} links nowhere; write owner/repo#N: {raw.strip()[:120]}"
            )
        for m in BARE_AFTER_QUALIFIED_RE.finditer(ln):
            if m.group("repo").lower() != host.lower():
                problems.append(
                    f"bare {m.group('bare')} after {m.group('repo')}# reads as this repo's;"
                    f" qualify it: {raw.strip()[:120]}"
                )
    bare = {
        int(m.group("num"))
        for text in prose
        for m in REF_RE.finditer(ref_text(text))
        if not m.group("repo")
    } - set(known)
    if bare:
        newest = gh_json(
            [
                "api",
                f"repos/{host}/issues?state=all&sort=created&direction=desc&per_page=1",
            ],
            "reading the repo's highest number",
        )
        top = newest[0]["number"] if newest else 0
        for n in sorted(x for x in bare if x > top):
            # The newest-created issue isn't always the highest number: an
            # issue transferred in keeps its old creation date. Ask (CR 260).
            try:
                gh_json(["api", f"repos/{host}/issues/{n}"], f"checking #{n}")
                continue
            except Infra as e:
                if not absent(e):
                    raise
            problems.append(
                f"#{n} is above {host}'s highest number (#{top}); a ref from another repo?"
            )
    if check_links:
        for text in prose:
            # A link quoted in a code span is an example, not a link (CR 310).
            for m in COMMENT_LINK_RE.finditer(text):
                try:
                    data = gh_json(
                        [
                            "api",
                            f"repos/{m.group('repo')}/issues/comments/{m.group('id')}",
                        ],
                        "resolving a comment link",
                    )
                except Infra as e:
                    if not absent(e):
                        raise
                    hint = token_hint(m.group("repo"))
                    problems.append(
                        f"comment link doesn't resolve: {m.group(0)} ({e})"
                        + (f"; {hint}" if hint else "")
                    )
                    continue
                if not str(data.get("issue_url", "")).endswith(
                    f"/issues/{m.group('num')}"
                ):
                    problems.append(
                        f"comment {m.group('id')} isn't on #{m.group('num')}: {m.group(0)}"
                    )
    return problems


# ---------------------------------------------------------------- foreign edits


def foreign_changes(
    baseline: list[str], live: list[str], host: str
) -> tuple[list[str], list[str]]:
    """(ticks, other) between the last body written and the live one.

    A tick is a [ ] -> [x] flip on an item line that is otherwise unchanged.
    Implementers may tick (status#16 finding 60); the platform may tick on a
    close (broker#80 finding 141). Either is a claim the caller verifies.
    """
    ticks, other = [], []
    sm = difflib.SequenceMatcher(a=baseline, b=live, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            for a, b in zip(baseline[i1:i2], live[j1:j2]):
                lr = line_ref(b, host)
                if (
                    lr
                    and lr[0] == "item"
                    and box_state(a) == "open"
                    and box_state(b) == "done"
                    and set_box(a, True) == set_box(b, True)  # [X] ticks too (CR 254)
                ):
                    ticks.append(lr[1])
                else:
                    other.append(f"- {a}\n+ {b}")
            continue
        other.extend(f"- {a}" for a in baseline[i1:i2])
        other.extend(f"+ {b}" for b in live[j1:j2])
    return ticks, other


# ---------------------------------------------------------------- state


def also_from_report(
    report: dict, name: str, ops: list[dict], uses_checked: bool
) -> dict:
    """Each --also repo's part of a scan.sh report, checked as the host's is,
    with {checked} and {last_seen:owner/repo} guarded per repo (#400).

    {checked} is one time for every repo, so a capped updates or comments
    listing in any of them holds it. {last_seen:owner/repo} takes CR 265,
    276 and 302's guards from that repo's own entry.
    """
    raw = report.get("also")
    if raw is not None and not isinstance(raw, dict):
        raise Usage(f"--scan {name}: also must be an object keyed by owner/repo")
    have = {str(k).lower() for k in (raw or {})}
    for op in ops:  # before the fetch: exit 1 means nothing was fetched (CR 2232)
        for v in op.values():
            for m in LAST_SEEN_FOR_RE.finditer(v if isinstance(v, str) else ""):
                if m.group("repo").lower() not in have:
                    raise Usage(
                        f"{m.group(0)}: the --scan report has no --also {m.group('repo')}"
                    )
    if raw is None:
        return {}
    out = {}
    for low, e in raw.items():
        if not isinstance(e, dict) or type(e.get("max_number")) is not int:
            raise Usage(f"--scan {name}: also {low} has no usable max_number")
        repo = str(e.get("repo") or low)
        for field in ("new_numbers", "updated_since"):
            rows = e.get(field)
            if rows is not None and not (
                isinstance(rows, list)
                and all(
                    isinstance(r, dict) and type(r.get("number")) is int for r in rows
                )
            ):
                raise Usage(
                    f"--scan {name}: also {low} {field} must be a list of rows with a number"
                )
        cur = e.get("cursors")
        wm = cur.get("watermark") if isinstance(cur, dict) else "?"
        if wm is not None and type(wm) is not int:
            raise Usage(
                f"--scan {name}: also {low} cursors must be an object whose"
                " watermark is a number or null"
            )
        capped = e.get("capped") or []
        if not isinstance(capped, list):
            raise Usage(f"--scan {name}: also {low} capped must be a list")
        out[low.lower()] = {
            "repo": repo,
            "last_seen": f"{repo}#{e['max_number']}",
            # As the host's new_issues: the walk's finds, and updates above
            # the old watermark (CR 276). Unrelated rows were never listed.
            "new_issues": sorted(
                {
                    r["number"]
                    for r in (e.get("new_numbers") or [])
                    + [
                        u
                        for u in e.get("updated_since") or []
                        if wm is not None and u["number"] > wm
                    ]
                    if r.get("kind") == "issue"
                }
            ),
        }
        cut = [w for w in capped if w in ("listing updates", "reading new comments")]
        if uses_checked and cut:
            raise Usage(
                f"the report's {repo} {', '.join(cut)} hit its page cap, so"
                " {checked} would move the window past rows it never listed."
                " Re-scan with a later --since, one you have read up to"
            )
        if not any(
            isinstance(v, str)
            and any(
                m.group("repo").lower() == low.lower()
                for m in LAST_SEEN_FOR_RE.finditer(v)
            )
            for op in ops
            for v in op.values()
        ):
            continue
        if "listing updates" in capped:
            raise Usage(
                f"the report's {repo} listing updates hit its page cap, so"
                f" {{last_seen:{repo}}} could skip an issue transferred in. Re-scan"
                " with a later --since"
            )
        if e.get("new_numbers") is None:
            raise Usage(
                f"the report scanned no {repo} numbers (no watermark), so"
                f" {{last_seen:{repo}}} would skip issues nobody saw. Write its"
                f" '- **Last issue seen ({repo}):** {repo}#N' line, then re-scan"
            )
        if "listing new numbers" in capped:
            raise Usage(
                f"the report's {repo} number walk hit its page cap, so"
                f" {{last_seen:{repo}}} would skip numbers it never reached."
                " Re-scan from a closer watermark"
            )
        if e.get("updated_since") is None:
            raise Usage(
                f"the report scanned no {repo} updates (no since), so"
                f" {{last_seen:{repo}}} would skip an issue transferred in. Give"
                " scan.sh --since, then re-run"
            )
    return out


def state_dir(arg: str | None, repo: str, num: int) -> Path:
    base = (
        Path(arg)
        if arg
        else Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        / "coordinating-epics"
    )
    # Nested and lowercased: GitHub names are case-insensitive, and "a-b/c"
    # and "a/b-c" must not share a baseline (CR 299).
    owner, name = repo.lower().split("/")
    return base / owner / name / str(num)


# ---------------------------------------------------------------- baseline
#
# The baseline is a plain per-user file, and a thread that learned the
# procedure once saved its own hand edit into it, so the diff read clean
# (#518). Each body this tool writes or adopts is recorded by hash, with
# GitHub's time for it; a baseline no record matches is refused, and the
# body's edit history is read for any edit since.

WRITES = "writes.jsonl"
# An edit-history entry this long after the baseline's own time is no part
# of it: GitHub's clocks for the issue and its history can differ by a beat.
HISTORY_SLACK = dt.timedelta(seconds=60)


def digest(body: str) -> str:
    """A body's hash, line endings and trailing blank lines aside: a baseline
    file and an edit-history entry hash alike for the same body."""
    return hashlib.sha256(("\n".join(split_raw(body)) + "\n").encode()).hexdigest()


def gh_time(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def read_writes(sd: Path) -> list[dict]:
    """Every record this tool made, skipping a line that isn't one."""
    try:
        lines = (sd / WRITES).read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("sha256"), str):
            out.append(rec)
    return out


def save_baseline(sd: Path, text: str, at: str, via: str) -> None:
    """Record the body's hash, then save it as the baseline.

    In that order: a baseline saved without its record would refuse the
    next run, while a record without its baseline leaves the old baseline,
    which the diff then calls foreign, as before.
    """
    sd.mkdir(parents=True, exist_ok=True)
    rec = {"sha256": digest(text), "at": at, "via": via}
    with open(sd / WRITES, "a") as f:
        f.write(json.dumps(rec) + "\n")
    write_atomic(sd / "last-written.md", text)


def foreign_edits(
    host: str,
    num: int,
    since: dt.datetime,
    mine: set[str],
    created: dt.datetime | None = None,
) -> list[dict]:
    """The body's history entries since the baseline that no write of this
    tool made, oldest first.

    Every thread writes as one account here, so logins can't tell them
    apart: an entry is this tool's when its body hashes to a recorded write.
    Any other entry later than the baseline's own time is foreign. GitHub
    can fold several writes into one entry: it is read at its latest time,
    with the body it ends on. A fold ending on a foreign edit is reported; one
    ending on this tool's write passes, and a foreign edit earlier in it had
    to pass that write's own diff against a recorded baseline.

    A body's first edit also adds a node for the body as created: editedAt
    the creation time, updatedAt the first edit's [measured on #516]. It is
    no edit, and GitHub's auto-ticks leave no node, so a body adopted after
    one never hashes to it. A node edited at or before the issue's creation
    is judged by that time alone, which no baseline precedes (CR 1195).
    """
    owner, name = host.split("/")
    data, _ = gh_graphql(
        "query($owner: String!, $name: String!, $number: Int!) {"
        " repository(owner: $owner, name: $name) { issue(number: $number) {"
        " userContentEdits(last: 100) { nodes {"
        " editedAt updatedAt editor { login } diff } } } } }",
        {"owner": owner, "name": name, "number": num},
        "reading the epic's edit history",
    )
    issue = (data.get("repository") or {}).get("issue") or {}
    out = []
    for e in (issue.get("userContentEdits") or {}).get("nodes") or []:
        edited = gh_time(e.get("editedAt"))
        if created and edited and edited <= created:
            continue
        times = [t for t in (edited, gh_time(e.get("updatedAt"))) if t]
        if not times or max(times) <= since + HISTORY_SLACK:
            continue
        diff = e.get("diff")
        if isinstance(diff, str) and digest(diff) in mine:
            continue
        out.append(
            {
                "at": max(times).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "editor": (e.get("editor") or {}).get("login"),
            }
        )
    return sorted(out, key=lambda x: x["at"])


def body_size(lines: list[str], limit: int) -> dict:
    """The body's size as GitHub keeps it (no final newline), against the limit."""
    chars = len("\n".join(lines))
    return {"chars": chars, "limit": limit, "share": round(chars / limit, 3)}


def size_text(size: dict) -> str:
    """ "262,319 characters, 100.1% of the 262,144-character limit" """
    return (
        f"{size['chars']:,} characters, {size['chars'] / size['limit']:.1%} of the"
        f" {size['limit']:,}-character limit"
    )


def near_limit(size: dict) -> bool:
    return size["chars"] > BODY_WARN * size["limit"]


def positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from None
    if n <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be above 0")
    return n


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        if os.path.getsize(tmp) == 0 and text:
            raise Infra(f"writing {path}: temp file came out empty")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- main


def run(argv: list[str]) -> int:
    p = Parser(
        prog="epic-edit.sh",
        description="Edit an epic's body with every check a coordinator thread once skipped.",
        epilog=USAGE_EXTRA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", required=True, help="owner/repo holding the epic")
    p.add_argument("--epic", required=True, type=int, help="the epic's issue number")
    p.add_argument("--ops", help="JSON array of operations: a file, or - for stdin")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="run every check, print the diff, write nothing",
    )
    p.add_argument(
        "--accept-ticks",
        default="",
        help="comma-separated refs whose foreign [ ]->[x] flip you have verified",
    )
    p.add_argument(
        "--adopt-live",
        action="store_true",
        help="take the live body as the baseline: first use, or after you merged a foreign edit by hand",
    )
    p.add_argument(
        "--closed-ok",
        action="store_true",
        help="write to a closed epic: the close-out's final write, after a child's"
        " thread already closed it. Without it, a closed epic is refused (a dry run"
        " only reports it)",
    )
    p.add_argument(
        "--account",
        nargs="?",
        const=0,
        type=int,
        metavar="FROM",
        help="refuse unless every open issue (numbered FROM or above, if given) is referenced"
        " in the body; a ref only in code doesn't count. For a whole-backlog or number-range"
        " epic, not a chosen subset. Warns about a ticked line whose subject is open",
    )
    p.add_argument(
        "--scan",
        metavar="FILE",
        help="scan.sh's JSON report, the one you read, for {checked} and {last_seen}."
        " Every new issue it found must be mentioned in the body (a tier line or the log),"
        " outside code",
    )
    p.add_argument(
        "--lint-all",
        action="store_true",
        help="lint the whole resulting body, not only the lines this edit changes."
        " For a body written outside this tool: a created or adopted epic",
    )
    p.add_argument(
        "--no-link-check", action="store_true", help="skip resolving new comment links"
    )
    p.add_argument(
        "--body-limit",
        type=positive_int,
        default=BODY_LIMIT,
        metavar="N",
        help=f"refuse a new body that grows past N characters (default {BODY_LIMIT:,},"
        " near the host's inferred cap, #653); warn past 85%%",
    )
    p.add_argument(
        "--state-dir",
        help="baseline directory, holding OWNER/REPO/N/ (default"
        " $XDG_STATE_HOME/coordinating-epics, else ~/.local/state/coordinating-epics)",
    )
    add_token_flag(p)
    a = p.parse_args(argv)
    host = a.repo
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", host) or any(
        part in (".", "..") for part in host.split("/")
    ):  # it names a directory, so no ".." (CR 299)
        p.error("--repo must be owner/repo")
    now = dt.datetime.now(dt.timezone.utc)
    summary: dict = {
        "repo": host,
        "epic": a.epic,
        "dry_run": a.dry_run,
        "written": False,
    }
    try:
        load_tokens(a.token_for)  # before any gh call: exit 1 fetches nothing
        ops = []
        scan = None
        try:
            if a.ops:
                raw = sys.stdin.read() if a.ops == "-" else Path(a.ops).read_text()
                ops = json.loads(raw)
            report = json.loads(Path(a.scan).read_text()) if a.scan else None
        except (OSError, json.JSONDecodeError) as e:
            raise Usage(f"reading --ops/--scan: {e}") from None
        check_ops(ops)
        if report is not None:
            if not isinstance(report, dict) or (
                str(report.get("repo", "")).lower() != host.lower()
                or report.get("epic") != a.epic
            ):
                raise Usage(f"--scan {a.scan} is not a scan.sh report on this epic")
            if (
                not re.fullmatch(
                    r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(report.get("now"))
                )
                or type(report.get("max_number")) is not int
            ):  # bool is an int (CR 270)
                raise Usage(f"--scan {a.scan} has no usable 'now' or 'max_number'")
            for name in ("new_numbers", "updated_since"):  # CR 282
                rows = report.get(name)
                if rows is not None and not (
                    isinstance(rows, list)
                    and all(
                        isinstance(r, dict) and type(r.get("number")) is int
                        for r in rows
                    )
                ):
                    raise Usage(
                        f"--scan {a.scan}: {name} must be a list of rows with a number"
                    )
            cursors = report.get("cursors") or {}
            wm = cursors.get("watermark") if isinstance(cursors, dict) else "?"
            if wm is not None and type(wm) is not int:  # CR 294
                raise Usage(
                    f"--scan {a.scan}: cursors must be an object whose watermark is a"
                    " number or null"
                )
            scan = {
                "checked": report["now"],
                "last_seen": f"#{report['max_number']}",
                # Everything the report moves the watermark past: the number walk's
                # finds, and any issue updated-since shows above the old watermark
                # (a transfer keeps its old creation date) (CR 276). With no
                # watermark, {last_seen} is refused below and nothing moves past
                # anything, so an old issue's update needs no mention (CR 287).
                "new_issues": sorted(
                    {
                        r["number"]
                        for r in (report.get("new_numbers") or [])
                        + [
                            u
                            for u in report.get("updated_since") or []
                            if wm is not None and u["number"] > wm
                        ]
                        if r.get("kind") == "issue" and r.get("number") != a.epic
                    }
                ),
                "numbers_scanned": report.get("new_numbers") is not None,
            }
            capped = report.get("capped") or []
            if not isinstance(capped, list):
                raise Usage(f"--scan {a.scan}: capped must be a list")

            def uses(name: str) -> bool:
                return any(
                    isinstance(v, str) and "{" + name + "}" in v
                    for op in ops
                    for v in op.values()
                )

            # A capped listing left rows unlisted: the updates listing its
            # oldest-created, where an issue transferred in sits, a comments
            # listing its newest. {checked} would move since past them all
            # (CR 306).
            cut = [
                w
                for w in capped
                if w
                in (
                    "listing updates",
                    "reading new comments",
                    "reading the epic's new comments",
                )
            ]
            if uses("checked") and cut:
                raise Usage(
                    f"the report's {', '.join(cut)} hit its page cap, so {{checked}}"
                    " would move the window past rows it never listed. Re-scan with a"
                    " later --since, one you have read up to"
                )
            if uses("last_seen"):
                if "listing updates" in capped:
                    raise Usage(
                        "the report's listing updates hit its page cap, so {last_seen}"
                        " could skip an issue transferred in. Re-scan with a later --since"
                    )
                if not scan["numbers_scanned"]:
                    raise Usage(
                        "the report scanned no numbers (no watermark), so {last_seen}"
                        " would skip issues nobody saw. Give scan.sh --watermark N,"
                        " then re-run"
                    )
                # The walk stopped short, or nothing caught what it can't see:
                # an issue transferred in keeps its old creation date (CR 302).
                if "listing new numbers" in capped:
                    raise Usage(
                        "the report's number walk hit its page cap, so {last_seen}"
                        " would skip numbers it never reached. Re-scan from a closer"
                        " --watermark"
                    )
                if report.get("updated_since") is None:
                    raise Usage(
                        "the report scanned no updates (no since), so {last_seen} would"
                        " skip an issue transferred in. Give scan.sh --since, then re-run"
                    )
            scan["also"] = also_from_report(report, a.scan, ops, uses("checked"))
            scan["uses_checked"] = uses("checked")
        if scan is None:
            needs = sorted(
                {
                    p
                    for op in ops
                    for v in op.values()
                    for p in ("{checked}", "{last_seen}")
                    if isinstance(v, str) and p in v
                }
                | {
                    m.group(0)
                    for op in ops
                    for v in op.values()
                    if isinstance(v, str)
                    for m in LAST_SEEN_FOR_RE.finditer(v)
                }
            )
            if needs:  # before the fetch: exit 1 means nothing was fetched (CR 269)
                raise Usage(f"{', '.join(needs)} needs --scan with scan.sh's report")
        try:  # before the fetch, like every usage check (CR 293)
            accepted = {
                parse_ref(r, host) for r in a.accept_ticks.split(",") if r.strip()
            }
        except Refused as e:
            raise Usage(f"--accept-ticks: {e}") from None
        sd = state_dir(a.state_dir, host, a.epic)
        base_path = sd / "last-written.md"

        live_issue = fetch_issue(host, a.epic)
        live_raw = live_issue.get("body") or ""
        # GitHub's time for the body as fetched, for the record of what this
        # run adopts (#518). The local clock only when GitHub sent none.
        live_at = str(
            live_issue.get("updated_at") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        live = normalize(live_raw)  # for comparisons only
        if scan and scan.get("uses_checked"):
            # A repo the body keeps a cursor for, which the scan didn't walk:
            # {checked} would move past its window unread (CR 2227).
            kept = {
                r
                for ln, code in zip(live, fenced(live))
                if not code
                and not ln[:1].isspace()
                and (m := FIELD_RE.match(ln))
                and (r := per_repo_cursor(m.group("field")))
            }
            unwalked = sorted(kept - set(scan.get("also") or {}))
            if unwalked:
                raise Refused(
                    "the epic keeps a Last issue seen for "
                    + ", ".join(unwalked)
                    + ", but the --scan report has no "
                    + ", ".join(f"--also {r}" for r in unwalked)
                    + ": {checked} would move past its window unread. Re-scan with it"
                )
        # A child's thread once closed the epic itself, and the editor then
        # wrote to it without complaint (#519).
        closed = closed_state(live_issue)
        summary.update(state=live_issue.get("state"), **(closed or {}))
        if closed and not a.closed_ok:
            msg = (
                f"the epic is closed (by {closed['closed_by']} at"
                f" {closed['closed_at']}). If that close is right, write with"
                " --closed-ok; if not, reopen it first"
            )
            if not a.dry_run:
                raise Refused(msg)
            print(f"NOTE {msg}", file=sys.stderr)
        live_lines = split_raw(live_raw)  # what the operations edit
        if not live:
            raise Refused(
                "the live body is empty; restore it from the edit history before editing"
            )

        if a.adopt_live or not base_path.exists():
            if not a.adopt_live:
                raise Refused(
                    f"no baseline at {base_path}. Read the live body, then re-run with"
                    " --adopt-live to take it as the baseline"
                )
            baseline = live
            summary["adopted_live"] = True
        else:
            base_text = base_path.read_text()
            writes = read_writes(sd)
            ours = [w for w in writes if w["sha256"] == digest(base_text)]
            if not ours:
                why = (
                    "it predates this tool's record of its writes (#518)"
                    if not writes
                    else "another thread may have saved it there"
                )
                raise Refused(
                    f"the baseline at {base_path} matches no body this tool wrote or"
                    f" adopted: {why}. Read the live body and its edit history, then"
                    " re-run with --adopt-live"
                )
            baseline = normalize(base_text)
            times = [t for t in (gh_time(w.get("at")) for w in ours) if t]
            try:
                if not times:
                    raise Infra("the record of this baseline has no usable time")
                summary["foreign_edits"] = foreign_edits(
                    host,
                    a.epic,
                    max(times),
                    {w["sha256"] for w in writes},
                    gh_time(live_issue.get("created_at")),
                )
            except Infra as e:
                summary["edit_history"] = f"unread: {gh_cause(e)}"
                print(
                    "WARNING the epic's edit history wasn't read, so an edit since"
                    f" the baseline shows only in the diff: {indented(gh_cause(e))}",
                    file=sys.stderr,
                )
            else:
                summary["edit_history"] = "read"
                if summary["foreign_edits"]:
                    print(
                        "WARNING the epic's edit history holds edits since this"
                        " tool's last write that none of its writes made: "
                        + ", ".join(
                            f"{e['at']} by {e['editor']}"
                            for e in summary["foreign_edits"]
                        )
                        + ". Read them in the history before trusting a clean diff",
                        file=sys.stderr,
                    )
        ticks, other = foreign_changes(baseline, live, host)
        summary["foreign_ticks"] = ticks
        if other:
            raise Refused(
                "the live body changed since this tool last wrote it, beyond box ticks."
                " Read the change, merge it by hand if needed, then re-run with --adopt-live:\n"
                + "\n".join(other)
            )
        unverified = [t for t in ticks if t not in accepted]
        if unverified:
            # The whole argument: the bare flag is a usage error (#621).
            raise Refused(
                "boxes ticked elsewhere since the last write: "
                + ", ".join(unverified)
                + ". A tick is a claim: verify each child, then pass --accept-ticks"
                f" '{','.join(sorted(set(ticks) | accepted))}'"
            )

        # compact keeps the issue's own title, read here so apply_ops stays
        # offline; a "title" in the op skips the read (#654).
        ops = [dict(op) for op in ops]
        for op in ops:
            if op.get("op") == "compact" and "title" not in op:
                repo, num = parse_ref(op["ref"], host).rsplit("#", 1)
                it = gh_json(
                    ["api", f"repos/{repo}/issues/{num}"], f"reading {op['ref']}"
                )
                op["title"] = str((it or {}).get("title") or "")
        before = counts(live_lines)
        new, expect, notes = apply_ops(live_lines, ops, host, now, scan)
        after = counts(new)
        size = body_size(new, a.body_limit)
        summary.update(counts_before=before, counts_after=after, notes=notes, body=size)
        if near_limit(size):
            print(
                f"WARNING the body is {size_text(size)}. Past the host's cap a"
                " write keeps the old body (#653): make room before it gets there",
                file=sys.stderr,
            )
        if not new:
            raise Refused("the result is empty")
        want = {k: before[k] + expect[k] for k in before}
        if after != want:
            raise Refused(
                f"checkbox counts {after} don't match the {want} the operations imply"
            )
        # Growth past the limit only: a write that shrinks an over-limit body
        # is how room gets made, and nothing written can't overflow (#653).
        if size["chars"] > a.body_limit and size["chars"] > len("\n".join(live_lines)):
            raise Refused(
                f"the new body is {size['chars']:,} characters,"
                f" {size['chars'] - a.body_limit:,} over the {a.body_limit:,}-character"
                " limit (--body-limit). Past its cap the host keeps the old body and"
                " still reports success (#653), so nothing was sent. Make room first:"
                " move the log into comments, or cut ticked lines to their title and"
                " a link"
            )

        comments = build_comments(ops, now, scan)
        posts = [{"chars": len(c), "posted": False, "url": None} for c in comments]
        if comments:
            summary["log_comments"] = posts

        # A created epic's body never passed through apply_ops, so an empty
        # ops list would lint nothing of it (CR 291).
        added, in_fence, in_table = introduced([] if a.lint_all else live_lines, new)
        problems = lint(added, host, not a.no_link_check, in_fence, in_table)
        # One checkbox line per issue lets each box follow its own issue (#662).
        # Valid either way, so a nudge on the lines this write adds or changes.
        multi = []
        for ln, code in zip(added, in_fence):
            ls = None if code else line_subjects(ln, host)
            if ls and ls[0] == "item" and len(ls[1]) > 1:
                multi.append(ln.strip())
        if multi:
            summary["multi_subject"] = multi
            print(
                "WARNING checkbox lines leading with two or more issues: "
                + "; ".join(f"'{m}'" for m in multi)
                + ". A line each lets each box follow its own issue (#662)",
                file=sys.stderr,
            )
        for c in comments:  # a log comment is linted as a changed line (#654)
            cl = c.split("\n")
            problems += lint(cl, host, not a.no_link_check, fenced(cl), tabled(cl))
        if problems:
            raise Refused("lint:\n" + "\n".join(f"  {x}" for x in problems))

        # The report moves the watermark past every issue it found, so each of
        # them must be accounted for in this write, or it is never seen again
        # (CR 265). A tier line or the log's "out of epic" both count; the
        # header's "Last issue seen" doesn't.
        if scan and scan["new_issues"]:
            mentioned = refs_in([ln for ln in new if not is_cursor_line(ln)], host)
            # The log comment is the log: naming an issue there counts (#654).
            mentioned |= refs_in([ln for c in comments for ln in c.split("\n")], host)
            missing = [
                n for n in scan["new_issues"] if key(None, n, host) not in mentioned
            ]
            if missing:
                raise Refused(
                    "the scan found issues this write doesn't mention: "
                    + ", ".join(f"#{n}" for n in missing)
                    + ". Slot each, or name it in the log line or log comment"
                    " (e.g. 'out of epic')"
                )
        # The same per --also repo, by qualified ref (#400).
        also_new = [
            (entry["repo"], n)
            for entry in ((scan or {}).get("also") or {}).values()
            for n in entry["new_issues"]
        ]
        if also_new:
            mentioned = refs_in([ln for ln in new if not is_cursor_line(ln)], host)
            mentioned |= refs_in([ln for c in comments for ln in c.split("\n")], host)
            missing_also = [
                f"{r}#{n}" for r, n in also_new if key(r, n, host) not in mentioned
            ]
            if missing_also:
                raise Refused(
                    "the scan found issues this write doesn't mention: "
                    + ", ".join(missing_also)
                    + ". Slot each, or name it in the log line or log comment"
                    " (e.g. 'out of epic')"
                )

        if a.account is not None:
            open_issues = gh_json(
                [
                    "issue",
                    "list",
                    "-R",
                    host,
                    "--state",
                    "open",
                    "--limit",
                    str(ACCOUNT_LIMIT),
                    "--json",
                    "number",
                ],
                "listing open issues",
            )
            if len(open_issues) >= ACCOUNT_LIMIT:
                raise Refused(
                    f"{ACCOUNT_LIMIT} or more open issues: the list may be cut off, so"
                    " the accounting can't be trusted (CR 259)"
                )
            # The header's "Last issue seen: #N" and "Next: #N" don't track an issue.
            listed = refs_in([ln for ln in new if not is_cursor_line(ln)], host)
            unlisted = sorted(
                i["number"]
                for i in open_issues
                if i["number"] != a.epic
                and i["number"] >= a.account
                and key(None, i["number"], host) not in listed
            )
            summary["unlisted"] = unlisted
            # A ticked line's subject should be closed (#662). The open set is
            # the whole repo's, so every ticked line is read, whatever N. A
            # warning, not a refusal: an existing epic may hold such a line.
            ticked_open, unchecked = ticked_subjects(
                new,
                host,
                {
                    key(None, i["number"], host)
                    for i in open_issues
                    if i["number"] != a.epic
                },
            )
            summary["ticked_open"] = ticked_open
            summary["ticked_unchecked"] = unchecked
            if ticked_open:
                print(
                    "WARNING ticked lines whose subject is still open: "
                    + "; ".join(
                        f"{', '.join(t['open'])} on '{t['line']}'" for t in ticked_open
                    )
                    + ". Untick the line, or close the issue (#662)",
                    file=sys.stderr,
                )
            if unchecked:
                print(
                    "NOTE ticked subjects in another repo aren't checked by --account: "
                    + ", ".join(unchecked),
                    file=sys.stderr,
                )
            if unlisted:
                # The body is the one place this reads: a log comment holds
                # history, so a disposition only it records is lost here (#657).
                raise Refused(
                    "open issues the epic doesn't reference: "
                    + ", ".join(f"#{n}" for n in unlisted)
                    + ". Slot each, or give it a line in a body section such as"
                    " '## Out of epic' (e.g. '- #N · out of epic: why'): a log"
                    " comment doesn't count, since --account reads the body only"
                    " (compaction.md)"
                )

        # The call this run's log comments belong to: the latest unfinished
        # one with the same comments in order, resumed, or a new one (#658).
        call: dict = {}
        if comments:
            keys = [comment_key(c) for c in comments]
            known = read_calls(sd)
            when = gh_time(live_at)
            since = (
                (when - SEARCH_SLACK).strftime("%Y-%m-%dT%H:%M:%SZ")
                if when
                else live_at
            )
            if known is None and read_writes(sd):
                # A state dir from before these records: its last run may have
                # left an exit 5, so this one run matches by body over the
                # two days before the epic's updated_at, as that version did
                # (CR 2213). The records start with this call.
                call = {"call": uuid.uuid4().hex[:16], "since": since, "new": True}
                old = (when - dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
                found, _ = comments_since(host, a.epic, old)
                seen = {b: u for b, u in found}
                for i, (c, post) in enumerate(zip(comments, posts)):
                    url = seen.get("\n".join(normalize(c)))
                    if url is not None:
                        post.update(posted="already", url=url)
                        call.setdefault("found", {})[i] = url
            else:
                calls, claimed = known or ([], set())
                hit = next((c for c in reversed(calls) if c["keys"] == keys), None)
                if hit is None:
                    call = {"call": uuid.uuid4().hex[:16], "since": since, "new": True}
                else:
                    call = {"call": hit["call"], "since": hit["since"], "found": {}}
                    for i, post in enumerate(posts):
                        if i in hit["posted"]:
                            post.update(posted="already", url=hit["posted"][i] or None)
                    left = [i for i in range(len(posts)) if i not in hit["posted"]]
                    if left:
                        # Its POST may have stored a part though gh reported a
                        # failure (CR 309): read from the call's own time.
                        found, capped = comments_since(host, a.epic, hit["since"])
                        if capped:
                            print(
                                "WARNING the epic's comments since the unfinished"
                                f" call passed {COMMENT_PAGES * 100}; a part not"
                                " read is posted again",
                                file=sys.stderr,
                            )
                        for i in left:
                            body = "\n".join(normalize(comments[i]))
                            url = next(
                                (u for b, u in found if b == body and u not in claimed),
                                None,
                            )
                            if url is not None:
                                claimed.add(url)
                                posts[i].update(posted="already", url=url)
                                call["found"][i] = url

        def post_all() -> int:
            """Post each log comment not yet posted, in order; stop at a failure.

            Only after the body is confirmed or unchanged: a comment can't be
            taken back, and the log must not run ahead of the epic (#654).
            """
            if comments:
                try:
                    # Before the first POST: a re-run then resumes this call,
                    # even when gh reports a failure after GitHub stored a part.
                    if call.get("new"):
                        record_attempt(
                            sd,
                            {
                                "call": call["call"],
                                "state": "pending",
                                "keys": [comment_key(c) for c in comments],
                                "since": call["since"],
                                "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            },
                        )
                        call["new"] = False
                    for i, url in (call.get("found") or {}).items():
                        record_attempt(
                            sd,
                            {
                                "call": call["call"],
                                "seq": i,
                                "state": "posted",
                                "url": url,
                            },
                        )
                    call["found"] = {}
                except OSError as e:
                    print(json.dumps(summary, indent=2))
                    print(
                        "ERROR the log comment wasn't posted: its call couldn't be"
                        f" recorded, so a re-run couldn't tell it was tried: {e}",
                        file=sys.stderr,
                    )
                    return EXIT_COMMENT
            for i, (c, post) in enumerate(zip(comments, posts)):
                if post["posted"]:
                    continue
                try:
                    post.update(posted=True, url=post_comment(host, a.epic, c))
                except Infra as e:
                    print(json.dumps(summary, indent=2))
                    body = (
                        ", but the body write is confirmed"
                        if summary.get("written") is True
                        else "; the body was unchanged"
                    )
                    print(
                        f"ERROR the log comment wasn't posted{body}. Re-run the same"
                        " call: the body ops hold, and a comment already posted is"
                        " found, not posted twice",
                        file=sys.stderr,
                    )
                    print(f"  gh's error: {indented(gh_cause(e))}", file=sys.stderr)
                    return EXIT_COMMENT
                try:
                    record_attempt(
                        sd,
                        {
                            "call": call["call"],
                            "seq": i,
                            "state": "posted",
                            "url": post["url"],
                        },
                    )
                except OSError as e:  # the call's record still finds it
                    print(f"WARNING attempt record not saved: {e}", file=sys.stderr)
            print(json.dumps(summary, indent=2))
            return EXIT_OK

        def held_comments() -> None:
            if any(not p["posted"] for p in posts):
                print(
                    "  the log comment wasn't posted: it waits for a confirmed body,"
                    " and the re-run posts it",
                    file=sys.stderr,
                )

        diff = list(
            difflib.unified_diff(live_lines, new, "live", "new", lineterm="", n=1)
        )
        if a.dry_run:
            print("\n".join(diff) or "(no change)", file=sys.stderr)
            for c, post in zip(comments, posts):
                if not post["posted"]:
                    print(f"log comment to post on the epic:\n{c}", file=sys.stderr)
            print(json.dumps(summary, indent=2))
            return EXIT_OK
        if new == live_lines:
            if summary.get("adopted_live") or ticks:
                save_baseline(
                    sd,
                    "\n".join(live_lines) + "\n",
                    live_at,
                    "adopt-live" if summary.get("adopted_live") else "accept-ticks",
                )
            summary["unchanged"] = True
            return post_all()

        # Compare-and-swap, as near as the API allows (CR 258).
        # Raw, not normalized: a whitespace-only edit is an edit too (CR 274).
        again = fetch_issue(host, a.epic)
        if split_raw(again.get("body") or "") != live_lines:
            raise Refused(
                "the live body changed while this run was checking it; nothing was"
                " written. Re-run to pick up the change"
            )
        if (shut := closed_state(again)) and not closed and not a.closed_ok:
            raise Refused(
                f"the epic was closed while this run was checking it (by"
                f" {shut['closed_by']} at {shut['closed_at']}); nothing was written"
            )
        text = "\n".join(new) + "\n"
        fd, payload = tempfile.mkstemp(dir=None, prefix="epic-edit-", suffix=".json")
        patch_error = None
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"body": text}, f)
            gh(
                [
                    "api",
                    "-X",
                    "PATCH",
                    f"repos/{host}/issues/{a.epic}",
                    "--input",
                    payload,
                ],
                "writing the epic",
            )
        except Infra as e:
            # A 502 or a timeout can come back after GitHub applied the
            # PATCH. The body says which; the exit code doesn't (CR 309).
            patch_error = e
        finally:
            os.unlink(payload)

        # Once the PATCH may have landed, a failure must still say so, or the
        # next run calls this tool's own edit foreign, unexplained (CR 300).
        # The ERROR line ends on the action; each cause follows on lines of
        # its own, whole, since gh's stderr can span lines (#426).
        def unconfirmed(
            why: str,
            head: str = "the body was written, but",
            causes: tuple[tuple[str, Infra], ...] = (),
        ) -> int:
            print(json.dumps(summary, indent=2))
            print(
                f"ERROR {head} {why}. The baseline was not updated: read the epic,"
                " then re-run with --adopt-live",
                file=sys.stderr,
            )
            for label, err in causes:
                print(f"  {label}: {indented(gh_cause(err))}", file=sys.stderr)
            held_comments()
            return EXIT_READBACK

        try:
            back_issue = fetch_issue(host, a.epic)
            back_raw = back_issue.get("body") or ""
        except Infra as e:
            if patch_error:
                summary["written"] = "unknown"
                return unconfirmed(
                    "reading the body to see whether it landed failed too",
                    head="the PATCH failed, and",
                    causes=(
                        ("the PATCH's error", patch_error),
                        ("the read-back's error", e),
                    ),
                )
            summary["written"] = True
            summary["readback"] = "failed"
            return unconfirmed(
                "reading it back failed", causes=(("the read-back's error", e),)
            )
        back = normalize(back_raw)
        # Raw first: a whitespace-only edit normalizes equal to the body it
        # changed, so only the raw lines say whether it landed (CR 274, 317).
        # The normalized match is for GitHub's own rewrites of what was sent.
        back_lines = split_raw(back_raw)
        if back_lines == new:
            landed = True
        elif back_lines == live_lines:
            landed = False
        else:
            landed = back == normalize(text)
        if not patch_error and not landed and back_lines == live_lines:
            # gh called the PATCH good, and the body is the one from before it:
            # the host kept it, as past its size cap (#653). Nothing landed, so
            # the baseline still matches the live body.
            summary["readback"] = "unchanged"
            print(json.dumps(summary, indent=2))
            if near_limit(size):
                why = (
                    "The host's issue-body size cap is the likely cause: make the body"
                    " smaller (move the log into comments, cut ticked lines to their"
                    " title and a link), then re-run"
                )
            else:
                why = (
                    "That is far below the limit. Read the epic and its edit history,"
                    " then re-run the same edit"
                )
            print(
                "ERROR the PATCH returned success, but the body read back is the one"
                " from before the edit: nothing landed. The baseline still matches the"
                f" live body, so it needs no re-adopting. The new body is"
                f" {size_text(size)}. {why}",
                file=sys.stderr,
            )
            held_comments()
            return EXIT_READBACK
        if patch_error:
            if landed:
                print(
                    "WARNING gh reported the PATCH failed, but it landed: "
                    + indented(gh_cause(patch_error)),
                    file=sys.stderr,
                )
            elif back_lines == live_lines:
                # Nothing written: exit 2. gh's words, not our header, whose
                # --input names the temp file unlinked above (CR 358).
                raise Infra(
                    f"writing the epic: {indented(gh_cause(patch_error))}",
                    stderr=patch_error.stderr,
                    code=patch_error.code,
                ) from None
            else:
                summary["written"] = "unknown"
                return unconfirmed(
                    "the body now matches neither the one sent nor the one before",
                    head="the PATCH failed, and",
                    causes=(("the PATCH's error", patch_error),),
                )
        summary["written"] = True
        if not landed:
            summary["readback"] = "differs"
            print(
                "\n".join(
                    difflib.unified_diff(new, back, "sent", "read back", lineterm="")
                ),
                file=sys.stderr,
            )
            return unconfirmed("the body read back differs from the body sent")
        summary["readback"] = "matches"
        try:
            save_baseline(
                sd,
                text,
                str(back_issue.get("updated_at") or live_at),
                "write",
            )
        except (OSError, Infra) as e:
            summary["baseline"] = "not saved"
            return unconfirmed(f"saving the baseline failed: {e}")
        try:  # a convenience copy: its loss is a warning, not an unconfirmed write
            write_atomic(sd / "history" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.md", text)
        except (OSError, Infra) as e:
            summary["history"] = f"not saved: {e}"
            print(f"WARNING history copy not saved: {e}", file=sys.stderr)
        return post_all()
    except Usage as e:
        print(f"USAGE {e}", file=sys.stderr)
        return EXIT_USAGE
    except Refused as e:
        summary["refused"] = str(e)
        print(json.dumps(summary, indent=2))
        print(f"REFUSED {e}", file=sys.stderr)
        return EXIT_REFUSED
    except Infra as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA
    except OSError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
