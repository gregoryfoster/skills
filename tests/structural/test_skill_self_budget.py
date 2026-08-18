"""Every skill measured against the budget `curating-context` enforces (#95, #141).

`curating-context` refuses to let a repo's `AGENTS.md` run over 6,000 tokens and
refuses to let a reference doc run over 10,000. A rule the author is exempt from
is not a rule, and the moment a cohort maintainer measures the skills we are
handing them, they find that out. #95 held that mirror up to one skill; #141
holds it up to all eighteen.

Three things this gate deliberately is, and is not:

- **A structural test, not a CI workflow.** This repo has no
  `.github/workflows/`; the only gate is `.pre-commit-config.yaml` running
  `pytest tests/structural/`, and `AGENTS.md` already ships gates as structural
  tests (`TestNoBareScriptPaths`, `TestPreShipGateHardening`).
- **Always-on offline, exact on request.** The always-on tests read the
  skill's calibrated offline estimate (`.skills/context-token-ratio`, 2.68
  bytes/token since #172 refit it over the whole surface). A gate that only
  fails when someone happens to hold a key is not a gate — but an estimate is
  not the contract either, so
  `TestTheContractMeasuredExactly` re-runs the same ratchets against
  `count_tokens` when `SKILL_BUDGET_EXACT=1` is set.

  It is opt-in rather than opportunistic, and the first draft got this wrong
  in both directions. It assumed "pre-commit has no `ANTHROPIC_API_KEY`" —
  false here, because `measure-context.sh` loads one from a repo-root `.env`
  *itself*, so the exact path ran on every commit, costing ~20s and ~36 API
  calls in a repo whose only gate is pre-commit. And it treated a credential
  that was present but UNUSABLE as a hard failure rather than a skip, so an
  expired key, a rate-limit or a plane meant no commits at all. Both are fixed;
  the second was the same absent-vs-unusable shape #140 removed from the
  shellcheck gate in the same batch. Ship time is where exact belongs. See
  "Which number is the contract" below.
- **The skill's own machinery.** The measurement shells out to
  `measure-context.sh` with the flags #95 named rather than reimplementing the
  estimator in Python, so the gate and the weekly run cannot disagree about a
  number.

Two neighbouring rules are deliberately NOT asserted here, because another test
already owns them and a second, weaker copy is worse than none:

- **Dead links** belong to `test_relative_links.py`, which has its own
  `EXEMPT_LINKS` mechanism (#143). #141 was scoped to token budgets precisely so
  this file would not grow a competing exemption scheme.
- **Orphaned reference docs** belong to
  `test_references.py::TestReferences::test_no_orphan_references`, which has
  covered every skill since long before this gate existed. #95's copy of that
  assertion, scoped to `curating-context`, was redundant the day it shipped and
  is gone.

## The standard, and the exceptions

`SKILL_MD_STANDARD` is **6,000 tokens** — the same figure `curating-context`
enforces on every repo's `AGENTS.md`, on the reasoning that an always-loaded
policy file is an always-loaded policy file whether it is called `AGENTS.md` or
`SKILL.md`. Thirteen of the eighteen skills meet it.

The five that do not are named in `SKILL_MD_RATCHETS`, each with the reason it
cannot, because #141 chose *shared standard plus named exceptions* over a
per-skill table. A table of eighteen numbers seeded at current size stops growth
without ever creating pressure toward the standard, and buries the outliers; a
named exception has to argue for itself in the diff and stays visible.

An exception's ratchet is set at **its current measured size, rounded up to the
next 50 tokens** — not at a comfortable round number above it. The ≤49 tokens of
slack exists so a no-op reflow (a renamed link, a widened table column) does not
require a code change; it is far below the +250-per-round edit budget that
governs deliberate additions, so for an exception the ratchet always binds
first. That is the intent: a skill already over the standard should not grow.

"Current measured size" means the larger of the two readings — see "Which number
is the contract" below.

A ratchet stops growth. It does not mandate a trim — reclaiming size already
spent is #96's recurring self-curation pass, not this static gate's job.

## Which number is the contract

The gate runs with `ANTHROPIC_API_KEY` stripped, so the always-on tests see the
**estimator**. Batch A of #144 found the estimator and `count_tokens` on
opposite sides of `curating-context`'s ratchet — 7,580 vs 7,621 against 7,600 —
and asked which one the ratchet actually names.

Measuring all eighteen both ways settles it, and disproves the assumption #95
wrote into this file. #95 recorded that the estimate "errs high, which is the
safe direction for a gate". That was true of `curating-context` and is false of
the library: **the estimator runs LOW on 12 of 18 `SKILL.md` files**, by as much
as **-13.4%** on `init-project-fastapi` (14,773 estimated vs 17,057 exact) — all
figures in this docstring measured 2026-08-17 and **partly superseded on
2026-08-18**, when #190 trimmed that file to 14,652 exact / -12.04% and its
unbudgeted-token gap to 1,764; see the note at `POLICY_ESTIMATE_BAND` — and
by as much as -23.9% on a single reference doc
(`init-project-fastapi/references/postgres-provisioning.md`, 1,211 vs 1,591).
The cause is visible in the per-file `bytes_per_token`, which ranges 2.32
(`init-project-fastapi`) to 2.84 (`orchestrating-issue-backlog`) across the
`SKILL.md` files, and 2.04 to 3.03 once the reference docs are included, against
the single global 2.68 the estimator assumes: code-and-path-dense files tokenize
denser than the prose the ratio was calibrated on. Low is the permissive
direction, so the error #95 believed was impossible is the common case.

Those figures are a 2026-08-17 remeasurement of all 87 files, and they are NOT
the ones this file carried before #159. #172 refit the ratio from 2.65 to 2.68,
which lowered every estimate by ~1.1% and so made the permissive direction
uniformly *worse*, not better: -12.4% became -13.4% and -23.0% became -23.9%.
A refit that improves the fit in aggregate can still widen the tail, and the
tail is the side a budget gate cares about.

The ruling, and the three questions Batch A raised:

1. **Neither number alone is the contract. The ratchet binds both.** One
   integer per skill, and a skill passes only if the offline estimate is under
   it *and* `count_tokens` is under it — so the effective bound is always the
   stricter of the two readings, and no one can loosen a ratchet by choosing a
   measurement. "Exact is the contract" was tried first and is wrong: it fails
   `orchestrating-issue-backlog`, whose estimate runs 1,252 tokens HIGH, in the
   only gate that actually runs. "Estimate is the contract" is worse: it is a
   number that does not describe what a run loads, and it would let
   `init-project-fastapi` carry 2,284 unbudgeted real tokens. Binding both costs
   nothing but honesty about which reading is in force, and every `SKILL.md`
   names its own figure *and* that it holds under both — `"6,000-token ratchet
   (estimate and exact)"` — so the prose and the test describe the same
   quantity.
2. **Ratchets carry no calibration margin.** A margin large enough to cover the
   measured worst case would have to be applied to every skill, and a 6,000
   standard minus 13% is a 5,220 standard nobody wrote down — the same class of
   dishonesty as a slack ratchet, pointing the other way. Binding both readings
   already removes the hazard the margin was proposed to cover: the straddle
   Batch A found now fails rather than passes, because the higher reading is the
   one that has to clear.
3. **The divergence is pinned — in two bands, one per population.**
   `POLICY_ESTIMATE_BAND` and `DOC_ESTIMATE_BAND` record how far the estimator
   may stray from `count_tokens` before someone has to look. Either fails if the
   ratio knob drifts out of calibration, or if a file's content mix moves far
   enough that the two readings pull apart — turning an invisible hazard into a
   maintained number. They are also the reason `SKILL_MD_RATCHETS` can carry one
   integer instead of two: the gap between the readings is bounded and watched.

   There are two constants because #159 found there had only ever been one, and
   it was asserted against the eighteen `SKILL.md` files alone while this
   paragraph claimed it pinned the estimator generally. The sixty-nine reference
   docs — the larger part of the surface, and the part carrying the repo's
   widest error at -23.9% — were checked by nothing. One band cannot cover both:
   the doc spread is 37 points wide against the policy spread's 19, so a single
   band is either red on four well-behaved docs or 15 points too slack for every
   `SKILL.md`. The constants carry their own measurements and the reasoning for
   each edge.

Because the ratchet binds the higher reading, an exception's recorded size is
`max(estimate, exact)` rounded up to the next 50 — which for two of the five is
the *estimate*, not the exact count.

Note the 500-line body cap in `test_schema.py::TestBody` is a *different*
constraint. `curating-context/SKILL.md` was 495 lines and 82% over budget at the
same time. Lines are not tokens; neither cap substitutes for the other.
"""

