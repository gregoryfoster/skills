"""`curating-context` measured against the budget it enforces on everyone else (#95).

The skill refuses to let a repo's `AGENTS.md` run over 6,000 tokens and refuses
to let a reference doc run over 10,000. Its own always-loaded `SKILL.md` was at
**10,902** exact tokens when this gate was written — 82% over the limit it
exists to enforce — and `references/budget-and-metrics.md` was within 4% of the
per-doc budget. A rule the author is exempt from is not a rule, and the moment a
cohort maintainer measures the skill we are handing them, they find that out.

Three things this gate deliberately is, and is not:

- **A structural test, not a CI workflow.** This repo has no
  `.github/workflows/`; the only gate is `.pre-commit-config.yaml` running
  `pytest tests/structural/`, and `AGENTS.md` already ships gates as structural
  tests (`TestNoBareScriptPaths`, `TestPreShipGateHardening`).
- **Offline.** Pre-commit has no `ANTHROPIC_API_KEY`, so the numbers here are
  the skill's calibrated offline estimate (`.skills/context-token-ratio`, 2.65
  bytes/token), not `count_tokens`. A gate that only fails when someone happens
  to hold a key is not a gate. Every failure message says so, and names the
  `--exact` command that produces the real number.
- **The skill's own machinery.** The measurement shells out to
  `measure-context.sh` with the flags #95 named rather than reimplementing the
  estimator in Python, so the gate and the weekly run cannot disagree about a
  number.

The estimate tracks the exact count closely on this content (7,551 estimated vs
7,574 exact after the trim; before it, 11,283 vs 10,902, +3.5%) and errs high on
the pre-trim shape,
which is the safe direction for a gate: it can report over-budget slightly
early, never late.

**Why the ratchet is 7,600 and not 6,000.** The trim took `SKILL.md` from 10,902
to 7,574 exact tokens (-30%) by demoting nine blocks into `references/` and splitting
`budget-and-metrics.md`, with `prove-no-loss.sh` proving every line survived.
What is left is a nine-phase runbook: a command, the rule that cannot be
re-derived, and a pointer, per phase. Reaching 6,000 from here means deleting
procedure, and Phase 4 is explicit that a budget which cannot be met without
touching class A is the wrong budget for that file — "an irreducible file is a
real finding". So the gate is set where the file actually sits, and the +250
per-round edit budget below is what makes that a ratchet rather than a rubber
stamp: the next addition has to displace something. Lower it when a later run
finds more; never raise it.

Note the 500-line body cap in `test_schema.py::TestBody` is a *different*
constraint. `SKILL.md` was 495 lines and 82% over budget at the same time.
Lines are not tokens; neither cap substitutes for the other.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "curating-context"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"
MEASURE = SKILL_DIR / "scripts" / "measure-context.sh"

# The knobs every surface reads. Named here so a failure message can say which
# file to change if the answer is "raise the budget" rather than "cut the file".
BUDGET_KNOB = REPO_ROOT / ".skills" / "context-budget"
DOC_BUDGET_KNOB = REPO_ROOT / ".skills" / "context-doc-budget"
RATIO_KNOB = REPO_ROOT / ".skills" / "context-token-ratio"

# The ratchet for the skill's own always-loaded body. Passed to the script as
# --budget rather than written into `.skills/context-budget`, because that knob
# is this repo's AGENTS.md budget and the two files are not the same argument:
# coupling them would mean ratcheting one silently ratchets the other.
SKILL_MD_RATCHET = 7_600

EXACT_CMD = (
    "bash skills/curating-context/scripts/measure-context.sh --exact --no-write "
    "--file skills/curating-context/SKILL.md "
    "--docs-dir skills/curating-context/references"
)

ESTIMATE_CAVEAT = (
    "This is the calibrated OFFLINE ESTIMATE at "
    f"{RATIO_KNOB.name} bytes/token, not an exact count — pre-commit has no "
    "ANTHROPIC_API_KEY. It runs a few percent high on this content, which is "
    "the safe direction. For the real number:\n  " + EXACT_CMD
)


def _clean_env() -> dict:
    """No credential, no knob overrides: reproduce what pre-commit sees."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR",
              "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    return env


