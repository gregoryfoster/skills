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
- **It names presence-only verification as insufficient.** #267's operator DID
  verify; a step that only says "check the merge" leaves them doing what
  already failed.
- **The SKILL.md pointer carries it too** — an agent that never opens the
  reference still gets told that grepping for what it expected is not a check.

Keep this list current — it is the file's index.
"""

import re
from pathlib import Path

from tests.utils.skill_loader import SKILLS_DIR

_REFERENCE = SKILLS_DIR / "managing-skills" / "references" / "local-overrides.md"
_SKILL = SKILLS_DIR / "managing-skills" / "SKILL.md"


def _section(path: Path, heading: str) -> str:
    """The text from `heading` to the next heading of the same or higher level.

    A guarded lookup rather than `str.index`: every assertion in this file is
    anchored on a heading, and a rename would otherwise surface as a bare
    `ValueError: substring not found` — a traceback that names neither the
    contract that broke nor the anchor that needs updating.

    Fenced blocks are skipped when looking for the terminator. A `#` comment
    inside a ```bash example is not a heading, and treating one as the end of
    the section would silently hand every assertion a truncated slice.
    """
    text = path.read_text()
    start = text.find(heading)
    assert start != -1, (
        f"{path.name} no longer contains the heading {heading!r}, which this "
        "file anchors on. Update the anchor if it was renamed; if the section "
        "itself is gone, #267's check went with it."
    )
    depth = len(heading) - len(heading.lstrip("#"))
    lines = text[start:].splitlines(keepends=True)
    kept, fenced = lines[:1], False
    for line in lines[1:]:
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(rf"#{{1,{depth}}} ", line):
            break
        kept.append(line)
    return "".join(kept)


def _resync_section() -> str:
    return _section(_REFERENCE, "## Re-syncing a drifted override")


def _removal_step() -> str:
    """Step 5 alone — from its number to the next numbered step.

    Scoped, because a test named for the step must fail when the step's own
    text loses the instruction, not pass because the surrounding prose still
    happens to carry the words.
    """
    section = _resync_section()
    start = re.search(r"^\d+\. \*\*Account for every removed line", section, re.M)
    assert start, (
        "the removal step is gone — test_the_procedure_has_a_numbered_removal_"
        "step is the finding, this helper just cannot slice what is not there"
    )
    rest = section[start.end() :]
    end = re.search(r"^\d+\. ", rest, re.M)
    return rest[: end.start()] if end else rest


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
    step = _removal_step()
    for phrase in ("superseded by upstream", "deliberately", "substance"):
        assert phrase in step, (
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
    section = _section(_SKILL, "### Updating a local override")
    assert re.search(r"remov|dropp", section) and "#267" in section, (
        "managing-skills/SKILL.md's 'Updating a local override' section should "
        "state the removal check alongside the re-sync direction (#267) — an "
        "agent that never loads references/local-overrides.md otherwise "
        "verifies by presence and passes over a dropped delta"
    )
