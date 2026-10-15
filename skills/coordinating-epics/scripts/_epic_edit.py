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
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_OK, EXIT_USAGE, EXIT_INFRA, EXIT_REFUSED, EXIT_READBACK = 0, 1, 2, 3, 4

USAGE_EXTRA = """\
operations (a JSON array, from --ops FILE or --ops - for stdin):
  {"op": "tick", "ref": "#12"}                set #12's box to [x]
  {"op": "untick", "ref": "#12"}              set #12's box to [ ]
  {"op": "note", "ref": "#12", "text": "..."} append text to #12's line, once
  {"op": "set-line", "ref": "#12", "line": "- [x] #12 ..."}
                                              replace #12's line; the new line
                                              must lead with the same ref
  {"op": "add-line", "line": "- [ ] #44 ...", "after_ref": "#43"}
  {"op": "add-line", "line": "- [ ] #44 ...", "section": "Tier 2"}
                                              insert, once; refuses a second
                                              line for a ref that has one
  {"op": "header", "field": "Last check-in", "value": "{checked}"}
                                              set a "- **Field:** value" line
  {"op": "log", "text": "{today}: #12 closed. No new issues. Next: #13."}
                                              append "- text" to the Log section
  {"op": "replace-section", "heading": "Measured state", "text": "..."}
                                              replace a section's body
  {"op": "add-section", "heading": "Log", "text": "...", "before": "Notes"}
                                              add a "## heading" section, once:
                                              before "before", else at the end

  A header op on a cursor field the body lacks (Last check-in, Last probe,
  Last issue seen, Last verified SHA, Next) adds its line after the header
  block, or before the first heading. With add-section, that brings an
  adopted epic onto the template without a hand edit.

  A ref is "#N" for this repo or "owner/repo#N". A ref's line is the checklist
  item, bullet or table row whose first token is that ref. In any text,
  {now} becomes the UTC time (2026-10-14T18:03Z) and {today} the UTC date.
  With --scan FILE (scan.sh's report), {checked} becomes the report's own time
  and {last_seen} its highest number (#58). Write those two into the header's
  Last check-in and Last issue seen: the next scan's window then starts where
  this one looked, not where the write happened.

lint:
  Every line the edit adds or changes is linted whole, so ticking a line that
  already holds a short ref or an unexpanded variable is refused with it. That
  is deliberate: legacy text is fixed the first time it is touched. Rewrite the
  line with set-line, then tick. A fenced code block renders as written, so its
  lines are checked for secrets only; a code span skips every check but SUBn,
  \\` and secrets.

exit codes:
  0  written and read back, or nothing to write (every operation already held)
  1  usage error: a bad flag, or a malformed ops or --scan file. Nothing was
     fetched or written.
  2  infrastructure failure (gh or python3 failed; gh's own stderr is shown)
  3  refused: a foreign edit, a missing anchor, a count or lint failure, an
     open issue the epic doesn't list (--account [FROM]), or a new issue in the
     --scan report that the body doesn't mention. Nothing was written.
  4  written, but not confirmed: the body read back differs from the body sent,
     the read-back failed, or the baseline couldn't be saved. The summary says
     which. Read the epic, then take it with --adopt-live before the next edit.
"""

