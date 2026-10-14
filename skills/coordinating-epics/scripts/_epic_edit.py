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
  line with set-line, then tick.

exit codes:
  0  written and read back, or nothing to write (every operation already held)
  1  usage error: a bad flag, or a malformed ops or --scan file. Nothing was
     fetched or written.
  2  infrastructure failure (gh or python3 failed; gh's own stderr is shown)
  3  refused: a foreign edit, a missing anchor, a count or lint failure, or an
     open issue the epic doesn't list (--account [FROM]). Nothing was written.
  4  written, but the body read back differs from the body sent. The baseline
     was not updated; read the epic before the next edit.
"""

BOX_RE = re.compile(r"^(?P<indent>\s*)(?P<bullet>[-*+]) \[(?P<mark>[ xX])\] ")
REF_PAT = r"(?<![\w/.-])(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)\b"
REF_RE = re.compile(REF_PAT)
LEAD = r"(?:~~|\*\*|\[|`)*"
ITEM_RE = re.compile(r"^\s*[-*+] \[[ xX]\] " + LEAD + REF_PAT)
BULLET_RE = re.compile(r"^\s*[-*+] " + LEAD + REF_PAT)
ROW_RE = re.compile(r"^\|\s*" + LEAD + REF_PAT)
# A closing #-sequence needs whitespace before it, as in CommonMark, so
# "## Notes on C#" keeps its "#" (CR 255).
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)(?:[ \t]+#+)?[ \t]*$")
FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
FIELD_RE = re.compile(
    r"^(?P<lead>\s*(?:[-*+]\s+)?\*\*(?P<field>[^*]+?):\*\*)(?P<value>.*)$"
)

SHELL_VAR_RE = re.compile(r"\$\{[A-Za-z_]\w*\}|\$[A-Z_][A-Z0-9_]+\b")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
PLACEHOLDER_RES = [
    (re.compile(r"\bSUB\d+\b"), "an unfilled SUBn placeholder"),
    (re.compile(r"\{\{[^}]*\}\}"), "an unfilled {{...}} placeholder"),
    (
        re.compile(r"\{(?:now|today|checked|last_seen)\}"),
        "an uninjected {now}/{today}/{checked}/{last_seen}",
    ),
    (re.compile(r"\\`"), "an escaped backtick"),
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
MD_LINK_RE = re.compile(
    r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]*)(?:\s+\"[^\"]*\")?\)"
)
GH_ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<num>\d+)(?![\w/])"
)
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
}
OP_OPTIONAL = {"add-line": ("after_ref", "section")}


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
    """The line as refs read it: a Markdown link becomes its GitHub ref, or its text.

    `[#400](https://github.com/o/r/issues/400)` is o/r#400, not this repo's #400,
    and `[plan](docs/plan.md#2-steps)` or `[s](#3-rescan)` holds no ref (CR 247).
    """

    def sub(m: re.Match) -> str:
        u = GH_ISSUE_URL_RE.match(m.group("target"))
        return f"{u.group('repo')}#{u.group('num')}" if u else m.group("text")

    return MD_LINK_RE.sub(sub, line)


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


def after_block(lines: list[str], i: int) -> int:
    """The index just past line i and the lines indented under it (CR 250).

    Inserting at i + 1 would put a new item between an item and its
    sub-bullets, and re-parent them under the new one. Blank lines inside
    the block don't end it while deeper lines follow (CR 266).
    """

    def indent(ln: str) -> int:
        return len(ln.expandtabs(4)) - len(ln.expandtabs(4).lstrip())

    base, end, j = indent(lines[i]), i + 1, i + 1
    while j < len(lines):
        if lines[j].strip():
            if indent(lines[j]) <= base:
                break
            end = j + 1
        j += 1
    return end


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
                # By the line's end, not a substring: a note "S" on "… · S"
                # is a new note, not one already there (CR 253).
                if lines[i].rstrip().endswith(" " + text):
                    notes.append(f"{where}: note already on {op['ref']}'s line")
                    continue
                lines[i] = lines[i].rstrip() + " " + text
            elif kind == "set-line":
                ref_key = parse_ref(op["ref"], host)
                i = find_ref_line(lines, ref_key, host)
                new = inject(op["line"], now, scan).rstrip()
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
                new = inject(op["line"], now, scan).rstrip()
                if "\n" in new or not new.strip():
                    raise Refused("add-line takes one non-empty line")
                if new in lines:
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
                if len(hits) != 1:
                    raise Refused(f"{len(hits)} '**{field}:**' lines; want exactly one")
                m = FIELD_RE.match(lines[hits[0]])
                assert m
                new = f"{m.group('lead')} {value}".rstrip()
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
                new_body = [""] + [ln.rstrip() for ln in text.split("\n")] + [""]
                if end == len(lines):
                    new_body.pop()
                old_body = lines[start + 1 : end]
                if normalize("\n".join(old_body)) == normalize("\n".join(new_body)):
                    notes.append(f"{where}: section already reads so")
                    continue
                before, after = counts(old_body), counts(new_body)
                _add(expect, {k: after[k] - before[k] for k in expect})
                lines[start + 1 : end] = new_body
            else:
                raise Usage(f"unknown op {kind!r}")
        except Usage as e:
            raise Usage(f"{where}: {e}") from None
        except KeyError as e:
            raise Usage(f"{where}: missing field {e}") from None
        except Refused as e:
            raise Refused(f"{where}: {e}") from None
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


def introduced(old: list[str], new: list[str]) -> list[str]:
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    out = []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(new[j1:j2])
    return out


def lint(new_lines: list[str], host: str, check_links: bool) -> list[str]:
    problems = []
    for raw in new_lines:
        # Placeholders, variables and secrets are read in the whole line, link
        # targets included; refs are read the way GitHub renders them.
        for rx, what in PLACEHOLDER_RES:
            if rx.search(raw):
                problems.append(f"{what}: {raw.strip()[:120]}")
        if SHELL_VAR_RE.search(CODE_SPAN_RE.sub("", raw)):
            problems.append(
                f"an unexpanded shell variable outside a code span: {raw.strip()[:120]}"
            )
        for rx in SECRET_RES:
            if rx.search(raw):
                problems.append("what looks like a secret (line withheld)")
        ln = ref_text(raw)
        for m in SHORT_REF_RE.finditer(CODE_SPAN_RE.sub("", ln)):
            problems.append(
                f"short ref {m.group('ref')} links nowhere; write owner/repo#N: {ln.strip()[:120]}"
            )
        for m in BARE_AFTER_QUALIFIED_RE.finditer(ln):
            if m.group("repo").lower() != host.lower():
                problems.append(
                    f"bare {m.group('bare')} after {m.group('repo')}# reads as this repo's;"
                    f" qualify it: {ln.strip()[:120]}"
                )
    bare = {
        int(m.group("num"))
        for ln in new_lines
        for m in REF_RE.finditer(ref_text(ln))
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
            except Infra:
                pass
            problems.append(
                f"#{n} is above {host}'s highest number (#{top}); a ref from another repo?"
            )
    if check_links:
        for ln in new_lines:
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
    return base / f"{repo.replace('/', '-')}-{num}"


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
        help="scan.sh's JSON report, for {checked} and {last_seen} (must be this repo's epic)",
    )
    p.add_argument(
        "--no-link-check", action="store_true", help="skip resolving new comment links"
    )
    p.add_argument(
        "--state-dir",
        help="baseline directory (default $XDG_STATE_HOME/coordinating-epics, else ~/.local/state/...)",
    )
    a = p.parse_args(argv)
    host = a.repo
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", host):
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
            scan = {
                "checked": report["now"],
                "last_seen": f"#{report['max_number']}",
                "new_issues": [
                    r["number"]
                    for r in report.get("new_numbers") or []
                    if r.get("kind") == "issue" and r.get("number") != a.epic
                ],
            }
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
        accepted = {parse_ref(r, host) for r in a.accept_ticks.split(",") if r.strip()}
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

        problems = lint(
            introduced(live_lines, new), host, check_links=not a.no_link_check
        )
        if problems:
            raise Refused("lint:\n" + "\n".join(f"  {x}" for x in problems))

        # The report moves the watermark past every issue it found, so each of
        # them must be accounted for in this write, or it is never seen again
        # (CR 265). A tier line or the log's "out of epic" both count; the
        # header's "Last issue seen" doesn't.
        if scan and scan["new_issues"]:
            mentioned = refs_in([ln for ln in new if not FIELD_RE.match(ln)], host)
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
            listed = refs_in([ln for ln in new if not FIELD_RE.match(ln)], host)
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
        if normalize(fetch_body(host, a.epic)) != live:
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
        back = normalize(fetch_body(host, a.epic))
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
        write_atomic(base_path, text)
        write_atomic(sd / "history" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.md", text)
        summary["readback"] = "matches"
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
