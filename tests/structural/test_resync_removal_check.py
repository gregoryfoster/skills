"""#267 — the re-sync procedure must check what a merge DROPPED, not only what
it brought in.

`references/local-overrides.md` gave the re-sync four careful steps for
performing the merge and one line for checking it. That asymmetry let a real
local delta go missing in a consumer's re-sync, and the miss survived the
operator's own verification: they grepped the merged file for the strings they
expected — upstream's new material present, local conventions present,
deliberate omissions absent — and every check passed.

Presence-only verification structurally cannot find this. It asks "is what I
expect here?", never "what did I take out?" The dropped line was a
*substitution*: an override's worktree step named `.worktrees/` as the local
directory, and the reapplied text carried a different, equally true worktree
line in its place, so the re-synced skill silently stopped saying where
worktrees go. Diffing the ORIGINAL override against the merged result is a
different question from step 1's diff (old *vendor* vs override), and only that
second question catches it.

What this file pins:

- **The procedure carries the removal check**, as its own numbered step, with
  the classify-each-removed-line instruction that makes it actionable.
- **It says the two diffs differ.** A reader who thinks step 5 is step 1 rerun
  will skip it.
- **The SKILL.md pointer carries it too** — an agent that never opens the
  reference still gets told that grepping for what it expected is not a check.
"""

import re

from tests.utils.skill_loader import SKILLS_DIR

_REFERENCE = SKILLS_DIR / "managing-skills" / "references" / "local-overrides.md"
_SKILL = SKILLS_DIR / "managing-skills" / "SKILL.md"


def _resync_section() -> str:
    text = _REFERENCE.read_text()
    start = text.index("## Re-syncing a drifted override")
    return text[start:]


def test_the_procedure_has_a_numbered_removal_step():
    """The check must be a step, not an aside — the steps are what get run."""
    section = _resync_section()
    assert re.search(r"^\d+\. \*\*Account for every removed line", section, re.M), (
        "the re-sync procedure must carry the removal accounting as its own "
        "numbered step (#267). As prose beside the list it reads as commentary "
        "on a procedure that is already complete, and gets skipped."
    )


def test_the_removal_step_says_what_to_do_with_each_removed_line():
    """A bare "diff it" leaves the reader in reflow noise.

    Most removed lines in a real re-sync are reworded prose. Without the
    three-way classification the step produces a diff nobody can act on, and a
    reader who cannot act on it stops running it.
    """
    section = _resync_section()
    for phrase in ("superseded by upstream", "deliberately", "substance"):
        assert phrase in section, (
            f"the removal step should tell the reader how to classify a removed "
            f"line (missing: {phrase!r}) — superseded, deliberately dropped, or "
            "reworded with its substance intact. #267's noise is real and an "
            "unclassifiable diff is one nobody runs twice."
        )


def test_the_procedure_distinguishes_the_two_diffs():
    """Step 1 diffs old vendor vs override; the new step diffs override vs merge.

    They look alike and are not: the first enumerates what the override added,
    the second finds what the merge removed. A reader who conflates them
    concludes the check is already done.
    """
    section = _resync_section()
    assert "not step 1's diff run again" in section, (
        "the reference must say the removal check is a DIFFERENT diff from step "
        "1's, or a reader treats step 1 as having already covered it (#267)"
    )
    assert re.search(r"#267|issues/267", section), (
        "the section should cite the miss it exists to prevent, so the next "
        "reader can see it is a recorded failure and not a counsel of perfection"
    )


def test_presence_only_verification_is_named_as_insufficient():
    """The trap is that the wrong check passes green, not that no check is run.

    #267's operator DID verify. Saying only "verify the merge" leaves them
    doing exactly what already failed.
    """
    section = _resync_section()
    assert "presence-only" in section, (
        "the reference must name grepping-for-what-you-expected as insufficient "
        "(#267) — an operator who verified that way and passed will otherwise "
        "read the new step as something they already do"
    )


def test_the_skill_pointer_carries_the_check():
    """The SKILL.md summary is what an agent reads before opening a reference.

    Its re-sync paragraph already carries the direction rule, which is the
    other thing that is easy to get wrong and cheap to state in a clause. The
    match is on the idea — a removal word plus the issue — not one sentence,
    since this paragraph is written against a 6,000-token ratchet with no
    headroom and gets reworded for tokens.
    """
    text = _SKILL.read_text()
    start = text.index("### Updating a local override")
    section = text[start : text.index("###", start + 3)]
    assert re.search(r"remov|dropp", section) and "#267" in section, (
        "managing-skills/SKILL.md's 'Updating a local override' section should "
        "state the removal check alongside the re-sync direction (#267) — an "
        "agent that never loads references/local-overrides.md otherwise "
        "verifies by presence and passes over a dropped delta"
    )
