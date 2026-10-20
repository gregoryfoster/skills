#!/usr/bin/env python3
"""Find a reference in a Markdown file again, and the sentence that holds it.

Import it; don't run it. Stdlib only, Python 3.9+. gregoryfoster/skills#438
landed it for `stale-issue-prose.sh`, and it's shared within curating-context
only: #441, #442 and #447 import it from beside them. It isn't generalised past
this skill.

**Units, then sentences.** A file is cut into units: a heading, a list item, a
table row, or a paragraph (consecutive lines up to a blank one). A unit's lines
are joined with single spaces, so a soft-wrapped sentence comes back whole.
Inside a paragraph or a list item the unit is then cut into sentences, at a
`.`, `!` or `?` followed by whitespace and an upper-case letter, a digit or an
opening mark, unless the word before it is a known abbreviation (`e.g.`) or a
single letter. A heading is one sentence. A table row gives its first cell,
which names the row, and the cell holding the reference, joined by ` | `. A
sentence over `MAX_CHARS` is cut down to a window around the reference.

**Code is not prose.** A line inside a fenced block (``` or ~~~) and a span
inside backticks hold no claims, so a match there is marked `in_code` and the
caller counts it rather than judging it. Indented code blocks aren't detected:
in a policy file an indented line is far more often a list item's
continuation. HTML comments are prose, since an agent reads the raw file.
A blockquote's leading `>` markers are dropped before a line is classified.

**The reference grammar is `verify-facts.sh`'s,** `REF` below, so the two can't
disagree about what a reference is. A bare match directly after a word
(`watcher#278`) is a short cross-repo reference. The verifier resolves it
against the current repo, so `short_repo` names the word for the caller to
judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# verify-facts.sh: grep -oE '(\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[0-9]+'
REF = re.compile(r"(\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[0-9]+", re.ASCII)
_WORD_CHAR = re.compile(r"[A-Za-z0-9_.-]", re.ASCII)
_SHORT_REPO = re.compile(r"[A-Za-z0-9_.-]+$", re.ASCII)

MAX_CHARS = 1200

# Any indentation, as verify-facts.sh's own fence toggle reads it: a fence
# inside a list item is indented past CommonMark's three spaces.
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])[ \t]+")
_TABLE_ROW = re.compile(r"^\s*\|")
_BOUNDARY = re.compile(r"[.!?][\"')\]*_]*\s+(?=[A-Z0-9(\[*_`\"'#])")
_TICKS = re.compile(r"`+")
_QUOTE = re.compile(r"^[ \t]*(?:>[ \t]?)+")
# Not "no": "The answer is no." ends a sentence far more often in a policy
# file than "No. 5" abbreviates one (CR 429).
_ABBREV = frozenset("e.g i.e etc vs cf approx fig al viz resp esp incl ca".split())


@dataclass
class Occurrence:
    ref: str  # the matched token, exactly as the verifier's grep prints it
    line: int  # 1-based
    sentence: str
    heading: str | None  # the nearest heading above, without its #s
    in_code: bool
    short_repo: str | None  # `watcher` for `watcher#278`, else None


@dataclass
class _Unit:
    kind: str  # heading | item | row | para
    text: str
    # (offset in text, line number, offset in that line) for each joined line
    pieces: list
    heading: str | None


def _code_spans(line: str) -> list[tuple[int, int]]:
    """Spans of inline code in one line: a run of n backticks closes at the next run of exactly n."""
    spans, i = [], 0
    while True:
        m = _TICKS.search(line, i)
        if not m:
            return spans
        n = len(m.group())
        close = re.compile(r"(?<!`)`{%d}(?!`)" % n).search(line, m.end())
        if not close:
            i = m.end()
            continue
        spans.append((m.start(), close.end()))
        i = close.end()


def _in(spans, pos: int) -> bool:
    return any(a <= pos < b for a, b in spans)


def _units(lines: list[str]):
    """Prose units, and a ("code", line number) tuple for each line inside a fence."""
    heading = None
    fence = None  # the opening fence's character and length
    cur = None

    def flush():
        nonlocal cur
        u, cur = cur, None
        return u

    out = []
    for n, raw in enumerate(lines, 1):
        # A blockquote's `>` markers aren't prose; left in, they land mid-
        # sentence once its lines are joined (CR 428).
        raw = _QUOTE.sub("", raw)
        m = _FENCE.match(raw)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                if not raw[m.end() :].strip():
                    fence = None
            out.append(("code", n))
            continue
        # A backtick fence's info string can't hold a backtick (CommonMark), so
        # "```json``` blocks" opens an inline span, not a fence that would
        # swallow the rest of the file as code (CR 421).
        if m and not (m.group(1)[0] == "`" and "`" in raw[m.end() :]):
            out.append(flush())
            fence = (m.group(1)[0], len(m.group(1)))
            out.append(("code", n))
            continue
        if not raw.strip():
            out.append(flush())
            continue
        h = _HEADING.match(raw)
        if h:
            out.append(flush())
            text = raw[h.end() :].rstrip().rstrip("#").rstrip()
            out.append(_Unit("heading", text, [(0, n, h.end())], heading))
            heading = text
            continue
        if _TABLE_ROW.match(raw):
            out.append(flush())
            out.append(
                _Unit(
                    "row", raw.strip(), [(0, n, len(raw) - len(raw.lstrip()))], heading
                )
            )
            continue
        li = _LIST_ITEM.match(raw)
        if li:
            out.append(flush())
            cur = _Unit("item", raw[li.end() :], [(0, n, li.end())], heading)
            continue
        stripped = raw.lstrip()
        lead = len(raw) - len(stripped)
        if cur is None:
            cur = _Unit("para", stripped, [(0, n, lead)], heading)
        else:
            cur.pieces.append((len(cur.text) + 1, n, lead))
            cur.text = f"{cur.text} {stripped}"
    out.append(flush())
    return [u for u in out if u is not None]


def _sentence(unit: _Unit, pos: int) -> str:
    """The sentence of `unit.text` holding offset `pos`."""
    text = unit.text
    if unit.kind == "row":
        return _cell(text, pos)
    if unit.kind == "heading":
        start, end = 0, len(text)
    else:
        spans = _code_spans(text)
        start, end = 0, len(text)
        for m in _BOUNDARY.finditer(text):
            if _in(spans, m.start()):
                continue
            word = re.search(r"([A-Za-z.]+)$", text[: m.start()])
            w = word.group(1).strip(".").lower() if word else ""
            if w in _ABBREV or (len(w) == 1 and w.isalpha()):
                continue
            if m.end() <= pos:
                start = m.end()
            elif m.start() >= pos:
                end = m.end()
                break
    raw = text[start:end]
    lead = len(raw) - len(raw.lstrip())
    return _clip(raw.strip(), pos - start - lead)


def _cell(row: str, pos: int) -> str:
    """A table row's first cell, which names the row, and the cell holding `pos`."""
    spans = _code_spans(row)
    bars = [i for i, c in enumerate(row) if c == "|" and not _in(spans, i)]
    bars = [i for i in bars if i == 0 or row[i - 1] != "\\"]
    cells = [(a + 1, b) for a, b in zip(bars, bars[1:])]
    if not cells:
        return _clip(row.strip(), pos)
    first = row[cells[0][0] : cells[0][1]].strip()
    for a, b in cells:
        if a <= pos < b:
            cell = row[a:b].strip()
            if (a, b) == cells[0]:
                return _clip(cell, pos - a)
            return _clip(f"{first} | {cell}", pos - a + len(first) + 3)
    return _clip(row.strip(), pos)


