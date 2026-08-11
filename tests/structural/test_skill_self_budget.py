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

The estimate runs a few percent above the exact count on this content (11,283
estimated vs 10,902 exact at the time of writing, +3.5%), which is the safe
direction for a gate: it can report over-budget slightly early, never late.

#95 asks for the gate to land before the trim, so the number is visible rather
than inferred from a diff. Pre-commit refuses a red commit, so the assertions
that the trim has to satisfy ship as `xfail(strict=True)` carrying the measured
figure in the reason: the gate commit is honest about failing, and the trim
commit cannot land without deleting the markers, because a strict xfail that
starts passing is itself a failure.

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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "#95, gate commit: SKILL.md is ~11,283 estimated / 10,902 exact "
            "tokens against a 6,000 budget — 82% over. Marked strict so the "
            "trim commit must delete this marker, and so nothing can quietly "
            "regrow past the budget once it does."
        ),
    )
    def test_skill_md_is_within_the_policy_budget(self, surface: dict):
        policy = surface["policy"]
        assert policy["tokens"] <= policy["budget"], (
            f"{SKILL_MD.relative_to(REPO_ROOT)} is ~{policy['tokens']:,} tokens "
            f"against the {policy['budget']:,}-token policy budget this skill "
            f"enforces on every repo's AGENTS.md "
            f"({policy['tokens'] - policy['budget']:,} over).\n\n"
            "Demote a section to references/ rather than deleting it — Phase 5, "
            "and prove it with prove-no-loss.sh --file "
            f"{SKILL_MD.relative_to(REPO_ROOT)}. Raising "
            f"{BUDGET_KNOB.relative_to(REPO_ROOT)} raises it for the whole repo, "
            "so that is a decision to argue for, not a fix.\n\n"
            + ESTIMATE_CAVEAT
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "#95, gate commit: references/budget-and-metrics.md estimates at "
            "~10,168 against the 10,000 per-doc budget (9,793 exact — the "
            "estimate crosses first, which is what a conservative estimator is "
            "for). It is the doc a Phase 4 demotion would naturally target, so "
            "it has to be split before anything moves into it."
        ),
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

    def test_the_gate_reads_the_repos_knobs(self, surface: dict):
        """The gate must not carry its own private copy of the budget.

        `measure-context.sh` resolves the policy budget through the same chain
        the write guard and the review delta use, so raising
        `.skills/context-budget` for this repo raises it here too — visibly,
        in one place, rather than by editing an assertion.
        """
        assert surface["policy"]["budget"] == int(BUDGET_KNOB.read_text().strip())
        assert RATIO_KNOB.is_file(), (
            "the offline estimate falls back to an uncalibrated 2.7 without "
            f"{RATIO_KNOB.relative_to(REPO_ROOT)}"
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

    @pytest.mark.xfail(
        strict=True,
        reason="#95 item 3, gate commit: SKILL.md states no edit budget yet.",
    )
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

    @pytest.mark.xfail(
        strict=True,
        reason="#95 item 3, gate commit: SKILL.md states no edit budget yet.",
    )
    def test_the_cap_says_what_happens_when_it_binds(self):
        body = SKILL_MD.read_text().lower()
        window = body[body.index("edit budget"):]
        assert "demote" in window or "tighten" in window, (
            "the edit budget states a cap but not the move it forces — a run "
            "that hits it needs to be told to displace something, not to stop"
        )
