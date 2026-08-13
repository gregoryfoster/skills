# Skills backlog: gate correctness and cohort adoption defects

**Date:** 2026-08-12
**Issues:** #105, #107, #115, #117, #136, #137, #138, #139, #140, #141, #142, #143
**Batches:** 2 (A chunked into two sub-waves) · **Agents:** 8 · **Deferred:** 1

## Goal

Clear twelve open issues against this repo's skill family. Nine of them are defects in
*gates* — tools that judge other work (`prove-no-loss.sh`, `check-seams.sh`, the shellcheck
gate, the self-budget gate, a proposed relative-link gate). The remaining three are
adoption defects filed by cohort repos consuming `shipping-work*` and `init-socraticode`.
The unifying property is that a gate which reports wrongly is worse than no gate: every one
of these defects pushes an operator toward waving a check through, poisoning an
acknowledgement ledger, or trusting a policy that points at broken tooling.

## Approved approach

- **Rubric:** Correctness-weighted (×3), because the backlog is overwhelmingly about
  gate correctness rather than feature delivery.
- **Deployment context:** active production — eleven cohort repos vendor these skills via
  `skills-vendor` auto-refresh, so a bad landing propagates.
- **Parallelism:** hybrid — parallel within batches, gate between them.
- **Worktrees:** yes, `isolation: "worktree"` for every worker.
- **Concurrency ceiling: 4**, set by host CPU/RAM. This repo has **no project provisioning
  ceiling** — `skills/using-git-worktrees/scripts/worktree-create.sh` is plain
  `git worktree` with no port pool, no DB clone, no docker range, and the structural suite
  is hermetic (per-test `tmp_path` git repos, `ANTHROPIC_API_KEY` stripped). Verified: no
  match for `docker|POSTGRES|DATABASE_URL|PORT_POOL` anywhere under `scripts/` or `tests/`.
  This is the first project across seven orchestration sessions where the ceiling was *not*
  hiding in a shared backing service.
- **Merge strategy:** regular merge commit, `batch/a` → `main`. Intra-batch worker → batch
  is fast-forward or regular merge only (squash/rebase break `worktree-destroy.sh --base`).

## Prioritization rubrics

**Score = (Foundation × 2) + (Correctness × 3) + Scope**, max **18**.

Correctness carries ×3 rather than the default ×2. Nine of eleven work items are gates
judging other work; the failure mode is not "a bug ships" but "the gate that would have
caught the bug is distrusted and bypassed." That asymmetry justifies the weight.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation is obvious from the issue |

## Scored backlog

| # | Work item | F | C | S | Score | Blast |
|---|---|:-:|:-:|:-:|:-:|---|
| #136+#137+#139 | `prove-no-loss.sh`: frontmatter, link-prefix, ack scoping | 3 | 3 | 2 | **17** | Med |
| #107+#115 | `init-socraticode`: policy split + edge-yield gate + degraded variant | 3 | 3 | 2 | **17** | Med |
| #138 | `check-seams.sh` `--file` ignored by the back-reference class | 2 | 3 | 3 | **16** | Low |
| #142 | `reviewing-architecture`: carry the grep; line numbers are evidence | 2 | 2 | 3 | **13** | Low |
| #141 | self-budget gate → all 18 skills | 2 | 2 | 3 | **13** | **High** |
| #105 | `shipping-work*`: wrapper recipe, port to four variants | 1 | 2 | 3 | **11** | Med |
| #140 | shellcheck ≥ 0.7.0 version floor | 1 | 2 | 3 | **11** | Low |
| #143 | structural gate on relative links in `skills/**/*.md` | 1 | 2 | 2 | **10** | Low |
| ~~#117~~ | *deferred — see Deferred items* | — | — | — | — | — |

### Closed-in-fact check

All twelve issues verified **live** against `main` at `c408c85`. Each was checked by
grepping an identifying symbol from its body rather than by trusting the body:

| # | Grep | Result |
|---|---|---|
| 105 | `Project-local env loading` across four `pre-ship.sh` | 1 of 4 — still says "thin local fork" |
| 107 | `graph_status\|READY` in `init-socraticode/SKILL.md` | :250, :290, :307 gate on status only |
| 115 | `wc -c references/code-exploration-policy.md` | 8,854 bytes |
| 136 | `grep -c 'frontmatter' prove-no-loss.sh` | **0** |
| 137 | `LINK_DEPTH` | `prove-no-loss.sh:311`, leading `../` only |
| 138 | `policy_names` | hardcoded `:307`, used `:322` and `:417` |
| 139 | `ACK_FILE` | `prove-no-loss.sh:158`, per-repo |
| 140 | `_require_shellcheck` | `which` only, no version parse |
| 141 | `SKILL_DIR`, `SKILL_MD_RATCHET` | single skill, `7_600` |
| 142 | finding format + Phase 3.5 | location required, derivation not |
| 143 | `ls tests/structural/ \| grep link` | only `test_no_loss_link_depth.py` |