def _clip(s: str, pos: int) -> str:
    """`s` cut to `MAX_CHARS` around `pos`, with an ellipsis where it was cut."""
    if len(s) <= MAX_CHARS:
        return s
    a = min(max(0, pos - MAX_CHARS // 2), len(s) - MAX_CHARS)
    return (
        ("…" if a else "")
        + s[a : a + MAX_CHARS]
        + ("…" if a + MAX_CHARS < len(s) else "")
    )


def occurrences(text: str) -> list[Occurrence]:
    """Every reference in `text`, in order, each with its sentence."""
    lines = text.split("\n")
    found: list[Occurrence] = []
    units = _units(lines)
    fenced = {u[1] for u in units if isinstance(u, tuple)}
    for n in sorted(fenced):
        for m in REF.finditer(lines[n - 1]):
            found.append(Occurrence(m.group(), n, "", None, True, None))
    for unit in units:
        if isinstance(unit, tuple):
            continue
        spans = _code_spans(unit.text)
        for m in REF.finditer(unit.text):
            line = unit.pieces[0][1]
            for off, ln, _lead in unit.pieces:
                if off <= m.start():
                    line = ln
            short = None
            if (
                m.group(1) is None
                and m.start() > 0
                and _WORD_CHAR.match(unit.text[m.start() - 1])
            ):
                short = _SHORT_REPO.search(unit.text[: m.start()]).group()
            in_code = _in(spans, m.start())
            found.append(
                Occurrence(
                    ref=m.group(),
                    line=line,
                    sentence="" if in_code else _sentence(unit, m.start()),
                    heading=unit.heading if unit.kind != "heading" else None,
                    in_code=in_code,
                    short_repo=short,
                )
            )
    found.sort(key=lambda o: o.line)
    return found
