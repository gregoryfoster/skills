# Skill-selection surface: prioritized backlog clearance (#240–#244)

## Goal

Close the five open issues carved out of #97's competitive-selection investigation
plus one lint straggler from #239's CR. Four are small, verified-mechanical edits to
the skill-selection surface and the test suite that measures it; the fifth (#242)
promotes the ad-hoc probe that actually answered #97's question into a real
integration test, so the shadowing property the current routing test is structurally
incapable of observing becomes something the suite states.

## Approved approach

- Rubric weights equal: **(Foundation ×2) + (Correctness ×2) + Scope, max 15** —
  inherited from `2026-08-27-skills-audit-and-hardening-backlog.md`, same repo,
  same day.
- Deployment context: **early production** — this repo is the vendor source for a
  12-repo cohort; changes propagate passively via daily submodule refresh.
- Nothing deferred. All five issues are scheduled.
- Parallelism: **hybrid** — parallel within batches, gates between, every worker in
  an `isolation: "worktree"` worktree.
- Concurrency ceiling: **none**. Plain `git worktree`; the structural suite is
  hermetic (no DB, no ports, no shared service). The effective cap is host CPU/RAM.
  The integration suite hits the live Anthropic API, but it is opt-in
  (`-m integration` + `ANTHROPIC_API_KEY`) and stateless — concurrent runs do not
  corrupt each other.
- Batch→main merge strategy: **regular merge commit** (per-agent history preserved).
  Intra-batch worker→`batch/a` integration is FF/regular-merge, never squash or
  rebase.

**Baseline test count (Rule 3).** On `main` **after this plan's own commit**:

```
.venv/bin/python -m pytest tests/structural/ -q
→ 3411 passed, 158 skipped
```

Measured at `d710691` it was **3407**. The Step 10 process-log entry committed
alongside this plan adds four parametrized tests, because `test_relative_links.py`
parametrizes over `SKILLS_DIR.rglob("*.md")` and the journal lives inside the skill
tree it describes. Briefing 3407 would have had every worker stop and report a
mismatch the orchestrator created. This is the 2026-08-21 lesson firing again —
**measure the baseline after committing the plan and its journal, not before.**

Every worker prompt carries this number **and the interpreter that produces it** —
`.venv/bin/python`, not bare `python`, which fails collection on six modules with
`ModuleNotFoundError: No module named 'frontmatter'`. A worker whose tree reports a
different count has been cut from the wrong base; it must stop and report rather than
reconcile to it. Each worker also reports its own final count, so the batch gate's
arithmetic can be checked against the sum rather than against four independent
"green" verdicts.

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation is obvious from the issue |

Score = (F×2) + (C×2) + S. Blast drives sequencing, not score.

## Scored backlog

| # | Issue | F | C | S | Score | Blast |
|---|---|---|---|---|---|---|
| 242 | Promote #97's competitive-selection probe into `tests/integration` | 3 | 3 | 1 | **13** | Low |
| 240 | Baseline variants' fallback role is invisible to the selection surface | 2 | 2 | 3 | **11** | Low |
| 243 | `_CONTEXT_DEPENDENT_TRIGGERS` keys on exact dir name → 2 spurious failures | 2 | 2 | 3 | **11** | Low |
| 241 | Click/FastAPI variant descriptions compete on a single token | 2 | 2 | 3 | **9** | Low |
| 244 | `measure-context.sh`: two SC2034 unused-variable warnings | 1 | 1 | 3 | **7** | Low |

Scoring notes:

- **#242 Foundation 3** — none of the other four issues *depend* on it, but every
  future variant landing does. AGENTS.md documents adding a stack variant as a
  routine operation (`cp -r skills/reviewing-code skills/reviewing-code-<suffix>`),
  and #97 established that the existing routing test cannot observe whether the new
  variant shadows anything. #242 is the instrument that makes that class of defect
  visible at all.
- **#242 Correctness 3** — the literal "silent failures" category. The existing
  `test_trigger_routing.py` injects one skill at a time; it passes, and its passing
  is consistent with total shadowing. A green suite that verifies nothing is the
  failure mode, not a red one.
- **#241 Correctness 2** — the issue calls itself prophylactic (selection held 72/72
  in the probe), so no defect has been observed. Scored 2 rather than 1 because the
  rubric's second tier names *runtime failure risk*, and a 0.94-similarity pair with
  a single differentiating token in a growing library is exactly that.
