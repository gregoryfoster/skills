"""Integration tests — competitive skill selection (#242).

`test_trigger_routing.py` asks each skill, in isolation, "does this request match
*your* skill?" — a question that cannot come out wrong no matter how badly the
library shadows itself. This file asks the question the runtime actually asks:
here are all nineteen skills, pick one.

Two contracts, one per half of AGENTS.md's variant strategy:

1. **Stack-specific routing.** A trigger plus evidence of a covered stack must
   select that stack's variant, not the baseline and not a sibling variant.
2. **Baseline fallback.** A trigger with *no* stack evidence, or with evidence
   of a stack no variant covers, must select the baseline. The uncovered-stack
   case is the one #97 measured failing: Haiku picked NONE 8/8 for a Go project
   because nothing on the selection surface said the baselines were the answer.
   #240 added that clause. **This file is the only thing in the repo that can
   tell you whether it worked** — Batch A's structural guard checks the clause
   is present, not that it functions.

## Trial count and cost

Ten scenarios × 5 Haiku trials, plus the two fallback scenarios × 3 Sonnet
trials: 56 calls, **≈$0.16 per full run**, ~45s wall clock. The listing dominates
the bill — every call carries all 19 descriptions, measured at 2288 input tokens
average via `count_tokens`, against ~10 output tokens for a bare skill name. So
cost scales with `trials × scenarios × library size`, and it is the *library*
that grows: each new variant adds a scenario **and** lengthens every other
scenario's prompt, making this quadratic-ish in skill count. Re-measure rather
than extrapolating when the library grows.

#97's probe was 72 calls and reported "well under $0.50", which is consistent.

Five was chosen over #97's eight because the assertion is unanimity, and the
failure it guards against was total (8/8 and 0/8, never a near-miss): at that
effect size the marginal trials buy precision the assertion does not spend. The
distribution is printed regardless of outcome, so a *partial* failure — the
interesting new signal, and the one that would justify raising N — is visible
rather than merely a red test.

## Why a second tier at all, on two scenarios only

The bulk is Haiku because Haiku is the tier that actually failed in #97; a
probe that only ran Sonnet would not have caught the original defect. But the
finding was specifically about *tier divergence* — Sonnet recovered on the
uncovered stack where Haiku did not. A Haiku-only suite cannot distinguish "the
fallback clause works" from "this model tier happens to cope", so the fallback
scenarios keep a small Sonnet arm. Every other scenario was 8/8 on both tiers in
#97, so a second tier there would buy nothing.

Model IDs are pinned to #97's exact tiers so a re-run is comparable with the
original measurement. Moving either is a deliberate re-baseline, not upkeep.

Run with:
    bash scripts/run-integration-tests.sh
    # or: pytest tests/integration/test_competitive_selection.py -m integration -s

`-s` surfaces the per-scenario distribution, which is the actual instrument —
a green run still tells you *how* green.
"""

import collections

import pytest

from tests.utils.selection_probe import (
    Scenario,
    UNCOVERED_STACK,
    UNPARSEABLE,
    choose_skill,
    parse_choice,
    scenarios,
    selection_prompt,
    skill_listing,
)

# The tier #97 measured failing. Same exact ID `tests/utils/api_harness.py`
# pins, so both integration files move tiers together or not at all.
_HAIKU = "claude-haiku-4-5-20251001"

# #97's second tier, kept only where the two diverged.
#
# Tracks the repo's current Sonnet (the ID `tests/benchmarks/test_quality.py`
# already uses) rather than pinning #97's exact `claude-sonnet-4-5-20250929`
# (CR finding 9). Pinning the original would keep the comparison like-for-like,
# but #242 asks this suite to run at growth checkpoints as a *regression guard*,
# and a guard aimed at a superseded tier passes green while the tier users
# actually get regresses. Reproducing #97 and detecting future drift are
# different jobs; this file does the second.
_SONNET = "claude-sonnet-4-6"

_HAIKU_TRIALS = 5
_SONNET_TRIALS = 3

_SCENARIOS = scenarios()
_FALLBACK_SCENARIOS = [s for s in _SCENARIOS if s.stack == UNCOVERED_STACK]

# (scenario, model, trials) — the full billed matrix.
_TRIALS = [(s, _HAIKU, _HAIKU_TRIALS) for s in _SCENARIOS] + [
    (s, _SONNET, _SONNET_TRIALS) for s in _FALLBACK_SCENARIOS
]


