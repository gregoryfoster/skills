"""A demoted block drifts by omission, and #148's pins cannot see it (#158).

`test_demoted_blocks.py` pins contract tokens on both sides of a demotion, which
catches **rewording**. It says so, and it says what it cannot catch: an
*addition* to `SKILL.md`. A snapshot is complete as of its demotion; when the
source section later grows a clause, every registered pin still matches, because
nothing was reworded. `### The rule in full` shipped in exactly that state — it
promised the cross-repo rule in full and had never heard of `--no-write`, which
`SKILL.md`'s Scope section grew after v1.7 demoted it.

The fix is not a bigger pin list. It is a classification, because "is this block
allowed to be incomplete?" has two honest answers and the convention as written
invites both:

  record    A **historical record**: this is what `SKILL.md` said, at the
            version named. Being out of date is what it is *for*. It owes the
            reader exactly one thing — the version, so the record cannot be
            mistaken for current text. Ten blocks.
  excerpt   A **living excerpt**: the long form of a section `SKILL.md` still
            states in compressed form, presented in the present tense with no
            date. A reader treats it as current, so it must track its source in
            **both** directions — no reworded token (#148) and no unrepresented
            clause (this module). Six blocks.

## How the split is drawn, and why not the other way

#158 proposed a two-part test: a record is "dated, explicitly frozen, and
`SKILL.md` does not point at it as current". The second half does not survive
contact with the tree. **No `SKILL.md` link names any block's anchor** — every
one of the sixteen is reached through a doc-level link or a link to the parent
`##`, so "does SKILL.md point at it" is either false for all sixteen or true for
all sixteen depending on how loosely you read a doc-level link. It cannot be
operationalised, and a criterion a gate cannot evaluate is a convention that
will be settled case-by-case forever, which is the state #158 was filed to end.

So the split is drawn on the first half alone: **does the block name the version
it left `SKILL.md` at?** Three reasons.

1. It is local and decidable. The evidence is inside the block.
2. It is the criterion the demoting agents already used, without naming it. Of
   the thirteen blocks that existed before #158, **eight** volunteer a version
   in their lead-in ("carried this inline until v1.9, in these words:") and five
   do not, and the split falls exactly where the writing is past tense. This
   module does not invent a convention; it names the one already in the file and
   makes it load-bearing. (The three blocks #158 gave headings are counted
   separately and prove nothing about the convention — two were written into the
   record class and one into the excerpt class by the same commit that named the
   classes. The evidence is the thirteen.)
3. It matches the observed defect. `### The rule in full` misleads *precisely
   because* it does not date itself. Had it said "as Scope carried it until
   v1.7", the missing `--no-write` would have been correct rather than a bug.

A block therefore chooses its own class, and the choice has a cost either way —
which is what keeps it honest. Claim currency and you owe the bidirectional
check; claim history and you must carry the date that stops a reader trusting
you as current. There is no third option, and `test_every_block_declares_a_kind`
is what makes that true.

## What an excerpt owes: `covers`, and tokens derived rather than listed

The bidirectional check cannot be a hand-written list, because a hand-written
list is what fails: nobody registers a token for a clause that does not exist
yet. So the tokens are **derived from the source** — every code span and every
bold run in the covered span — and every one of them must appear in the excerpt.
Add a clause to `SKILL.md` naming a new flag, and the gate fires the same day.

`covers` bounds that derivation, and it is not optional. `### Tagging the row —
the Phase 7 text in full` claims two paragraphs of Phase 7; the rest of Phase 7
went to four other destinations. Deriving over the whole `## ` section would
demand the excerpt carry text it never claimed, and the only way to make that
pass is to stop deriving — so the scope is declared per block, as the pair of
substrings that open and close the claimed span, each required to be unique.

Derivation is why this is a separate module from `test_demoted_blocks.py`: that
one asserts a registered contract, this one asserts a contract it computes.

What this still does NOT catch, stated so it is not rediscovered:

- **Unmarked prose.** A clause added to `SKILL.md` in plain words, with no code
  span and no bold, is invisible here. The two markups are the falsifiable half
  of a section; a derived check over every sentence would be a diff, not a gate.
- **A record going stale in a way that matters.** By construction: a record is
  allowed to be stale. If a record is load-bearing, it was misclassified, and
  nothing here can tell.
- **Whether `covers` is honest.** A block can narrow `covers` until the check is
  vacuous. `test_covers_spans_are_substantial` sets a floor, not a proof.

No API calls required.
"""

