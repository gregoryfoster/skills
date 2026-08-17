"""Demotion is a manual copy, and a copy can arrive damaged (#158).

`curating-context` Phase 5 moves a block out of `SKILL.md` into a reference doc
by hand. `prove-no-loss.sh` checks that every base line arrived *somewhere*; it
does not check that what arrived is still a paragraph. Two failure shapes have
shipped, both from the same commit (`4c942b2`, the v1.7 trim), and neither was
visible to any existing gate:

  truncated   The copy started or stopped mid-sentence, leaving a **tail with
              its head gone**. `telemetry.md` carried two — "version makes the
              cohort look uniform when it isn't…" (head: "Rows also carry
              `skill_version`…") and "distinction in
              [budget-and-metrics.md]…". `prove-no-loss.sh` is line-oriented, so
              a surviving tail line satisfies it exactly as well as the whole
              paragraph would.
  indented    The copy kept an indent it should have lost. `validation-gate.md`
              opened `### Two more Phase 6 notes` with a **5-space-indented**
              fragment, which CommonMark renders as a *code block* — prose
              displayed as source, inside the doc that teaches how to demote.

  unheaded    The copy arrived without the heading or lead-in that says what it
              is. `cohort-patterns.md` carries two — an indented block sitting
              under the filenames table introduced by nothing, and a **`4.`**
              opening an ordered list with no `1.`, `2.` or `3.` above it,
              stranded under `### 5. Command blocks duplicating docs/COMMANDS.md`
              which is about something else entirely. Both are Phase 5 step 4,
              demoted out of a numbered list and never re-seated.

A fourth shape, a heading demoted **inside a fenced example**, was found and
fixed under #148 and is asserted by
`test_demoted_blocks.py::test_no_marker_is_buried_in_a_code_fence`.

Both rules here are shape rules over rendered Markdown, so they need no registry
and no per-block judgement: they hold for every paragraph in the tree, demoted
or not. That is deliberate. A registry-scoped version would have missed
`### Two more Phase 6 notes` entirely, because the block was never registered —
its heading does not speak the demotion convention, so `test_demoted_blocks.py`
could not discover it.

Scoped to `curating-context/references/`, whose Phase 5 owns the demotion
convention. Demotion damage in another skill's docs is not gated here.

No API calls required.
"""

import re
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "curating-context"
REFERENCES = SKILL_DIR / "references"

LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
ORDERED_ITEM = re.compile(r"^(\s*)(\d+)[.)]\s")
HEADING = re.compile(r"^#{1,6} ")
FENCE = re.compile(r"^\s*```")

# A paragraph opening with one of these is a continuation by construction, not a
# truncation: a code span, a link, an emphasis run, or a list marker can all
# legitimately begin a block and can all legitimately be lowercase.
SENTENCE_START_EXEMPT = ("`", "*", "_", "-", "[", "(", "|", ">", "#", "+", "<")

# CommonMark makes four spaces an indented code block. Three is the deepest
# indent the demotion convention itself uses (`### Normalizing the index` quotes
# its snapshot at three), so the threshold sits exactly between them.
CODE_BLOCK_INDENT = 4


class Paragraph:
    """The first line of a block, plus what precedes it."""

    def __init__(self, doc, line_no, line, prev_nonblank, after_fence):
        self.doc = doc
        self.line_no = line_no
        self.line = line
        self.prev_nonblank = prev_nonblank
        self.after_fence = after_fence

    @property
    def key(self) -> str:
        return f"{self.doc}:{self.line_no}"

    @property
    def indent(self) -> int:
        return len(self.line) - len(self.line.lstrip(" "))

    @property
    def inside_a_list(self) -> bool:
        """A block indented under a list item is a continuation, not a code block."""
        prev = self.prev_nonblank
        if prev is None:
            return False
        return bool(LIST_ITEM.match(prev)) or (len(prev) - len(prev.lstrip(" "))) >= 2


def _paragraphs(path: Path) -> list[Paragraph]:
    """Every block-opening line in one doc, outside fences."""
    out: list[Paragraph] = []
    fenced = False
    prev_blank = True
    prev_nonblank: str | None = None
    closed_a_fence = False
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            if fenced:
                closed_a_fence = True
            fenced = not fenced
            prev_blank, prev_nonblank = False, line
            continue
        if fenced:
            prev_nonblank = line
            continue
        if not line.strip():
            prev_blank = True
            continue
        if prev_blank:
            out.append(Paragraph(path.name, i, line, prev_nonblank, closed_a_fence))
            closed_a_fence = False
        prev_blank, prev_nonblank = False, line
    return out


def _all_paragraphs() -> list[Paragraph]:
    return [p for path in sorted(REFERENCES.rglob("*.md")) for p in _paragraphs(path)]


