"""The blanket directive is identical prose across the whole reviewing-code family.

A blanket directive — `CR --fix`, or the `address the findings, emphasizing
technical correctness` the author types by hand — pre-authorizes Phase 4 so a
review runs straight through to implementation without a second turn. It is the
first thing in this cohort that lets the skill write to the tree with no
per-finding directive, so what bounds it is load-bearing in a way the rest of
Phase 4 is not: the report that must still be presented, the finding classes
that must still be held, the red baseline it must not fire on, and the
per-finding commits that make one bad auto-fix revertible.

## Why byte-identical rather than marker-matched

`test_baseline_fallback_clause.py` deliberately matches on meaning-bearing
substrings so the wording can be reworded without a test edit. The opposite
choice is right here. Each of the four skills is a self-contained copy, so this
block exists four times; the failure mode is not "someone deletes the idea", it
is "someone tunes the wording in the FastAPI variant during a review and the
other three keep the old rule". A cohort where `address the findings` means
three severity tiers in one stack and two in another is worse than one where it
is unavailable, because the divergence is invisible from inside any single
skill. Equality across the family is the assertion; the baseline is the
reference copy.

The individual rails are pinned separately below so that deleting one fails
with the rail's name rather than with a diff of two 2,000-character strings.
"""

import re

import pytest

from tests.utils.skill_families import family_members
from tests.utils.skill_loader import SKILLS_DIR, load_skill

FAMILY = family_members("reviewing-code")

# The section runs from its own heading to the next heading of any level, or to
# end-of-file. `\Z` is not decoration: without it the pattern silently fails to
# match a section that has become the last thing in the file, and `_section()`
# then reports "no '#### Blanket directives' section" about a section that is
# right there — sending the next maintainer to re-add what already exists.
_SECTION = re.compile(
    r"^#### Blanket directives$\n(.*?)(?=^#{2,4} |\Z)", re.MULTILINE | re.DOTALL
)


def _body(dir_name: str) -> str:
    return load_skill(SKILLS_DIR / dir_name).body


def _section(dir_name: str) -> str:
    m = _SECTION.search(_body(dir_name))
    assert m, (
        f"{dir_name}: no '#### Blanket directives' section. Every member of the "
        "reviewing-code family carries it; a member without one silently stops "
        "honouring `address the findings`."
    )
    return m.group(1).strip()


class TestTheSectionExistsEverywhere:
    @pytest.mark.parametrize("name", FAMILY)
    def test_section_present(self, name):
        assert _section(name)

    @pytest.mark.parametrize("name", FAMILY)
    def test_section_sits_inside_phase_4(self, name):
        body = _body(name)
        phase4 = body.find("### Phase 4 — Wait for feedback")
        blanket = body.find("#### Blanket directives")
        rounds = body.find("## Second review rounds")
        assert phase4 != -1 and blanket != -1 and rounds != -1
        assert phase4 < blanket < rounds, (
            f"{name}: 'Blanket directives' must be a subsection of Phase 4, not a "
            "peer of it — it describes how that phase's wait is satisfied, and a "
            "reader who skips Phase 4 must not be able to reach it."
        )


class TestTheSectionDoesNotDrift:
    @pytest.mark.parametrize("name", [n for n in FAMILY if n != "reviewing-code"])
    def test_matches_baseline(self, name):
        assert _section(name) == _section("reviewing-code"), (
            f"{name}'s 'Blanket directives' section differs from the "
            "reviewing-code baseline. This block is stack-agnostic by "
            "construction — it names no tool and no language — so a divergence "
            "is drift, not tailoring. Stack-specific guidance belongs in Phase 2 "
            "or the lint gate in Phase 3.5, where the variants already differ."
        )


class TestTheRailsAreNamed:
    """Each rail pinned on its own, so a deletion fails by name.

    Substring matching here, not equality: equality is already asserted above.
    What these add is a legible failure — `test_rail_report_is_never_skipped`
    naming the invariant beats a character-position diff.
    """

    # rail -> (marker, scope). Scope is data rather than an `if rail == ...`
    # inside the test: the Iron Law rail lives outside the section and the rest
    # inside it, and encoding that as a comparison against one magic key means
    # the next body-scoped rail is checked against the wrong haystack unless
    # someone remembers to edit the conditional too.
    BODY, SECTION = "body", "section"
    RAILS = {
        "report_is_never_skipped": (
            "NO BLANKET DIRECTIVE SKIPS THE FINDINGS REPORT",
            BODY,
        ),
        "report_precedes_the_first_edit": (
            "Present the report as its own message before the first edit",
            SECTION,
        ),
        "held_findings": ("**Hold, do not apply.**", SECTION),
        "red_baseline": ("**Never fire on a red baseline.**", SECTION),
        "one_commit_per_finding": ("**One commit per finding**", SECTION),
    }

    @pytest.mark.parametrize("name", FAMILY)
    @pytest.mark.parametrize("rail", sorted(RAILS))
    def test_rail_present(self, name, rail):
        marker, scope = self.RAILS[rail]
        haystack = _body(name) if scope == self.BODY else _section(name)
        assert marker in haystack, (
            f"{name}: the {rail.replace('_', ' ')} rail is missing. Autonomy in "
            f"this cohort is bounded by these {len(self.RAILS)} and nothing else."
        )


class TestTheIronLawStillForbidsTheShortcut:
    """The pre-authorization must not have loosened the two original laws.

    The three integration probes in `test_hard_gates.py` all ask for a fix with
    the report skipped, and all three must keep firing. That is a billed suite;
    this is the always-on half.
    """

    @pytest.mark.parametrize("name", FAMILY)
    def test_original_laws_intact(self, name):
        body = _body(name)
        for law in (
            "NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST",
            "NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES",
        ):
            assert law in body, f"{name}: Iron Law '{law}' was dropped"

    @pytest.mark.parametrize("name", FAMILY)
    def test_phase_4_still_stops(self, name):
        assert "Stop. Do not make changes until the user responds." in _body(name), (
            f"{name}: Phase 4's stop was deleted rather than pre-authorized. A "
            "blanket directive satisfies the wait; it does not remove it, and "
            "without the stop a bare `CR` implements unasked."
        )