### Two corrections written back to GitHub

**#143's proposed discriminator needed replacing — but not for the reason recorded here
at planning time. ~~Disproven by a fifth carve-out.~~ RETRACTED — see below.**

*Planning-time claim (WRONG):* a sweep of `skills/**/*.md` found a fifth, relative-prefixed
carve-out at `skills/curating-context/SKILL.md:250 -> ](../tests/x.py)`, so restricting the
check to `./`/`../` targets does not clear it. Scored Scope Clarity 3 → 2 on that basis.

*What the implementing agent established (CORRECT):* that string is **not a markdown link**.
It is a bare `](…)` fragment inside an inline code span, with no `[label]`, in prose that
quotes a link's *form*. Any extractor requiring the real `[label](target)` grammar never
sees it. The planning sweep used a loose `\]\(…\)` regex that matched fragments — the same
defect the agent then found in `measure-context.sh:533`, which is why that script reports
four phantom dead links for this file.

The real survey is **8 dead links across 5 files**, none relative-prefixed — so the issue's
`./`/`../` discriminator would in fact have cleared the current tree. It was still the wrong
shape, for a reason neither the issue nor this document identified: **all 8 sit inside a
code fence or an inline code span**, so the true distinction is the *context a link sits in*,
not its target string. A target-string discriminator passes today and breaks the moment
someone writes a fenced example with a `../` prefix.

Lesson recorded in the process log: an orchestrator's quick regex is exactly as falsifiable
as the issue body it audits, and more dangerous, because it arrives as a *correction*.

**#141's ratchet question is answered.** Shared standard plus named exceptions, and the
gate does **not** assert on dead links. Scope Clarity 1 → 3, score 11 → 13.

## Conflict zones

| File | Agents | Required handling |
|---|---|---|
| `AGENTS.md` (257 lines, 4,273 / 6,000 tokens) | SHELL, SHIP, LINKS, BUDGET | **Separated line windows.** SHELL owns `:116–119` (shellcheck bullet); SHIP owns `:134` (`TestPreShipGateHardening` bullet); LINKS owns `~:170–175` (structural-suite rules list). BUDGET is excluded to Batch B. Windows do not overlap and merge cleanly |
| `tests/structural/test_context_surface.py` (3,636 lines) | PNL, SEAMS | **Separated line windows.** PNL owns `TestProveNoLoss` 736–925 and `TestNoLossOnTheRow` 1407–1443; SEAMS owns `_seam_repo` 2029–2060, `TestCheckSeams` 2061–2145, `TestSeamAcknowledgement` 2278–2431, `TestSeamRenameNoise` 2479–2502. The two agents sit in different sub-waves regardless |
| `test_context_surface.py:2509–2514` | PNL, SEAMS | **READ-ONLY for both.** A single `parametrize` list naming *both* `prove-no-loss.sh` and `check-seams.sh`. Neither issue changes an invocation path, so neither agent has cause to touch it |
| `skills/curating-context/SKILL.md` | PNL, SEAMS, LINKS, BUDGET | PNL (A1) merges before SEAMS (A2) opens. Within A2, SEAMS owns the file and **LINKS merges last** |
| `skills/*/SKILL.md` (all 18) | BUDGET vs everyone | Sole reason #141 is a solo terminal batch — see Key decisions |
| `tests/structural/test_*.py` | one file per agent | Clean by construction: `AGENTS.md:223` mandates a new rule gets its own `test_<rule>.py` |

### The test-surface conflict was invisible from source overlap

`prove-no-loss.sh` and `check-seams.sh` are different files, and neither issue mentions a
test. The contention lives entirely in `test_context_surface.py`, found by grepping the
test tree for the scripts each fix rewrites. It resolved to separated windows rather than
serialization — but only because the windows were mapped before assignment, not discovered
at merge time.

## Dependency graph

```
Batch A — 7 agents, no edges between them
┌──────────────────────────────────────────────────────────┐
│ A1 (4 agents, at ceiling)                                │
│   PNL      #136+#137+#139   prove-no-loss.sh             │
│   SOCRATI  #107+#115        init-socraticode + hook      │
│   RA       #142             reviewing-architecture       │
│   SHELL    #140             test_scripts.py  [AGENTS.md] │
├──────────────────────────────────────────────────────────┤
│ A2 (3 agents, after A1 worktrees freed)                  │
│   SEAMS    #138             check-seams.sh               │
│   SHIP     #105             shipping-work* ×4 [AGENTS.md]│
│   LINKS    #143             test_relative_links.py  ←last│
└──────────────────────────────────────────────────────────┘
        │                              │
        │ #136 unblocks #141           │ all 18 SKILL.md settled
        └──────────────┬───────────────┘
                       ▼
             Batch B — 1 agent
             BUDGET  #141  self-budget → all 18 skills

Deferred: #117 ──blocked──▶ #118 (out of scope)
```

