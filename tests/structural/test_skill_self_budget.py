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
- **Always-on offline, opportunistically exact.** Pre-commit has no
  `ANTHROPIC_API_KEY`, so the always-on tests read the skill's calibrated
  offline estimate (`.skills/context-token-ratio`, 2.65 bytes/token). A gate
  that only fails when someone happens to hold a key is not a gate — but an
  estimate is not the contract either, so `TestTheContractMeasuredExactly`
  re-runs the same ratchets against `count_tokens` whenever a credential is
  available, and skips when one is not. See "Which number is the contract"
  below.
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
the library: **the estimator runs LOW on 11 of 18 `SKILL.md` files**, by as much
as **-12.4%** on `init-project-fastapi` (14,940 estimated vs 17,057 exact), and
by as much as -23.0% on a single reference doc
(`init-project-fastapi/references/postgres-provisioning.md`, 1,225 vs 1,591).
The cause is visible in the per-file `bytes_per_token`, which ranges 2.32
(`init-project-fastapi`) to 2.84 (`orchestrating-issue-backlog`) against the
single global 2.65 the estimator assumes: code-and-path-dense files tokenize
denser than the prose the ratio was calibrated on. Low is the permissive
direction, so the error #95 believed was impossible is the common case.

The ruling, and the three questions Batch A raised:

1. **Neither number alone is the contract. The ratchet binds both.** One
   integer per skill, and a skill passes only if the offline estimate is under
   it *and* `count_tokens` is under it — so the effective bound is always the
   stricter of the two readings, and no one can loosen a ratchet by choosing a
   measurement. "Exact is the contract" was tried first and is wrong: it fails
   `orchestrating-issue-backlog`, whose estimate runs 1,532 tokens HIGH, in the
   only gate that actually runs. "Estimate is the contract" is worse: it is a
   number that does not describe what a run loads, and it would let
   `init-project-fastapi` carry 2,117 unbudgeted real tokens. Binding both costs
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
3. **The divergence is pinned.** `ESTIMATE_BAND` records how far the estimator
   may stray from `count_tokens` before someone has to look. It fails if the
   ratio knob drifts out of calibration, or if a skill's content mix moves far
   enough that the two readings pull apart — turning an invisible hazard into a
   maintained number. It is also the reason `SKILL_MD_RATCHETS` can carry one
   integer instead of two: the gap between the readings is bounded and watched.

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
    # tokenizes at 2.32 bytes/token — the densest file in the repo. See the
    # outlier note below. Bound by its EXACT count; its estimate reads 2,117
    # lower, the worst calibration gap in the repo.
    "init-project-fastapi": 17_100,
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
    # outlier note below. Bound by its ESTIMATE, which reads 1,532 higher than
    # count_tokens — the reason this file learned that "exact is the contract"
    # does not survive contact with the gate that actually runs.
    "orchestrating-issue-backlog": 22_900,
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

# Reference docs are held to the repo's 10,000-token per-doc knob, with one
# named exception, on the same shared-standard-plus-exceptions model.
DOC_BUDGET_EXCEPTIONS = {
    # An append-only session ledger with an index table at the top, not a
    # document anyone loads whole: a run reads the index, then the one entry it
    # needs, then appends. The per-doc budget exists because past it, loading a
    # doc stops costing less than carrying it inline — a premise that does not
    # describe a ledger.
    #
    # UNBOUNDED, and deliberately so. A numeric ratchet was tried first and was
    # wrong within the hour: it was set at 60,750 against a measured 60,748, and
    # a concurrent session appended one entry and pushed it to 61,280 — red on
    # `main`, from a session that did nothing but journal correctly. A ratchet
    # says "this may not grow"; an append-only ledger's whole contract is that
    # it grows. Holding both means every future journaling session must also
    # trim the ledger to afford its own entry, which inverts the point of
    # keeping one, and the only way to stay green is to raise the integer each
    # time — which is exactly the loosening-by-editing a ratchet exists to stop.
    #
    # So the honest state is recorded rather than a number nobody can hold: this
    # file is exempt, the exemption is visible here, and the real fix is content
    # work (split by year, or truncate behind a summary) tracked separately.
    # `None` means exempt; every other entry is a hard ceiling.
    "skills/orchestrating-issue-backlog/references/process-log.md": None,
}


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
# look. Measured across all eighteen SKILL.md files on 2026-08-13: the estimator
# ran from -12.4% (init-project-fastapi, the permissive direction and the one
# that matters) to +7.2% (orchestrating-issue-backlog, reviewing-architecture).
# Widening this band is not a fix — it is the record of a blind spot getting
# bigger, and the reason to recalibrate `.skills/context-token-ratio` instead.
ESTIMATE_BAND = (-0.15, 0.15)