BOX_RE = re.compile(r"^(?P<indent>\s*)(?P<bullet>[-*+]) \[(?P<mark>[ xX])\] ")
REF_PAT = r"(?<![\w/.-])(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)\b"
REF_RE = re.compile(REF_PAT)
LEAD = r"(?:~~|\*\*|\[|`)*"
ITEM_RE = re.compile(r"^\s*[-*+] \[[ xX]\] " + LEAD + REF_PAT)
BULLET_RE = re.compile(r"^\s*[-*+] " + LEAD + REF_PAT)
ROW_RE = re.compile(r"^\|\s*" + LEAD + REF_PAT)
UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
# A closing #-sequence needs whitespace before it, as in CommonMark, so
# "## Notes on C#" keeps its "#" (CR 255).
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)(?:[ \t]+#+)?[ \t]*$")
FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
FIELD_RE = re.compile(
    r"^(?P<lead>\s*(?:[-*+]\s+)?\*\*(?P<field>[^*]+?):\*\*)(?P<value>.*)$"
)

SHELL_VAR_RE = re.compile(r"\$\{[A-Za-z_]\w*\}|\$[A-Z_][A-Z0-9_]+\b")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
# (pattern, what, read inside code spans too). A code span shows `${{ x }}`
# as written, so those two skip spans (CR 290). A SUBn in a span is still a
# leftover, and stripping spans would hide the \` an unquoted heredoc leaves,
# since the escaped backtick itself opens or closes the span.
PLACEHOLDER_RES = [
    (re.compile(r"\bSUB\d+\b"), "an unfilled SUBn placeholder", True),
    (re.compile(r"\{\{[^}]*\}\}"), "an unfilled {{...}} placeholder", False),
    (
        re.compile(r"\{(?:now|today|checked|last_seen)\}"),
        "an uninjected {now}/{today}/{checked}/{last_seen}",
        False,
    ),
    (re.compile(r"\\`"), "an escaped backtick", True),
]
SECRET_RES = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
BARE_AFTER_QUALIFIED_RE = re.compile(
    r"(?<![\w/.-])(?P<repo>[\w.-]+/[\w.-]+)#\d+(?:\s*(?:,|/|;|&|\band\b|\bor\b)\s*)(?P<bare>#\d+)\b"
)
SHORT_REF_RE = re.compile(r"(?<![\w/.#-])(?P<ref>[A-Za-z][\w.-]*#\d+)\b")
# Link text may hold one level of brackets; the target may be <angled> or hold
# one level of parentheses; the title may be "…", '…' or (…) (CR 271).
LINK_MARK = "\ufffc"  # what a non-issue link reads as: no ref, no separator
MD_LINK_RE = re.compile(
    r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
    r"\((?P<target><[^>]*>|(?:[^()\s]|\([^()\s]*\))*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
_ISSUE_URL = r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<num>\d+)(?![\w/])"
GH_ISSUE_URL_RE = re.compile(_ISSUE_URL)
# GitHub renders a bare or <angled> issue URL as its ref, and "Fixes <url>"
# closes the issue (CR 288). A fragment (#issuecomment-…) stays a ref.
ANGLED_ISSUE_URL_RE = re.compile(r"<" + _ISSUE_URL + r"[^<>\s]*>")
BARE_ISSUE_URL_RE = re.compile(r"(?<![\w/<])" + _ISSUE_URL)
COMMENT_LINK_RE = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<num>\d+)#issuecomment-(?P<id>\d+)"
)


class Refused(Exception):
    """A check failed; nothing was written."""


class NotFound(Refused):
    """No line leads with the ref: the one refusal add-line's duplicate guard expects."""


class Infra(Exception):
    """A tool the check depends on failed."""


class Usage(Exception):
    """The invocation or the ops file is malformed; exit 1, nothing fetched or written."""


class Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; 2 means infrastructure here (CR 249)."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


ACCOUNT_LIMIT = 5000

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
}
OP_OPTIONAL = {"add-line": ("after_ref", "section"), "add-section": ("before",)}


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


def is_cursor_line(line: str) -> bool:
    """A header cursor line, whose refs (Last issue seen, Next) track no issue.

    Only these: a tier line "- **#15:** …" or a log line "**2026-10-14:** #15 …"
    mentions #15 (CR 278).
    """
    m = FIELD_RE.match(line)
    return bool(m) and m.group("field").strip().lower() in CURSOR_FIELDS


def trailing(line: str) -> str:
    """A line's trailing whitespace: two spaces of it are a hard line break."""
    return line[len(line.rstrip()) :]


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


def key(repo: str | None, num: str | int, host: str) -> str:
    return f"{(repo or host).lower()}#{int(num)}"


def parse_ref(ref: str, host: str) -> str:
    m = re.fullmatch(r"\s*" + REF_PAT + r"\s*", ref)
    if not m:
        raise Refused(f"not a ref: {ref!r} (want #N or owner/repo#N)")
    return key(m.group("repo"), m.group("num"), host)