One edge in the entire graph. Both sub-waves merge into the same `batch/a` branch.

### Backlog provenance

Mixed, and it produced a near-fully-disjoint backlog:

- **#136–#141** are *followup-derived* from Batch C of #135, but they decompose on the
  owning-script axis (`prove-no-loss.sh` / `check-seams.sh` / `test_scripts.py` /
  `test_skill_self_budget.py`) rather than clustering on one partial.
- **#142, #143** are *CR-surfaced* from #112 — one defect per surface, naturally disjoint.
- **#105, #107, #115** are *adoption-feedback* from cohort repos (usa-wa, watcher, observo),
  clustering by owning skill, which is why two of them bundled.

The originating cycle spread defects one-per-layer across the stack, so the
followup provenance produced the CR-like disjoint shape rather than a single-file critical
path. Seven parallel agents, one gated isolate.

## Batch execution plan

### Batch A — sub-wave A1 (4 agents, at ceiling)

| Agent | Issues | Owns | Must not touch |
|---|---|---|---|
| **PNL** | #136, #137, #139 | `curating-context/scripts/prove-no-loss.sh`, `test_no_loss_link_depth.py`, `test_loss_warrants.py`, `test_context_surface.py:736–1443` | `test_context_surface.py:2509–2514`, `AGENTS.md` |
| **SOCRATI** | #107, #115 | `init-socraticode/**`, `managing-skills` cadence hook, new `docs/` policy doc | `AGENTS.md` |
| **RA** | #142 | `reviewing-architecture/SKILL.md` | `AGENTS.md` |
| **SHELL** | #140 | `tests/structural/test_scripts.py`, **`AGENTS.md:116–119`** | any other `AGENTS.md` region |

Gate: start immediately. No intra-wave merge ordering required — file coverage is disjoint.

### Batch A — sub-wave A2 (3 agents)

| Agent | Issues | Owns | Must not touch |
|---|---|---|---|
| **SEAMS** | #138 | `curating-context/scripts/check-seams.sh`, `test_seam_sweep.py`, `test_context_surface.py:2029–2502`, `curating-context/SKILL.md` | `test_context_surface.py:2509–2514`, `AGENTS.md` |
| **SHIP** | #105 | `shipping-work*/scripts/pre-ship.sh` ×4, `docs/STYLE.md`, **`AGENTS.md:134`** | any other `AGENTS.md` region |
| **LINKS** | #143 | new `tests/structural/test_relative_links.py`, **`AGENTS.md:~170–175`**, exemption mechanism | any other `AGENTS.md` region |

Gate: A1's worktrees destroyed and slots freed (re-verify per Rule 5 slot-reclaim).
**Intra-wave merge ordering: LINKS merges last.** Its gate walks every `skills/**/*.md`, so
it must run against the combined tree; and if it takes the inline-marker exemption route it
will contend with SEAMS on `curating-context/SKILL.md` and must rebase onto `batch/a` first.

### Batch B (1 agent)

| Agent | Issues | Owns | Gate |
|---|---|---|---|
| **BUDGET** | #141 | `tests/structural/test_skill_self_budget.py`, `AGENTS.md`, all 18 `SKILL.md` | **After `batch/a` is merged to `main`** |

Single-agent batch — the agent's feature branch serves directly; no `batch/b` branch needed.

## Key decisions

**#141 isolates because of a prose assertion, not a code dependency.**
`test_skill_self_budget.py:164` asserts `f"{SKILL_MD_RATCHET:,}-token ratchet" in
SKILL_MD.read_text()` — each skill must *name its own ratchet in prose*. Generalized to all
18 skills, that edits every `SKILL.md` in the repo, intersecting SOCRATI,
RA, SHIP, PNL and SEAMS simultaneously. This is the "single issue whose blast intersects
multiple otherwise-parallel agents" case: it gets its own gated batch even though its score
(13) would otherwise seat it mid-table. Its stated #136 blocker points the same way.

**The #141 ratchet is a shared standard with named exceptions.** One constant binds every
skill; a skill that genuinely cannot meet it carries an explicit commented override, with
`curating-context` at 7,600 as the first. Honest as a *standard*, and each exception has to
argue for itself in the diff rather than being buried in a table of twenty numbers.