def ratchet_for(skill: str) -> int:
    return SKILL_MD_RATCHETS.get(skill, SKILL_MD_STANDARD)


def ratchet_phrase(skill: str) -> str:
    """The exact string a SKILL.md must contain to name its own budget.

    Naming the METHOD alongside the figure is not decoration: the always-on gate
    reads an estimate and the credential-gated one reads count_tokens, so prose
    that said "6,000 tokens" and stopped would leave a reader unable to tell
    which of two numbers, up to 12% apart, it meant.
    """
    return f"{ratchet_for(skill):,}-token ratchet (estimate and exact)"


def exact_cmd(skill: str) -> str:
    return (
        "bash skills/curating-context/scripts/measure-context.sh --exact "
        f"--no-write --file skills/{skill}/SKILL.md "
        f"--docs-dir skills/{skill}/references"
    )


def estimate_caveat(skill: str) -> str:
    return (
        "This is the calibrated OFFLINE ESTIMATE at "
        f"{RATIO_KNOB.name} bytes/token, not an exact count — pre-commit has "
        "no ANTHROPIC_API_KEY. Across this library it runs anywhere from 12% "
        "low to 7% high, and the ratchet binds BOTH readings — so clearing "
        "this one is necessary, not sufficient. The other:\n  "
        + exact_cmd(skill)
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


@pytest.fixture(scope="module")
def exact_surfaces() -> dict:
    """Every skill's surface, measured by count_tokens. ~20s, needs a key."""
    if not _has_credential():
        pytest.skip(
            "no credential count_tokens accepts; the offline gate still ran. "
            "Load one with `set -a && source .env && set +a`."
        )
    return {name: _measure(name, exact=True) for name in SKILLS}


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
        unambiguous = SKILL_MD_STANDARD * (1 + ESTIMATE_BAND[0])
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
            + estimate_caveat(skill)
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
            "The offline gate may well be green: the estimator runs up to 12% "
            "low on this library. The ratchet binds both readings, so this one "
            "failing is enough."
        )

    @pytest.mark.parametrize("skill", SKILLS)
    def test_every_reference_doc_is_within_the_per_doc_budget(
        self, skill: str, exact_surfaces: dict
    ):
        """The per-doc budget binds both readings too.

        The estimator's largest errors in this repo are on reference docs, not
        on SKILL.md — up to -23% — so a doc gate that only ever saw the
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
        low, high = ESTIMATE_BAND
        assert low <= drift <= high, (
            f"skills/{skill}/SKILL.md: offline estimate {est:,} vs exact "
            f"{exact:,} is {drift:+.1%}, outside the pinned "
            f"{low:+.0%}..{high:+.0%} band.\n\n"
            "Below the band means the always-on gate is passing files that are "
            "over — recalibrate .skills/context-token-ratio (currently "
            f"{RATIO_KNOB.read_text().strip()} bytes/token) against this "
            "library rather than widening ESTIMATE_BAND. Above it only wastes "
            "headroom, but is the same calibration drift."
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