def _distribution(
    scenario: Scenario, model: str, trials: int
) -> collections.Counter:
    """Sample `trials` independent selections and tally them.

    Each trial is a fresh single-turn request: no conversation state, so the
    trials are independent samples of the selection distribution rather than a
    model being asked the same question repeatedly in one context.
    """
    listing = skill_listing()
    prompt = selection_prompt(scenario, listing)
    picks = collections.Counter(
        parse_choice(choose_skill(prompt, model=model)) for _ in range(trials)
    )
    print(f"\n{scenario.id} @ {model}: {dict(picks)}")
    return picks


def _assert_unanimous(picks: collections.Counter, scenario: Scenario, model: str, note: str) -> None:
    """Deterministic selection is the contract, so unanimity is the assertion.

    Any non-`expected` pick is reported with its count rather than a bare
    boolean — the difference between 1/5 and 5/5 wrong is the difference
    between sampling noise worth investigating and a shadowed description.
    """
    wrong = {name: n for name, n in picks.items() if name != scenario.expected}
    unparseable = picks.get(UNPARSEABLE, 0)
    diagnosis = (
        f"\n{unparseable}/{sum(picks.values())} response(s) had no readable first line. "
        "That is a formatting failure, not a selection failure — check max_tokens "
        "before concluding anything about the descriptions."
        if unparseable
        else ""
    )
    assert not wrong, (
        f"{scenario.id} @ {model}: expected {scenario.expected} on every trial, "
        f"got {dict(picks)}.\n{note}\n"
        f"Stack evidence given: {scenario.context or '(none)'}{diagnosis}\n"
        f"Do NOT fix this by editing a SKILL.md description to match the test — "
        f"the descriptions are what is under measurement."
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario,model,trials",
    [t for t in _TRIALS if t[0].stack not in ("none", UNCOVERED_STACK)],
    ids=lambda v: v.id if isinstance(v, Scenario) else str(v),
)
def test_a_covered_stack_selects_its_variant(
    scenario: Scenario, model: str, trials: int
) -> None:
    """Contract 1 — evidence of a covered stack routes to that stack's variant.

    A failure naming the *baseline* means the variant's stack tag is not
    carrying; a failure naming a *sibling variant* is inter-variant shadowing,
    which #97 measured at 0/72 and which would be the first sign that the
    library has outgrown flat descriptions (AGENTS.md's variant strategy, and
    the option-3 merge that #97 recommended against).
    """
    picks = _distribution(scenario, model, trials)
    _assert_unanimous(
        picks,
        scenario,
        model,
        note=(
            "A baseline pick means the stack tag is not carrying; a sibling-variant "
            "pick is inter-variant shadowing (#97 measured 0/72 — revisit the "
            "merge question if it appears)."
        ),
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario,model,trials",
    [t for t in _TRIALS if t[0].stack == "none"],
    ids=lambda v: v.id if isinstance(v, Scenario) else str(v),
)
def test_no_stack_context_selects_the_baseline(
    scenario: Scenario, model: str, trials: int
) -> None:
    """Contract 2a — a bare trigger with no stack evidence lands on the baseline.

    This is the half #97 already measured passing (8/8 at both tiers). It is
    here because #240 *changed the baseline descriptions*, and the cheapest way
    for a fallback clause to backfire is to pull uncovered traffic in while
    pushing no-context traffic out.
    """
    picks = _distribution(scenario, model, trials)
    _assert_unanimous(
        picks,
        scenario,
        model,
        note=(
            "A variant pick here means a stack-specific description is claiming "
            "context-free traffic; NONE means the family stopped answering its own "
            "bare trigger."
        ),
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario,model,trials",
    [t for t in _TRIALS if t[0].stack == UNCOVERED_STACK],
    ids=lambda v: v.id if isinstance(v, Scenario) else str(v),
)
def test_an_uncovered_stack_falls_back_to_the_baseline(
    scenario: Scenario, model: str, trials: int
) -> None:
    """Contract 2b — #240's fix, measured.

    #97: a Go project got `NONE` 8/8 at Haiku tier and the baseline 4/4 at
    Sonnet tier. The baselines were always the intended answer; nothing on the
    selection surface said so, and the smaller model would not infer it from
    the variants' existence — if anything the variants taught it the family was
    stack-gated.

    A `NONE` here means #240's clause did not land behaviourally, which is a
    finding about the fix, not about this test. Report it; do not relax this
    assertion, and do not reword a description until it passes — that would
    make the test measure the rewording.
    """
    picks = _distribution(scenario, model, trials)
    _assert_unanimous(
        picks,
        scenario,
        model,
        note=(
            f"This is #240's contract. NONE means the fallback clause is not "
            f"reaching the selection decision at this tier — the exact #97 failure. "
            f"A variant pick means a stack-specific description is claiming a stack "
            f"it does not cover ({UNCOVERED_STACK})."
        ),
    )