import json
import os
import subprocess
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
MEASURE = SKILLS_DIR / "curating-context" / "scripts" / "measure-context.sh"

SKILLS = sorted(
    p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file()
)

# The knobs every surface reads. Named here so a failure message can say which
# file to change if the answer is "raise the budget" rather than "cut the file".
BUDGET_KNOB = REPO_ROOT / ".skills" / "context-budget"
DOC_BUDGET_KNOB = REPO_ROOT / ".skills" / "context-doc-budget"
RATIO_KNOB = REPO_ROOT / ".skills" / "context-token-ratio"

# The standard every SKILL.md is held to, under BOTH readings. Deliberately a
# separate constant from `.skills/context-budget` even though both read 6,000:
# that knob is this repo's own AGENTS.md budget, and coupling them would mean
# ratcheting one silently ratchets the other.
SKILL_MD_STANDARD = 6_000

# The five skills that cannot meet the standard, each with the reason. Set at
# max(estimate, exact) rounded up to the next 50 (see module docstring).
# Lower one when a later run finds it smaller; never raise one.
SKILL_MD_RATCHETS = {
    # A nine-phase runbook: a command, the rule that cannot be re-derived, and a
    # pointer, per phase. Came down from 10,902 by demoting nine blocks into
    # references/. Reaching 6,000 means deleting procedure, and this skill's own
    # Phase 4 is explicit that a budget which cannot be met without touching
    # class A is the wrong budget for that file. Unlike the four below, its
    # ratchet sits above current size on purpose: the gap is the working room
    # for the documented +250-per-round edit budget, reconciled in its prose.
    "curating-context": 7_600,
    # A bootstrap runbook that emits a whole project: pyproject, FastAPI
    # skeleton, structured logging, TDD scaffold, deploy key, systemd unit. Most
    # of the body is literal file content and command sequences, which is why it
    # tokenizes at 2.35 bytes/token — the densest SKILL.md in the repo, though
    # three of its own reference docs are denser still (2.04 to 2.12). See the
    # outlier note below. Bound by its EXACT count; its estimate reads 1,764
    # lower, the worst calibration gap of any SKILL.md. Came down from 17,100 by
    # demoting Phases 8, 10, 11 and 16's table into references/ (#190) — an
    # interim pass at #96's problem, not the redesign the outlier note describes.
    "init-project-fastapi": 14_700,
    # Docker/Node preflight, plugin enablement, a project-adapted policy doc,
    # two hook wirings, and a blocking index verified by edge yield. Grew during
    # Batch A of #144 (#107's yield-gate table, #115's two-variant Phase 3).
    "init-socraticode": 10_050,
    # The submodule + symlink pattern in full, including the two-level chain,
    # the doctor's self-heal, and the pin file. Carries no references/ at all,
    # so every word of it is always-loaded by construction — the one skill where
    # demotion is the whole remaining move.
    "managing-skills": 8_750,
    # A ten-step orchestration procedure with scoring rubrics, conflict-zone
    # analysis, and batch-plan templates. The largest file in the repo. See the
    # outlier note below. Bound by its ESTIMATE, which reads 1,252 higher than
    # count_tokens — the reason this file learned that "exact is the contract"
    # does not survive contact with the gate that actually runs.
    #
    # Raised once, from 22,900, and the raise is the record of what it bought:
    # the skill's own Orchestrator step 2 ("check out `batch/<X>` before
    # spawning agents") took production down in a repo whose deploy units carry
    # a checkout guard, across three separate batches before anyone connected
    # the outage to this file (#146). A ratchet that forces a runbook to omit
    # the rule its own instruction needs is optimising the wrong quantity.
    #
    # The session paid most of the way first, so the raise is the residue and
    # not the bill: ~1,275 bytes of genuine double-writing removed — the
    # stale-checkout paragraph told three times over (checklist item 0, Step
    # 1–2, Rule 1), four Key Principles bullets restating Step 7 and the branch
    # strategy, and nine provenance lines folded into the siblings that already
    # named the same steps — against ~1,820 bytes of new rule. Net +207 tokens.
    # Set at current size again: this file still cannot grow without someone
    # arguing for it here.
    "orchestrating-issue-backlog": 23_110,
}