- **#243 Foundation 2** — #242 adds its test to the same `tests/integration/`
  directory. A suite with a standing 2-failed baseline degrades the signal from the
  new disambiguation test, so fixing the spurious failures first is worth a point.

### Rescope: #244

The issue offers two branches — delete the assignments as dead, or keep them with a
`# shellcheck disable=SC2034` naming the reason. **The grep settles it: keep-and-
document.** Both variables are read by the sourced library, so deleting either would
break the script:

- `CTX_ARCHIVAL` — consumed by `_context-lib.sh:499` (`for name in $CTX_ARCHIVAL`)
- `CTX_BPT_X100` — consumed by `_context-lib.sh:307` (`$1 * 100 / CTX_BPT_X100`)

Shellcheck reports them unused because it does not follow the `source` into the
library. The same assignment pattern already appears in `context-budget-guard.sh:228`
and `context-delta.sh:109`, confirming it is the library's deliberate calling
convention (documented at `_context-lib.sh:52,67,79`), not an accident in one script.
This resolves the issue's own open question before a worker has to guess at it, and
raises its Scope Clarity to 3. **Written back to the issue** per Step 4.

## Conflict zones

**None.** Every issue's file footprint is disjoint from every other's, verified by
grep rather than inferred from the bodies:

| Issue | Files |
|---|---|
| 240 | `skills/reviewing-code/SKILL.md`, `skills/shipping-work/SKILL.md` (`description:` line only) |
| 241 | `skills/{reviewing-code,shipping-work}-python-{click,fastapi}/SKILL.md` (`description:` line only) |
| 242 | new file under `tests/integration/`; reads all `SKILL.md` descriptions |
| 243 | `tests/integration/test_trigger_routing.py` |
| 244 | `skills/curating-context/scripts/measure-context.sh` |

#240 and #241 both edit `description:` lines but in **six disjoint files** — the two
baselines vs. the four stack variants. #242 and #243 are both in
`tests/integration/`, but #242 adds a new file and #243 modifies an existing one.

### Test-surface grep (the modify half)

Grepping the test tree for the literal strings #240/#241 rewrite:

- `tests/structural/test_content_invariants.py:1022,1089` match `"Pydantic v2 idioms"`
  — but they assert against the **SKILL body's Phase 2 dimension list**, not the
  frontmatter description parenthetical. #241 does not touch them.
- `TestVariantFamilyConsistency` (`:1554–1575`) is the real guard on this surface.
  Three of its four assertions constrain what #240/#241 may do:
  - `test_description_differs_from_baseline` — variant ≠ baseline. Both issues
    *increase* the distance, so it stays green.
  - `test_compatibility_mentions_stack` — checks the **`compatibility` field**, not
    the description. #241's parenthetical rewrite is unconstrained by it.
  - `test_triggers_match_baseline` — variant triggers must equal baseline triggers.
    **Neither issue may touch `metadata.triggers`.** #240 adds a sentence to the
    baseline `description:`; if a worker also edited baseline triggers, all four
    variants would go red.
- `test_schema.py:36` caps descriptions at 1024 chars. Current longest is well under;
  #240 adds roughly one sentence to two of them.

No assertion is *invalidated* by either issue, and none is made *vacuous* — the
guards compare descriptions to each other rather than to frozen literals, so they
keep verifying after the rewrite.

### Fixture-escape grep

Not applicable — no shared backing service sets a ceiling here (see Approved
approach). The structural suite touches no database, port, or external process.

## Dependency graph

```
  #244 ──────────────── (isolated; no relation to any other issue)
  #243 ──────────────── (isolated by file; feeds #242 a clean suite)
                                                    │
  #240 ┐                                            │
       ├── (A1 bundle) ────────────────────────────►├──► #242
  #241 ┘                                            │
```

