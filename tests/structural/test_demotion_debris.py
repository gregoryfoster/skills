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

The rules for those shapes are shape rules over rendered Markdown, so they need
no registry and no per-block judgement: they hold for every paragraph in the
tree, demoted or not. That is deliberate. A registry-scoped version would have
missed `### Two more Phase 6 notes` entirely, because the block was never
registered — its heading does not speak the demotion convention, so
`test_demoted_blocks.py` could not discover it.

Two later additions sit at the edge of that thesis, and say so where they are:

  copied      `TestNoBlockWasCopiedInsteadOfMoved` (#204) is still a shape rule,
              but over *pairs* of docs rather than single paragraphs — a block
              copied instead of moved. It carries this file's only exemption
              registry, and a second test that fails an exemption once its
              duplicate is gone.
  misplaced   `TestTheGuardsNonVetoClaimIsWhereTheReaderArrives` (#205) is a
              placement pin on one paragraph, the one thing here that is not a
              shape rule at all. It exists because that paragraph has no heading
              of its own, so nothing else holds it where a reader will find it.

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

        The test is the **first character**, deliberately. A tail that begins
        with a code span, a link or a bold run opens with punctuation and is not
        caught — `_flat`-ing the line to find its first *letter* would flag
        every legitimate paragraph opening "`docs/` filenames …". Both live
        instances began with a bare lowercase word; a narrow rule that fires is
        worth more than a wide one that has to be exempted into silence.
        """
        orphans = [
            f"{p.key}: {p.line.strip()[:70]!r}"
            for p in paragraphs
            if not p.after_fence and (word := p.line.strip()) and word[0].islower()
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


# -- The copy that was never a move (#204) ------------------------------------
#
# `prove-no-loss.sh` is satisfied by *presence*, so a block copied instead of
# moved is invisible to it: the lines arrived, the check passed. Phase 6 names
# the shape — "No block was copied instead of moved. Presence anywhere satisfies
# the check, so a bullet left inline and in a destination is invisible to it" —
# and has no instrument. This is the instrument, and like the rules above it is
# a shape rule over the whole tree rather than a registry.
#
# Cross-file only. A doc restating its own `##` section inside a generated
# artefact it quotes is not this defect: `cadence.md`'s workflow header comment
# repeats two of its own sections *on purpose*, because the reader of the
# installed `.yml` has no access to the doc.
DUPLICATE_RUN = 3  # consecutive non-blank lines
DUPLICATE_MIN_CHARS = 120  # skip incidental repeats — table rules, short fences

# Keyed on the first line of the maximal run. Every entry needs a reason and a
# reference; "it was there already" is not one.
DUPLICATION_EXEMPTIONS: dict[str, str] = {
    # Found by #204's sweep of this tree, in a file pair whose ownership
    # question #204 does not settle: `write-guard-hook.md`'s § Deliberate limits
    # closes with a paragraph byte-identical to `continuous-surfaces.md`'s
    # § Review-time delta, which also restates the bullet immediately above it.
    # Deciding which doc owns it is a curation call, not a delete — left standing
    # and pinned here so it cannot go quiet again.
    "It sees what the write guard cannot, twice over: the guard evaluates one edit at a":
        "#204 sweep — unadjudicated; which doc owns this paragraph is a "
        "curation judgement, not a mechanical delete",
}


def _duplicate_runs() -> list[tuple[str, list[str]]]:
    """Maximal runs of identical non-blank lines shared by two reference docs."""
    # Keyed on the path relative to the tree, not on `.name`: the tree is flat
    # today, but two same-named docs in different subdirectories would otherwise
    # collide into one entry and the rule would silently stop covering both.
    docs = {
        str(path.relative_to(REFERENCES)): path.read_text().splitlines()
        for path in sorted(REFERENCES.rglob("*.md"))
    }

    windows: dict[str, list[tuple[str, int]]] = {}
    for name, lines in docs.items():
        for i in range(len(lines) - DUPLICATE_RUN + 1):
            window = lines[i:i + DUPLICATE_RUN]
            if any(not line.strip() for line in window):
                continue
            key = "\n".join(line.rstrip() for line in window)
            if len(key) < DUPLICATE_MIN_CHARS:
                continue
            windows.setdefault(key, []).append((name, i + 1))

    shared = {
        key: locs for key, locs in windows.items()
        if len({name for name, _ in locs}) > 1
    }
    starts = {tuple(sorted(locs)) for locs in shared.values()}

    runs = []
    for key, locs in shared.items():
        # A window whose one-line-earlier twin is also shared is a continuation
        # of that run, not a run of its own. Report only the maximal one.
        if tuple(sorted((name, n - 1) for name, n in locs)) in starts:
            continue
        length = DUPLICATE_RUN
        while True:
            grown = {
                "\n".join(x.rstrip() for x in docs[name][n - 1:n + length])
                for name, n in locs
            }
            if len(grown) != 1 or any(
                n - 1 + length >= len(docs[name]) for name, n in locs
            ):
                break
            length += 1
        runs.append((
            key.splitlines()[0],
            [f"{name}:{n}-{n + length - 1}" for name, n in sorted(locs)],
        ))
    return runs


class TestNoBlockWasCopiedInsteadOfMoved:
    """Phase 6's own check, which `prove-no-loss.sh` cannot make (#204).

    `cadence.md:424-432` was byte-identical to `continuous-surfaces.md:20-28`,
    and both claims in it were already made twice more inside `cadence.md`
    itself — once as a `##` section and once in the generated workflow's header
    comment. It survived every gate because presence satisfies them all.
    """

    def test_no_reference_doc_carries_another_doc_verbatim(self):
        offenders = [
            f"{first[:78]!r}\n      " + " == ".join(locs)
            for first, locs in _duplicate_runs()
            if first not in DUPLICATION_EXEMPTIONS
        ]
        assert not offenders, (
            f"Runs of {DUPLICATE_RUN}+ identical lines shared by two reference "
            "docs:\n    " + "\n    ".join(offenders) + "\n"
            "A demotion moves a block; it does not copy one. `prove-no-loss.sh` "
            "sees only that the lines are present somewhere, so a copy passes it "
            "forever. Delete the copy from the doc that does not own the claim, "
            "or replace it with a pointer to the section that does (#204)."
        )

    def test_every_exemption_still_describes_a_live_duplicate(self):
        """An exemption outliving its duplicate silently narrows the rule."""
        live = {first for first, _ in _duplicate_runs()}
        stale = sorted(DUPLICATION_EXEMPTIONS.keys() - live)
        assert not stale, (
            "Exemptions with nothing left to exempt:\n  " + "\n  ".join(stale)
            + "\nThe duplicate was resolved. Drop the entry so the rule covers "
            "the whole tree again (#204)."
        )


class TestTheGuardsNonVetoClaimIsWhereTheReaderArrives:
    """A placement pin, not a shape rule — the one exception in this module.

    "the advisory is not a veto" is what the write guard is *for*: it is the
    answer to "it fired, now what?". It sat under `## Relationship to the weekly
    run`, a section about how the guard and the cadence divide labour, which is
    not where that reader looks (#205). Pinned rather than left to drift back,
    because the paragraph has no heading of its own and nothing else holds it.
    """

    CLAIM = "the advisory is not a veto"
    HOME = "When it speaks"

    def _sections(self) -> dict[str, str]:
        """Section title -> body, wrapped lines rejoined.

        The claim is hard-wrapped mid-phrase ("that is fine — the\\nadvisory is
        not a veto"), so a body searched line by line would never match it. The
        pin is on the sentence, not on where the author's fill happened to break.
        """
        text = (REFERENCES / "write-guard-hook.md").read_text()
        parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
        return {
            title: " ".join(body.split())
            for title, body in zip(parts[1::2], parts[2::2])
        }

    def test_the_claim_lives_under_when_it_speaks(self):
        sections = self._sections()
        assert self.HOME in sections, (
            f"write-guard-hook.md no longer has a `## {self.HOME}` section; the "
            "claim below has nowhere to be (#205)."
        )
        holders = [name for name, body in sections.items() if self.CLAIM in body]
        assert holders == [self.HOME], (
            f"{self.CLAIM!r} is under {holders or 'no'} section, not "
            f"`## {self.HOME}`. That paragraph is the guard's central design "
            "claim — a reader asking what happens when they have to go over "
            f"budget arrives at `## {self.HOME}`, which is where the two "
            "conditions and the never-nag rule already are (#205)."
        )