def ref_text(line: str) -> str:
    """The line as refs read it: a link to an issue becomes its ref; any other, nothing.

    `[#400](https://github.com/o/r/issues/400)` is o/r#400, not this repo's #400,
    and `[plan](docs/plan.md#2-steps)` or `[s](#3-rescan)` holds no ref (CR 247).
    GitHub doesn't autolink inside link text, so `[see #5](doc)` holds none
    either (CR 271). Reference-style links (`[text][id]`) aren't resolved: their
    text reads as plain text. A bare or <angled> issue URL is its ref (CR 288).
    """

    def sub(m: re.Match) -> str:
        u = GH_ISSUE_URL_RE.match(m.group("target").strip("<>"))
        # A neutral mark, not "": dropping the link could join a qualified ref
        # and a bare one into what reads as "a/b#5, #6" (CR 277).
        return f"{u.group('repo')}#{u.group('num')}" if u else LINK_MARK

    def as_ref(m: re.Match) -> str:
        return f"{m.group('repo')}#{m.group('num')}"

    line = MD_LINK_RE.sub(sub, line)
    return BARE_ISSUE_URL_RE.sub(as_ref, ANGLED_ISSUE_URL_RE.sub(as_ref, line))


def line_ref(line: str, host: str) -> tuple[str, str] | None:
    """(kind, key) when the line is an item, bullet or row led by a ref."""
    line = ref_text(line)
    for kind, rx in (("item", ITEM_RE), ("bullet", BULLET_RE), ("row", ROW_RE)):
        m = rx.match(line)
        if m:
            return kind, key(m.group("repo"), m.group("num"), host)
    return None


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


def section_level(lines: list[str]) -> int:
    """The level a new last section takes: the shallowest the sections use.

    A first heading whose level appears nowhere else is the title, not a
    section, so "# Burn-down" over "##" sections gives 2. No sections: 2.
    """
    levels = [lvl for _, lvl, _ in headings(lines)]
    if (
        levels
        and levels.count(levels[0]) == 1
        and all(lv > levels[0] for lv in levels[1:])
    ):
        levels = levels[1:]
    return min(levels, default=2)


def section_span(lines: list[str], heading: str) -> tuple[int, int]:
    """(index of the heading line, index one past the section's last line)."""
    hs = headings(lines)
    want = heading.strip().lower()
    found = [(i, lvl) for i, lvl, text in hs if text.lower() == want]
    if not found:
        raise Refused(f"no section headed {heading!r}")
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


def header_end(lines: list[str]) -> int:
    """Where a new header line goes: after the field lines above the first
    heading, else just before that heading (or the body's end)."""
    hs = headings(lines)
    first = hs[0][0] if hs else len(lines)
    fence = fenced(lines)
    fields = [i for i in range(first) if not fence[i] and FIELD_RE.match(lines[i])]
    if fields:
        return fields[-1] + 1
    while first > 0 and not lines[first - 1].strip():
        first -= 1
    return first


def section_tail(lines: list[str], start: int, end: int) -> int:
    """Insertion point at a section's end, before its trailing blank lines."""
    pos = end
    while pos - 1 > start and not lines[pos - 1].strip():
        pos -= 1
    return pos


def counts(lines: list[str]) -> dict[str, int]:
    fence = fenced(lines)
    out = {"open": 0, "done": 0}
    for i, ln in enumerate(lines):
        m = BOX_RE.match(ln)
        if m and not fence[i]:
            out["done" if m.group("mark") in "xX" else "open"] += 1
    return out


def box_state(line: str) -> str | None:
    m = BOX_RE.match(line)
    if not m:
        return None
    return "done" if m.group("mark") in "xX" else "open"


def set_box(line: str, done: bool) -> str:
    m = BOX_RE.match(line)
    assert m
    mark = "x" if done else " "
    return f"{m.group('indent')}{m.group('bullet')} [{mark}] " + line[m.end() :]


def refs_in(lines: list[str], host: str) -> set[str]:
    fence = fenced(lines)
    out = set()
    for i, ln in enumerate(lines):
        if fence[i]:
            continue
        for m in REF_RE.finditer(ref_text(ln)):
            out.add(key(m.group("repo"), m.group("num"), host))
    return out


# ---------------------------------------------------------------- operations


def inject(text: str, now: dt.datetime, scan: dict | None = None) -> str:
    for name in ("checked", "last_seen"):
        if "{" + name + "}" in text:
            if not scan:
                raise Usage(f"{{{name}}} needs --scan with scan.sh's report")
            text = text.replace("{" + name + "}", scan[name])
    return text.replace("{now}", now.strftime("%Y-%m-%dT%H:%MZ")).replace(
        "{today}", now.strftime("%Y-%m-%d")
    )