import re

import pytest

from tests.structural.test_demoted_blocks import (
    REGISTRY,
    SKILL_MD,
    VERSION,
    _normalize,
    _registry_key,
    discover_blocks,
)

KINDS = ("record", "excerpt")

CODE_SPAN = re.compile(r"`([^`\n]+)`")
BOLD_RUN = re.compile(r"\*\*([^*]+?)\*\*")

# `##` is two characters and appears in every doc that discusses headings; `<N>`
# is three and is the exact placeholder Phase 7's command substitutes. Three is
# the shortest token that can still discriminate.
MIN_TOKEN = 3

# A `covers` span shorter than this is not an excerpt of anything.
MIN_SPAN = 120


def _flat(text: str) -> str:
    """Collapse whitespace, preserving case.

    Markdown reflows, and a code span or bold run wraps across lines freely —
    `(`--no-loss\nok`)` in one file is `(`--no-loss ok`)` in the other. Tokens
    have to be extracted from flattened text or half of them are missed.
    """
    return " ".join(text.split())


def _sections(text: str) -> dict[str, str]:
    """SKILL.md split on `## ` headings."""
    out: dict[str, str] = {}
    current, buf = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                out[current] = "\n".join(buf)
            current, buf = line.strip(), [line]
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf)
    return out


def _covered_span(section: str, covers: tuple[str, str]) -> str:
    """The claimed span of a source section, between two unique substrings."""
    body = _flat(section)
    start, end = (_flat(c) for c in covers)
    for label, needle in (("start", start), ("end", end)):
        hits = body.count(needle)
        assert hits == 1, (
            f"`covers` {label} bound {needle!r} matches {hits} times in the source "
            "section; it must match exactly once or the span it delimits is not "
            "well-defined. Rewrite the bound, or the section it points into moved."
        )
    i, j = body.index(start), body.index(end)
    assert j >= i, f"`covers` bounds are in the wrong order: {end!r} precedes {start!r}"
    return body[i : j + len(end)]


def _contract_tokens(span: str) -> list[str]:
    """Every code span and bold run in a span of source, deduped in order.

    These are the falsifiable half of a section: a flag, a script, a path, a
    field name, an emphasised rule. Prose around them can be rewritten freely —
    that is `test_demoted_blocks.py`'s stated blind spot and stays one.
    """
    found: list[str] = []
    for pattern in (CODE_SPAN, BOLD_RUN):
        for raw in pattern.findall(span):
            token = _flat(raw).strip(" .,;:")
            if len(token) >= MIN_TOKEN and token not in found:
                found.append(token)
    return found


@pytest.fixture(scope="module")
def skill_sections() -> dict[str, str]:
    return _sections(SKILL_MD.read_text())


@pytest.fixture(scope="module")
def matched() -> dict[tuple, object]:
    seen: dict[tuple[str, str], int] = {}
    return {_registry_key(b, seen): b for b in discover_blocks()}


def _entries():
    return [
        pytest.param(k, v, id=f"{k[0]}::{k[1][:44]}" + (f"#{k[2]}" if len(k) > 2 else ""))
        for k, v in REGISTRY.items()
    ]


def _entries_of(kind: str):
    return [p for p in _entries() if p.values[1].get("kind") == kind]


