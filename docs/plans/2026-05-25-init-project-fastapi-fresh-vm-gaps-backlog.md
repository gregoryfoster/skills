# `init-project-fastapi` fresh-VM gaps — backlog orchestration

## Goal

Clear the four gaps in `init-project-fastapi` surfaced by the 2026-05-25 fresh-VM bootstrap of `CannObserv/usa-wa` (pinned to `gregoryfoster/skills@93063f2`), so the next operator running the skill against a clean Ubuntu 24.04 VM with `DB_BACKED=yes` completes Phase 12 with a verified database path and no permanent dangling symlinks in the obra submodule.

## Approved approach

Two parallel agents in a single batch (`batch/h`):

- **H1** ships #42 (missing `httpx` dev dep) — one-line edit to `references/pyproject-toml.md`.
- **H2** ships #43 → #41 → #44 as three sequential commits on one branch. #43's `PROJECT_UNDERSCORE` convention lands first so #41's new Phase 5d Postgres provisioning inherits it.

Both agents use `isolation: "worktree"` with no host-project provisioning ceiling (plain `git worktree add`). The orchestrator checks out `batch/h` before spawning agents (Rule 3) so both outputs accumulate on the batch branch. After human review, `batch/h` merges to `main` via regular merge commit (`--no-ff`), matching the precedent set by `batch/f` and `batch/g`.

**Effective worktree ceiling:** none. Repo has no Lima VM, Nginx vhosts, or port pool. 2-agent parallelism is well under any conceivable git-side limit.

## Prioritization rubrics

User adjusted the standard formula to weight Correctness above Foundation, on the grounds that this skill is a bootstrap surface — downstream consumers pin to a SHA and silent failures during fresh-VM runs are the worst failure mode.

**Score = (Foundation × 2) + (Correctness × 3) + Scope**, max 18.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, **silent failures** |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation is obvious from the issue |

Blast radius drives sequencing, not score.

## Scored backlog

| # | Title | F | C | S | **Score** | Blast | Notes |
|---|---|---|---|---|---|---|---|
| **#41** | Phase 5d Postgres provisioning + Phase 12/14 nits + push.sh -u | 3 | 3 | 1 | **16** | Med | Today swallows `ConnectionRefusedError` via `\|\| true` — DB path unverified on every fresh VM. Phase 5d is a new phase with real design choices. |
| **#44** | Phase 10 `ln -s` collision → `ln -sfn` | 1 | 3 | 3 | **14** | Low | Silent failure: second vendor discarded, permanent dangling symlink in obra submodule, `git status` perpetually dirty. |
| **#43** | alembic.ini hyphen-DSN → `PROJECT_UNDERSCORE` | 2 | 2 | 3 | **13** | Low | Foundation for #41's Phase 5d (same underscore form provisions the real DB). |
| **#42** | `httpx` missing from dev deps | 1 | 2 | 3 | **11** | Low | One line in one file. Loud failure (import error on `uv run pytest`), not silent. |