def _orphaned_ordered_items(path: Path) -> list[str]:
    """Ordered-list items numbered n > 1 with no n-1 above them.

    Scoped to the nearest heading above, because a list cannot span one. The
    predecessor may be many lines up — a numbered step often carries paragraphs
    of continuation — so this looks back through the section rather than at the
    immediately preceding line.
    """
    out: list[str] = []
    seen: dict[int, set[int]] = {}
    fenced = False
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if HEADING.match(line):
            seen = {}
            continue
        m = ORDERED_ITEM.match(line)
        if not m:
            continue
        indent, number = len(m.group(1)), int(m.group(2))
        if number > 1 and (number - 1) not in seen.get(indent, set()):
            out.append(f"{path.name}:{i}: {line.strip()[:70]!r}")
        seen.setdefault(indent, set()).add(number)
    return out


@pytest.fixture(scope="module")
def paragraphs() -> list[Paragraph]:
    found = _all_paragraphs()
    assert found, (
        f"No paragraphs found under {REFERENCES}. The docs tree moved or is empty; "
        "this module is silently asserting nothing."
    )
    return found


class TestNoParagraphArrivedTruncated:
    def test_no_paragraph_begins_mid_sentence(self, paragraphs):
        """A block opening with a lowercase word is a tail whose head went missing.

        The exemption is real prose, not a loophole: `cadence.md` wraps a fenced
        `.gitattributes` snippet mid-sentence and resumes with "in
        `.gitattributes`, appending to whatever is already there." A sentence
        that continues *around* a fence is the one legitimate way a block starts
        lowercase, so a paragraph immediately following a closing fence is
        exempt and nothing else is.
        """
        orphans = [
            f"{p.key}: {p.line.strip()[:70]!r}"
            for p in paragraphs
            if not p.after_fence
            and (word := p.line.strip())
            and word[0].islower()
            and not word.startswith(SENTENCE_START_EXEMPT)
        ]
        assert not orphans, (
            "Paragraphs beginning mid-sentence — a demoted tail whose head was left "
            f"behind in transit:\n  " + "\n  ".join(orphans) + "\n"
            "Recover the head from `git log` for the demoting commit and restore it, "
            "or remove the tail under a duplication warrant if the whole sentence "
            "already lives elsewhere. `prove-no-loss.sh` cannot see this: the line "
            "arrived, so the check passed (#158)."
        )


class TestNoBlockArrivedWithoutItsFrame:
    """A demoted block must say what it is; the two ways of not saying it.

    This is the same defect `test_demoted_blocks.py` exists for, one step
    earlier: a block with no heading and no lead-in cannot be *discovered*, so
    it cannot be registered, so no pin protects it. Two of the three blocks
    #158 sent this branch after were invisible to #148 for exactly that reason.
    """

    def test_no_ordered_list_starts_mid_sequence(self):
        stranded = [
            line for path in sorted(REFERENCES.rglob("*.md"))
            for line in _orphaned_ordered_items(path)
        ]
        assert not stranded, (
            "Ordered-list items with no predecessor in their section:\n  "
            + "\n  ".join(stranded) + "\n"
            "A numbered step demoted out of `SKILL.md`'s Phase list keeps its number "
            "and loses its siblings, so it renders as a list of one that begins at "
            "four. Give it a heading and a lead-in naming the phase and version it "
            "came from, as the demotion convention does everywhere else (#158)."
        )

    def test_no_indented_block_stands_without_a_lead_in(self, paragraphs):
        """The convention indents a quoted snapshot; a heading or `:` introduces it.

        `### Normalizing the index` is the shape: a heading, a lead-in ending in
        a colon, then the snapshot indented three spaces. An indented block with
        neither is a quotation of nothing — the reader cannot tell whose words
        they are, or when they were true.
        """
        unframed = [
            f"{p.key}: {p.line.strip()[:60]!r} (after {p.prev_nonblank.strip()[:40]!r})"
            for p in paragraphs
            if p.indent >= 2
            and not p.inside_a_list
            and not p.after_fence
            and not LIST_ITEM.match(p.line)
            and p.prev_nonblank is not None
            and not HEADING.match(p.prev_nonblank)
            and not p.prev_nonblank.rstrip().endswith(":")
        ]
        assert not unframed, (
            "Indented blocks introduced by nothing:\n  " + "\n  ".join(unframed) + "\n"
            "An indented block is the demotion convention's quotation mark. Introduce "
            "it with a heading or a lead-in ending in a colon that names the section "
            "and version it was demoted from, or un-indent it if it is this doc's own "
            "prose rather than a quotation (#158)."
        )


class TestNoProseRendersAsACodeBlock:
    def test_no_paragraph_is_an_accidental_code_block(self, paragraphs):
        """Four-space-indented prose outside a list renders as source, not text."""
        indented = [
            f"{p.key} (indent {p.indent}): {p.line.strip()[:70]!r}"
            for p in paragraphs
            if p.indent >= CODE_BLOCK_INDENT and not p.inside_a_list
        ]
        assert not indented, (
            "Paragraphs indented far enough to render as a code block:\n  "
            + "\n  ".join(indented) + "\n"
            f"CommonMark turns {CODE_BLOCK_INDENT}+ leading spaces outside a list into "
            "an indented code block, so this prose is displayed as source — links in "
            "it do not resolve and `test_relative_links.py` cannot see them, exactly "
            "as it could not see the fenced heading #148 fixed. The demotion "
            "convention quotes snapshots at three spaces; use that, or none (#158)."
        )
