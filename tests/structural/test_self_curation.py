"""#96: the slow-cadence self-curation pass has an executable contract.

The pass itself is procedure — Phases 1–7 of `curating-context` run with
`skills/curating-context/SKILL.md` as the policy file, defined in
`skills/curating-context/references/self-curation.md`. Two parts of that
contract are checkable from the ledger, and this file pins them:

- **The eviction rule.** #96 decided that self-curation never deletes: a
  superseded rationale is demoted into `references/`, never removed, and the
  Iron Law's three warrants stay unchanged rather than growing a fourth. A
  `self:curation` row carrying a `delete:*` tag is therefore a contract
  violation, not a judgement call — the one shape of drift this file can
  refuse mechanically.
- **The tag's scope.** `self:curation` means "the pass over the skill's own
  surface". On any other `file` it would let a repo curation borrow the
  pass's exemptions (or its clock) without doing the pass.

The cadence is a WARNING, never a failure, raised from the module's autouse
fixture rather than from a test — the same reasoning as
`test_skill_self_budget.warn_about_the_blind_spot` (#217): it is a report, and
a test that can only ever pass is a vacuous assertion, while a test that fails
on the passage of time reddens an unrelated commit on day 93. The warning is
deliberately not a `UserWarning` subclass: the scheduled exact workflow runs
pytest under `-W error::UserWarning`, and an overdue nag must not turn that
job red.

The clock reads the newest row for `skills/curating-context/SKILL.md` whose
actions are not purely `baseline*` — any real curation of the surface resets
it, tagged or not, because the drift is countered by the work and not by the
tag. Before any such row exists, the epoch is the mechanism's adoption date.
No ledger row is seeded for it: `.skills/context-metrics.jsonl` records
measurements, and a row fabricated to start a clock would be the
"self-confirming fake measurement" budget-and-metrics.md warns about.
"""

import datetime
import json
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / ".skills" / "context-metrics.jsonl"
SELF_SURFACE = "skills/curating-context/SKILL.md"
SELF_TAG = "self:curation"

# When the mechanism shipped (#96). The clock's fallback until the first
# curation row for SELF_SURFACE exists; after that, the ledger is the clock.
MECHANISM_ADOPTED = datetime.date(2026, 8, 27)

# "Quarterly" as a number of days: the longest calendar quarter, so the warning
# means "a quarter has passed" in every season rather than only the short ones.
QUARTER_DAYS = 92


class SelfCurationOverdueWarning(Warning):
    """More than a quarter since the skill's own surface was last curated.

    Deliberately NOT a UserWarning subclass — see the module docstring.
    """


def ledger_rows() -> list[dict]:
    """Every parseable row. Malformed lines are skipped, not repaired or
    failed on: record-telemetry.sh's documented behaviour is to leave them
    where it found them, and a gate for ledger well-formedness would belong to
    a file about the ledger, not to this one."""
    if not LEDGER.is_file():
        return []
    rows = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def self_tagged(rows: list[dict]) -> list[dict]:
    return [r for r in rows if SELF_TAG in (r.get("actions") or [])]


def surface_curations(rows: list[dict]) -> list[dict]:
    """Rows that curated the skill's own surface: right file, and actions that
    are present and not purely baseline* — the same predicate every ledger
    reader uses to tell a curation from a measurement."""
    out = []
    for r in rows:
        if r.get("file") != SELF_SURFACE:
            continue
        actions = r.get("actions") or []
        if actions and not all(a.startswith("baseline") for a in actions):
            out.append(r)
    return out


@pytest.fixture(autouse=True, scope="module")
def warn_when_the_pass_is_overdue():
    """The quarterly clock (#96). A report, not a gate — see module docstring."""
    dates = [MECHANISM_ADOPTED]
    for row in surface_curations(ledger_rows()):
        try:
            dates.append(datetime.date.fromisoformat(row.get("ts") or ""))
        except ValueError:
            continue
    last = max(dates)
    age = (datetime.date.today() - last).days
    if age > QUARTER_DAYS:
        warnings.warn(
            f"SELF-CURATION OVERDUE: {SELF_SURFACE} was last curated "
            f"{last.isoformat()}, {age} days ago, against a {QUARTER_DAYS}-day "
            "(quarterly) cadence. Run the pass in "
            "skills/curating-context/references/self-curation.md — Phases 1-7 "
            f"with {SELF_SURFACE} as the policy file, demote/tighten only — "
            "and record it with a curation row so this clock resets. "
            "This is a WARNING and nothing is red: time passing must not "
            "block an unrelated commit.",
            SelfCurationOverdueWarning,
            stacklevel=1,
        )
    yield


class TestTheEvictionRule:
    """Self-curation never deletes — #96's decided contract, made refusable."""

    def test_a_self_curation_row_never_carries_a_delete_tag(self):
        offenders = [
            r for r in self_tagged(ledger_rows())
            if any(a.startswith("delete:") for a in (r.get("actions") or []))
        ]
        assert not offenders, (
            f"{len(offenders)} {SELF_TAG} row(s) carry delete:* tags: "
            f"{[(r.get('ts'), r.get('actions')) for r in offenders]}\n\n"
            "The self-curation pass demotes and tightens only (#96): a "
            "superseded rationale moves to references/, it does not vanish. "
            "If the content truly warranted deletion under the Iron Law's "
            "three warrants, it was a normal curation of the surface and the "
            f"row must not claim the {SELF_TAG} tag."
        )

    def test_the_tag_is_scoped_to_the_skills_own_surface(self):
        offenders = [
            r for r in self_tagged(ledger_rows())
            if r.get("file") != SELF_SURFACE
        ]
        assert not offenders, (
            f"{SELF_TAG} rows recorded against files other than "
            f"{SELF_SURFACE}: "
            f"{[(r.get('ts'), r.get('file')) for r in offenders]}\n\n"
            f"{SELF_TAG} means the pass over the skill's own surface; on any "
            "other file it borrows the pass's demote-only exemption without "
            "being the pass."
        )


class TestTheClockPredicate:
    """The fixture's `surface_curations` filter, pinned against synthetic rows.

    The clock must be reset only by a real curation of the right file — a
    baseline row measures a state nobody changed, and a curation of another
    file did not touch this surface. If the filter drifts, the warning either
    nags forever past real passes or stays silent forever, and no other test
    would notice: the fixture itself can only ever warn or not.
    """

    def test_a_curation_of_the_surface_resets_the_clock(self):
        rows = [{"file": SELF_SURFACE, "actions": [SELF_TAG, "prune:Phase 1"],
                 "ts": "2026-09-01"}]
        assert surface_curations(rows) == rows

    def test_an_untagged_curation_of_the_surface_also_resets_it(self):
        rows = [{"file": SELF_SURFACE, "actions": ["demote:Phase 8"],
                 "ts": "2026-09-01"}]
        assert surface_curations(rows) == rows

    def test_a_baseline_row_does_not(self):
        rows = [{"file": SELF_SURFACE, "actions": ["baseline:pre-curation"],
                 "ts": "2026-09-01"}]
        assert surface_curations(rows) == []

    def test_an_untagged_row_does_not(self):
        # record-telemetry.sh emits actions: [] when --actions was omitted; a
        # row that cannot be told from a baseline cannot restart a clock.
        rows = [{"file": SELF_SURFACE, "actions": [], "ts": "2026-09-01"}]
        assert surface_curations(rows) == []

    def test_another_files_curation_does_not(self):
        rows = [{"file": "AGENTS.md", "actions": ["demote:Layout"],
                 "ts": "2026-09-01"}]
        assert surface_curations(rows) == []
