"""An architecture finding must carry the command that produced it (#142).

`reviewing-architecture` findings are routinely carved into GitHub issues and
implemented weeks later. A 13-issue backlog in `CannObserv/observo` was carved
directly from one such review and executed across six batches; the implementing
agent found a material error in the issue body **every single time**
(`orchestrating-issue-backlog/references/process-log.md`, 2026-08-09 entry).
Three of those would have shipped a defect as written.

The failure is not carelessness. One finding tabulated seven inline
`is StreamProvider.TVW` branch points with line numbers; it was correct when
written, and 5 of the 7 had become `==` value comparisons by the time the
implementing batch ran, because an earlier batch in the same backlog changed the
column type. No reviewer could have known. The specifics are cheap for the
implementer to re-derive and expensive for the reviewer to keep current, so the
fix is to stop presenting them as authoritative rather than to try harder to
keep them accurate.

Two properties, and only both together are worth having:

  carries its derivation   every finding records the command, query or
                           gather-context section that produced its citation, in
                           a form the reader can re-run — not only the location
                           the citation points at.
  specifics are dated      Phase 3 tells the reviewer to lead with the invariant
                           and treat file:line as evidence-of-the-moment rather
                           than as specification.

The first without the second yields a finding whose stale table is now merely
accompanied by a command nobody is told to prefer; the second without the first
leaves the implementer re-deriving from scratch what the reviewer already ran.

The addition must be **purely additive** to the existing envelope: eleven cohort
repos vendor this skill, so the four original labels must survive verbatim and
in order, with `Evidence:` slotted in beside them.

No API calls required.
"""

import re
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "reviewing-architecture"
SKILL_MD = SKILL_DIR / "SKILL.md"
DIMENSIONS = SKILL_DIR / "references" / "dimensions.md"

# The original four, in their original order, plus the new derivation slot.
ORIGINAL_LABELS = ("What:", "Why it matters:", "Suggested approach:", "Effort/Blast radius:")
EVIDENCE_LABEL = "Evidence:"
REQUIRED_LABELS = ("What:", EVIDENCE_LABEL, *ORIGINAL_LABELS[1:])


@pytest.fixture(scope="module")
def body() -> str:
    return SKILL_MD.read_text()


@pytest.fixture(scope="module")
def format_line(body: str) -> str:
    """The blockquoted finding-format template in Phase 3."""
    for line in body.splitlines():
        if line.startswith("> ") and "**[module/file]**" in line:
            return line
    pytest.fail("Phase 3 finding-format template line ('> N. **[module/file]** …') not found")


def _section(body: str, start: str, end: str) -> str:
    i = body.find(start)
    assert i != -1, f"section heading {start!r} not found in SKILL.md"
    j = body.find(end, i)
    assert j != -1, f"section heading {end!r} not found after {start!r} in SKILL.md"
    return body[i:j]