# The two outliers, at 2.8x and 3.6x the standard, deserve more than one line.
#
# `init-project-fastapi` and `orchestrating-issue-backlog` are long procedural
# runbooks, not policy files: read top-to-bottom once, in order, with each step
# depending on the state the previous one left behind. That shape resists the
# demotion move that got `curating-context` from 10,902 to ~7,350, because
# demotion trades an always-loaded token for an on-demand one only when the
# demoted block is genuinely optional. A step in the middle of a bootstrap is
# not optional, and a run that has to fetch it mid-sequence pays the tokens
# anyway plus a round trip.
#
# What would have to change for either to conform:
#
# - `init-project-fastapi` would have to stop being one skill. Its size is
#   variant explosion in a single file — DEPLOY_TARGET, DB_BACKED, ADMIN_UI,
#   PRIVATE_WHEELHOUSE each fork the procedure, and every run loads all four
#   forks to walk one. Conditional-block delimiters (docs/CONVENTIONS.md) or a
#   split into a core bootstrap plus per-variant references would let a run load
#   only its own path. That is a redesign, and it is #96's kind of work.
# - `orchestrating-issue-backlog` would have to move its rubrics and templates
#   out of the body. Unlike the bootstrap, much of its bulk IS optional per run:
#   a session that never hits a conflict zone still loads the conflict-zone
#   analysis. It already carries references/ and already demotes its process log
#   there, so the mechanism exists and only the classification pass is missing.
#
# Neither trim belongs to #141. This gate stops growth; #96 reclaims size.

# Reference docs are held to the repo's 10,000-token per-doc knob.
#
# EMPTY, and that is the finding. It held one entry until #152: the
# `orchestrating-issue-backlog` process log, exempt with a `None` because a
# numeric ratchet had already been tried and was wrong within the hour — set at
# 60,750 against a measured 60,748, then pushed to 61,280 by a concurrent
# session that did nothing but journal correctly. A ratchet says "this may not
# grow"; an append-only ledger's whole contract is that it grows, and holding
# both means every future journaling session must trim the ledger to afford its
# own entry.
#
# The exemption was honest and it was not a fix. What resolved it was changing
# the artifact rather than the rule: the ledger became an indexed journal, one
# file per session under `references/process-log/<year>/`, and the per-doc
# budget — which measures with `find`, recursively — now binds each entry on its
# own. Nothing is exempt, and the append-only artifact still grows without any
# file growing.
#
# The index is nonetheless the doc to watch, and it has moved since #152: at
# 2026-08-17 it reads 8,018 estimated / 8,050 exact against 10,000, up from the
# ~6,600 recorded here, while the largest single entry reads 6,010 / 5,845. The
# index is the one file in this tree that every journaling session appends to,
# so it is the one whose growth is structural rather than incidental. When it
# crosses, splitting it by year is the move — not an exception.
#
# `None` would mean exempt; any other value is a hard ceiling. The mechanism is
# kept, and proven by TestTheExemptionMechanism, because the next doc that needs
# it should find a tested one — but it is deliberately unused, so an exemption
# has to be argued for in a diff rather than joined to an existing list.
DOC_BUDGET_EXCEPTIONS: dict[str, int | None] = {}


def _doc_over(doc: dict, doc_budget: int) -> bool:
    """True when a reference doc exceeds the ceiling that binds it.

    A `None` entry in DOC_BUDGET_EXCEPTIONS is EXEMPT, not zero — comparing
    against it directly raises TypeError, and a bare `or doc_budget` would
    silently re-impose the 10,000 default on the one file the exemption is for.
    """
    ceiling = DOC_BUDGET_EXCEPTIONS.get(doc["path"], doc_budget)
    if ceiling is None:
        return False
    return doc["tokens"] > ceiling

# How far the offline estimate may stray from count_tokens before someone has to
# look. TWO bands, because the surface is two populations and #159 found that one
# number cannot honestly describe both.
#
# Widening either is not a fix — it is the record of a blind spot getting bigger,
# and the reason to recalibrate `.skills/context-token-ratio` instead. Both are
# set from a full both-ways measurement of all 87 files (18 SKILL.md + 69
# reference docs) on 2026-08-17, at the 2.68 ratio in force since #172.
#
# POLICY — the eighteen SKILL.md files. Measured -13.4%
# (`init-project-fastapi`, the permissive direction and the one that matters) to
# +5.8% (`reviewing-architecture`). Kept at ±15%: the low edge now has only 1.6
# points of headroom, which is the band doing its job rather than a reason to
# move it. If `init-project-fastapi` crosses, the answer is the ratio, not this.
#
# SUPERSEDED IN PART, 2026-08-18 (#190). The spread above is a 2026-08-17
# snapshot and the file it names as the extreme has since been trimmed: demoting
# four phases took `init-project-fastapi` from 17,057 to 14,652 exact and its
# drift from -13.4% to -12.04%, so the low edge has 2.96 points of headroom, not
# 1.6. WHICH file is now the extreme is unmeasured — the -13.4% endpoint above
# is stale, and re-running the full 87-file spread is what would replace it.
# The band itself is unchanged and still correct; only the evidence quoted for
# it is dated, and it is quoted in four places (this block, and the module
# docstring's -13.4% / 2.32 bytes-per-token / 2,284-unbudgeted-tokens figures).
POLICY_ESTIMATE_BAND = (-0.15, 0.15)

# DOCS — the sixty-nine reference docs, and the population #159 found uncovered
# while the docstring above claimed the estimator was pinned generally. Measured
# -23.9% (`init-project-fastapi/references/postgres-provisioning.md`, mostly TOML
# and Python) to +13.0% (`reviewing-architecture/references/dimensions.md`, prose
# and tables). Four docs sit outside the policy band — three under
# `init-project-fastapi/references/`, one under `vendoring-openapi-client/` —
# which is what makes reusing the policy band here a false negative machine
# rather than a stricter gate.
#
# Wider is not laxer here, for two reasons:
#
# - Docs carry the wider content mix by construction. A SKILL.md is always part
#   prose; a reference doc can be a single TOML file or a single rubric table,
#   and per-file bytes_per_token spans 2.04 to 3.03 across this population
#   against 2.32 to 2.84 across the SKILL.md files.
# - Nothing depends on this band to keep a doc under budget.
#   `TestTheContractMeasuredExactly` already binds every doc's EXACT count to the
#   per-doc budget, so this band is a calibration tripwire, not the safety net.
#   The one place it does gate — `_stale_doc_exceptions` — is made stricter by
#   widening it, not looser.
#
# Each edge sits 6-7 points beyond the measured extreme. That is deliberate and
# it is sized: refitting the ratio from 2.65 to 2.68 in #172 moved every reading
# here by about 1.1 points, so a band with one point of slack would be a band
# that fires on the next recalibration rather than on a content change.
DOC_ESTIMATE_BAND = (-0.30, 0.20)