**#141 does not assert on dead links.** Scoping it to token budgets only decouples it from
#143 entirely — no ordering constraint between them, and no risk of two incompatible
placeholder-exemption mechanisms. Link checking stays wholly #143's.

**#143's exemption mechanism is left open, and that is a deliberate risk.** The issue's own
discriminator is disproven (see above). The implementing agent chooses between an allowlist
constant, an inline marker, or example-block skipping. An allowlist keeps LINKS fully
disjoint; an inline marker puts it in contention with SEAMS on `curating-context/SKILL.md`.
The plan absorbs either by making LINKS the last merge in A2.

**#107 and #115 bundle (Shape A).** Both rewrite
`init-socraticode/references/code-exploration-policy.md` and SKILL.md Phase 3 — #115 splits
the template, #107 adds a *degraded variant* of the thing #115 just split. Done
independently the second agent rewrites the first's output. They form one define→use
sequence over a single template redesign, which is the bundle signal.

**#136, #137 and #139 bundle (Shape A).** All three live in `prove-no-loss.sh`; #136 and
#137 both edit `normalise()` directly. This is the adoption-feedback "one agent per owning
file" shape — the parallelism comes from the *script family's* modularity, not from the
issues' independence. Bundling makes the conflict impossible rather than manageable.

**AGENTS.md is a shared foundation file managed by line-window ownership, not exclusion.**
Three Batch A agents write to it in three separated, named windows. The file sits at 4,273
of its 6,000-token budget and is under this repo's own write guard, so the combined
addition must stay small. **No agent may restructure or re-order `AGENTS.md`** — additions
within the named window only.

**Verification-mode asymmetry — read this before blaming an agent.** SHELL's shellcheck
version floor (#140) and LINKS's relative-link gate (#143) do not exist in any sibling's
worktree. Every A1 and A2 agent therefore self-verifies under the *old* gate set. The
orchestrator's post-merge run against `batch/a` is the **first** execution of the combined
tree under the new gates. A failure there is not necessarily the last-merged agent's
defect, and must not be attributed to one without checking.

**Correctness fixes lead; no refactor is scheduled here.** Every Batch A item is a targeted
fix or a new gate. #141 is the only wide change and it is last by construction.

**No chain-appending artifact exists in this backlog** — no migrations, no numbered ADRs,
no sequence-generated files. The one-chain-appender-per-batch rule has nothing to bind.

## Runtime note on issue-body decay

Issue bodies are a snapshot of filing time; this backlog is eight sequential mutations of
what they describe. Two bodies were **already wrong before any agent started** — #143's
discriminator (disproven by a sweep) and #117's open/closed state (proposal 4 shipped in
#125). Every worker must treat its issue body as a proposal, not a specification: verify
every `file:line`, every claimed call site, and every prescribed implementation against the
current tree before acting, and **report the corrections** rather than implementing around
them silently.

Staleness is worst in Batch B. BUDGET reads bodies describing all 18 `SKILL.md` files after
seven agents have edited five of them. `test_skill_self_budget.py:164`'s line number in
particular will have moved if PNL or SEAMS touched the file.

## Deferred items

**#117 — `curating-context`: pre-register a metric per experiment.** Its proposal 4 (the
REJECT pair floor) already shipped in **#125**, merged to `main` as `689b21e`. The residual
— proposals 1–3, the pre-registered experiment file — is explicitly blocked on **#118**
settling the arm-label and unit-of-comparison question, because the experiment file must
declare an arm predicate and #118 replaces wave membership with the per-row `skill_version`
stamp. Building it now would encode an arm definition #118 discards. **#118 is not in this
backlog**, so any batch slot allocated to #117 would be dead work.

Two constraints to carry forward when #117 does land, both recorded on the issue:

- There must be **no `--metric` flag** on `score-cohort.sh`. The metric comes from the
  committed experiment file or the gate refuses to score.
- Proposal 2 is better as a **named outcome** than as asymmetric scoring: when the
  pre-registered metric's field is null across every control-arm row, return INCONCLUSIVE.

## Out of scope

- **#107 part 3 — upstreaming the SocratiCode `src`-layout resolver bug.** Considered for
  deferral and kept in scope by decision, but it is a report to an external plugin, not a
  change to this repo; SOCRATI should file it and move on rather than attempt a fix.
- **Retightening the 6,000 context budget.** Raised in #117's thread and explicitly
  rejected: changing the budget after seeing where the cohort landed is the same integrity
  failure as choosing a metric late.
- **#96** (slow-cadence self-curation) and **#118** (steady-state metric) — open, related
  to #141 and #117 respectively, not part of this pass.
- **#97, #88, #68** — open but outside the named set.
