# Skills repo: Batch F follow-ups (Batch G)

## Goal

Clear four follow-up issues filed during Batch F's ship report (#35, #36, #37, #38). Three are cross-variant propagations of patterns Batch F established in single variants (#35 follows #33, #36 follows #27, #37 wires #31); the fourth (#38) removes a documented limitation in the #31 audit script. All four are file-disjoint after bundling #36 + #37's pre-ship-layer work into a single agent.

## Approved approach

- **Single batch** (`batch/g`) with 4 worker agents running in parallel under `isolation: "worktree"`.
- **Worktree provisioning ceiling:** 6 (same repo as Batch F; no custom wrapper). Cap is the issue count.
- **Intra-batch worker → batch/g integration:** FF / regular merge (fixed by orchestrator skill's Iron Law).
- **Batch → main merge strategy:** regular merge commit (same as Batch F, preserves per-agent history).
- **#36 + #37 pre-ship work bundled in G1** to eliminate a 3-file conflict zone in `shipping-work*/scripts/pre-ship.sh`.
- **#37 worktree-create piece split into G2** because its code shape differs from the pre-ship gate-script discipline and the file is uncontested.

## Prioritization rubrics

User reaffirmed Batch F's weighting: "Correctness above all" → Correctness × 3.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures, real downstream breakage |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation obvious from issue |

**Formula:** `Score = (Foundation × 2) + (Correctness × 3) + Scope`, max 18.

## Scored backlog

| Rank | # | Title | F | C | S | **Score** | Blast |
|---|---|---|---|---|---|---|---|
| 1 | #36 | pre-ship.sh `has_script` probe across sibling variants | 2 | 3 | 3 | **16** | Med |
| 2 | #37 | wire audit-worktree-zombies into worktree-create + pre-ship | 3 | 2 | 2 | **14** | Med-High |
| 3 | #38 | audit script honors WORKTREE_ROOT resolver | 2 | 2 | 2 | **12** | Low |
| 4 | #35 | doc-check.sh DOC_SECTIONS alignment across variants | 1 | 1 | 3 | **8** | Low |

## Conflict zones

| File | Issues | Resolution |
|---|---|---|
| `shipping-work/scripts/pre-ship.sh` | #36 + #37 | Bundle into G1 |
| `shipping-work-php/scripts/pre-ship.sh` | #36 + #37 | Bundle into G1 |
| `shipping-work-python-click/scripts/pre-ship.sh` | #36 + #37 | Bundle into G1 |
| `shipping-work-python-fastapi/scripts/pre-ship.sh` | #37 only | Owned by G1 (#37 piece only — #36 doesn't touch FastAPI; #27 already landed there) |
| `using-git-worktrees/scripts/worktree-create.sh` | #37 only | Owned by G2 |
| `using-git-worktrees/scripts/audit-worktree-zombies.sh` | #38 only | Owned by G4 |
| 3× `doc-check.sh` (baseline, -php, -python-fastapi) | #35 only | Owned by G3 |

All real overlaps resolved by single-owner assignment (G1) — same pattern that worked for Batch F's contested SKILL.md.

## Dependency graph

```
#35 ──┐
#36 ──┤  (#36 + #37 pre-ship piece bundled in G1; #37 worktree-create in G2)
#37 ──┼──► all 4 agents run in parallel
#38 ──┘

Soft (informational, not file-level):
  #38 → #37   ideally #38 lands first so #37's wiring calls the resolver-aware
              audit script, BUT the wiring invokes `bash audit-worktree-zombies.sh
              --quiet` — call site doesn't depend on internal changes. Independent
              in practice.
```

## Batch execution plan

### Batch G — 4 parallel agents, start immediately

| Agent | Issue(s) | Files (write) | Scope notes |
|---|---|---|---|
| G1 | #36 + #37 (pre-ship) | All 4 `shipping-work*/scripts/pre-ship.sh` | Two layers: (1) #36 `has_script` + JSON validation in 3 non-FastAPI variants; (2) #37 audit pre-flight WARN in all 4. **Two commits recommended** (`#36 fix:`, `#37 feat:`) for clean issue traceability. |
| G2 | #37 (worktree-create) | [skills/using-git-worktrees/scripts/worktree-create.sh](../../skills/using-git-worktrees/scripts/worktree-create.sh) | Audit preamble WARN call near top, before provisioning. Detection-only — non-zero from audit becomes WARN, not hard stop. |
| G3 | #35 | 3× [doc-check.sh](../../skills/shipping-work/scripts/doc-check.sh) (baseline, -php, -python-fastapi) | One-line DOC_SECTIONS README replacement per file. Exact wording from #33's Click-variant precedent. **Out of scope**: SENSITIVE_PATHS, AGENTS.md line, project-override comment block at L19–20. |
| G4 | #38 | [skills/using-git-worktrees/scripts/audit-worktree-zombies.sh](../../skills/using-git-worktrees/scripts/audit-worktree-zombies.sh) | Source `resolve-worktree-root.sh`; pgrep filter + existence check use the resolved root; remove the script-header limitation note. Default fallback to `<project-root>/.worktrees/` preserved (the resolver's step 3). |

**Gate:** start immediately. After all 4 workers signal, orchestrator runs `pytest tests/structural/ -v` against `batch/g`.

## Key decisions

- **#36 + #37 bundled in G1.** Splitting would force rebase ceremony on 3 contested pre-ship.sh files with no benefit. Bundling reads each file once and lands a coherent diff.
- **G1's two-commit split** keeps each commit attributable to one issue, which matters for the closing comments in the ship phase.
- **G2 is small but separate.** The worktree-create.sh hook is a 5-line addition on an uncontested file with different code shape (provisioning logic, not gate-script discipline). Keeping it isolated avoids context-switching for the G1 agent.
- **#35 stays separate from G1** despite being adjacent in spirit. Different files, no conflict — bundling adds no value.
- **No #38 → #37 sequencing required.** The wiring invokes the audit script by path; internal changes are transparent to callers. Parallel is safe.

## Deferred items

Explicitly excluded from this orchestration:

- **#37 path-resolution edge cases for vendored layouts** — the wiring uses `skills/using-git-worktrees/scripts/audit-worktree-zombies.sh` from the consuming project's repo root, falling back silently if not found. A more elaborate vendor-aware resolver could be filed if downstream usage demands it.
- **#38 broader resolver enhancements** — only the worktree-root lookup is wired through. If `audit-worktree-zombies.sh` ever needs other resolver outputs (port pools, env files), that's a follow-up.

## Out of scope

- Any new variants or skills.
- Backport of Batch F changes to projects vendoring this skill (consumers self-update on `git submodule update --remote`).