class TestEveryBlockCommitsToOneKind:
    @pytest.mark.parametrize("key,entry", _entries())
    def test_entry_declares_a_kind(self, key, entry):
        assert entry.get("kind") in KINDS, (
            f"{key}: declare `kind`, one of {KINDS}. A demoted block is either a "
            "record of what SKILL.md used to say — which must carry the version, so a "
            "reader knows not to trust it as current — or an excerpt a reader is meant "
            "to treat as current, which must track its source in both directions. "
            "Leaving it unsaid is what let `### The rule in full` be read both ways "
            "and be wrong on one of them (#158)."
        )

    def test_both_kinds_are_populated(self):
        counts = {k: sum(1 for e in REGISTRY.values() if e.get("kind") == k) for k in KINDS}
        assert all(counts.values()), (
            f"one kind is now empty: {counts}. A classification with a single "
            "inhabited class is a field nobody reads; if the convention really "
            "collapsed to one kind, delete the other and this module with it."
        )


class TestARecordCarriesItsDate:
    """The one thing a record owes: the version it left SKILL.md at.

    `test_demoted_blocks.py::TestDatedBlocksSayWhenTheyLeft` asserts this for
    the single entry whose *pins* are unavailable. That is a different question
    — it asks "can this block be pinned?", not "does this block claim to be
    current?" — and it reached one of the eight records. This reaches all eight.
    """

    @pytest.mark.parametrize("key,entry", _entries_of("record"))
    def test_record_names_its_version(self, key, entry, matched):
        block = matched[key]
        assert VERSION.search(block.text), (
            f"{block.key}: classified `record`, so it is allowed to disagree with "
            "SKILL.md — but only if it says when it was true. Name the version it was "
            "demoted from ('carried this inline until v1.9'), or reclassify it as an "
            "`excerpt` and accept the bidirectional check."
        )


class TestAnExcerptTracksItsSourceBothWays:
    @pytest.mark.parametrize("key,entry", _entries_of("excerpt"))
    def test_excerpt_declares_what_it_covers(self, key, entry):
        covers = entry.get("covers")
        assert isinstance(covers, tuple) and len(covers) == 2, (
            f"{key}: an `excerpt` must declare `covers` — the (start, end) substrings "
            "bounding the span of its source section it claims to carry in full. "
            "Without it the check either compares against the whole section, which no "
            "partial excerpt can pass, or against nothing."
        )

    @pytest.mark.parametrize("key,entry", _entries_of("excerpt"))
    def test_covers_spans_are_substantial(self, key, entry, skill_sections):
        span = _covered_span(skill_sections[entry["source"]], entry["covers"])
        assert len(span) >= MIN_SPAN, (
            f"{key}: `covers` resolves to {len(span)} characters. A span narrowed "
            f"below {MIN_SPAN} makes the derived-token check pass by covering almost "
            "nothing — if the block really is that small, it is a quotation, not an "
            "excerpt claiming a section in full."
        )

    @pytest.mark.parametrize("key,entry", _entries_of("excerpt"))
    def test_the_source_states_nothing_the_excerpt_omits(self, key, entry, skill_sections, matched):
        """The check #148 named and could not make: drift by **omission**.

        Every contract token the source states inside the covered span must also
        appear in the excerpt. Rewording is #148's; this is the other direction,
        and it is the one no pin list can express, because the token that will
        break it has not been written yet.
        """
        span = _covered_span(skill_sections[entry["source"]], entry["covers"])
        block = matched[key]
        text = _normalize(block.text)
        missing = [t for t in _contract_tokens(span) if _normalize(t) not in text]
        assert not missing, (
            f"{block.key}: {entry['source']} states {missing}, and this block claims "
            "to carry that span in full but does not. SKILL.md grew a clause after the "
            "demotion and the snapshot never heard about it — the drift-by-omission "
            "#158 is about. Carry the clause into the block, narrow `covers` if the "
            "block never claimed that text, or reclassify the block as a `record` and "
            "date it so a reader stops treating it as current."
        )