All four were surfaced by the same 2026-05-25 `CannObserv/usa-wa` bootstrap run. None are closed by recent commits (last merge: #40 managing-skills hook).

## Conflict zones

| File | Touched by | Required merge order |
|---|---|---|
| `init-project-fastapi/SKILL.md` | #41 (Phases 5c, 5d, 12, 14), #43 (Phase 5c), #44 (Phases 10, 11) | Single agent, sequential commits: #43 → #41 → #44 |
| `init-project-fastapi/references/database-scaffolding.md` | #41 (Phase 5d references), #43 (alembic.ini fallback) | Same agent handles both |
| `init-project-fastapi/references/pyproject-toml.md` | #42 only | Isolated — H1 |
| `shipping-work/scripts/push.sh` | #41 only | Isolated to H2 (different skill, no concurrent edits) |

**Rationale for the chosen serialization within H2:**

1. **#43 first** — establishes the `PROJECT_UNDERSCORE` derivation. Phase 5d (#41) creates the role and databases using SQL identifiers, which fail for hyphenated project names without the underscore form. Landing #43 first means #41's Phase 5d inherits the correct convention rather than reinventing it.
2. **#41 second** — Phase 5d uses underscore form from commit 1. Also bundles the three smaller nits (Phase 12 `--no-cov`, Phase 14 GitHub-default-LICENSE divergence, `shipping-work/push.sh -u`).
3. **#44 third** — mechanical fix to Phases 10 and 11. Functionally independent of #43/#41; placed last because it's the most pattern-replacement-shaped of the three.

H1 (#42) is fully file-disjoint from H2 — different skill (`init-project-fastapi/references/pyproject-toml.md` vs. SKILL.md + database-scaffolding + shipping-work) — so they run in parallel without any merge ceremony at the batch branch.

## Dependency graph

```
                Batch H (2 agents in parallel)
              ┌──────────────────────────────┐
              │                              │
              ▼                              ▼
         Agent H1                       Agent H2
          #42                       #43 ─▶ #41 ─▶ #44
   (pyproject.toml: httpx)    (3 sequential commits, one branch)
              │                              │
              └──────────────┬───────────────┘
                             ▼
                       batch/h branch
                  (orchestrator merges both)
                             │
                             ▼
               human review → merge to main (--no-ff)
```

## Batch execution plan

| Batch | Issues | Agents | Files | Gate |
|---|---|---|---|---|
| **H** | #42, #43, #41, #44 | 2 (parallel) | H1: `pyproject-toml.md` <br/> H2: `SKILL.md`, `database-scaffolding.md`, `shipping-work/scripts/push.sh` | Start immediately |

**Branches:**

- Worker H1: `feature/batch-h-42-httpx-dev-dep`
- Worker H2: `feature/batch-h-init-fastapi-bundle`
- Integration: `batch/h`

**Worker → batch/h merge:** fast-forward or regular merge (Rule 3, never squash/rebase — required for the `worktree-destroy.sh --base batch/h` Iron Law check).

**Batch → main merge:** regular merge commit (`--no-ff`). Preserves per-issue commit history matching `batch/f` and `batch/g` precedent.

**Gate after H:** human review on `batch/h` — full test suite, scan the combined diff, optionally manual smoke if you have a fresh VM handy. Then `git checkout main && git merge --no-ff batch/h && git push origin main`.

**Policy questions for H2 to raise at implementation time:**

- **#44 collision policy.** Issue offers two options: A (`ln -sfn`, last vendor wins, atomic) and B (check-before-link, first vendor wins, warns). Issue text notes CannObserv's `using-git-worktrees` and `writing-plans` are project-specific customizations that "likely should beat the obra defaults" — argues for `ln -sfn` with current loop order (obra first → gregoryfoster overrides). H2 should confirm with user before coding.
- **#41 Phase 5d parameter name.** Issue suggests `PROVISION_POSTGRES`. Default `yes`. H2 can ship with that unless user prefers otherwise.

## Key decisions

- **Correctness×3 weighting.** This is a bootstrap-surface skill — silent failures during fresh-VM runs are the worst failure mode. Foundation is still doubled but correctness leads.
- **Pre-production runway for the skill itself.** Downstream consumers (CannObserv repos) pin to a SHA when bootstrapping, so changes here don't break running services. This gives us runway to introduce a new phase (Phase 5d) without backward-compat ceremony.
- **#41 bundles its three nits rather than splitting them out.** All four sub-changes (Phase 5d, Phase 12 `--no-cov`, Phase 14 divergence, `push.sh -u`) came from the same fresh-VM run. Splitting would create extra merge ceremony without reducing risk — they're all touched by one agent (H2) anyway.
- **#43 leads #41 inside H2, not its own earlier batch.** Both touch the same file (`SKILL.md`). Putting them in one agent with the underscore form first follows the "correctness fixes lead refactors" principle without needing a gate between batches.
- **#44 last inside H2 rather than parallel.** Functionally independent of #41/#43, but SKILL.md is the same file — serializing eliminates merge-conflict surface entirely. Cheaper than any merge-order ceremony for what is ultimately a ~10-line agent.
- **Batch-branch pattern despite small batch size.** Two agents still benefits from a single integration point for human review. H2 has 3 commits across multiple files — better to land on `batch/h` than directly on `main`.

## Deferred items

None. All four issues from the 2026-05-25 fresh-VM run are in scope.

## Out of scope

- **Phase 10's recommendation to "also document the chosen collision policy near the loop."** H2 may include a brief comment in SKILL.md near the new `ln -sfn` line; full policy documentation in a separate references file is out of scope for this batch.
- **Phase 14 fallback to "create empty repo" pre-Phase-2 instruction.** The issue offers two fix options (detect-divergence-and-suggest-rebase vs. tell-operator-to-create-empty-repo). H2 picks one; cross-skill instructions to operators about how to create their GitHub repos are out of scope.
- **Refactoring `references/database-scaffolding.md` structure.** #43's edit is a substitution; broader restructuring of the database scaffolding reference is a separate concern.
