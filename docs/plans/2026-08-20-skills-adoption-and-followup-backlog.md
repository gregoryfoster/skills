# Backlog orchestration — the #199 followups and the cohort adoption feedback

Tracking issue: [#213](https://github.com/gregoryfoster/skills/issues/213)
Session: 2026-08-20 · Orchestrated with `orchestrating-issue-backlog`

## Goal

Clear thirteen of the fourteen issues in #198, #200–212 — five filed by agents
during the #199 backlog execution (#200, #202–205), six adoption feedback from
cohort repos (#198, #201, #206, #208–211), one new-skill proposal distilled from
two ad-hoc CI-cost audits (#212) — as nine work items across three merge-safe
batches. #207 is deferred on an upstream blocker. The dominant failure shape
repeats #199's: guidance that is wrong as written, consumed daily by twelve
cohort repos.

## Approved approach

- **Rubric**: `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Third
  consecutive Correctness-×3 session; same justification.
- **Deployment context**: active production (Q2) — cohort repos pull daily.
- **Deferrals**: #207 only (Q3) — hard-blocked on upstream
  giancarloerra/SocratiCode#112, which is OPEN and unreleased (latest v1.12.0
  predates it). Unblocks when a release carries it.
- **Parallelism**: hybrid (Q4) — parallel within batches, merge-and-test gate
  between, all workers in `isolation: "worktree"`.
- **Concurrency ceiling: 4 per batch, host-bound** (Q5). **Fourth consecutive
  negative result** (2026-08-12, -16, -18, now -20). Re-verified:
  `worktree-create.sh` is plain `git worktree add`; no `conftest.py` in
  `tests/`; `addopts = -m 'not integration and not benchmark'`; the
  backing-service escape grep hits only `init-project-fastapi` template
  content. Cap is CPU/RAM for a ~168-second hermetic suite × N.
- **Merge strategy**: regular merge commit, batch → `main`. Intra-batch
  worker → batch fixed at FF/regular merge (preserves
  `worktree-destroy.sh --base` ancestor check).
- **Suite baseline on `main` (`072e3d2`)**: **2793 passed, 153 skipped**, 168s,
  via `.venv/bin/python -m pytest tests/structural/`. Every worker brief
  carries this number with "stop and report if it does not match."

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** ×2 | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** ×3 | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** ×1 | Requires design discovery | Clear direction, minor decisions needed | Mechanical — obvious from the issue |

## Scored backlog

Final scores after the decide-then-rescore pass (#206 S1→2 on the backfill
decision; #201 S2→3 on the knob decision).

| # | Issue | F | C | S | **Score** | Blast | Batch |
|---|---|---|---|---|---|---|---|
| **#198** | `socraticode-doc.md` never explains `unresolvedPct`; the daily hook line reads as a defect | 1 | 3 | 3 | **14** | Med | A1 |
| **#208** | `ParamType.callback()` does not exist; the review dimension recommends an unreachable API | 1 | 3 | 3 | **14** | Low-Med | A2 |
| **#210** | `docs/SOCRATICODE.md` re-run silently destroys repo-specific content | 1 | 3 | 2 | **13** | Med | A1 |
| **#202** | `resolve-plans-dir.sh` nests in worktrees; untracked `plans_dir` knob silently ignored | 1 | 2 | 3 | **11** | Low-Med | A3 |
| **#209** | prefetch omits `codebase_graph_circular`, which the same doc's table recommends | 1 | 2 | 3 | **11** | Med | A1 |
| **#200** | generalize `install-refresh.sh` into one hook installer | 3 | 1 | 2 | **11** | High | B1 |
| **#211** | documented `load_env()` snippet should declare its locals — **all four variants** | 1 | 2 | 3 | **11** | Low | A4 |
| **#201** | worktree venv-link opt-out (`.skills/worktree_venv` knob) | 1 | 2 | 3 | **11** | Low-Med | B2 |
| **#206** | telemetry `repo_commit` lags the tree it describes — backfill fix | 1 | 2 | 2 | **10** | Low-Med | B3 |
| **#203** | `resolve-worktree-root.sh` nests in a linked worktree of a submodule — document-and-close | 1 | 1 | 3 | **8** | Low | A3 |
| **#205** | 'advisory is not a veto' sits under the wrong heading | 1 | 1 | 3 | **8** | Low | B4 |
| **#204** | `cadence.md` pastes two paragraphs its own sections already make | 1 | 1 | 2 | **7** | Low | B4 |
| **#212** | new skill: `auditing-ci-cost` | 1 | 1 | 2 | **7** | Low (new files) | C1 |
| **#207** | retire edge-yield workaround for the upstream advisory | — | — | — | **deferred** | — | — |

### Q0 dispositions

- **#198+#209+#210 → bundled (A1)**, the adoption-feedback owning-file pattern:
  all three edit `references/socraticode-doc.md`. One agent, sequential
  commits, one review surface.
- **#204+#205 → bundled (B4)**: same skill, same judgement kind, and #204's
  same-shape sweep overlaps #205's target region in `write-guard-hook.md`.
- **#203 → #202 → bundled (A3), #203 first**: #202 ports the implementation
  and its "Two traps" comment from `resolve-worktree-root.sh`; #203 amends
  that comment. Settle the boundary, then port the settled version.
- **#207 → deferred**: upstream PR #112 unmerged, no release. The issue's own
  instruction ("do not start until it lands and a release carries it") governs.
- No duplicates — every bundle is distinct work sharing a file.

### Gate decisions (decide-then-rescore)

- **#206 → option 1 (backfill)**: `record-telemetry.sh` accepts
  `--repo-commit`; Phase 7 backfills after the commit (a rewrite-within-run
  `telemetry.md` already permits). Most faithful to the field's two documented
  meanings. Options 2 (tree hash) and 3 (redefine as run-start) rejected —
  rationale preserved in the issue comment.
- **#209 → add the three `codebase_graph_*` inspection tools** to both pinned
  copies of the prefetch string, making the prefetch a superset of every tool
  the doc recommends. The annotate-the-table-row alternative rejected: every
  future table addition would have to remember the annotation.
- **#201 → `.skills/worktree_venv` file knob** (`link` | `none`), matching the
  `.skills/worktree_root` convention. Env-var shape rejected (per-shell, not
  per-project). The knob doc must say to **track** the file — #202 proves
  untracked `.skills/` entries are invisible in linked worktrees.

## Conflict zones

| Contested surface | Issues | Resolution |
|---|---|---|
| `init-socraticode/references/socraticode-doc.md` | #198, #209, #210 | Bundled → single writer (A1) |
| `init-socraticode/SKILL.md` Phase 3 (L135–199) | #210 and #200 (hook-install prose L174–187 is *inside* Phase 3) | Sequence: A1 before B1 |
| `tests/structural/test_reminder_hook_vendored.py` | #209 (prefetch pins :65/:148 + doc↔script sync test :120) and #200 (install-half :136–155) | Same edge: A1 before B1 |
| `tests/structural/test_content_invariants.py` | #208 (~:1011–1016, batch A), #201 (~:430–465, batch B) | Different batches; windows separated anyway |
| 4× `shipping-work*/scripts/pre-ship.sh` + `test_pre_ship_env_override.py` | #211 only — the body names one variant but the consistency test (:76) forces all four | Single writer (A4) |
| curating-context | #206 (scripts + SKILL.md Phase 7 + telemetry.md + test_context_surface.py + test_arm_predicate.py) vs #204/#205 (references/cadence.md, write-guard-hook.md) | File-disjoint → parallel in B |
| `using-git-worktrees/` | #201 (worktree-create.sh, SKILL.md) vs A3 (resolve-worktree-root.sh, contract test) | File-disjoint, different batches anyway |
| README.md skills table | #212 (one new row) | Single writer (C1) |

No chain-appending artifacts this cycle. The one byte-sync hazard (prefetch
string pinned in doc and reminder script, asserted equal by
`test_reminder_hook_vendored.py:120`) is contained inside A1.

## Dependency graph

```
A1 (#198+#209+#210) ──► B1 (#200)     [SKILL.md Phase 3 + reminder-test surface]
A3: #203 ──► #202                     [intra-agent commit order]
#207 ▸ deferred (upstream SocratiCode#112 unmerged)
all other pairs: disjoint
```

## Batch execution plan

| Batch | Agent | Issues | Files owned | Gate |
|---|---|---|---|---|
| A | A1 | #198+#209+#210 | `skills/init-socraticode/**` + test_socraticode_policy_split.py, test_reminder_hook_vendored.py | Start immediately |
| A | A2 | #208 | `skills/reviewing-code-python-click/SKILL.md` + test_content_invariants.py :1011–1016 | Start immediately |
| A | A3 | #203→#202 | resolve-worktree-root.sh, resolve-plans-dir.sh, test_worktree_root_contract.py | Start immediately |
| A | A4 | #211 | 4× pre-ship.sh + test_pre_ship_env_override.py | Start immediately |
| B | B1 | #200 | `skills/managing-skills/scripts/**`, init-socraticode install prose, test_refresh_hook_install.py, test_guard_install_paths.py, test_reminder_hook_vendored.py (install half) | After A merged |
| B | B2 | #201 | worktree-create.sh, using-git-worktrees/SKILL.md, test_content_invariants.py :430–465 | After A merged |
| B | B3 | #206 | record-telemetry.sh, curating-context SKILL.md Phase 7, telemetry.md, test_context_surface.py, test_arm_predicate.py | After A merged |
| B | B4 | #204+#205 | cadence.md, write-guard-hook.md (+ same-shape sweep of curating-context/references) | After A merged |
| C | C1 | #212 | new `skills/auditing-ci-cost/**` + one README.md row | After B merged |

Intra-agent ordering:
- **A1**: #209 first (mechanical, both pinned copies + sync test), then #198
  (Graph health paragraph), then #210 (marker region + Phase 3 rescue logic).
- **A3**: #203 first (boundary comment + pinning test), then #202 (port the
  settled implementation).

## Key decisions

- **A1 → B1 is the only cross-batch edge.** #200 rewrites install prose that
  lives inside the same SKILL.md Phase 3 that #210 restructures, and the same
  test file whose prefetch pins #209 moves. B1's brief must re-read both
  surfaces post-merge — the issue body predates A1.
- **#198's wording anticipates #207.** Per #207's note, the unresolvedPct
  paragraph should point toward the coming upstream advisory as the eventual
  yield signal rather than teaching unresolvedPct as one — without depending
  on unreleased upstream behavior.
- **#211 widened to all four variants** by
  `test_pre_ship_env_override.py:76` (`discovered == ALL_VARIANTS`); the
  agent should add a `local line key val` assertion to the block-consistency
  suite so the fix cannot regress per-variant.
- **B4 briefed on the phrase pin** at `test_demoted_blocks.py:293`
  (`**measurement, not a curation**`) — the cadence.md delete is safe only
  because the `##` section copy at :10 survives; verify, don't assume.
- **#206 changes what `test_arm_predicate.py:242–272` pins** (`repo_commit`
  naming what is derived from it). The backfill must keep that contract true —
  re-anchor the assertions on the post-backfill meaning and keep them
  non-vacuous.
- **C1 is a single-agent batch** → no batch branch; its feature branch serves
  directly. The new skill must pass the generic per-skill structural suites
  (test_schema.py, test_naming.py, test_scripts.py, test_references.py) that
  enumerate `skills/` automatically.
- **No verification-mode asymmetry this cycle** — no agent changes the test
  runner's config.
- **Read-only declarations**: A1's merged `socraticode-doc.md` and Phase 3 are
  read-only for B2–B4 (only B1 may touch init-socraticode, per its brief).

## Runtime note on issue-body decay

The backlog is N sequential mutations of what the bodies describe. B1's body
(#200) is the most exposed — it describes install surfaces A1 rewrites.
Workers in B and C must re-verify any file:line their issue cites against the
merged batch branch (Worker step 5); the later the batch, the staler the body.
Precedent: in the #144 backlog every one of 13 bodies carried a material
error.

## Deferred items

- **#207** — retire the edge-yield workaround in favor of the server's
  import-resolution advisory. Blocked on upstream
  giancarloerra/SocratiCode#112 (OPEN, unreleased as of 2026-08-20). Re-check
  at the next backlog session; unblocks when a release carries the advisory.

## Out of scope

- Closing #199 (the prior tracking issue) — its execution journal shipped in
  `072e3d2`; closure is bookkeeping outside this plan.
- Any edit to the `unresolvedPct` gate logic in `mcp-driver.mjs` — #198 is a
  documentation fix; the gate itself is correct and stays.
- Upstreaming #211 to CannObserv/wslcb-licensing-tracker (already applied
  there as d5c13a7); this plan fixes the skill's four variants only.