def _delta(before: str | None, after: str | None) -> dict[str, int]:
    d = {"open": 0, "done": 0}
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
    expect = {"open": 0, "done": 0}
    notes: list[str] = []
    for n, op in enumerate(ops, 1):
        kind = op.get("op")
        where = f"op {n} ({kind})"
        try:
            if kind in ("tick", "untick"):
                i = find_ref_line(
                    lines, parse_ref(op["ref"], host), host, want_item=True
                )
                want = kind == "tick"
                before = box_state(lines[i])
                if (before == "done") == want:
                    notes.append(
                        f"{where}: {op['ref']} already {'ticked' if want else 'unticked'}"
                    )
                    continue
                lines[i] = set_box(lines[i], want)
                _add(expect, _delta(before, box_state(lines[i])))
            elif kind == "note":
                i = find_ref_line(lines, parse_ref(op["ref"], host), host)
                text = inject(op["text"], now, scan).strip()
                if not text or "\n" in text:
                    raise Refused("note text must be one non-empty line")
                head, close = lines[i].rstrip(), ""
                if ROW_RE.match(ref_text(head)):
                    # Inside the last cell: GFM drops a cell past the header's
                    # count, so text after the closing pipe never shows (CR 286).
                    if UNESCAPED_PIPE_RE.search(text):
                        raise Refused(
                            "a note on a table row can't hold a bare |; write \\|"
                        )
                    if head.endswith("|") and not head.endswith("\\|"):
                        head, close = head[:-1].rstrip(), " |"
                # By the line's end, not a substring: a note "S" on "… · S"
                # is a new note, not one already there (CR 253).
                if head.endswith(" " + text):
                    notes.append(f"{where}: note already on {op['ref']}'s line")
                    continue
                # The note goes before the line's own trailing break (CR 274).
                lines[i] = head + " " + text + close + trailing(lines[i])
            elif kind == "set-line":
                ref_key = parse_ref(op["ref"], host)
                i = find_ref_line(lines, ref_key, host)
                new = inject(op["line"], now, scan).rstrip("\r\n")
                if "\n" in new:
                    raise Refused("set-line takes one line")
                lr = line_ref(new, host)
                if not lr or lr[1] != ref_key:
                    raise Refused(f"the new line doesn't lead with {op['ref']}")
                if new == lines[i]:
                    notes.append(f"{where}: {op['ref']}'s line already reads so")
                    continue
                _add(expect, _delta(box_state(lines[i]), box_state(new)))
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
                if "after_ref" in op:
                    anchor = find_ref_line(
                        lines, parse_ref(op["after_ref"], host), host
                    )
                    pos = after_block(lines, anchor)
                elif "section" in op:
                    start, end = section_span(lines, op["section"])
                    pos = section_tail(lines, start, end)
                else:
                    raise Refused("add-line needs after_ref or section")
                lines.insert(pos, new)
                _add(expect, _delta(None, box_state(new)))
            elif kind == "header":
                field = op["field"].strip()
                value = inject(op["value"], now, scan).strip()
                fence = fenced(lines)
                hits = [
                    i
                    for i, ln in enumerate(lines)
                    if not fence[i]
                    and (m := FIELD_RE.match(ln))
                    and m.group("field").strip().lower() == field.lower()
                ]
                if not hits and field.lower() in CURSOR_FIELDS:
                    # An adopted epic gets its cursors through here, not a
                    # hand edit (CR 292). Other fields aren't added: a typo
                    # would make a line no script reads.
                    pos = header_end(lines)
                    new = [f"- **{CURSOR_FIELDS[field.lower()]}:** {value}".rstrip()]
                    if pos < len(lines) and lines[pos].strip():
                        new.append("")
                    if (
                        pos
                        and lines[pos - 1].strip()
                        and not FIELD_RE.match(lines[pos - 1])
                    ):
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
    return lines, expect, notes


# ---------------------------------------------------------------- gh


