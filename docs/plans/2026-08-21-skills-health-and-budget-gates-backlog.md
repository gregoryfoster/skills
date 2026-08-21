# Backlog orchestration — the #213 followups: health-check parity and the budget gate

Tracking issue: [#219](https://github.com/gregoryfoster/skills/issues/219)
Session: 2026-08-21 · Orchestrated with `orchestrating-issue-backlog`

## Goal

Clear #214–#217 — four issues filed during the #213 execution cycle — as three
work items in a single merge-safe batch. Three of the four are the same shape:
a gate that reports green over a real degradation. #214 is a health-check that
misses an unindexed context artifact behind three green lights; #217 is a budget
ratchet whose always-on reading runs 13% low and has now passed three breaches;
#216 is the inverse failure, a gate that reports a problem where none exists and
cost one cohort repo weeks of distrust in a provably exact import graph. #215 is
a test-coverage port: a documented trap asserted in the derived script and
nowhere in the original.

## Approved approach

- **Rubric**: `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Fourth
  consecutive Correctness-×3 session; same justification — twelve cohort repos
  vendor this library and pull daily, so wrong guidance ships wide before
  anyone reads it.
- **Deployment context**: active production (Q2).
- **Deferrals** (Q3): #207 stays deferred on upstream
  giancarloerra/SocratiCode#112 — **re-verified this session**: still `open`,
  and the latest release (v1.12.0, 2026-08-14) predates it. #218 stays out of
  scope as outside the named range. The stale `AGENTS.md` skill count folds
  into #217's agent, which is already editing that section.
- **Parallelism**: hybrid (Q4) — parallel within the batch, merge-and-test gate
  before `main`, all workers in `isolation: "worktree"`.
- **Concurrency ceiling: 4 per batch, host-bound** (Q5). **Fifth consecutive
  negative result** (2026-08-12, -16, -18, -20, now -21). Re-verified:
  `worktree-create.sh` is plain `git worktree add` with no port pool, docker or
  vhost provisioning; no `conftest.py` under `tests/`; `addopts` is
  `-m 'not integration and not benchmark'`; and the backing-service escape grep
  (`docker|POSTGRES|DATABASE_URL|PORT_POOL|redis`) returns exactly three hits,
  all of which are the substring `redis` inside the word *rediscovered*. Read
  the hits before accepting them — that is the whole lesson of the check. The
  cap is host CPU/RAM for a ~171-second hermetic suite × N. Not binding here:
  only three work items.
- **Shared credential**: `ANTHROPIC_API_KEY` in the gitignored `.env` is a
  single shared resource, but only A3 has any reason to spend it
  (`SKILL_BUDGET_EXACT=1`, ~19 calls). No contention, no serialization needed.
- **Merge strategy**: regular merge commit, `batch/a` → `main`. Intra-batch
  worker → batch fixed at FF/regular merge so
  `worktree-destroy.sh --base batch/a` can verify ancestry.
- **Suite baseline on `main` (`69bd674`)**: **2991 passed, 159 skipped**, 171s,
  via `.venv/bin/python -m pytest tests/structural/`. Every worker brief carries
  this number with "stop and report if it does not match."

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** ×2 | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** ×3 | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** ×1 | Requires design discovery | Clear direction, minor decisions needed | Mechanical — obvious from the issue |

## Scored backlog

Final scores after the decide-then-rescore pass. All three gate decisions moved
a Scope column: #217 S1→3, #214 S2→3, #216 S2→3.

| # | Issue | F | C | S | **Score** | Blast | Agent |
|---|---|---|---|---|---|---|---|
| **#217** | the exact ratchet is opt-in, so it has now been breached three times past a green suite | 2 | 3 | 3 | **16** | Low-Med | A3 |
| **#214** | health-check misses a COMPLETED operation that left a context artifact unindexed | 1 | 3 | 3 | **14** | Med | A1 |
| **#215** | `resolve-worktree-root`'s "absolutize both sides" trap is untested | 1 | 2 | 3 | **11** | Low | A2 |
| **#216** | the unresolvedPct finding reads as an accusation *(rescoped to part 1)* | 1 | 2 | 3 | **11** | Med | A1 |
| #207 | retire the edge-yield workaround for the upstream advisory | — | — | — | **deferred** | — | — |
| #218 | `write-guard-hook.md` restates the bullet above it | — | — | — | **out of scope** | — | — |

### Closed-in-fact verification

Every issue was verified against the tree rather than against its own body:

- **#214** — `cmdHealthCheck` (`mcp-driver.mjs:869–945`) pushes findings for
  infrastructure, a FAILED last operation, an INCOMPLETE index and graph yield.
  No artifact-parity finding exists. The helpers it needs already do:
  `parseArtifacts` (`:382`) and the manifest's authoritative `expectedArtifacts`
  (`:606`) are both built and both unused by health-check.
- **#215** — `test_worktree_root_contract.py` has fifteen tests and none runs the
  script from a subdirectory. The ported original,
  `test_plans_dir_contract.py:143 :: test_resolve_from_a_subdirectory_uses_the_repo_root`,
  is present.
- **#216** — `mcp-driver.mjs:938–939` verbatim, and line 938 does sit outside
  the `low`/`unknown` verdict branches as the issue claims.
- **#217** — `SKILL_BUDGET_EXACT` appears in two test files and nowhere else;
  not in `.pre-commit-config.yaml`, not in `.github/workflows/context-cadence.yml`.

### Q0 dispositions

- **#214+#216 → bundled (A1)**, Shape A with sequential commits. They contest
  *two* files, not one: both edit `cmdHealthCheck` in `mcp-driver.mjs` (windows
  ~30 lines apart) and both edit `references/socraticode-doc.md` (Per-tool notes
  vs. Graph health — adjacent sections, so an insert in the first shifts the
  second). Both are small, both answer the same question — what health-check
  reports and how the generated doc explains it — so one review surface is the
  natural shape. Bundling makes the conflict impossible rather than manageable.
  It also lands #214's template note beside its parity finding, which is what
  retires power-map#455's `local-divergence` block in one move.
- **#216 → rescoped to part 1.** The issue asked for two things. Part 1 (reword
  the finding) is independent and cheap. Part 2 (an acknowledgement mechanism
  for a structurally-high repo) is entangled with #207, whose upstream blocker
  is still open — and #216's own sequencing note says #207 may make the local
  statistic moot. Designing an ack mechanism the server is about to obsolete is
  the dead work this disposition exists to prevent. Part 2 moves to #207 with its
  three candidate options preserved.
- **No duplicates.** The bundle is distinct work sharing a file, not one issue
  filed twice.

### Gate decisions (decide-then-rescore)

**#217 → options 1 + 3 together.** The issue recommends option 2 ("assert the
worst case against the ratchet") and calls it the strongest. Measurement
falsifies that recommendation. `worst_case_exact()` already exists at
`test_skill_self_budget.py:422` but is only used to *format the failure
message*, never as the assertion — so the work is real. Asserting it today
fails **7 of 19 skills**, requiring ~8,100 tokens of trimming:

| Skill | estimate | ratchet | worst case | trim needed |
|---|---|---|---|---|
| `orchestrating-issue-backlog` | 23,054 | 23,110 | 27,122 | **3,410** |
| `init-socraticode` | 9,758 | 10,050 | 11,480 | 1,216 |
| `curating-context` | 7,485 | 7,600 | 8,806 | 1,025 |
| `managing-skills` | 8,388 | 8,750 | 9,868 | 950 |
| `using-git-worktrees` | 5,854 | 6,000 | 6,887 | 754 |
| `init-project-fastapi` | 12,936 | 14,700 | 15,219 | 441 |
| `reviewing-architecture` | 5,438 | 6,000 | 6,398 | 338 |

That is a campaign several times larger than this entire backlog, and one of
the seven is the file whose own ratchet comment refuses precisely this trade:
*"A ratchet that forces a runbook to omit the rule its own instruction needs is
optimising the wrong quantity."* The issue reasoned about the option without
running it — a grep sizes a surface, only execution measures a behaviour.

So: **option 1** adds an exact-mode job to `context-cadence.yml` (already
weekly, already carries `ANTHROPIC_API_KEY`, ~19 calls) as the gate that
actually fails; **option 3** surfaces `estimate_caveat`'s existing verdict as
an always-on WARN when `worst_case_exact(estimate) > ratchet`, so the blind
spot is visible on every commit instead of only inside a failure message.
Neither adds a red test today. Option 2's rationale is preserved on the issue
as a pointer rather than deleted — it becomes correct the moment the seven
ratchets come down on their own merits.

**#216 → verdict-aware wording.** Keep the line outside the verdict branches —
the statistic is always worth reporting — but select its text from `y.verdict`:
corroboration language when paired with a `low`/`unknown` verdict, a neutral
statement of the statistic when the verdict is `ok`. This answers the issue's
own framing ("corroboration-when-paired, neutral-when-alone") without
suppressing data.

**#214 → a finding, exit 1.** Every other `findings.push` in `cmdHealthCheck`
sets `process.exitCode = 1`, and the field case is a 2.5M docs tree unreachable
via `codebase_context_search` with nothing reporting it. Making the parity gap
informational would reproduce the exact three-green-lights shape the issue is
filed about. The "suppress while an index is in flight" variant was considered
and rejected: it needs a staleness rule the issue does not specify, which would
push Scope back to 1.

## Conflict zones

Followup-derived, low-discovery backlog — all four issues were filed during the
#213 cycle, so the contested files were named before this session started.
Steps 5/6 compressed accordingly; the grep confirmed the map and added two
things no issue body states.

| File | A1 (#216→#214) | A2 (#215) | A3 (#217) |
|---|---|---|---|
| `init-socraticode/scripts/mcp-driver.mjs` | ✓ | | |
| `init-socraticode/references/socraticode-doc.md` | ✓ | | |
| `tests/structural/test_socraticode_policy_split.py` | ✓ | | |
| `tests/structural/test_worktree_root_contract.py` | | ✓ | |
| `tests/structural/test_skill_self_budget.py` | | | ✓ |
| `.github/workflows/context-cadence.yml` | | | ✓ |
| `AGENTS.md` (Self-budget, L195–205) | | | ✓ |

**Zero contested files.** Q0's bundle absorbed the only two, which is what it
was for. No merge ordering constraints within the batch.

### The vacuous-assertion gap in #216's path

`test_socraticode_policy_split.py:353 :: test_graph_health_explains_unresolved_pct`
pins the doc's **Graph health** section *as concepts* — `unresolved`,
`call edge`, `corrobo`, `re-index` — and deliberately not as a sentence. A
sibling test additionally requires `edges/file`. That design is right, and it
means rewording the driver string leaves the test **green while the doc goes
stale**: `socraticode-doc.md:124–126` quotes the current finding string
verbatim, and the test's own docstring at `:356` quotes it again. Nothing
asserts that the doc's quoted string matches what the driver actually emits.

This is the *green* half of the test-surface problem, not the red half. A
keyword sweep cannot find it, because the assertion names neither the literal
being removed nor the one being added. A1 must update all three sites and pin
the doc↔driver agreement so the next reword cannot diverge silently.

### The no-file-overlap edge on `init-socraticode/SKILL.md`

`init-socraticode/SKILL.md` measures 9,758 estimated against a 10,050 ratchet —
**292 tokens of headroom** — and its worst case, 11,480, already exceeds the
ratchet, so A3's new WARN fires on it from day one. If A1 documents its new
health-check finding in `SKILL.md` rather than in `references/`, it breaches
the ratchet: the precise failure #217 exists to catch, committed by the agent
working beside it. There is no file overlap to reveal this edge — only the
budget arithmetic does.

Handled by brief, not by a gate: `references/socraticode-doc.md` is at 3,222 of
its 10,000 per-doc budget and has ample room.

## Dependency graph

```
Batch A — three agents, no edges between them
├── A1  #216 → #214   init-socraticode driver + generated doc   [bundle, sequential commits]
├── A2  #215          worktree-root subdirectory test           [disjoint]
└── A3  #217          budget gate: cadence job + always-on WARN [disjoint]
                                   │
                                   └─ weak edge, brief-handled: A3's WARN fires on
                                      init-socraticode/SKILL.md, which A1 must not touch
```

No chain-appending artifacts this cycle — no migrations, no numbered ADRs, no
sequence-generated files. No byte-for-byte sync test spans two agents; the one
in this file family (the `select:` prefetch, pinned identical between
`socraticode-doc.md:91` and `socraticode-reminder.sh`) is read-only for
everyone, since no issue needs it.

## Batch execution plan

| Batch | Agent | Issues | Files | Gate |
|---|---|---|---|---|
| **A** | **A1** | #216 → #214 | `mcp-driver.mjs`, `references/socraticode-doc.md`, `test_socraticode_policy_split.py` | Start immediately |
| **A** | **A2** | #215 | `test_worktree_root_contract.py` | Start immediately |
| **A** | **A3** | #217 | `test_skill_self_budget.py`, `.github/workflows/context-cadence.yml`, `AGENTS.md` L195–205 | Start immediately |

Single batch, so `batch/a` is a merge target only and the gate is the
post-merge suite run before `main`. Ceiling is 4; three agents fit without
chunking.

**A1 intra-agent ordering: #216 first, then #214.** This is the define→use
sequence that earns the Shape A bundle. #216 settles how a finding phrases
severity and pins the doc↔driver agreement that nothing currently asserts;
#214's new parity finding then inherits both the convention and the pin.
Reversed, #214 writes a finding against a wording convention that changes under
it, and the doc↔driver pin arrives after the string it was meant to protect.

## Key decisions

**Read-only shared files.**

- `tests/structural/test_skill_self_budget.py` — **A3 only.** It is the file
  every agent's `pytest tests/structural/` run executes, which makes it this
  batch's foundation shared file regardless of its kind. A1 and A2 have no
  reason to touch it and must not; a necessary edit becomes a post-merge PR.
- `skills/init-socraticode/SKILL.md` — **read-only for A1**, per the budget
  arithmetic above. New prose goes to `references/socraticode-doc.md`.
- `socraticode-doc.md:91` (the `select:` prefetch string) — read-only for all
  three. It is asserted byte-identical against `scripts/socraticode-reminder.sh`.

**Single chain-appending agent: none required.** No artifact in this batch
appends to a linear chain.

**Verification-mode asymmetry — two of them, both real.**

1. A3 changes what the budget gate emits. A1 and A2 verify under the *old* gate
   inside their own worktrees, so the orchestrator's run against `batch/a` is
   the first execution under the new WARN — and on day one that WARN fires on
   seven skills, `init-socraticode` among them, whose file A1 was briefed not to
   touch. **Warnings on those seven at the gate are A3's change working as
   designed, not a defect in A1's work.** Recording it here so the interaction
   is not misattributed to one agent's diff.
2. A3's new `context-cadence.yml` job is schedule-triggered, so **no batch gate
   exercises it.** Its first real execution is post-merge on the weekly
   schedule. A3 must verify the job's shape statically — workflow parses, the
   `ANTHROPIC_API_KEY` secret is wired the way the existing jobs wire it, the
   command is the one the test file documents — and say in its report that it
   did so, rather than reporting a green suite as though the job had run.

**Report-back arithmetic.** Baseline is `2991 passed, 159 skipped`. Each worker
reports its own collected count rather than a bare "green"; the merged gate must
equal 2991 plus the three agents' additions. N verdicts cannot be reconciled
against each other, N counts can — and a stale briefed baseline then surfaces as
arithmetic rather than being silently adopted.

**Why #217 is not isolated in its own batch.** It changes a file every other
agent's verification runs, which is an argument for a gate. It was rejected
because the WARN fails nothing: the asymmetry is an attribution problem, solved
by naming it here, not a correctness problem. Isolating it would roughly double
wall-clock for work that is verified file-disjoint.

## Runtime note on issue-body decay

This backlog is three concurrent mutations of the tree the bodies describe, and
the bodies are already one cycle old. Every worker treats its issue body as a
**proposal, not a specification**: verify every file:line, every claimed call
site, and every prescribed implementation against the current tree before
acting, and **report the correction rather than implementing around it
silently**.

This session has already found three material body errors before any agent
launched — #217's recommended option is falsified by measurement, #214's
"the `codebase_context` call it effectively already makes" is a call
`cmdHealthCheck` does not currently make at all, and #216's part 2 is blocked on
an issue outside the named set. The direction of every body was right; the
specifics were not. Expect more of the same, and say so.

## Deferred items

- **#207** — retire the local edge-yield arithmetic once upstream
  giancarloerra/SocratiCode#112 ships an import-resolution advisory. Re-verified
  this session: the PR is still `open` and unreleased (v1.12.0, 2026-08-14,
  predates it). Now additionally carries **#216's part 2**, the acknowledgement
  mechanism for a structurally-high repo, since #216's own sequencing note
  identifies #207 as the thing that may make the local statistic moot.
  Unblocks when a release carries the advisory.

## Out of scope

- **#218** — `curating-context`'s `write-guard-hook.md` pastes a block from
  `continuous-surfaces.md` that also restates the bullet above it. Filed in the
  same minute as #217 but outside the named #214–217 range. It is fully
  file-disjoint from all three agents (`curating-context/references/`), so it
  would be a parallel-safe fourth slot under the ceiling of 4 if pulled in later.
- **Option 2 of #217** — asserting `worst_case_exact()` against the ratchet.
  Not rejected on merit; rejected on measured cost today. Preserved on the issue
  as a pointer, and it becomes the correct move once the seven ratchets in the
  table above come down on their own merits.
- **`tests/structural/test_policy_surface_budget.py`** — mirrors
  `test_skill_self_budget.py`'s opt-in exact design for `AGENTS.md` and the
  `docs/` surfaces, so the same blind spot plausibly applies there. #217 does not
  ask for it and no breach has been observed on that surface. A3 should **name
  it in its report** rather than silently expanding scope to cover it.
