"""A reference doc must not send a reader to the file they are already reading.

Demotion debris, and a class C2's `test_demotion_debris.py` does not reach. A
block demoted out of `SKILL.md` often ends with the pointer that sent a reader to
its new home — "Semantics, the uncovered write paths, and uninstall:
[references/write-guard-hook.md](write-guard-hook.md)." When the block lands in
that very file, the pointer becomes a loop, and it reads as a live instruction
rather than as the artefact of a move. Every hit found was this exact shape: a
trailing colon, then a link to the enclosing file.

Two forms are NOT debris and the rule has to tell them apart, because a gate that
cannot is one somebody switches off:

- **A fragment makes it a within-document jump.** `[both](budget-and-metrics.md
  #measuring-tokens)` inside `budget-and-metrics.md` is a table of contents entry,
  not a loop. Three of the eleven self-links in this tree are these.
- **A verbatim quotation keeps its pointer.** The demotion convention preserves
  `SKILL.md`'s wording under a heading that says so — "in full", "as Phase 7 puts
  it" — and `test_demoted_blocks.py` pins those blocks character for character.
  Rewriting the link inside one would falsify the quotation and break that test.
  Four of the eleven are these.

That leaves four real ones, all in `curating-context`. Sites outside this agent's
line windows are inventoried rather than fixed, because editing another agent's
file to satisfy a gate is how two branches end up disagreeing. The inventory
exempts a *site*, never a file: the docs holding known debris stay under the
gate, so a self-link written into one tomorrow still fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent / "skills"

# A heading that declares its section a verbatim copy of policy-file text. The
# demotion convention writes one of these whenever it preserves wording, so the
# markers are the convention's own vocabulary rather than a list invented here.
QUOTATION_MARKERS = ("in full", "as phase", "carried it", "puts it", "states them")

LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(#[^)\s]*)?\)")

# Known debris this agent does not own, each with the exact link text and who
# owns it. An entry that is FIXED must be deleted from here — `test_no_stale_entries`
# fails otherwise, so the inventory can only shrink. It is deliberately not a
# permanent exemption: the defect is real at every one of these sites.
#
# Keyed by link text rather than by file, and that is the whole point. A
# file-level skip would exempt these three docs from the gate entirely, so the
# NEXT self-link written into one of them would ship unseen — an inventory that
# grows silent coverage gaps is worse than no inventory. Line numbers would be
# the obvious key and are the wrong one: they move under every edit, and a
# stale number reads as a fixed site.
NOT_MINE_TO_FIX = {
    "curating-context/references/cadence.md":
        ("[references/cadence.md](cadence.md)",
         "read-only this batch — changed in batch A/B (#128, #169)"),
    "curating-context/references/validation-gate.md":
        ("[references/validation-gate.md](validation-gate.md)",
         "inside `## The adoption rule`, which is #117's window in batch D"),
    "curating-context/references/write-guard-hook.md":
        ("[references/write-guard-hook.md](write-guard-hook.md)",
         "unassigned in this batch; no agent owns the file"),
}


def _self_links(md: Path) -> list[tuple[int, str]]:
    """Bare self-links in a doc's own prose: no fragment, not inside a quotation."""
    out = []
    heading = ""
    in_fence = False
    for i, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("#"):
            heading = line.lower()
            continue
        if any(marker in heading for marker in QUOTATION_MARKERS):
            continue
        for m in LINK.finditer(line):
            target, fragment = m.group(1), m.group(2)
            if fragment or target.startswith(("http", "mailto")):
                continue
            if (md.parent / target).resolve() == md.resolve():
                out.append((i, m.group(0)))
    return out


def _docs() -> list[Path]:
    return sorted(SKILLS.glob("*/references/**/*.md"))


def _rel(md: Path) -> str:
    return str(md.relative_to(SKILLS))


@pytest.mark.parametrize("doc", _docs(), ids=_rel)
def test_no_doc_links_to_itself(doc: Path):
    hits = _self_links(doc)
    known = NOT_MINE_TO_FIX.get(_rel(doc))
    if known:
        link, why = known
        surplus = [(n, text) for n, text in hits if text != link]
        assert not surplus, (
            f"{_rel(doc)} carries a self-link the inventory does not cover:\n"
            + "\n".join(f"  line {n}: {text}" for n, text in surplus)
            + f"\n\nThe inventoried site ({link}) is exempt because it is {why}. "
            "Nothing else in this file is — fix this one, or add it to "
            "NOT_MINE_TO_FIX with who owns it."
        )
        assert len(hits) == 1, (
            f"{_rel(doc)} carries {len(hits)} copies of the inventoried "
            f"self-link {link}; only one is accounted for:\n"
            + "\n".join(f"  line {n}: {text}" for n, text in hits)
        )
        return
    assert not hits, (
        f"{_rel(doc)} links to itself:\n"
        + "\n".join(f"  line {n}: {text}" for n, text in hits)
        + "\n\nThis is the pointer a demoted block carried with it out of "
        "SKILL.md. Drop it — the reader is already here. Add a `#fragment` "
        "instead if a jump within the doc is what was meant, or move the block "
        "under an 'in full' heading if it is meant to read as a quotation."
    )


def test_no_stale_entries():
    """An inventoried site that has been fixed must leave the inventory.

    Otherwise the list outlives the defect and the next reader takes it as
    evidence of debris that is no longer there — the same failure the roster's
    wave annotations had.
    """
    stale = [
        rel for rel, (link, _why) in NOT_MINE_TO_FIX.items()
        if (SKILLS / rel).exists()
        and link not in {text for _n, text in _self_links(SKILLS / rel)}
    ]
    assert not stale, (
        "these are listed in NOT_MINE_TO_FIX but no longer carry the self-link "
        f"the entry names; delete the entries: {stale}"
    )


def test_the_inventory_names_only_real_files():
    missing = [rel for rel in NOT_MINE_TO_FIX if not (SKILLS / rel).exists()]
    assert not missing, missing


def test_a_fragment_is_not_debris(tmp_path: Path):
    """The rule's load-bearing exemption, proven rather than asserted: a doc
    that jumps within itself must not be reported."""
    d = tmp_path / "x" / "references"
    d.mkdir(parents=True)
    doc = d / "a.md"
    doc.write_text("# A\n\nSee [both](a.md#later).\n\n## Later\n")
    assert _self_links(doc) == []


def test_a_quotation_keeps_its_pointer(tmp_path: Path):
    """The other exemption. test_demoted_blocks.py pins these blocks verbatim,
    so a gate that demanded the link change would put two tests in conflict."""
    d = tmp_path / "x" / "references"
    d.mkdir(parents=True)
    doc = d / "a.md"
    doc.write_text("# A\n\n## The rule, as Phase 7 puts it\n\nSee [a](a.md).\n")
    assert _self_links(doc) == []


def test_a_bare_self_link_in_the_docs_own_prose_is_reported(tmp_path: Path):
    d = tmp_path / "x" / "references"
    d.mkdir(parents=True)
    doc = d / "a.md"
    doc.write_text("# A\n\n## How it works\n\nDetail: [a](a.md).\n")
    assert [n for n, _ in _self_links(doc)] == [5]
