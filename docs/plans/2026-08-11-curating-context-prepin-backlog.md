# curating-context: round-1/2 feedback fixes before the cohort re-pins

**Date:** 2026-08-11
**Tracking:** [#135](https://github.com/gregoryfoster/skills/issues/135)
**Scope:** [#134](https://github.com/gregoryfoster/skills/issues/134) Groups A/B/C, plus #100, #108, #90
**Issues:** 15 (14 work items)
**Batches:** 3 — A (7 parallel), B (1), C (2 parallel)

## Goal

Land every measurement, install-wiring and self-surface fix that `curating-context`
has accumulated from wave-A/B adoption feedback, **before** twelve cohort repos
re-pin their `skills-vendor/gregoryfoster-skills` submodule for the cadence
rollout. The sequencing argument is [#134](https://github.com/gregoryfoster/skills/issues/134)'s
and it is the whole reason this is one bundle rather than twelve trickled
adoptions: every cohort pin currently predates the cadence, so adoption issues
filed today are unactionable until each pin moves — and the pin then moves to
whatever is latest at that moment. Doing the fixes first means the cohort
re-pins **once**, onto a version that already has them.

## Approved approach

Hybrid parallelism: a wide first batch of file-disjoint fix agents, then two
gated batches for the work that must observe the first batch's final state.

- **Deployment context:** early production. Twelve repos carry committed pins and
  `skills-submodule-update.sh` auto-commits a pin bump once per UTC day on
  `SessionStart` — but no repo has the cadence workflow installed, so the new
  flags and scripts are inert. Propagation is passive and currently harmless.
  This justifies wide batches and few gates.
- **Worktree provisioning ceiling: none binding.** No `dev.sh`, no port pool, no
  database clone, no vhosts. Plain `git worktree add`; the ceiling is disk and
  CPU. (Same shape as the 2026-07-23 `CannObserv/cli` session.)
- **Batch → main merge strategy:** regular merge commit (`git merge --no-ff`),
  matching this repo's existing merge-commit-per-PR history.
- **Intra-batch worker → batch integration:** fast-forward or regular merge only.
  Never squash or rebase — `worktree-destroy.sh --base batch/<X>` verifies the
  worker branch is an ancestor of the batch branch, and both rewrite forms break
  that check.
- **Design doc committed directly on `main`**, so workers branching from local
  main see it on disk without a merge gate before Batch A launches.

## Prioritization rubrics

**Score = (Foundation × 2) + (Correctness × 3) + Scope**, max 18.

Correctness is weighted ×3 rather than the standard ×2. Every Group A issue's
defining property is *silent wrongness* — a wrong number or a wrong verdict
rather than an error — and #134's argument is that these must land before the
weekly cadence starts writing a row per repo per week. Weighting correctness
above foundation ranks the ledger-corrupting fixes first. (Precedent for the
variable weight: 2026-05-24 in this repo, also Correctness ×3.)

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation is obvious from the issue |

## Scored backlog

| # | Issue | F | C | S | Score | Blast | Owning file | Batch |
|---|---|---|---|---|---|---|---|---|
| #100 | selective submodule pin | 3 | 3 | 2 | **17** | Med | `skills-submodule-update.sh` | A7 |
| #132 | knob deletes non-digits → 26000 | 2 | 3 | 3 | **16** | Low | `_context-lib.sh` | A1 |
| #119 | normaliser erases one `../` → 172 false LOSTs | 2 | 3 | 3 | **16** | Low | `prove-no-loss.sh` | A3 |
| #120+#124 | dead-link check strips `#fragments` | 2 | 3 | 2 | **15** | Med | `measure-context.sh` | A2 |
| #113 | seam sweep never scans source | 2 | 3 | 2 | **15** | Med | `check-seams.sh` | A4 |
| #123 | `tokens_exact` run-wide only | 2 | 2 | 3 | **13** | Low | `measure-context.sh` | A2 |
| #111 | no verdict for a self-invalidated pointer | 3 | 2 | 1 | **13** | Med-Hi | `prove-no-loss.sh` +2 | B1 |
| #95 | SKILL.md over the budget it enforces | 3 | 2 | 1 | **13** | **High** | `SKILL.md` | C1 |
| #131 | moved-title floods (205 FPs) | 2 | 2 | 2 | **12** | Low | `check-seams.sh` | A4 |
| #99 | hook symlink outside doctor's heal scope | 2 | 2 | 2 | **12** | Med | `doctor.sh` | A6 |
| #108 | `cd X &&` prefix → false FALSE | 1 | 2 | 3 | **11** | Low | `verify-facts.sh` | A5 |
| #109 | guard log path breaks in worktrees | 1 | 2 | 3 | **11** | Low-Med | `context-budget-guard.sh` | A6 |
| #110 | cwd-relative hook command | 2 | 1 | 3 | **10** | **High** | 3 installers | A6 |
| #90 | shellcheck in the structural gate | 2 | 1 | 3 | **10** | **High** | all 11 `.sh` | C2 |
| #103 | matcher misses shell-redirect writes | 1 | 1 | 3 | **8** | Low | `write-guard-hook.md` | A6 |

**Nothing is closed-in-fact.** All 15 were verified live at the line each issue
names, by grepping an identifying symbol per issue plus `Issue #<n>` across the
files named.

### Scoring calls worth recording

- **#100 tops the table**, above every Group A fix, on Foundation 3 + Correctness 3.
  The auto-refresh hook silently auto-commits a pin bump that ends an experiment
  hold with no signal, so `score-cohort.sh` returns INCONCLUSIVE — corruption of
  the experiment itself, not merely of a row. #134 argued independently that it
  is a prerequisite rather than ergonomics.
- **#110 scored Correctness 1**, not 2. Its own body says "it works today"; it is
  hardening against an undocumented cwd assumption, not a live defect. Its
  **High blast** is what actually drives its placement, not its score.
- **#95 scored Correctness 2**, lifted from an initial 1. Every activation pays
  those tokens, so the over-budget body is a live per-run cost rather than a
  credibility problem. The lift does not change its placement — that is
  blast-driven.

## Footprint corrections

Per the bidirectional grep (issue bodies understate *and* overstate scope), four
corrections that must reach the worker prompts. See open issue
[#122](https://github.com/gregoryfoster/skills/issues/122) — "issue bodies give
reliable directions and unreliable specifics."

1. **#132 is not latent in this repo.** Its body says "no cohort repo sets either
   knob." This repo sets both: `.skills/context-budget` = `6000`,
   `.skills/context-doc-budget` = `10000`.
2. **#131's character filter already exists.** `check-seams.sh:215` computes
   `sweepable = {k: v for k, v in moved.items() if len(k) >= 8}`. `Organizations`
   and `Jurisdictions` are 13 characters and sail through. The fix must be
   word-count- or corroboration-based; raising the character threshold will not
   work.
3. **#99, #110 and #100 reach into `managing-skills`**, not only
   `curating-context` — `doctor.sh:202`, `skills-submodule-update.sh:99`, and
   five occurrences of the cwd-relative hook command in `managing-skills/SKILL.md`.
   **#110 additionally lands in `init-project-fastapi/SKILL.md:294`** — a third
   skill, unnamed in the issue.
4. **#95's stated blocker is already cleared.** Its body says "This should follow
   #94, not precede it." #94 shipped at `3fc7b71`. Its token figure is also
   stale — the issue says 9,235, #134 says 10,197, and `SKILL.md` is now 27,996
   bytes. C1 re-measures before trimming.

## Conflict zones

This backlog is **not** the CR-surfaced disjoint shape. It is the tightest
clustering geometry available: one skill, one script family, fifteen defects.

| File | Issues | Regions | Resolution |
|---|---|---|---|
| `scripts/measure-context.sh` | #120+#124, #123 | `extract_links()` :487 / row emit :649 | One agent (A2) |
| `scripts/prove-no-loss.sh` | #119, #111 | `normalise()` :185 / verdict model | **Shape B** — A3 parallel, B1 gated |
| `scripts/check-seams.sh` | #131, #113 | both touch `sweepable` :215 and the moved-title loop :241 | **Shape A** — A4, #131 → #113 |
| `scripts/install-guard.sh` | #110 :76, #109 :198, #103 :124 | three distant lines | One agent (A6) |
| `managing-skills/SKILL.md` | #99, #110, #100 | hook-command strings :166–241 / new pin section | **A6 merges before A7** |
| `curating-context/SKILL.md` | #95, and #120/#124, #113, #111, #103 | #95 rewrites what four others edit | **#95 merges last (C1)** |
| all 11 `.sh` with findings | #90 | seven identical bootstrap blocks | **#90 merges last (C2)** |

### The test monolith

`tests/structural/test_context_surface.py` is 3,560 lines and covers every
`curating-context` measurement script. The repo convention is to append a new
test class at the end — so six Group A workers would append at the same line.

**Resolution, two parts:**

- **New tests go to a new per-agent file.** Removes the EOF pile-up entirely.
  This applies only to `test_context_surface.py`; single-owner test files may be
  extended in place (`test_doctor_self_sync.py` → A6, `test_skills_update_hook.py`
  → A7, `test_scripts.py` → C2).
- **Existing assertions are region-partitioned.** Five agents must *modify*
  assertions already in the monolith, and those windows turn out to be cleanly
  separated:

| Agent | Owned region in `test_context_surface.py` |
|---|---|
| A1 (#132) | `TestDocsDirKnob` :189–241, `TestBudgetKnobIsOneAnswer` :3451–3560 |
| A2 (#123) | `TestLedgerStaysSingleMethod` :517–604, `TestExactFlagReflectsCountsNotCredentials` :605–686 |
| A3 (#119) | `TestProveNoLoss` :736–925 |
| A4 (#131/#113) | `TestCheckSeams` :2049–2133, `TestSeamAcknowledgement` :2266–2419, `TestSeamRenameNoise` :2467–2490 |
| A6 (#110/#109) | `TestSharedLibrary` :331–415 — including the literal `"bash .claude/hooks/context-budget-guard.sh"` at :404 that #110 changes, and the `.git/context-budget.log` path at :371 that #109 changes |

Five non-overlapping windows in a 3,560-line file. Git merges distant hunks
cleanly, so the file stays contested but is not a serializer.

## Dependency graph

```
BATCH A — 7 agents, parallel
  A1  #132              _context-lib.sh          knob parsing
  A2  #120+#124, #123   measure-context.sh       anchors + per-row exactness
  A3  #119              prove-no-loss.sh         normalise() regex only
  A4  #131 -> #113      check-seams.sh           tighten, then widen
  A5  #108              verify-facts.sh          cd-prefix
  A6  #99 #110 #109 #103  install/hook wiring    --+ merges 1st
  A7  #100              skills-submodule-update  --+ merges 2nd  [managing-skills/SKILL.md]
        |
        +-- gate: batch/a -> main, structural suite green
        v
BATCH B — 1 agent
  B1  #111   fourth verdict + ack file + record-telemetry + score-cohort
             ^ needs A3
        |
        +-- gate: batch/b -> main, suite green
        v
BATCH C — 2 agents, parallel (disjoint: .md vs .sh)
  C1  #95   SKILL.md trim + budget gate   <- needs SKILL.md edits from A2, A4, A6, B1
  C2  #90   shellcheck gate + 23-finding sweep <- needs every script edit from A, B
```

**Two edges invisible to file-overlap analysis:**

- **A3 → B1 is semantic, not textual.** They edit different regions of
  `prove-no-loss.sh`, but #111's entire job is deciding what a genuine
  unaccounted-for line looks like — undecidable while #119's bug reports every
  link-carrying line as LOST.
- **C2 validates the bundle's final state.** #90 last means the shellcheck gate
  lints what A, B and C1 actually shipped, not what they started from.
  (Validator-merges-last, per the 2026-07-19 `CannObserv/archiver` session.)

## Batch execution plan

### Batch A — 7 agents, parallel · Gate: start immediately

| Agent | Issues | Files owned | Tests |
|---|---|---|---|
| **A1** | #132 | `scripts/_context-lib.sh` | new `test_knob_parsing.py`; edits `TestDocsDirKnob`, `TestBudgetKnobIsOneAnswer` |
| **A2** | #120, #124, #123 | `scripts/measure-context.sh`, `references/budget-and-metrics.md`, SKILL.md Phase 6 assertion | new `test_context_anchors.py`; edits :517–686 |
| **A3** | #119 | `scripts/prove-no-loss.sh` — **`normalise()` only** | new `test_no_loss_link_depth.py`; edits `TestProveNoLoss` |
| **A4** | #131 → #113 | `scripts/check-seams.sh`, SKILL.md Phase 6.5 | new `test_seam_sweep.py`; edits :2049–2490 |
| **A5** | #108 | `scripts/verify-facts.sh`, `references/fact-verification.md` | new `test_fact_command_prefix.py` |
| **A6** | #99, #110, #109, #103 | `install-guard.sh`, `context-budget-guard.sh`, `references/write-guard-hook.md`, SKILL.md Phase 8, `managing-skills/scripts/doctor.sh`, `managing-skills/SKILL.md`, `init-project-fastapi/SKILL.md` | new `test_guard_install_paths.py`; edits `TestSharedLibrary`; may extend `test_doctor_self_sync.py` |
| **A7** | #100 | `managing-skills/scripts/skills-submodule-update.sh`, `managing-skills/SKILL.md` | extends `test_skills_update_hook.py` |

> **Intra-batch merge order: A6 merges into `batch/a` before A7.** Both edit
> `managing-skills/SKILL.md` — A6 rewrites five hook-command strings, A7 adds a
> pin-file section. Every other agent merges in any order. If the A7 merge
> conflicts, it returns to the A7 worker to resolve.

### Batch B — 1 agent · Gate: `batch/a` merged to main, suite green

| Agent | Issues | Files owned | Tests |
|---|---|---|---|
| **B1** | #111 | `prove-no-loss.sh` (verdict model), `record-telemetry.sh`, `score-cohort.sh`, new loss-warrant ack file, SKILL.md Phase 6 plus the "split before demoting, never after" rule, `references/budget-and-metrics.md` | new `test_loss_warrants.py` |

Single-agent batch — the agent's feature branch serves as the batch branch; no
separate `batch/b` is needed.

### Batch C — 2 agents, parallel · Gate: `batch/b` merged to main, suite green

| Agent | Issues | Files owned | Tests |
|---|---|---|---|
| **C1** | #95 | `curating-context/SKILL.md` (trim to ≤6,000, plus the version bump), `references/*.md` as demotion destinations | new `test_skill_self_budget.py` |
| **C2** | #90 | the 11 `.sh` files carrying findings, AGENTS.md gate note | extends `tests/structural/test_scripts.py` |

C1 and C2 are disjoint by extension — `.md` versus `.sh`.

## Key decisions

1. **#120 and #124 bundle into one agent; both stay open.** They are the same
   defect (#134 calls them "the `#fragment` pair. One change"), but each carries
   unique specifics: #124 names the `dead_anchors` output class and the
   `<`/`>`/`*`/`, ` prose-guard carve-outs; #120 names two edge cases — per-file
   duplicate slug numbering after a split, and archival subtrees scanned as link
   *sources* even when excluded from the doc inventory. Closing either as a
   duplicate would strand its half. A2's prompt carries the union.
2. **Shape B for #119 / #111.** Both live in `prove-no-loss.sh`, but they differ
   in kind and the dependent dwarfs the prerequisite: #119 is a one-line regex,
   #111 is a new verdict, a new ack file, and edits across three scripts plus the
   ledger schema. Splitting costs one gate and buys a small correctness fix
   shipping in parallel with unrelated work, plus a design-heavy change reviewed
   on its own merits.
3. **Shape A for #131 → #113.** Both touch the same `sweepable` computation and
   the same moved-title loop, and they form a define→use sequence: tighten what
   is sweepable, then widen where it is swept. Widening the surface while the
   class still floods 205 false positives would multiply the noise.
4. **`test_context_surface.py` is region-partitioned, not read-only.** New tests
   go to new per-agent files; the five agents that must modify existing
   assertions own non-overlapping windows.
5. **#95 and #90 merge last on blast, not score.** Both sit mid-table (13 and 10).
   #95 rewrites the file four other agents edit; #90 sweeps the seven scripts
   the others rewrite. Blast radius drives sequencing, not priority.
6. **#90 lands as a structural test, not a CI workflow.** This repo has no
   `.github/workflows/` — the only gate is `.pre-commit-config.yaml` running
   `pytest tests/structural/`. AGENTS.md sets the precedent with
   `TestNoBareScriptPaths` and `TestPreShipGateHardening`.
7. **#95's budget gate cannot use `--exact`.** Pre-commit has no
   `ANTHROPIC_API_KEY`, so the gate must use the offline estimator against
   `.skills/context-token-ratio` (2.65) or run at integration tier.
8. **C1 owns the version bump.** `SKILL.md` carries `version: "1.6"`, and its own
   Phase 7 rule says to bump whenever a change would plausibly alter what a run
   does. This bundle alters what every run does. C1 is the only agent that
   touches the frontmatter.
9. **A3 is scoped to `normalise()` only.** The remainder of `prove-no-loss.sh` is
   B1's; a wider A3 would collide with the gated batch.

### Shellcheck debt, measured

23 findings, **0 errors** — 4 warnings and 19 notes across 11 files, all but one
inside `curating-context`. They are highly clustered: seven are the identical
`A && B || C` bootstrap block copy-pasted across seven scripts, and eight more
are `SC1091` on the same `_context-lib.sh` source line. That clustering is
exactly why #90 must merge last: landing it first would put a mechanical sweep
across seven scripts directly under the seven agents rewriting them.

## Deferred items

Named per #134's "Not in this bundle" section — design work that adoption does
not wait on:

| Issue | Reason |
|---|---|
| [#117](https://github.com/gregoryfoster/skills/issues/117) | Pre-register a metric per experiment — design work, no adoption dependency |
| [#118](https://github.com/gregoryfoster/skills/issues/118) | Steady-state metric and longitudinal unit of comparison — the paired design #100 unblocks, but not itself a prerequisite for re-pinning |
| [#88](https://github.com/gregoryfoster/skills/issues/88) | Graduate the token budget into a fitness function — follows #95, not this bundle |
| [#96](https://github.com/gregoryfoster/skills/issues/96) | Slow-cadence self-curation — the durable version of #95's problem; #95 is the one-off fix, #96 the standing process |
| [#97](https://github.com/gregoryfoster/skills/issues/97) | Skill shadowing across 7 trigger phrases — repo-wide frontmatter change, unrelated to the cadence argument |

Also open and out of scope: #115 and #107 (`init-socraticode`), #105
(`shipping-work*`), #68 (parked research), and the `orchestrating-issue-backlog`
process-log entries #130, #129, #127, #122, #114, #112.

## Out of scope

- **The twelve adoption issues themselves.** Per #134: secret, workflow, merge
  attribute, and one manual run per repo to prove it. Four of the twelve
  (`usa-wa`, `power-map`, `address-validator`, `wslcb-licensing-tracker`) have no
  `.github/workflows` at all today. That work begins after this bundle merges and
  the cohort re-pins once.
- **Any cross-repo commit.** Cohort repos are probed read-only; remediation is
  filed as per-repo issues.

## Agent protocol

Standard `orchestrating-issue-backlog` worker protocol applies. Points that
matter specifically here:

- Every worker runs in an `isolation: "worktree"` worktree and **verifies
  isolation before writing** — `[ -f "$(git rev-parse --show-toplevel)/.git" ]`.
- Workers do **not** open PRs and do **not** destroy their own worktree.
- The orchestrator reconciles and merges each worker explicitly on its completion
  signal; `isolation: "worktree"` auto-merge is unreliable.
- `git -C <main> status --porcelain` runs on every completion signal to detect
  worktree fall-through.
- TDD throughout — red, green, refactor — then the full structural suite
  (`pytest tests/structural/`) and a self-review of the diff before signalling.
