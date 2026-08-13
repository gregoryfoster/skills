# Skills follow-up backlog — the carve-outs from #144, plus the journal

**Date:** 2026-08-13
**Tracking issue:** [#155](https://github.com/gregoryfoster/skills/issues/155)
**Predecessor:** [2026-08-12 gates-and-adoption backlog](2026-08-12-skills-gates-and-adoption-backlog.md) (#144, eleven issues, closed)

## Goal

Clear the ten issues left standing after #144: five carve-outs filed *during* that
execution, one from a cohort curation run, and four pending process-log entries from
other repos' sessions.

This is a **followup-derived** backlog in the strict sense the skill names — every issue
but #145 was filed by an agent or orchestrator inside the #144 cycle, which means the
contested files were already named by the work that surfaced them. Steps 5/6 are
compressed accordingly: the conflict map below is confirmation, not discovery.

## Approved approach

Three gated waves, concurrency ceiling **4** (host CPU/RAM alone — plain `git worktree`,
hermetic suite, no shared backing service). Regular merge commit per batch branch to
`main`.

## Rubric

Carried unchanged from #144, where it was agreed against the same deployment context
(eleven cohort repos vendor these skills; correctness of the gates themselves is what
"quality" means here):

**Score = (Foundation × 2) + (Correctness × 3) + Scope**, max 18.

## Scored backlog

| # | Issue | F | C | S | **Score** | Blast |
|---|---|---|---|---|---|---|
| 150 | harness worktrees cut from `origin/main`, not the batch branch | 3 | 3 | 3 | **18** | Low |
| 147 | `extract_links` matches bare `](…)` and links inside code | 2 | 3 | 3 | **16** | Low |
| 149 | `worktree-destroy.sh` cannot address harness worktrees | 2 | 2 | 3 | **13** | Low |
| 148 | 8 demoted "in full" blocks are unchecked snapshots | 2 | 2 | 2 | **12** | Med |
| 145 | global bytes/token ratio over-flags code-heavy docs by 7–10% | 2 | 2 | 2 | **12** | Med |
| 152 | the process log is 6× the per-doc budget and grows every session | 2 | 1 | 2 | **9** | High |
| 146/151/153/154 | four pending process-log entries + 7 promotion candidates | 1 | 1 | 3 | **8** | High |

**#150 scoring 18 is not inflation.** It is the defect that nearly had two agents in the
preceding batch measure and edit a tree missing eight merged issues; both recovered
because their brief quoted a test baseline they could compare against, which was luck
rather than design. It governs every future batch in every cohort repo.

**#147 scores Scope 3 because the fix already exists.** `tests/structural/test_relative_links.py`
solved the identical defect one layer up during #144. This is a port.

## Premises verified against the tree

Every issue was re-checked before scoring — none is closed-in-fact.

| # | Claim | Verdict |
|---|---|---|
| 147 | `extract_links` still `grep -oE '\]\([^)]+\)'` | Live — `measure-context.sh:525–535`, unchanged |
| 150 | Rule 3 still says branch base "varies" | Live — `SKILL.md:378`, unchanged |
| 149 | destroy script constructs path from `resolve-worktree-root.sh` | Live — `worktree-destroy.sh:111` |
| 148 | 8 demoted blocks across 5 reference files | Confirmed — 8 exactly |
| 145 | one global ratio drives guard and estimator | Confirmed — `.skills/context-token-ratio`, `measure-context.sh:378` |
| 152 | process log 6× the per-doc budget | Confirmed and **worse**: 174,055 bytes ≈ 65,700 tokens, up ~4,400 from the 61,280 #141 measured two days ago |

### Two corrections to issues this session filed

- **#152 overstated the glob gap.** Four non-recursive `references/*.md` globs exist
  (`test_content_invariants.py:1407`, `:1560`; `test_references.py:76`, `:97`) — but
  `test_relative_links.py:190` was **already** `rglob`, so link-checking would have
  followed entries into yearly subdirectories unaided. The recursion work is real but
  narrower than the issue's comment implied.
- **#148's "one coincidental hit" is now two.** `test_skill_self_budget.py:184` picked up
  the phrase "in full" during #141, after the issue was filed.

Both are written back to the issues.

## Conflict zones

| File | Contending issues | Handling |
|---|---|---|
| `curating-context/scripts/measure-context.sh` | #147 (`extract_links` :525–535) · #145 (ratio :378, :813–854) | Separated windows — resolved by putting them in different batches, which is cheaper than defending a boundary |
| `curating-context/references/budget-and-metrics.md` | #148 (3 "in full" blocks) · #145 (ratio prose :231, :242 — **not :313**) | See the correction below |
| `orchestrating-issue-backlog/SKILL.md` | #150 (Rule 3 :370–407, worker protocol :301–310) · #152 (reference links :33, :437) · #146/#153/#154 (7 promotions) | Sequenced across all three waves |
| `references/process-log.md` | #152 (restructure) · #146/#151/#153/#154 (appends) | Appends land **first**; #152 migrates once |
| `test_context_surface.py` (3,724 ln) | #147 (`links_dead` :1176–1277, :3678–3723) · #145 (`bytes_per_token` :3688) | **Line 3688 read-only for both** — one fixture row naming both concerns |

## Dependency graph

```
Batch C  #147 ─┐
         #150 ─┼─→ merged to batch/c ─→ main
         #149 ─┤
         #148 ─┘
                        ↓
Batch D  #145 ────────┐        (#145 needs C's measure-context.sh + budget-and-metrics.md)
         #146/151/    ├─→ batch/d ─→ main
         153/154 ─────┘        (appends need C's SKILL.md promotions settled)
                        ↓
Batch E  #152 ─────────────────→ main
                                 (migrates a ledger that is finally complete)
```

**One edge no file overlap can show:** #152 must run after the four appends not because
they touch the same lines — appends go at EOF and the migration rewrites everything — but
because migrating a ledger that four entries are still queued for means running the
migration twice, on content that arrives between passes. This is the same property that
defeated #141's ratchet: an append-only artifact cannot be stabilised while appends are
outstanding.

## Batch execution plan

### Batch C — 4 agents, at ceiling, file-disjoint

| Agent | Issue | Owns | Must not touch |
|---|---|---|---|
| **PROTO** | #150 | `orchestrating-issue-backlog/SKILL.md:370–407` (Rule 3), `:301–310` (worker protocol) | `references/process-log.md`, `SKILL.md:33`/`:437` |
| **LINKX** | #147 | `curating-context/scripts/measure-context.sh:520–560` (`extract_links`, `is_prose`), `test_context_surface.py` link assertions | `measure-context.sh:370–390`, `:800–870`; `test_context_surface.py:3688` |
| **DESTROY** | #149 | `using-git-worktrees/scripts/worktree-destroy.sh`, `resolve-worktree-root.sh`, `test_worktree_destroy_base.py` | `orchestrating-issue-backlog/**` |
| **INFULL** | #148 | `curating-context/references/{budget-and-metrics,cohort-patterns,continuous-surfaces,telemetry,validation-gate}.md`, new `tests/structural/test_demoted_blocks.py` | `budget-and-metrics.md:225–320` (ratio prose, #145's) |

Gate: start immediately. No intra-wave merge ordering required.

### Batch D — 2 agents, gated on `batch/c` merged to `main`

| Agent | Issues | Owns |
|---|---|---|
| **RATIO** | #145 | `measure-context.sh` ratio machinery, `context-budget-guard.sh`, `budget-and-metrics.md` ratio prose at **`:231` and `:242` only** |
| **APPENDS** | #146, #151, #153, #154 | `references/process-log.md` (index + EOF), `orchestrating-issue-backlog/SKILL.md` (promotions only) |

Gate: `batch/c` on `main`. **APPENDS merges last** — its promotions edit the same SKILL.md
PROTO reshaped, so it rebases onto the merged result.

### Batch E — 1 agent, gated on `batch/d`

| Agent | Issue | Owns |
|---|---|---|
| **JOURNAL** | #152 | `references/process-log.md` → indexed journal in yearly subdirectories, the four `references/*.md` globs, `DOC_BUDGET_EXCEPTIONS` |

Single-agent batch; the feature branch serves directly.

## Batch C execution — what the plan got wrong

Merged as `8db23ba`. Suite 1956 → **2080 passed, 110 skipped, 147 deselected**. All four
agents corrected the issue body, the brief, or both.

**The Batch D ownership boundary above was wrong, and INFULL caught it before RATIO
launched.** `budget-and-metrics.md`'s `### The Phase 1 credential note, in full` occupies
lines **303–316** — inside the `:225–320` window this plan reserved for #145. Worse, the
ratio site named at `:313` is a line *inside that demoted snapshot*, so RATIO would have
been rewording a frozen copy of `SKILL.md` Phase 1 text rather than live prose. Only `:231`
and `:242` are live. The table above is corrected; the original boundary is recorded here
because the lesson is that **a line-window boundary drawn over a file containing demoted
snapshots is not safe until you know where the snapshots are** — the window looks like
prose from the outside.

**Three of four agents found the provisioned worktree has no `.venv`,** which this plan's
briefs mandated. Filed as [#156](https://github.com/gregoryfoster/skills/issues/156). This
is a second instance of #150's own class — a brief prescribing state the worktree does not
have — and it was in the brief written *to fix* the first instance.

**#147 was not "mechanical, Scope 3".** The brief flagged the risk and it landed: the
grammar ports from `test_relative_links.py`, the *masking* does not. Python has
backreferences and lookarounds; awk has neither, so the code-span matcher is a hand-written
character scanner and the "cannot cross a blank line" guard became paragraph buffering.
125 lines of awk for a 3-line pipeline. Correct score was Scope 2.

**#148's count was 8; the truth was 13.** The issue's grep saw two of the six phrasings the
convention actually uses. One block had shipped *inside* a fenced ```` ```markdown ```` example
since v1.7 — never a heading, unanchorable, first line lost in transit, and invisible to
every gate because a fenced link is not a link.

**#149's premise was inverted, and the correction came from evidence I had in hand.** The
agent found every harness worktree `locked` and concluded `--unlock` was routinely required
— then noted that this contradicted #144's eight successful manual teardowns and doubted
the *record* rather than its own inference. One `git worktree list --porcelain` with two
agents finished and two running settled it: **the lock tracks agent liveness**, so it is
always gone by teardown. Teardown of all four worktrees then ran with no flags at all.

**#150's own fix (2) was wrong as filed.** "Step 1, before the isolation pre-flight" would
have a fallen-through worker run `git merge` — which writes files — in the main checkout,
which is exactly what the pre-flight's abort clause exists to prevent. Implemented as step
3, after it. Option (4) is rejected: pushing `batch/<X>` creates `origin/batch/<X>` and does
not move `origin/main`, so it cannot change what the harness reaches for.

## Key decisions

**The four journal issues bundle into one agent (Shape A).** All four append to one file
and all four propose promotions into one SKILL.md. Run as four slots they would serialize
on both anyway, and each would adjudicate its promotions blind to the other three's — the
7 candidates need to be weighed against each other, which is a single judgment.

**#145 and #147 are separated by batch, not by line window.** Their windows in
`measure-context.sh` genuinely do not overlap (`:525` vs `:378`/`:813–854`), so line-window
ownership would work. Putting them in different batches costs one gate and removes the
boundary entirely — worth it because #147 changes what `extract_links` returns, and #145's
telemetry rows carry link counts, so a shared-file merge would be clean while the
*behaviour* underneath it moved.

**The falsifiable baseline is `1956 passed, 94 skipped, 147 deselected` under `.venv/bin/python`.**
Every worker prompt in every wave carries it with an instruction to stop if it does not
match. This is #150's own third recommendation, applied to the batch that implements it —
and it is the mechanism that saved two agents in #144.

Note the venv: a bare `python3 -m pytest` fails collection on 9 modules
(`ModuleNotFoundError: No module named 'anthropic'`). An agent that reports a collection
error has used the wrong interpreter, not found a defect.

**Worktree base is `origin/main`, stated as fact.** Pending #150's fix to the skill itself,
every worker prompt in this backlog carries the merge instruction explicitly:
`git merge batch/<X>` as step 1, expecting a clean fast-forward. Batch C is exempt in
effect — `batch/c` will equal `main` at launch — but the instruction ships anyway, because
the whole point of #150 is that the wave where it does not matter is the wave that teaches
you it never does.

**Verification-mode asymmetry, again.** INFULL's new `test_demoted_blocks.py` and
DESTROY's revised destroy-script tests exist in no sibling's worktree. Every Batch C agent
self-verifies under the old gate set; the post-merge run against `batch/c` is the first
execution of the combined tree. A failure there is not necessarily the last-merged agent's
defect.

## Deferred

- **#117** — residual blocked on #118, which is outside this set. Carried forward from #144
  unchanged.
- **#88, #96, #97, #118, #68** — not named in this set.