def _stale_doc_exceptions(measured: dict[str, int], doc_budget: int) -> list[str]:
    """Numeric doc exceptions whose file is now unambiguously under the budget.

    Discounted by DOC_ESTIMATE_BAND, not the policy band (#159). These are doc
    rows and a doc row's estimate runs as much as 24% low here, so the policy
    band's -15% would call an exception stale at 8,500 estimated tokens — a file
    that can be over 11,000 exactly and still needs the exception it is about to
    lose. `None` entries are exempt by construction and cannot go stale.
    """
    unambiguous = doc_budget * (1 + DOC_ESTIMATE_BAND[0])
    return [
        path for path, ceiling in DOC_BUDGET_EXCEPTIONS.items()
        if ceiling is not None
        and path in measured
        and measured[path] <= unambiguous
    ]


def ratchet_for(skill: str) -> int:
    return SKILL_MD_RATCHETS.get(skill, SKILL_MD_STANDARD)


def ratchet_phrase(skill: str) -> str:
    """The exact string a SKILL.md must contain to name its own budget.

    Naming the METHOD alongside the figure is not decoration: the always-on gate
    reads an estimate and the credential-gated one reads count_tokens, so prose
    that said "6,000 tokens" and stopped would leave a reader unable to tell
    which of two numbers, up to 13% apart, it meant.
    """
    return f"{ratchet_for(skill):,}-token ratchet (estimate and exact)"


def exact_cmd(skill: str) -> str:
    return (
        "bash skills/curating-context/scripts/measure-context.sh --exact "
        f"--no-write --file skills/{skill}/SKILL.md "
        f"--docs-dir skills/{skill}/references"
    )


def worst_case_exact(estimate: int) -> int:
    """The highest `count_tokens` reading POLICY_ESTIMATE_BAND still permits.

    The band bounds the estimator's error against the truth — the estimate is
    `exact * (1 + err)` for some `err` in the band — so the worst case inverts
    it: `estimate / (1 + low)`. Multiplying by `(1 + high)` instead answers how
    high the ESTIMATE could read for a known exact, which is the other direction
    and understates the answer at every input.

    This is not a licence to spend up to the worst case. It is the number a run
    needs to tell "comfortably under" from "green offline, over in fact", which
    is the only distinction the always-on gate cannot make for itself.
    """
    return round(estimate / (1 + POLICY_ESTIMATE_BAND[0]))


def estimate_caveat(skill: str, estimate: int | None = None) -> str:
    """The offline caveat, with the band-derived worst case when one applies.

    `estimate` is optional because only the SKILL.md ratchet failure has a
    policy estimate to convert. The per-doc failure fails about reference docs,
    a population `DOC_ESTIMATE_BAND` describes and this one does not, so it
    passes nothing and gets the prose alone rather than a figure computed from
    the wrong band.

    #190: the issue asked for the exact margin here, on the assumption that an
    exact figure is available offline. None is — `.skills/context-token-counts`
    anchors `AGENTS.md` and three `docs/` files and no `skills/*/SKILL.md` — so
    a run gets the worst case the band permits instead. `init-project-fastapi`
    is why: it read 14,773 estimated against a 17,100 ratchet, which presents as
    2,327 tokens of headroom and was 43.
    """
    caveat = (
        "This is the calibrated OFFLINE ESTIMATE at "
        f"{RATIO_KNOB.name} bytes/token, not an exact count — pre-commit has "
        "no ANTHROPIC_API_KEY. Across this library it runs 13% low to 6% high "
        "on SKILL.md files and 24% low to 13% high on reference docs, and the "
        "budget binds BOTH readings — so clearing this one is necessary, not "
        "sufficient. The other:\n  "
        + exact_cmd(skill)
    )
    if estimate is None:
        return caveat
    ratchet = ratchet_for(skill)
    worst = worst_case_exact(estimate)
    verdict = (
        "this file may already be over"
        if worst > ratchet
        else "the whole band clears the ratchet"
    )
    return (
        f"estimate {estimate:,} → worst case ~{worst:,} against a "
        f"{ratchet:,} ratchet; {verdict}.\n\n"
        + caveat
    )


def _env(*, exact: bool) -> dict:
    """Reproduce what pre-commit sees, plus a credential only when asked."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    if not exact:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def _measure(skill: str, *, exact: bool) -> dict:
    """Measure one skill's surface with the skill's own script.

    `--no-write` because a measurement run inside a test must not leave the
    observed ratio behind.
    """
    cmd = [
        "bash", str(MEASURE),
        "--no-write",
        "--budget", str(ratchet_for(skill)),
        "--file", f"skills/{skill}/SKILL.md",
        "--docs-dir", f"skills/{skill}/references",
    ]
    if exact:
        cmd.insert(3, "--exact")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
        env=_env(exact=exact), timeout=300,
    )
    assert result.returncode == 0, (
        f"measure-context.sh failed on skills/{skill}:\n{result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def surfaces() -> dict:
    """Every skill's surface, measured offline. ~3s for all eighteen."""
    return {name: _measure(name, exact=False) for name in SKILLS}