@pytest.fixture(scope="module")
def surface() -> dict:
    """The skill's own surface, measured by the skill's own script.

    `--no-write` because a measurement run inside a test must not leave the
    observed ratio behind, and no `--exact` because the gate must not depend on
    a credential.
    """
    result = subprocess.run(
        [
            "bash", str(MEASURE),
            "--no-write",
            "--budget", str(SKILL_MD_RATCHET),
            "--file", str(SKILL_MD.relative_to(REPO_ROOT)),
            "--docs-dir", str(REFERENCES.relative_to(REPO_ROOT)),
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env=_clean_env(), timeout=120,
    )
    assert result.returncode == 0, (
        f"measure-context.sh failed on the skill's own surface:\n{result.stderr}"
    )
    return json.loads(result.stdout)


class TestTheSkillsOwnSurface:
    """#95: the skill's own files, held to the budgets the skill enforces."""

    def test_the_gate_does_not_need_a_credential(self, surface: dict):
        """Pre-commit holds no key, so the gate must run without one.

        `tokens_exact: false` here is the assertion, not a defect: it proves
        the number this gate acts on is one every contributor can reproduce.
        """
        assert surface["policy"]["tokens_exact"] is False, (
            "the gate reached count_tokens, so it is measuring something "
            "pre-commit cannot. Strip ANTHROPIC_API_KEY from the test env."
        )

    def test_skill_md_is_within_its_ratchet(self, surface: dict):
        policy = surface["policy"]
        assert policy["tokens"] <= SKILL_MD_RATCHET, (
            f"{SKILL_MD.relative_to(REPO_ROOT)} is ~{policy['tokens']:,} tokens "
            f"against its {SKILL_MD_RATCHET:,}-token ratchet "
            f"({policy['tokens'] - SKILL_MD_RATCHET:,} over).\n\n"
            "Demote a section to references/ rather than deleting it (Phase 5), "
            "and prove it with:\n"
            "  bash skills/curating-context/scripts/prove-no-loss.sh --base "
            "<branch-point> --file skills/curating-context/SKILL.md "
            "--docs-dir skills/curating-context/references\n\n"
            "Raising SKILL_MD_RATCHET is not the fix. It is a ratchet: it came "
            "down from 10,902 and only ever comes down.\n\n"
            "Note the +250 per-round edit budget is a RATE limit, not a "
            "licence to add 250: this ceiling is usually the tighter of the "
            "two, and a learning that does not fit under it has to displace "
            "something first.\n\n"
            + ESTIMATE_CAVEAT
        )

    def test_the_ratchet_stays_below_where_it_was_last_set(self, surface: dict):
        """A ratchet nobody can loosen by editing one integer.

        SKILL.md states the figure in prose for the run that reads it; the test
        enforces it. If the two ever disagree, the file is lying to the agent
        following it, which is the specific failure this whole skill exists to
        prevent.
        """
        assert f"{SKILL_MD_RATCHET:,}-token ratchet" in SKILL_MD.read_text(), (
            f"SKILL.md does not name its own {SKILL_MD_RATCHET:,}-token "
            "ratchet, so a run has no way to know what it is working against"
        )

    def test_every_reference_doc_is_within_the_per_doc_budget(self, surface: dict):
        doc_budget = int(DOC_BUDGET_KNOB.read_text().strip())
        over = [d for d in surface["docs"] if d["over_budget"]]
        assert not over, (
            f"reference docs over the {doc_budget:,}-token per-doc budget:\n"
            + "\n".join(f"  {d['path']} ~{d['tokens']:,}" for d in over)
            + "\n\nPast the per-doc budget, loading the doc stops costing less "
            "than carrying it inline — split it on its top-level headings. A "
            "demotion into an already-full doc moves the problem instead of "
            "solving it (Phase 4).\n\n"
            + ESTIMATE_CAVEAT
        )

    def test_no_reference_doc_is_orphaned(self, surface: dict):
        """The defect the skill finds most often in the cohort, on itself."""
        assert surface["links"]["orphans"] == [], (
            "reference docs nothing in SKILL.md links to: "
            f"{surface['links']['orphans']}"
        )

    def test_the_per_doc_budget_comes_from_the_repos_knob(self, surface: dict):
        """The doc budget is not a private copy — it is the repo's own knob.

        `measure-context.sh` resolves it through the same chain the write guard
        and the review delta use, so a change lands in one place and is visible
        to all three.
        """
        doc_budget = int(DOC_BUDGET_KNOB.read_text().strip())
        assert doc_budget == 10_000, (
            "the per-doc budget moved; if that is deliberate, say so here"
        )
        assert RATIO_KNOB.is_file(), (
            "the offline estimate falls back to an uncalibrated 2.7 without "
            f"{RATIO_KNOB.relative_to(REPO_ROOT)}"
        )

    def test_the_gap_to_the_enforced_budget_is_still_named(self):
        """The skill must not quietly forget that 6,000 is the real target.

        A ratchet above the enforced budget is only honest while the file says
        so. Silently normalising 7,600 as "the budget" is how the gap stops
        being a finding and starts being the status quo.
        """
        repo_budget = int(BUDGET_KNOB.read_text().strip())
        assert repo_budget < SKILL_MD_RATCHET, (
            "the ratchet is no longer above the budget the skill enforces — "
            "delete this test and the prose that goes with it"
        )
        assert str(repo_budget) in SKILL_MD.read_text(), (
            f"SKILL.md no longer names the {repo_budget:,} it enforces on every "
            "repo's AGENTS.md, so the gap it is carrying has gone unrecorded"
        )


class TestTheEditBudgetForLearnings:
    """#95 item 3: a learning must compete for space, not accumulate.

    A budget on the file is a ceiling; without a per-round cap a self-improving
    skill still walks up to it one plausible addition at a time, which is the
    accretion Library Drift documents and the reason this skill's own body
    reached 82% over. SkillOpt's equivalent is the per-step edit budget it calls
    a textual learning rate.

    The rule is only real if the run can read it, so it is asserted here rather
    than left to reviewer memory.
    """

    def test_skill_md_states_the_per_round_cap(self):
        body = SKILL_MD.read_text()
        assert "edit budget" in body.lower(), (
            "SKILL.md never names the edit budget, so a run adding a learning "
            "has nothing to weigh it against"
        )
        assert "250" in body, (
            "SKILL.md names an edit budget without a number; a cap with no "
            "figure never binds"
        )

    def test_the_cap_is_reconciled_with_the_ratchet(self):
        """CR round 2, finding 8. The two numbers have to be read together.

        The ratchet left ~49 tokens of headroom while the prose advertised
        +250, so a contributor spending their documented budget failed a gate
        whose message never mentioned the budget. Neither number was wrong —
        one is a ceiling and one a rate limit — but stating the rate without
        the ceiling invites exactly one wasted round.
        """
        body = SKILL_MD.read_text().lower()
        window = body[body.index("edit budget"):body.index("edit budget") + 600]
        assert "ratchet" in window, (
            "the edit budget is stated without naming the ratchet, so nothing "
            "tells a contributor which of the two actually binds"
        )
        assert "smaller" in window or "whichever" in window, (
            "the edit budget does not say it is capped by the remaining "
            "headroom, which is the constraint that actually fires"
        )

    def test_the_cap_says_what_happens_when_it_binds(self):
        body = SKILL_MD.read_text().lower()
        window = body[body.index("edit budget"):]
        assert "demote" in window or "tighten" in window, (
            "the edit budget states a cap but not the move it forces — a run "
            "that hits it needs to be told to displace something, not to stop"
        )