One edge, and **no file overlap can show it**: #242 asserts *baseline fallback for
uncovered stacks*, which is red until #240 ships the fallback clause. #242's own body
states the ordering ("the second half is red until #240 ships, which is the right
order"). #241 joins the same gate because #242's per-family determinism assertions
read the parentheticals #241 rewrites — writing the test against the pre-#241
descriptions would pin the thing #241 is about to change.

#243's edge into #242 is softer: not a correctness dependency, just a clean baseline
for the suite #242 extends. It is satisfied by the same batch boundary at no extra
cost.

## Batch execution plan

| Batch | Agent | Issues | Files | Gate |
|---|---|---|---|---|
| A | A1 | #240 → #241 (bundle, sequential commits) | 6 × `SKILL.md` `description:` lines | Start immediately |
| A | A2 | #243 | `tests/integration/test_trigger_routing.py` | Start immediately |
| A | A3 | #244 | `skills/curating-context/scripts/measure-context.sh` | Start immediately |
| B | B1 | #242 | new `tests/integration/` file | After A merged to `main` |

Three parallel agents in Batch A, one in Batch B. No intra-batch merge ordering
constraint — all three Batch A branches are file-disjoint and merge into `batch/a` in
any order.

## Key decisions

**#240 + #241 bundled as Shape A (one agent, sequential commits).** Both are
single-line edits to the same *kind* of surface (skill `description:` frontmatter),
both are define-the-selection-signal work, and together they total roughly six edited
lines — far inside the ≈500-line single-review-sitting threshold. They are in
disjoint files, so two agents were possible, but splitting six lines across two
review surfaces is ceremony. The commits stay separate so each issue's rationale is
independently readable.

**Batch boundary before #242 is a design-coherence gate, not a file conflict.** The
file sets are verified disjoint; the gate exists because #242's assertions describe
the selection surface that #240/#241 are changing. Writing the test first would
either pin the old descriptions or require the same agent to write both — which is
the split this boundary buys.

**Verification-mode asymmetry — Batch A cannot verify its own change.** The
integration suite is opt-in (`-m integration`, needs `ANTHROPIC_API_KEY`); it is
skipped in a default run. So A1 edits the live skill-selection surface and verifies
only against the *structural* suite, which checks description shape, not description
*behaviour*. **Nothing in Batch A measures whether #240 actually fixes Haiku's Go
fallback or whether #241 actually widens the Click/FastAPI margin.** #242 is that
measurement, and it runs a batch later. Do not read Batch A's green suite as
confirmation the selection defect is fixed — it confirms only that the descriptions
are well-formed. B1's brief must include running the new test with a real key.

**The six `description:` lines are read-only for Batch B.** #242 asserts *against*
them. If B1 finds its test failing, the correct move is to report the finding, not to
edit a description until the test passes — that would make the test measure B1's edit
instead of #240/#241's. Route any genuinely needed description change as a small
post-merge PR after Batch B lands.

**No chain-appending artifact in this backlog.** No migrations, no numbered ADRs, no
generated-artifact sync test in any of the five footprints. The one-chain-agent-per-
batch rule has nothing to bind here.

**#244's `--no-verify` question.** The red-phase commit for a shellcheck-only fix has
no natural red phase (there is no behaviour to pin). A3 should treat this as the
documented exception: one commit, with the reasoning for the `disable` directive in
the commit body, and a shellcheck run as the verification.

## Runtime note on issue-body decay

This backlog is four sequential mutations of what the bodies describe. Two specific
decay risks:

1. **#242's body was written before #240/#241 shipped.** By the time B1 reads it, the
   descriptions it describes as needing a fallback clause will already have one. Its
   phrase "the second half is red until #240 ships" will be stale in exactly the way
   that matters: the second half should be **green** when B1 runs it. If it is still
   red, that is a real finding about #240's fix, not a reason to weaken the assertion.
2. **#243's cited failure count (2 failed / 1 xpassed) is from #97's investigation
   run**, not from current `main`. A2 must re-run and report the actual count rather
   than reconciling to the body's number.

Per Worker step 5: treat every body as a proposal. Across the 2026-08-09 13-issue
backlog the implementing agent found a material error in the body **every single
time**, and three would have shipped a defect as written. Report corrections; do not
implement around them silently.

## Deferred items

None. All five issues in the user-named range #240–#244 are scheduled.

## Out of scope

- **#144 / the SocratiCode graph-yield issue** appeared in the open-issue listing but
  sits outside the named #240–#244 range, and is explicitly blocked on upstream
  SocratiCode PR #112 merging and shipping in a release. Not scheduled here.
- **Re-running #97's full 72-trial probe as a one-off.** #242's deliverable is the
  promoted, repeatable test; reproducing the original ad-hoc measurement is not part
  of it.
- **Adding new stack variants.** #241 differentiates the four that exist; growing the
  family is separate work that #242's test is designed to keep honest.