def _has_credential() -> bool:
    """Ask the script itself, so the test and the tool agree on what counts.

    `--check-credential` exits 3 when nothing usable answers — including when
    only an `ant auth login` JWT profile does, which count_tokens rejects.
    """
    result = subprocess.run(
        ["bash", str(MEASURE), "--check-credential"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env=_env(exact=True), timeout=60,
    )
    return result.returncode == 0


# Opt-in, not opportunistic. Two reasons, both learned the hard way (#144 CR):
#
#   1. `measure-context.sh` loads a key from a repo-root `.env` ITSELF, so
#      "pre-commit has no credential" was false here — the exact path was the
#      DEFAULT, adding ~20s and ~36 API calls to every commit in a repo whose
#      only gate is pre-commit.
#   2. Worse, a credential that was present but UNUSABLE (expired, rotated,
#      rate-limited, or simply offline) hard-failed 18 tests instead of
#      skipping, so a bad key meant no commits at all — including a one-line
#      docs fix. That is the same shape as the absent-vs-too-old shellcheck
#      binary #140 fixed in this very batch.
#
# So: the always-on gate is the offline estimate, and the exact contract is
# verified when asked for. `shipping-work`'s pre-ship gate is the natural place
# to ask — commit-time stays fast and offline, ship-time is exact.
EXACT_ENV = "SKILL_BUDGET_EXACT"


def _exact_requested() -> bool:
    return os.environ.get(EXACT_ENV, "") not in ("", "0")


@pytest.fixture(scope="module")
def exact_surfaces() -> dict:
    """Every skill's surface, measured by count_tokens. ~20s, needs a key."""
    if not _exact_requested():
        pytest.skip(
            f"exact verification is opt-in: set {EXACT_ENV}=1 to run it. The "
            "offline gate ran and is the always-on contract; this pass costs "
            "~20s and one API call per surface, so it is not on the "
            "pre-commit path."
        )
    measured = (
        {name: _measure(name, exact=True) for name in SKILLS}
        if _has_credential() else {}
    )

    # `--check-credential` answers "is a key string reachable", NOT "does the
    # API accept it" — it exits 0 on any non-empty value in `.env`. So the
    # honest test of usability is whether the run actually reached
    # count_tokens, which is only knowable after measuring. Detect the
    # fallback HERE and skip the class once, rather than letting eighteen
    # per-skill assertions each fail on the same infrastructure condition.
    #
    # Skip, do not fail. An expired key, a rate limit or a plane is not a
    # budget violation, and failing here blocks every commit in a repo whose
    # only gate is pre-commit — the same absent-vs-unusable shape #140 removed
    # from the shellcheck gate. The warning is loud because silently skipping
    # a check that was explicitly REQUESTED is the other way to get this wrong.
    if not measured or not all(
        s["policy"]["tokens_exact"] for s in measured.values()
    ):
        warnings.warn(
            f"{EXACT_ENV} was set but the run could not reach count_tokens, so "
            "the exact contract WAS NOT VERIFIED — only the offline estimate "
            "ran. Check the key is current and the API reachable: "
            "`bash skills/curating-context/scripts/measure-context.sh "
            "--check-credential`.",
            UserWarning,
            stacklevel=2,
        )
        pytest.skip(
            f"{EXACT_ENV} set but count_tokens was not reached; see the "
            "warning above."
        )
    return measured


class TestTheGateItself:
    """The properties that make this a gate rather than a report."""

    def test_the_gate_does_not_need_a_credential(self, surfaces: dict):
        """Pre-commit holds no key, so the always-on gate must run without one.

        `tokens_exact: false` here is the assertion, not a defect: it proves
        the number the always-on tests act on is one every contributor can
        reproduce.
        """
        reached = [s for s in SKILLS if surfaces[s]["policy"]["tokens_exact"]]
        assert not reached, (
            f"the offline gate reached count_tokens for {reached}, so it is "
            "measuring something pre-commit cannot. Strip ANTHROPIC_API_KEY "
            "from the test env."
        )

    def test_every_skill_is_measured(self, surfaces: dict):
        """A skill added without a ratchet must not silently escape the gate."""
        on_disk = sorted(
            p.name for p in SKILLS_DIR.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
        assert on_disk == SKILLS, (
            f"skills/ holds directories without a SKILL.md: "
            f"{sorted(set(on_disk) - set(SKILLS))}"
        )
        assert set(surfaces) == set(SKILLS)

    def test_no_exception_survives_the_skill_conforming(self, surfaces: dict):
        """A named exception has to still be one.

        If a skill is trimmed under the standard, its entry in
        `SKILL_MD_RATCHETS` stops being an exception and becomes an unused
        licence to grow back. Deleting the entry is the whole fix.

        Judged against the standard discounted by the calibration band, not
        against the standard itself: this test only sees the estimate, and a
        skill reading 5,900 offline may still be over 6,000 exactly. It fires
        only where the estimate is under by more than the estimator can be
        wrong.
        """
        unambiguous = SKILL_MD_STANDARD * (1 + POLICY_ESTIMATE_BAND[0])
        stale = [
            s for s in SKILL_MD_RATCHETS
            if surfaces[s]["policy"]["tokens"] <= unambiguous
        ]
        assert not stale, (
            f"these skills now fit the {SKILL_MD_STANDARD:,}-token standard "
            f"and no longer need an exception: {stale}. Delete their entries "
            "from SKILL_MD_RATCHETS (and the line in their SKILL.md), rather "
            "than leaving a ratchet that permits growing back."
        )

    def test_no_doc_exception_survives_the_doc_conforming(self, surfaces: dict):
        """The sibling of the ratchet staleness guard, for reference docs.

        A numeric doc exception whose file has since shrunk under the per-doc
        budget is an unused licence to grow back, exactly as a stale
        SKILL_MD_RATCHETS entry is. `None` entries are exempt by construction
        and cannot go stale — they assert nothing to outgrow.
        """
        doc_budget = int(DOC_BUDGET_KNOB.read_text().strip())
        measured = {
            d["path"]: d["tokens"]
            for skill in SKILLS for d in surfaces[skill]["docs"]
        }
        stale = _stale_doc_exceptions(measured, doc_budget)
        assert not stale, (
            f"these docs now fit the {doc_budget:,}-token per-doc budget and "
            f"no longer need an exception: {stale}. Delete their entries from "
            "DOC_BUDGET_EXCEPTIONS rather than leaving a ceiling that permits "
            "growing back."
        )

    def test_every_doc_exception_value_is_well_formed(self):
        """`None` means exempt; anything else must be a usable ceiling.

        A typo'd value would otherwise reach `_doc_over` and either crash with
        a TypeError or, worse, compare truthily and silently change what the
        gate enforces.
        """
        bad = {
            path: value for path, value in DOC_BUDGET_EXCEPTIONS.items()
            if not (value is None or (isinstance(value, int) and value > 0))
        }
        assert not bad, (
            f"DOC_BUDGET_EXCEPTIONS values must be None (exempt) or a positive "
            f"int (ceiling); got {bad}"
        )

    def test_every_exception_is_a_skill_that_exists(self):
        """A ratchet for a renamed or deleted skill gates nothing."""
        unknown = sorted(set(SKILL_MD_RATCHETS) - set(SKILLS))
        assert not unknown, (
            f"SKILL_MD_RATCHETS names skills that do not exist: {unknown}"
        )
        unknown_docs = [
            p for p in DOC_BUDGET_EXCEPTIONS if not (REPO_ROOT / p).is_file()
        ]
        assert not unknown_docs, (
            f"DOC_BUDGET_EXCEPTIONS names files that do not exist: "
            f"{unknown_docs}"
        )

    def test_the_per_doc_budget_comes_from_the_repos_knob(self):
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


class TestTheExemptionMechanism:
    """`_doc_over` decides which docs the per-doc budget binds.

    Added in #144 CR round 3 because the helper shipped untested, and its
    `None` branch is load-bearing: a bare `or doc_budget` there would silently
    re-impose the 10,000 default on the one file the exemption exists for, and
    every test in this module would stay green while the gate did the opposite
    of what its comment claims.
    """

    def test_none_exempts(self):
        doc = {"path": "x/y.md", "tokens": 10_000_000}
        assert _doc_over(doc, 10_000) is True, "sanity: no exemption binds it"
        exempt = dict(DOC_BUDGET_EXCEPTIONS)
        try:
            DOC_BUDGET_EXCEPTIONS["x/y.md"] = None
            assert _doc_over(doc, 10_000) is False, (
                "a None entry must exempt the file, not fall through to the "
                "default budget"
            )
        finally:
            DOC_BUDGET_EXCEPTIONS.clear()
            DOC_BUDGET_EXCEPTIONS.update(exempt)

    def test_a_numeric_entry_still_binds(self):
        exempt = dict(DOC_BUDGET_EXCEPTIONS)
        try:
            DOC_BUDGET_EXCEPTIONS["x/y.md"] = 500
            assert _doc_over({"path": "x/y.md", "tokens": 501}, 10_000) is True
            assert _doc_over({"path": "x/y.md", "tokens": 500}, 10_000) is False
        finally:
            DOC_BUDGET_EXCEPTIONS.clear()
            DOC_BUDGET_EXCEPTIONS.update(exempt)

    def test_an_unlisted_doc_gets_the_default_budget(self):
        assert _doc_over({"path": "not/listed.md", "tokens": 10_001}, 10_000) is True
        assert _doc_over({"path": "not/listed.md", "tokens": 10_000}, 10_000) is False

    def test_a_doc_the_policy_band_clears_is_not_called_stale(self):
        """#159. The staleness guard must discount by the DOC population's error.

        A doc reading 8,500 tokens offline clears a 10,000 ceiling discounted by
        the SKILL.md band's -15%, so today's guard reports its exception stale
        and tells a maintainer to delete it. But a reference doc's estimate runs
        as much as 24% low on this library, so 8,500 estimated can be over
        11,000 exactly — the exception is doing its job and deleting it would
        put the doc over budget in silence.
        """
        exempt = dict(DOC_BUDGET_EXCEPTIONS)
        try:
            DOC_BUDGET_EXCEPTIONS["x/y.md"] = 10_000
            assert _stale_doc_exceptions({"x/y.md": 8_500}, 10_000) == [], (
                "the doc staleness guard is discounting by the SKILL.md band, "
                "not the wider band reference docs actually estimate within"
            )
        finally:
            DOC_BUDGET_EXCEPTIONS.clear()
            DOC_BUDGET_EXCEPTIONS.update(exempt)

    def test_a_doc_no_band_could_excuse_is_still_called_stale(self):
        """The guard still has to fire, or widening it has disabled it."""
        exempt = dict(DOC_BUDGET_EXCEPTIONS)
        try:
            DOC_BUDGET_EXCEPTIONS["x/y.md"] = 10_000
            assert _stale_doc_exceptions({"x/y.md": 5_000}, 10_000) == ["x/y.md"]
        finally:
            DOC_BUDGET_EXCEPTIONS.clear()
            DOC_BUDGET_EXCEPTIONS.update(exempt)

    def test_the_exemption_is_scoped_to_the_named_path(self):
        """The exemption must not leak to a sibling in the same directory."""
        exempt = dict(DOC_BUDGET_EXCEPTIONS)
        try:
            DOC_BUDGET_EXCEPTIONS["a/exempt.md"] = None
            assert _doc_over({"path": "a/other.md", "tokens": 10_001}, 10_000) is True
        finally:
            DOC_BUDGET_EXCEPTIONS.clear()
            DOC_BUDGET_EXCEPTIONS.update(exempt)


@pytest.mark.parametrize("skill", SKILLS)
class TestEverySkillsOwnSurface:
    """#141: every skill held to the budget `curating-context` enforces."""

    def test_skill_md_is_within_its_ratchet(self, skill: str, surfaces: dict):
        policy = surfaces[skill]["policy"]
        ratchet = ratchet_for(skill)
        named = skill in SKILL_MD_RATCHETS
        assert policy["tokens"] <= ratchet, (
            f"skills/{skill}/SKILL.md is ~{policy['tokens']:,} tokens against "
            f"its {ratchet:,}-token "
            + ("ratchet" if named else "standard")
            + f" ({policy['tokens'] - ratchet:,} over).\n\n"
            "Demote a section to references/ rather than deleting it, and "
            "prove it with:\n"
            "  bash skills/curating-context/scripts/prove-no-loss.sh --base "
            f"<branch-point> --file skills/{skill}/SKILL.md "
            f"--docs-dir skills/{skill}/references\n\n"
            + (
                "Raising this skill's entry in SKILL_MD_RATCHETS is not the "
                "fix. It is a ratchet: it only ever comes down.\n\n"
                if named else
                "Adding an entry to SKILL_MD_RATCHETS is a last resort, not "
                "the first move: an exception has to argue in the diff why "
                "this skill cannot meet the standard the other seventeen "
                "do.\n\n"
            )
            + estimate_caveat(skill, policy["tokens"])
        )

    def test_skill_md_names_its_own_ratchet(self, skill: str):
        """A ratchet nobody can loosen by editing one integer.

        SKILL.md states the figure in prose for the run that reads it; the test
        enforces it. If the two ever disagree, the file is lying to the agent
        following it, which is the specific failure `curating-context` exists
        to prevent.
        """
        # Whitespace-normalised: prose wraps at 80 columns and a ratchet that
        # only counts when the phrase happens to fit on one line is a gate on
        # line width, not on the sentence.
        body = " ".join((SKILLS_DIR / skill / "SKILL.md").read_text().split())
        assert ratchet_phrase(skill) in body, (
            f"skills/{skill}/SKILL.md does not contain the phrase "
            f'"{ratchet_phrase(skill)}", so a run has no way to know what it '
            "is working against — or by which method it is measured."
        )

    def test_an_exception_names_the_standard_it_misses(self, skill: str):
        """An exception argues for itself where the reader is, not only here.

        A skill whose prose names 17,100 and stops there reads like a budget.
        Naming the 6,000 it is failing is what keeps the gap a finding rather
        than the status quo.
        """
        if skill not in SKILL_MD_RATCHETS:
            pytest.skip("conforms to the standard; nothing to justify")
        body = (SKILLS_DIR / skill / "SKILL.md").read_text()
        assert f"{SKILL_MD_STANDARD:,}" in body, (
            f"skills/{skill}/SKILL.md carries a ratchet above the "
            f"{SKILL_MD_STANDARD:,}-token standard without naming the "
            "standard, so the gap it is carrying goes unrecorded where anyone "
            "reads it"
        )

    def test_every_reference_doc_is_within_the_per_doc_budget(
        self, skill: str, surfaces: dict
    ):
        doc_budget = int(DOC_BUDGET_KNOB.read_text().strip())
        over = [
            d for d in surfaces[skill]["docs"]
            if _doc_over(d, doc_budget)
        ]
        assert not over, (
            f"skills/{skill} reference docs over the {doc_budget:,}-token "
            "per-doc budget:\n"
            + "\n".join(f"  {d['path']} ~{d['tokens']:,}" for d in over)
            + "\n\nPast the per-doc budget, loading the doc stops costing less "
            "than carrying it inline — split it on its top-level headings. A "
            "demotion into an already-full doc moves the problem instead of "
            "solving it.\n\n"
            + estimate_caveat(skill)
        )


class TestTheContractMeasuredExactly:
    """The ratchets against count_tokens — the quantity they actually name.

    Skipped, never silently passed, when no credential answers. The offline
    tests above still ran; this is the difference between them and the truth.
    """

    @pytest.mark.parametrize("skill", SKILLS)
    def test_skill_md_is_within_its_ratchet(
        self, skill: str, exact_surfaces: dict
    ):
        policy = exact_surfaces[skill]["policy"]
        ratchet = ratchet_for(skill)
        assert policy["tokens_exact"] is True, (
            f"the exact run fell back to the estimate for {skill}; a partial "
            "count cannot enforce an exact contract"
        )
        assert policy["tokens"] <= ratchet, (
            f"skills/{skill}/SKILL.md is {policy['tokens']:,} EXACT tokens "
            f"against its {ratchet:,}-token ratchet "
            f"({policy['tokens'] - ratchet:,} over).\n\n"
            "The offline gate may well be green: the estimator runs up to 13% "
            "low on this library. The ratchet binds both readings, so this one "
            "failing is enough."
        )

    @pytest.mark.parametrize("skill", SKILLS)
    def test_every_reference_doc_is_within_the_per_doc_budget(
        self, skill: str, exact_surfaces: dict
    ):
        """The per-doc budget binds both readings too.

        The estimator's largest errors in this repo are on reference docs, not
        on SKILL.md — up to -23.9% — so a doc gate that only ever saw the
        estimate would have the widest blind spot in the file.
        """
        doc_budget = int(DOC_BUDGET_KNOB.read_text().strip())
        over = [
            d for d in exact_surfaces[skill]["docs"]
            if _doc_over(d, doc_budget)
        ]
        assert not over, (
            f"skills/{skill} reference docs over the {doc_budget:,}-token "
            "per-doc budget by EXACT count:\n"
            + "\n".join(f"  {d['path']} {d['tokens']:,}" for d in over)
        )

    @pytest.mark.parametrize("skill", SKILLS)
    def test_the_offline_estimate_tracks_the_exact_count(
        self, skill: str, surfaces: dict, exact_surfaces: dict
    ):
        """Pin the divergence the always-on gate is blind to.

        Batch A of #144 found the estimator and count_tokens straddling
        `curating-context`'s ratchet — green offline, over in fact. That is
        tolerable only while the size of the gap is known and watched. This
        test is what makes it watched.
        """
        est = surfaces[skill]["policy"]["tokens"]
        exact = exact_surfaces[skill]["policy"]["tokens"]
        drift = (est - exact) / exact
        low, high = POLICY_ESTIMATE_BAND
        assert low <= drift <= high, (
            f"skills/{skill}/SKILL.md: offline estimate {est:,} vs exact "
            f"{exact:,} is {drift:+.1%}, outside the pinned "
            f"{low:+.0%}..{high:+.0%} band.\n\n"
            "Below the band means the always-on gate is passing files that are "
            "over — recalibrate .skills/context-token-ratio (currently "
            f"{RATIO_KNOB.read_text().strip()} bytes/token) against this "
            "library rather than widening POLICY_ESTIMATE_BAND. Above it only "
            "wastes headroom, but is the same calibration drift."
        )

    @pytest.mark.parametrize("skill", SKILLS)
    def test_the_offline_estimate_tracks_the_exact_count_for_docs(
        self, skill: str, surfaces: dict, exact_surfaces: dict
    ):
        """#159: the same pin, for the population it was never applied to.

        The band was asserted only against the eighteen SKILL.md files, while
        the module docstring claimed it pinned the estimator generally. The
        reference docs are the larger population (sixty-nine of the surface's
        eighty-seven files) AND carry the wider error, so the widest divergence
        in the repo sat outside the only assertion that would have flagged it.

        A doc row is checked against DOC_ESTIMATE_BAND, not the policy band. The
        two are separate constants because the measured populations do not
        overlap enough for one to describe both, and collapsing them would mean
        either failing four docs that are behaving normally or loosening the
        SKILL.md band by 15 points to accommodate them.
        """
        exact_rows = {
            d["path"]: d["tokens"] for d in exact_surfaces[skill]["docs"]
        }
        low, high = DOC_ESTIMATE_BAND
        outside = []
        for d in surfaces[skill]["docs"]:
            exact = exact_rows[d["path"]]
            drift = (d["tokens"] - exact) / exact
            if not low <= drift <= high:
                outside.append((d["path"], d["tokens"], exact, drift))
        assert not outside, (
            f"skills/{skill} reference docs outside the pinned "
            f"{low:+.0%}..{high:+.0%} DOC band:\n"
            + "\n".join(
                f"  {p} estimate {e:,} vs exact {x:,} is {dr:+.1%}"
                for p, e, x, dr in outside
            )
            + "\n\nBelow the band means the always-on gate is pricing this doc "
            "well under what a run actually loads. Recalibrate "
            ".skills/context-token-ratio (currently "
            f"{RATIO_KNOB.read_text().strip()} bytes/token), or give the file "
            "its own anchor in .skills/context-token-counts, rather than "
            "widening DOC_ESTIMATE_BAND — this band is already 6-7 points wider "
            "than the measured spread it was set from."
        )


class TestCuratingContextsExtraProcedure:
    """Rules that belong to `curating-context` alone, not to the library.

    The +250-per-round edit budget is this skill's own self-curation rule — the
    textual learning rate that keeps a self-improving skill from walking up to
    its ceiling one plausible addition at a time. It is asserted here because
    #95 put it here; it is NOT generalised to the other seventeen, which do not
    rewrite themselves and would gain eighteen copies of a rule that governs
    one.
    """

    SKILL_MD = SKILLS_DIR / "curating-context" / "SKILL.md"

    def test_skill_md_states_the_per_round_cap(self):
        body = self.SKILL_MD.read_text()
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
        body = self.SKILL_MD.read_text().lower()
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
        body = self.SKILL_MD.read_text().lower()
        window = body[body.index("edit budget"):]
        assert "demote" in window or "tighten" in window, (
            "the edit budget states a cap but not the move it forces — a run "
            "that hits it needs to be told to displace something, not to stop"
        )

    def test_the_gap_to_the_enforced_budget_is_still_named(self):
        """The skill must not quietly forget that 6,000 is the real target.

        A ratchet above the enforced budget is only honest while the file says
        so. Silently normalising 7,600 as "the budget" is how the gap stops
        being a finding and starts being the status quo.
        """
        repo_budget = int(BUDGET_KNOB.read_text().strip())
        assert repo_budget < SKILL_MD_RATCHETS["curating-context"], (
            "the ratchet is no longer above the budget the skill enforces — "
            "delete this test and the prose that goes with it"
        )
        assert str(repo_budget) in self.SKILL_MD.read_text(), (
            f"SKILL.md no longer names the {repo_budget:,} it enforces on every "
            "repo's AGENTS.md, so the gap it is carrying has gone unrecorded"
        )


class TestTheOfflineFailureQuotesANumber:
    """#190: the offline gate must hand over a figure, not only a caveat.

    `init-project-fastapi` sat 43 exact tokens under a 17,100 ratchet while the
    offline reading showed 2,327 of headroom. The same blind spot had already put
    `init-socraticode` 186 exact tokens over its ratchet on a green suite, a
    passed pre-commit hook, and a completed code review — because none of those
    gates measures the reading the ratchet binds, and the estimate is the only
    number anyone is shown.

    #190 proposed printing the exact margin in the offline failure. That cannot
    be built as proposed: `.skills/context-token-counts` anchors four paths —
    `AGENTS.md` and three under `docs/` — and no `skills/*/SKILL.md` among them,
    so `ctx_est_tokens_for` has no per-file anchor to fall back on and there is
    no exact figure available offline to print. That absence is also *why* the
    estimator runs ~12-13% low on this file with no correction available.

    `POLICY_ESTIMATE_BAND` is what does exist offline. An estimate plus the
    band's permissive edge is a worst case, and a worst case measured against the
    ratchet is the quotable number the proposal was after — at no API call.
    """

    SKILL = "init-project-fastapi"

    def test_the_worst_case_inverts_the_band_rather_than_adding_it(self):
        """The band bounds the estimator's error, so solve for the truth.

        The estimate is `exact * (1 + err)` for some `err` in the band, so the
        largest exact reading the band still permits is `estimate / (1 + low)`.
        Multiplying by `(1 + high)` would answer a different question — how high
        the ESTIMATE could read for a known exact — and understates the worst
        case at every input, which is the one direction this number must not err.
        """
        low, high = POLICY_ESTIMATE_BAND
        # The figure #190 was filed over: 14,773 estimated, 17,057 exact.
        assert worst_case_exact(14_773) == round(14_773 / (1 + low)) == 17_380
        assert worst_case_exact(14_773) > round(14_773 * (1 + high))

    def test_the_failure_quotes_the_estimate_the_worst_case_and_the_ratchet(self):
        """All three, because any two of them leave the reader doing arithmetic."""
        estimate = 12_942
        message = estimate_caveat(self.SKILL, estimate)
        for figure in (
            f"{estimate:,}",
            f"{worst_case_exact(estimate):,}",
            f"{ratchet_for(self.SKILL):,}",
        ):
            assert figure in message, (
                f"the offline failure never quotes {figure}, so a reader still "
                "has to run the credential-gated command to learn where they are"
            )

    def test_a_worst_case_over_the_ratchet_says_the_file_may_be_over(self):
        """The whole point: an estimate that looks green while the file is red."""
        ratchet = ratchet_for(self.SKILL)
        estimate = round(ratchet * (1 + POLICY_ESTIMATE_BAND[0])) + 100
        assert estimate < ratchet, "the estimate must still read green offline"
        assert worst_case_exact(estimate) > ratchet
        assert "may already be over" in estimate_caveat(self.SKILL, estimate)

    def test_a_worst_case_under_the_ratchet_does_not_cry_wolf(self):
        """A warning on every failure is a warning nobody reads."""
        ratchet = ratchet_for(self.SKILL)
        estimate = round(ratchet * (1 + POLICY_ESTIMATE_BAND[0])) - 100
        assert worst_case_exact(estimate) <= ratchet
        assert "may already be over" not in estimate_caveat(self.SKILL, estimate)

    def test_the_caveat_still_serves_a_caller_with_no_policy_estimate(self):
        """The per-doc failure has no policy estimate, and must not borrow one.

        `test_every_reference_doc_is_within_the_per_doc_budget` fails about doc
        rows, which `DOC_ESTIMATE_BAND` describes and `POLICY_ESTIMATE_BAND` does
        not. Quoting a SKILL.md worst case there would be a number about the
        wrong population, so that call site passes no estimate and gets the prose
        caveat alone.
        """
        message = estimate_caveat(self.SKILL)
        assert "worst case" not in message
        assert "OFFLINE ESTIMATE" in message
        assert exact_cmd(self.SKILL) in message