def gh(args: list[str], what: str) -> str:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise Infra("gh is not on PATH") from None
    if r.returncode != 0:
        raise Infra(
            f"{what}: gh {' '.join(args)} exited {r.returncode}:\n{r.stderr.strip()}"
        )
    return r.stdout


def gh_json(args: list[str], what: str):
    out = gh(args, what)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise Infra(f"{what}: gh returned non-JSON: {out[:200]!r}") from None


def fetch_body(repo: str, num: int) -> str:
    data = gh_json(["api", f"repos/{repo}/issues/{num}"], "fetching the epic")
    return data.get("body") or ""


# ---------------------------------------------------------------- lint


def introduced(old: list[str], new: list[str]) -> tuple[list[str], list[bool]]:
    """The lines new adds or changes, and whether each sits in a fenced block."""
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    fence = fenced(new)
    out, code = [], []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(new[j1:j2])
            code.extend(fence[j1:j2])
    return out, code


def absent(e: Infra) -> bool:
    """Whether gh's failure says the thing doesn't exist (404, or 410 deleted).

    Only that is a lint finding. A rate limit, an auth failure or a network
    error is infrastructure, exit 2, not a refusal of the line (CR 304).
    """
    return bool(re.search(r"\bHTTP 4(?:04|10)\b", str(e)))


def rendered_refs(line: str) -> str:
    """ref_text, with code spans read as a neutral mark: GitHub links no ref in one."""
    return CODE_SPAN_RE.sub(LINK_MARK, ref_text(line))