class TestFindingCarriesItsDerivation:
    def test_evidence_label_in_format_template(self, format_line):
        assert EVIDENCE_LABEL in format_line, (
            "The Phase 3 finding-format template must carry an 'Evidence:' label so a "
            "finding records how its citation was derived, not only where it points (#142)"
        )

    def test_original_four_labels_survive_verbatim(self, format_line):
        missing = [lbl for lbl in ORIGINAL_LABELS if lbl not in format_line]
        assert not missing, (
            f"The finding format must stay additive — original labels missing: {missing}. "
            "Eleven cohort repos vendor this skill and pin these four verbatim"
        )

    def test_label_order_is_stable(self, format_line):
        positions = [format_line.index(lbl) for lbl in REQUIRED_LABELS]
        assert positions == sorted(positions), (
            f"Finding labels must appear in the order {REQUIRED_LABELS}; got order "
            f"{[lbl for _, lbl in sorted(zip(positions, REQUIRED_LABELS))]}"
        )

    def test_evidence_slot_asks_for_a_rerunnable_command(self, format_line):
        slot = format_line[format_line.index(EVIDENCE_LABEL):]
        slot = slot.split("Why it matters:")[0].lower()
        assert "command" in slot, (
            "The Evidence slot must ask for the command (or query) that produced the "
            f"citation. Got: {slot!r}"
        )
        assert "re-run" in slot or "rerun" in slot, (
            "The Evidence slot must say the command is for the reader to re-run — that is "
            f"the whole point of recording it. Got: {slot!r}"
        )

    def test_labels_required_sentence_names_all_five(self, body):
        m = re.search(r"All five labels \(([^)]*)\) are required in every finding, verbatim", body)
        assert m, (
            "SKILL.md must state that all five labels are required in every finding, "
            "verbatim — the sentence that previously said 'All four labels'"
        )
        named = m.group(1)
        missing = [lbl for lbl in REQUIRED_LABELS if lbl not in named]
        assert not missing, f"The required-labels sentence omits: {missing}"

    def test_phase35_requires_the_derivation_not_only_the_location(self, body):
        phase35 = _section(body, "### Phase 3.5 — Verify before reporting", "### Phase 4")
        assert "Evidence:" in phase35, (
            "Phase 3.5's citation bullet must name the Evidence: label — it is the bullet "
            "that previously required a location and nothing about how it was obtained"
        )
        lowered = phase35.lower()
        assert "actually ran" in lowered or "this session" in lowered, (
            "Phase 3.5 must require the recorded command to be one actually run in this "
            "session, not one reconstructed for the report"
        )


class TestSpecificsAreDatedNotSpecified:
    @pytest.fixture(scope="class")
    def phase3(self, body: str) -> str:
        return _section(body, "### Phase 3 — Present findings", "### Phase 3.5")

    def test_shelf_life_note_present_in_phase3(self, phase3):
        assert "shelf life" in phase3.lower(), (
            "Phase 3 must carry a shelf-life note: findings become issue bodies read "
            "after other findings from the same review have landed (#142)"
        )

    def test_note_says_lead_with_the_invariant(self, phase3):
        assert "invariant" in phase3.lower(), (
            "The shelf-life note must tell the reviewer to lead with the invariant — the "
            "durable claim outlives the file:line specifics that evidence it"
        )

    def test_note_demotes_line_numbers_to_evidence(self, phase3):
        lowered = phase3.lower()
        assert "line numbers" in lowered, "The shelf-life note must name line numbers explicitly"
        assert "specification" in lowered or "not spec" in lowered, (
            "The shelf-life note must say line numbers are evidence-of-the-moment rather "
            "than specification — the fix is to stop presenting them as authoritative"
        )

    def test_note_explains_staleness_grows_with_execution_depth(self, phase3):
        lowered = phase3.lower()
        assert "stale" in lowered, "The shelf-life note must name staleness"
        assert "execution order" in lowered or "batch depth" in lowered, (
            "The note must say staleness is proportional to how deep in the execution "
            "order a finding sits — that is what makes it predictable rather than random"
        )


class TestDimensionsReferenceDoesNotDrift:
    """dimensions.md points at the SKILL.md envelope; the two must agree."""

    def test_envelope_pointer_lists_every_required_label(self):
        text = DIMENSIONS.read_text()
        m = re.search(r"the required report envelope \(([^)]*)\)", text)
        assert m, (
            "dimensions.md must keep its pointer at the required report envelope in "
            "SKILL.md Phase 3"
        )
        named = m.group(1)
        missing = [lbl.rstrip(":") for lbl in REQUIRED_LABELS if lbl.rstrip(":") not in named]
        assert not missing, (
            f"dimensions.md's envelope pointer has drifted from SKILL.md — missing: {missing}"
        )

    def test_envelope_pointer_no_longer_says_four(self):
        text = DIMENSIONS.read_text()
        assert "all four verbatim" not in text, (
            "dimensions.md still describes the envelope as four labels; it is five (#142)"
        )
