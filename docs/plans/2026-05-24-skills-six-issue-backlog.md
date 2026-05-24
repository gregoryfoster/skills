# Skills repo: six-issue backlog clearance (Batch F)

## Goal

Clear six open issues (#26, #27, #28, #30, #31, #33) in a single parallel batch. The set spans two downstream-blocking bug fixes (worktree-destroy process leaks; pre-ship.sh npm script assumption), one detection-only janitor script, structural tests for the `references/` convention, the convention itself, and a default-text tightening in `doc-check.sh`. All six are file-disjoint at minimum scope and can ship as one batch with no intra-batch sequencing.

## Approved approach

- **Single batch** (`batch/f`) with 6 worker agents running in parallel under `isolation: "worktree"`.
- **Worktree provisioning ceiling:** 6 (matches batch size). Repo has no custom `worktree-create.sh` wrapper, no port pool, no docker — plain `git worktree add`. Pytest runs against ephemeral fixtures.
- **Intra-batch worker → batch/f integration:** fast-forward / regular merge (fixed by the orchestrator skill's Iron Law for the destroy script's ancestor check).
- **Batch → main merge strategy:** regular merge commit (preserves per-agent history).
- **Worker branches:** `feature/batch-f-<issue>`.

## Prioritization rubrics

User selected "Correctness above all" → Correctness weight × 3.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures, real downstream breakage |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation obvious from issue |

**Formula:** `Score = (Foundation × 2) + (Correctness × 3) + Scope`, max 18.

Blast radius drives sequencing, not score (all six are Low blast — none touch shared files).

## Scored backlog

| Rank | # | Title | F | C | S | **Score** | Blast |
|---|---|---|---|---|---|---|---|
| 1 | #28 | worktree-destroy.sh leaks dev-server processes | 2 | 3 | 3 | **16** | Low |
| 2 | #27 | pre-ship.sh assumes npm scripts exist | 1 | 3 | 3 | **14** | Low |
| 3 | #30 | structural tests for `references/` (no-orphan + linked-file-exists) | 2 | 2 | 3 | **13** | Low |
| 3 | #31 | bundle `audit-worktree-zombies.sh` | 2 | 2 | 3 | **13** | Low |
| 5 | #26 | research + codify `references/*.md` conventions | 2 | 1 | 1 | **8** | Low |
| 5 | #33 | doc-check.sh DOC_SECTIONS default tightening | 1 | 1 | 3 | **8** | Low |

## Conflict zones

Only one zone surfaces overlap, and it is procedurally resolved:

- [skills/using-git-worktrees/SKILL.md](../../skills/using-git-worktrees/SKILL.md) — potentially edited by both #28 (to mention improved destroy behavior) and #31 (to document the new audit script).
  - **Resolution:** F4 (#31) owns all SKILL.md edits in this zone. F1 (#28) modifies `worktree-destroy.sh` only; the improved destroy behavior is documented in the commit message and the script's inline comments. SKILL.md does not need to chronicle internal fixes.

All other issues touch disjoint files.

## Dependency graph

```
#26 ──┐
#27 ──┤
#28 ──┤
#30 ──┼──► all independent, all run in parallel
#31 ──┤
#33 ──┘

Soft (informational, not file-level):
  #26 → #30   #30's narrow tests are agnostic to convention shape;
              any convention-specific assertions are a follow-up.
  #28 → #31   #31 is detection-only and does not import #28's code path;
              the pairing is narrative.
```

## Batch execution plan

### Batch F — 6 parallel agents, start immediately

| Agent | Issue | Files (write) | Scope notes |
|---|---|---|---|
| F1 | #28 | [skills/using-git-worktrees/scripts/worktree-destroy.sh](../../skills/using-git-worktrees/scripts/worktree-destroy.sh) | `pgrep -f $WORKTREE_PATH` block before `git worktree remove`; keep `.port` fallback; optional post-removal warn-only sweep. **No SKILL.md edits** (ceded to F4). |
| F2 | #27 | [skills/shipping-work-python-fastapi/scripts/pre-ship.sh](../../skills/shipping-work-python-fastapi/scripts/pre-ship.sh) | `has_script` probe (issue's recommended approach). Replace lines 126–138 only. |
| F3 | #30 | new [tests/structural/test_references.py](../../tests/structural/test_references.py) | Two narrow assertions only: `test_referenced_files_exist` + `test_no_orphan_references`. Out of scope: length cap, frontmatter, parameter-row → Phase-header check. |
| F4 | #31 | new [skills/using-git-worktrees/scripts/audit-worktree-zombies.sh](../../skills/using-git-worktrees/scripts/audit-worktree-zombies.sh) + [skills/using-git-worktrees/SKILL.md](../../skills/using-git-worktrees/SKILL.md) | Owns all SKILL.md edits in this zone. **Defer** the `worktree-create.sh` preamble hook and the `pre-ship.sh` wiring (called out as optional in the issue) to a follow-up to keep the diff narrow. |
| F5 | #26 | [AGENTS.md](../../AGENTS.md) addition (new "References convention" section); [skills/orchestrating-issue-backlog/references/recovery.md](../../skills/orchestrating-issue-backlog/references/recovery.md) (align to agreed convention) | Pick AGENTS.md addition over a new ADR file (no ADR convention exists yet). Establish: no frontmatter; every references file linked from its sibling SKILL.md; no length cap. |
| F6 | #33 | [skills/shipping-work-python-click/scripts/doc-check.sh](../../skills/shipping-work-python-click/scripts/doc-check.sh) | DOC_SECTIONS default text tightening only. **Defer** the equivalent fix in `shipping-work`, `shipping-work-php`, `shipping-work-python-fastapi` (issue scope is click only). |

**Gate:** start immediately. After all six workers signal, orchestrator runs `pytest tests/structural/ -v` against `batch/f` and notifies the user for review.

## Key decisions

- **One batch, not waves.** All six issues touch disjoint files, and the ceiling is 6 — no benefit to splitting into sub-waves.
- **F4 owns SKILL.md exclusively.** Cheapest way to eliminate the only contested file. F1 documents its behavior in the script and commit message.
- **#26's convention is scoped tightly** (no-frontmatter, linked-from-parent, no length cap) so F5's work doesn't fan out into a multi-week design process. The narrow conventions are exactly what #30's structural tests need.
- **#33 stays scoped to the click variant.** The issue itself notes equivalent fixes likely warranted in three other variants but explicitly leaves them out of scope. Expanding here would inflate the diff with no Correctness payoff (this is the lowest-scoring issue in the batch).
- **#31 ships as detection-only.** The issue lists `worktree-create.sh` preamble integration and `pre-ship.sh` wiring as optional. Both are good ideas but would force F4 into files (`worktree-create.sh`) that risk diff bloat for low Correctness gain. Detection-only is the merge-safe minimum that delivers the audit signal.
- **Correctness × 3 ranks #28 first.** The downstream forensics (40 stale processes, 2 root-owned burning 40% CPU each in address-validator#120) demonstrated real cost that Foundation × 3 weighting would have hidden under the convention/test work.

## Deferred items

Explicitly excluded from this orchestration:

- **#33 sibling variants** — equivalent `doc-check.sh` default tightening in `shipping-work`, `shipping-work-php`, `shipping-work-python-fastapi`. File a follow-up issue if cross-variant consistency matters.
- **#31 wiring** — `worktree-create.sh` preamble call and `pre-ship.sh` zombie-warn integration. Both are explicitly optional in the issue; ship as follow-ups if operators want the soft check.
- **#26 broader convention questions** — length cap, frontmatter, parameter-row → Phase-header assertions. Out of scope per #30's "Out of scope" section.

## Out of scope

- Host-project port-pool widening (filed against `cannabis.observer-wordpress#279` follow-up).
- Any additional skills or variants beyond the six issues listed.
- Migration of other `references/*.md` files if any are added before F5 lands (recovery.md is the only one at orchestration time).