def lint(
    new_lines: list[str],
    host: str,
    check_links: bool,
    in_fence: list[bool] | None = None,
) -> list[str]:
    in_fence = in_fence or [False] * len(new_lines)
    problems = []
    prose = []
    for raw, code in zip(new_lines, in_fence):
        for rx in SECRET_RES:
            if rx.search(raw):
                problems.append("what looks like a secret (line withheld)")
        # A fenced block renders as written: a command's $VAR, a CI
        # ${{ matrix.x }} or an example ref are its text (CR 290).
        if code:
            continue
        prose.append(raw)
        # Placeholders and variables are read in the whole line, link targets
        # included; refs are read the way GitHub renders them.
        for rx, what, in_spans in PLACEHOLDER_RES:
            if rx.search(raw if in_spans else CODE_SPAN_RE.sub("", raw)):
                problems.append(f"{what}: {raw.strip()[:120]}")
        if SHELL_VAR_RE.search(CODE_SPAN_RE.sub("", raw)):
            problems.append(
                f"an unexpanded shell variable outside a code span: {raw.strip()[:120]}"
            )
        ln = rendered_refs(raw)
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
        for ln in prose
        for m in REF_RE.finditer(rendered_refs(ln))
        if not m.group("repo")
    }
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
        for ln in prose:
            for m in COMMENT_LINK_RE.finditer(ln):
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
                    problems.append(f"comment link doesn't resolve: {m.group(0)} ({e})")
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
        "--account",
        nargs="?",
        const=0,
        type=int,
        metavar="FROM",
        help="refuse unless every open issue (numbered FROM or above, if given) is referenced"
        " in the body. For a whole-backlog or number-range epic, not a chosen subset",
    )
    p.add_argument(
        "--scan",
        metavar="FILE",
        help="scan.sh's JSON report, the one you read, for {checked} and {last_seen}."
        " Every new issue it found must be mentioned in the body (a tier line or the log)",
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
        "--state-dir",
        help="baseline directory, holding OWNER/REPO/N/ (default"
        " $XDG_STATE_HOME/coordinating-epics, else ~/.local/state/coordinating-epics)",
    )
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

            # A capped listing is cut at its oldest-created rows, where an
            # issue transferred in sits, and {checked} would move since past
            # every row it never listed (CR 306).
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
        if scan is None:
            needs = sorted(
                {
                    p
                    for op in ops
                    for v in op.values()
                    for p in ("{checked}", "{last_seen}")
                    if isinstance(v, str) and p in v
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

        live_raw = fetch_body(host, a.epic)
        live = normalize(live_raw)  # for comparisons only
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
            baseline = normalize(base_path.read_text())
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
            raise Refused(
                "boxes ticked elsewhere since the last write: "
                + ", ".join(unverified)
                + ". A tick is a claim: verify each child, then pass --accept-ticks"
            )

        before = counts(live_lines)
        new, expect, notes = apply_ops(live_lines, ops, host, now, scan)
        after = counts(new)
        summary.update(counts_before=before, counts_after=after, notes=notes)
        if not new:
            raise Refused("the result is empty")
        want = {k: before[k] + expect[k] for k in before}
        if after != want:
            raise Refused(
                f"checkbox counts {after} don't match the {want} the operations imply"
            )

        # A created epic's body never passed through apply_ops, so an empty
        # ops list would lint nothing of it (CR 291).
        added, in_fence = introduced([] if a.lint_all else live_lines, new)
        problems = lint(added, host, not a.no_link_check, in_fence)
        if problems:
            raise Refused("lint:\n" + "\n".join(f"  {x}" for x in problems))

        # The report moves the watermark past every issue it found, so each of
        # them must be accounted for in this write, or it is never seen again
        # (CR 265). A tier line or the log's "out of epic" both count; the
        # header's "Last issue seen" doesn't.
        if scan and scan["new_issues"]:
            mentioned = refs_in([ln for ln in new if not is_cursor_line(ln)], host)
            missing = [
                n for n in scan["new_issues"] if key(None, n, host) not in mentioned
            ]
            if missing:
                raise Refused(
                    "the scan found issues this write doesn't mention: "
                    + ", ".join(f"#{n}" for n in missing)
                    + ". Slot each, or name it in the log line (e.g. 'out of epic')"
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
            if unlisted:
                raise Refused(
                    "open issues the epic doesn't reference: "
                    + ", ".join(f"#{n}" for n in unlisted)
                )

        diff = list(
            difflib.unified_diff(live_lines, new, "live", "new", lineterm="", n=1)
        )
        if a.dry_run:
            print("\n".join(diff) or "(no change)", file=sys.stderr)
            print(json.dumps(summary, indent=2))
            return EXIT_OK
        if new == live_lines:
            if summary.get("adopted_live") or ticks:
                write_atomic(base_path, "\n".join(live_lines) + "\n")
            summary["unchanged"] = True
            print(json.dumps(summary, indent=2))
            return EXIT_OK

        # Compare-and-swap, as near as the API allows (CR 258).
        # Raw, not normalized: a whitespace-only edit is an edit too (CR 274).
        if split_raw(fetch_body(host, a.epic)) != live_lines:
            raise Refused(
                "the live body changed while this run was checking it; nothing was"
                " written. Re-run to pick up the change"
            )
        text = "\n".join(new) + "\n"
        fd, payload = tempfile.mkstemp(dir=None, prefix="epic-edit-", suffix=".json")
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
        finally:
            os.unlink(payload)
        summary["written"] = True

        # The PATCH landed: from here a failure must still say "written", or
        # the next run calls this tool's own edit foreign, unexplained (CR 300).
        def unconfirmed(why: str) -> int:
            print(json.dumps(summary, indent=2))
            print(
                f"ERROR the body was written, but {why}. The baseline was not"
                " updated: read the epic, then re-run with --adopt-live",
                file=sys.stderr,
            )
            return EXIT_READBACK

        try:
            back = normalize(fetch_body(host, a.epic))
        except Infra as e:
            summary["readback"] = "failed"
            return unconfirmed(f"reading it back failed:\n{e}")
        if back != normalize(text):
            summary["readback"] = "differs"
            print(
                "\n".join(
                    difflib.unified_diff(new, back, "sent", "read back", lineterm="")
                ),
                file=sys.stderr,
            )
            print(json.dumps(summary, indent=2))
            print(
                "ERROR the body read back differs from the body sent; baseline not updated",
                file=sys.stderr,
            )
            return EXIT_READBACK
        summary["readback"] = "matches"
        try:
            write_atomic(base_path, text)
        except (OSError, Infra) as e:
            summary["baseline"] = "not saved"
            return unconfirmed(f"saving the baseline failed: {e}")
        try:  # a convenience copy: its loss is a warning, not an unconfirmed write
            write_atomic(sd / "history" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.md", text)
        except (OSError, Infra) as e:
            summary["history"] = f"not saved: {e}"
            print(f"WARNING history copy not saved: {e}", file=sys.stderr)
        print(json.dumps(summary, indent=2))
        return EXIT_OK
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
