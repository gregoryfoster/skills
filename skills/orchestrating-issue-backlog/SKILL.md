---
name: orchestrating-issue-backlog
description: Prioritize an open issue backlog using agreed rubrics, analyze conflict zones and dependencies, design a parallel-safe batch execution plan using git worktrees, produce a design doc and GitHub issue, and hand off to an agent team.
compatibility: Designed for Claude. Requires git, gh CLI, and a project using git worktrees for branch isolation.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: "orchestrate backlog, prioritize issues, plan issue execution, clear backlog"
---

# Orchestrating an Issue Backlog

Turn an open GitHub issue backlog into a prioritized, parallel-safe execution plan for an agent team. Interview the user to agree on rubrics, score all issues, identify conflict zones, design merge-safe batch assignments, and produce a design doc and tracking issue.

<HARD-GATE>
Do NOT assign priorities, design batches, write a design doc, or open a GitHub issue until rubrics are agreed upon and the scored backlog has been presented to and approved by the user. Each major section requires explicit approval before proceeding to the next.
</HARD-GATE>

## Checklist

Create a task for each item and complete them in order:

1. **Fetch all open issues** — `gh issue list --state open --limit 50 --json number,title,labels,body`
2. **Explore project context** — read AGENTS.md, recent commits, existing design docs
3. **Interview user** — establish rubrics and constraints (one question at a time)
4. **Score all issues** — apply rubrics, present table, get approval
5. **Analyze conflict zones** — identify files touched by multiple issues; build dependency graph
6. **Present dependency analysis** — get approval before batch design
7. **Design batch plan** — assign issues to merge batches; get approval
8. **Write design doc** — `docs/plans/YYYY-MM-DD-<topic>-backlog.md`; commit
9. **Open GitHub tracking issue** — link to design doc; list batches
10. **Write or update skill** — capture process learnings for reuse

---

## Process

### Step 1–2: Context gathering

Fetch issues and read project context before asking any questions. Go into the interview knowing:
- Rough categories of issues (architectural, bug, feature, infra)
- Which files are most frequently touched across issues
- Any issues that are likely already closed (cross-reference recent commits)
- Pairs of issues that may describe the same underlying bug or fix — check title overlap, body keywords, and **files/symbols mentioned** (files/symbols catches duplicates that don't share title language). If found, surface as Q0 in Step 3 — resolving before scoring avoids redundant ranking and accidental two-agent overlap.

### Step 3: Interview (one question at a time)

These questions establish everything needed. Ask them in order; do not stack multiple questions.

**Q0 (conditional) — Resolve any candidate duplicate pairs surfaced in Step 1–2.**
> For each candidate pair: **bundle** (one agent handles both — see the Step 7 bundling rule), **close one as dup**, or **score independently** (separate batch slots)?

Skip Q0 entirely if Step 1–2 didn't flag any candidates. The HARD-GATE permits this question because it gates *priorities*, not clarifying questions. Close any agreed-upon dups via `gh issue close <issue> --comment 'duplicate of #<survivor>'` before moving to Q1 so the scored backlog reflects the resolved state and the closed issue records the dup link.

**Q1 — What does "quality" mean here?**
> Which matters most: testability, correctness, maintainability, or all roughly equally?

**Q2 — What is the deployment context?**
> Pre-production (runway to build it right), early production (real users, low volume), or active production (stability required)?

**Q3 — Are any issue categories explicitly deferred?**
> e.g. "Phase 7 fetchers are not a priority right now" — establishes what to exclude from scoring

**Q4 — Parallelism preference?**
> Maximize parallel agents, sequential waves, or hybrid (parallel within batches, gates between)?
> Follow up: worktrees for branch isolation? (almost always yes)

**Q5 — Worktree provisioning mechanics and ceiling?**
> Does the host project have a custom worktree-create script (e.g. `dev.sh worktree create`)? If so, what concurrent ceiling does it support? What does it provision beyond plain `git worktree add` — Nginx vhosts, DB clones, port pools, node_modules overlays?
> The answer caps the per-batch agent count regardless of file-disjointness. If the user doesn't know, ask them to grep the script for port-pool size, docker-compose port ranges, or similar limits before proceeding.

Record agreements explicitly as you go — they feed the design doc.

### Step 4: Scoring rubric

Use this three-dimension rubric unless the user requests different dimensions or weights.

**Score = (Foundation × 2) + (Correctness × 2) + Scope**, max 15.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** | Requires design discovery | Clear direction, minor decisions needed | Mechanical — implementation is obvious from the issue |

**Blast radius** (files touched across issues) drives *sequencing*, not score. High-blast issues get their own batch slot even when high priority.

Present the scored table sorted by score descending. Include a blast column (Low/Med/High). Note any issues that appear closed by recent commits.

Get approval before moving to conflict analysis.

### Step 5–6: Conflict zone analysis

Identify files touched by 2+ issues — these drive sequencing decisions:

1. List each contested file and the issues that touch it
2. Determine required merge order within each file (usually: smaller targeted fixes first, wide refactors last, features after foundations)
3. Derive a dependency graph showing which issues must precede which

Present the conflict zones and dependency graph. Get approval.

### Step 7: Batch design

Group issues into **merge batches**. The core principle: within a batch, all agents work on branches with disjoint file coverage so PRs can be merged in any order. Between batches, a gate ensures prior work is merged and stable before the next batch begins.

**Batch design rules:**
- **Batch 0 / Batch A**: truly isolated issues — each touches files no other issue in this batch touches. Maximum agent count.
- **Cap parallel agents at the project's worktree provisioning ceiling** (Q5 / Rule 5). The effective per-batch parallelism is `min(file-disjoint count, project worktree ceiling)`. Exceeding the ceiling produces silent fall-through, not a graceful error — see Rule 5.
- **Chunk when N > ceiling**: if a batch has more file-disjoint agents than the ceiling permits, split it into sub-waves (A1 ≤ ceiling, A2 launches after A1's worktrees free). Agents within a sub-wave run in parallel up to the ceiling; sub-waves themselves run sequentially, each merging into the same `batch/<X>` branch. Narrowing the batch (dropping issues) is the fallback only when chunking would create new file conflicts across sub-waves.
- **Subsequent batches**: ordered by the dependency chain of contested files. One agent per batch on the critical path; parallelize only where file coverage is genuinely disjoint.
- **Bundle related issues** in one agent when: they touch the same file(s) AND are best reviewed together (e.g. define constants then use them; fix protocol then add config models).
- **Correctness fixes first within a batch**: if a targeted bug fix touches a file that later gets a wide refactor, put the bug fix at the head of the refactor agent's commit sequence, not in an earlier parallel slot.
- **Features last**: issue categories scored below architectural work go in the final batch(es).

Present a table:

| Batch | Issues | Agents | Gate |
|---|---|---|---|
| A | #n, #m, ... | N (parallel) | Start immediately |
| B | #n → #m | 1 (sequential commits) | After A merged |
| ... | | | |

Include a note for any intra-batch merge ordering (e.g. "F1 merges first; F2 rebases before merge").

Get approval before writing the design doc.

### Step 8: Design doc

The design doc is stored in the plans directory governed by [`writing-plans`](../writing-plans/). Resolve the target directory via `bash skills/writing-plans/scripts/resolve-plans-dir.sh` (env `PLANS_DIR` → `.skills/plans_dir` → `<repo>/docs/plans/`); the filename is `YYYY-MM-DD-<topic>-backlog.md`. The section structure below is specific to backlog orchestration and differs from the generic plan structure prescribed by `writing-plans` — share the directory, not the shape.

Path (default): `docs/plans/YYYY-MM-DD-<topic>-backlog.md`

Sections:
- **Goal** — one paragraph
- **Approved approach** — summary
- **Prioritization rubrics** — table + formula
- **Scored backlog** — full table
- **Conflict zones** — contested files and their required merge order
- **Dependency graph** — ASCII or text
- **Batch execution plan** — per-batch table with agents, issues, files, gate condition
- **Key decisions** — rationale for non-obvious choices (e.g. why a correctness fix leads a refactor batch)
- **Deferred items** — what was explicitly excluded and why
- **Out of scope** — anything that came up but was ruled out

**Where to commit.**

Default: directly on `main`. Matches the orchestrator's "workers branch from local main" assumption (Rule 1) and avoids an extra merge gate before launching agents.

Use a feature branch + PR when the host project enforces filesystem isolation for plan creation (e.g. a workspace-isolation pre-commit hook that names "spec/plan creation" as an in-worktree activity), or when the user wants a review checkpoint before launching agents. Ask if the project's conventions aren't already clear. In that case, either:
- **Merge the doc PR before launching workers** (cleanest; workers' local main sees the doc on disk), OR
- **Include the plan in the Agent tool's prompt when launching each worker** (workers don't actually need the doc on disk to function; acceptable if the user wants the doc PR to land alongside the batch branch).

**Commit format.**

```
#<n> docs: add <topic> backlog orchestration plan
```

The `#<n>` prefix is the tracking issue number, which doesn't exist until Step 9. Two viable orderings: (a) commit without the `#<n>` prefix, then open the issue (recent precedent in this repo); (b) open the issue first, then commit with the prefix. Either works — don't block waiting for an issue number.

### Step 9: GitHub tracking issue

```bash
gh issue create \
  --title "<topic>: prioritized backlog clearance (<N> batches, <M> issues)" \
  --body "$(cat <<'EOF'
## Summary
<2–3 sentences>

## Design doc
\`docs/plans/YYYY-MM-DD-<topic>-backlog.md\`

## Scope
**Batch A — N parallel agents**
- #n Issue title
...

**Batch B — 1 agent (after A merged)**
- #n, #m Issue titles
...

**Deferred:** #n, #m (reason)
EOF
)"
```

Report the issue number.

### Step 10: Process documentation

After the plan is approved and committed, capture any adjustments made during this session:
- Did the user adjust rubric weights? Document the new formula.
- Were any standard questions skipped or reordered? Note why.
- Did any conflict analysis surface surprises? Record the pattern.
- Were any rubric dimensions inadequate for this project type? Flag for skill revision.

Update this skill file if patterns emerged that should be generalized.

---

## Agent Roles

### Branch strategy

Each **multi-agent batch** gets a shared integration branch (e.g. `batch/a`, `batch/f`). The orchestrator creates this branch and checks it out **before spawning any agents**. Worker agents use `isolation: "worktree"` — because that parameter merges completed work to the caller's current branch, each agent's output accumulates on the batch branch automatically.

**Single-agent batches** do not need a separate batch branch — the agent's feature branch serves directly.

The human review happens against the **batch branch**: run tests, inspect the combined diff, then merge to `main`. After merge, the orchestrator checks `main` back out, pulls to sync, and uses it as the base for the next batch branch.

**Intra-batch worker→batch integration must be fast-forward or regular-merge — not squash or rebase.** The orchestrator destroys completed workers' worktrees via `worktree-destroy.sh --base batch/<X>` (Orchestrator step 5), which verifies the worker branch is an ancestor of `batch/<X>`. Squash merges drop the parent link and rebase rewrites commits; both break the ancestor check and force the orchestrator to descope the destroy, defeating the merge-safety gate. This is a separate decision from the batch-branch→main merge strategy below (which the user picks).

Ask the user their preferred **batch→main** merge strategy (regular, squash, rebase) and record it in the design doc. The intra-batch strategy is fixed at FF/regular-merge regardless.

### Orchestrator agent

The orchestrator reads the batch plan and manages progression. It:
1. **Sync local main before every batch launch** — `git checkout main && git pull --ff-only`. Agents worktree from local main; if local main is stale, agents base their work on the wrong commit.
2. **Check out the batch branch before spawning agents** — `git checkout -b batch/<X>`. Because `isolation: "worktree"` merges to the caller's current branch, this ensures all worker output accumulates on `batch/<X>` rather than `main` (see Rule 3).
3. **Verify worktree slot availability** — before launching, check that consumed slots + planned agents ≤ project ceiling (Rule 5). Prefer the host project's own slot-status command if it exists (e.g., a `dev.sh worktree status` or listing files in the port-pool directory) — this reports the **actual** resource consumption. If only the git-worktree count is available, use `bash skills/using-git-worktrees/scripts/worktree-list.sh --porcelain | grep -c '^worktree '` (minus 1 for the main checkout) as a **lower-bound** proxy and apply a safety margin (e.g., treat the effective ceiling as `ceiling - 1`) to absorb port leaks from previously-destroyed worktrees whose project-side cleanup didn't run.
4. Launches all worker agents whose batch gate is currently satisfied simultaneously
5. **On each worker completion signal**:
   - Run `git -C <main> status --porcelain` (Rule 6). Any output → halt the batch and salvage.
   - Verify the merge landed on `batch/<X>` (respecting any intra-batch ordering; returns conflicts to the responsible worker agent to resolve).
   - Destroy the merged worker's worktree: `bash skills/using-git-worktrees/scripts/worktree-destroy.sh <agent-branch> --base batch/<X>`. The `--base` flag tells the destroy script to verify the merge against the batch branch rather than `main`, since the human batch-to-main merge hasn't happened yet (would otherwise refuse). Frees the slot for a chunked sub-wave.
   - Drop the now-unused ref: `git branch -d <agent-branch>`. The lowercase `-d` refuses if the branch isn't merged into HEAD, providing a second guard against the same merge-safety class as the destroy script's Iron Law. If `-d` refuses, the worker's commits are not actually on `batch/<X>` — escalate before forcing.
6. When all workers are merged, runs the full test suite against `batch/<X>`
7. **Between sub-waves of a chunked batch** — after destroying completed workers' worktrees in sub-wave Aₙ, re-verify slot availability (step 3) before launching Aₙ₊₁
8. Notifies the user: "Batch X ready for review: `batch/<X>`, N issues, tests passing"
9. Waits for merge confirmation before proceeding
10. **On confirmation**, checks out `main`, merges `batch/<X>`, pushes, then syncs local main before launching the next batch

Never writes implementation code itself.

### Worker agents

Each worker agent follows this protocol before signaling completion:

1. **Set up worktree** — isolated branch `feature/batch-<X>-<issue>` in `.worktrees/` (or the project's resolved worktree root — see [`using-git-worktrees`](../using-git-worktrees/))
2. **Pre-flight: verify isolation** — confirm cwd is an isolated worktree, not the main checkout. Use either:
   - `[ -f "$(git rev-parse --show-toplevel)/.git" ]` — in a linked worktree, `.git` is a *file* pointing to the worktree's git-dir; in the main checkout it's a *directory*. Cheapest reliable check.
   - Or compare resolved paths: `[ "$(realpath "$(git rev-parse --git-dir)")" != "$(realpath "$(git rev-parse --git-common-dir)")" ]`. Do not compare the raw `git rev-parse` outputs without `realpath` — git may return one as absolute and the other as relative depending on cwd, producing false-unequal results that mask a fall-through.

   If the check fails, abort and signal the orchestrator that worktree provisioning fell through (Rule 5/6) — do NOT modify files in the main checkout.
3. **Implement with TDD** — red → green → refactor
4. **Run full test suite** — all tests must pass
5. **Run linter** — no violations
6. **Self-review diff** — check: correctness, test coverage, project conventions, no unintended side effects outside issue scope
7. **Address findings** — fix before signaling; do not signal with known issues
8. **Signal completion** — notify orchestrator the branch is ready to merge into the batch branch. The orchestrator destroys the worktree after merge (see Orchestrator step 5); the worker does NOT destroy it itself (premature destruction can race with the merge).

**No PR is opened by the worker.** The orchestrator merges into the batch branch; the user reviews the batch branch as a whole.

## Key Principles

- **One question at a time** — stacking questions gets partial answers
- **Approval gates are real** — do not proceed past a section without explicit user sign-off
- **Blast radius ≠ priority** — a high-blast issue may score high but still must wait for lower-priority isolates to merge first
- **Correctness fixes lead refactors** — if a bug fix and a structural refactor both touch the same file, fix the bug in the first commit of the refactor branch, not in a separate earlier batch
- **Bundle when cohesive** — two issues that naturally sequence (define → use, protocol → config) belong in one agent with sequential commits, not two agents with a gate
- **Worktrees always — and verify the host project can provision them** — use `isolation: "worktree"` for all worker agents; each gets an isolated working directory. Pre-create and check out the batch branch first so their output lands there, not on `main`. The Agent tool parameter does NOT guarantee filesystem isolation if the host project's worktree-create script falls through (port pool exhausted, docker port collision, etc.); cap per-batch agents at the project's provisioning ceiling (Rule 5) and detect fall-through at runtime (Rule 6).
- **Deferred is a decision** — explicitly name what is out of scope and why; don't silently omit
- **Batch feature branches for multi-agent batches** — gives the user a single integration point to test and review before merging to main; surfaces intra-batch conflicts at the batch branch, not at main
- **Single-agent batches skip the extra branch** — the agent's feature branch is the batch branch
- **No worker PRs** — workers signal to the orchestrator; the orchestrator merges into the batch branch; the user reviews the batch branch
- **Conflict resolution stays with the worker** — if a merge into the batch branch conflicts, the orchestrator sends it back to that agent
- **Self-review before signal** — worker agents resolve all findings before signaling; no known issues at signal time
- **Orchestrator launches all unblocked batches** — not just the next one in sequence; if two independent batches become unblocked simultaneously, launch both
- **Regular merge commit to main** — preserves per-agent commit history; ask user preference at design time

## Branch Hygiene Rules

These rules prevent the class of failures that produced the Batch B→C conflict:

### Rule 1 — Sync local main before every agent launch

`git push origin HEAD:main` from a feature branch advances `origin/main` but does **not** move local `main`. Worktree agents branch from local `main`. If local `main` is behind `origin/main`, agents silently base their work on the wrong commit.

**Before launching any batch:**
```bash
git checkout main
git pull --ff-only   # or: git fetch origin && git merge --ff-only origin/main
```

If `--ff-only` fails, the branches have diverged — stop and investigate before proceeding.

### Rule 2 — Never use `git push origin HEAD:main` to advance main

This is the root cause of Rule 1 violations. Always push from local `main`:
```bash
git checkout main
git merge --ff-only feature/batch-x   # or rebase; whatever the agreed strategy is
git push origin main
```

Or, if agents auto-merged to main (see Rule 3), just:
```bash
git push origin main   # from local main after verifying it is up to date
```

### Rule 3 — `isolation: "worktree"` merges to the caller's current local branch

The `isolation: "worktree"` Agent tool parameter creates a temporary worktree, runs the agent in it, then merges any changes back to **the current local branch** of the calling process (not to origin, not to a named feature branch).

**Canonical pattern for multi-agent batches:** check out the batch branch *before* spawning agents. Because `isolation: "worktree"` merges to the current branch, all agent output accumulates on `batch/<X>` rather than `main`:

```bash
git checkout main
git pull --ff-only               # sync (Rule 1)
git checkout -b batch/f          # switch workspace to batch branch
# spawn all worker agents with isolation: "worktree"
# their completed work merges into batch/f as each agent finishes
```

After human review and merge approval:

```bash
git checkout main
git merge --ff-only batch/f      # or rebase/squash per agreed strategy
git push origin main
# sync local main before next batch (Rule 1)
```

Consequences of this model:
- Per-agent worktree branches are temporary; work accumulates on `batch/<X>`
- `main` is only updated when the human explicitly merges the batch branch
- The next batch launch must start with `git pull --ff-only` on `main` (Rule 1) before creating the new batch branch

### Rule 4 — Fix commit messages before continuing after a rebase conflict

When `git rebase --continue` auto-generates a commit message from the conflict resolution, it replaces the original `#N type: description` format with a verbose blob. Fix it immediately with `git commit --amend` on that commit **before** continuing the rebase or adding more commits — amending the wrong commit requires a `reset --soft` recovery.

```bash
git rebase --continue          # resolves conflict, creates commit with bad message
git commit --amend -m "..."    # fix message before doing anything else
# only then: git rebase --continue for the next patch (if any)
```

### Rule 5 — Cap per-batch parallelism at the host project's worktree provisioning ceiling

`isolation: "worktree"` is an Agent tool parameter; it does not control the host project's worktree-create tooling. If that tooling has a finite resource ceiling (port pool, docker port range, license slot), exceeding it produces **silent fall-through**, not a graceful error: the agent's worktree-create script may print a warning and fall back to plain `git worktree add` (losing project-specific provisioning), or — worse — drop the agent into the main checkout where it modifies tracked files in place.

**Before launching any batch**, verify `len(agents) ≤ project ceiling` established in Q5. If file-disjointness allows more parallelism than the ceiling, chunk the batch into ceiling-sized sub-waves (see Step 7 batch design rules) rather than narrowing.

**Recording the ceiling**: capture it in the design doc's "Approved approach" section so subsequent sessions inherit it without re-interviewing.

### Rule 6 — Detect worktree fall-through at runtime

A ceiling check is a precondition, not a guarantee — Q5 answers can be wrong, port pools can shrink mid-run, scripts can fail in new ways. The orchestrator MUST detect when an agent fell through into the main checkout.

**Between worker completion signals**, the orchestrator runs:
```bash
git -C <main checkout> status --porcelain
```

Any output indicates a worker fell through and is modifying files in the main checkout. Stop processing further completion signals from this batch until the salvage completes and `git -C <main> status --porcelain` is clean again. Identify the responsible agent (most recently signaled, or — if commits ended up on the wrong branch — via `git log main..HEAD` on the main checkout), and salvage per the Recovery procedure in [`references/recovery.md`](references/recovery.md).

This check is cheap and runs on the orchestrator's host, not in any agent's worktree. Do it on every signal, not just on suspicion.

---

## Recovery

When Rule 6 detects uncommitted work in the main checkout — or a worker's pre-flight isolation check (Worker step 2) fires — halt further completion signals for the affected batch and follow the salvage procedure in [`references/recovery.md`](references/recovery.md). The procedure preserves the worker's intended commits, replays uncommitted modifications onto the correct feature branch, and re-runs verification (the agent's pre-salvage test pass is invalid — it ran against the main checkout's working tree, not an isolated copy).

Do not relaunch a salvaged agent in the same wave that hit the ceiling. Resolve the ceiling first (destroy a completed worktree, widen the host-project pool, or chunk the remaining work into smaller sub-waves per Step 7).

---

## Process Log — Session 2026-03-23

**Agreements reached:**
- Rubric dimensions: Foundation Leverage, Correctness Risk, Scope Clarity
- Score formula: (Foundation×2) + (Correctness×2) + Scope (doubles Foundation and Correctness to weight architectural and safety concerns over mechanical effort)
- Blast radius drives sequencing, not score
- Phase 7 issues (#3, #4, #5) explicitly deferred until architectural foundation is solid
- Parallelism: maximize where file coverage is disjoint; git worktrees for isolation
- Deployment context: pre-production (runway to build right)
- Output: design doc + GitHub tracking issue + this skill

**Observed agent behavior (2026-03-23 execution):**
- `isolation: "worktree"` agents auto-merge their completed changes back to the orchestrator's **current local branch**. Per-agent worktree branches do not persist after completion.
- **Corrected batch branch pattern** (retrofitted after session): the orchestrator should check out `batch/<X>` *before* spawning agents. Since `isolation: "worktree"` merges to the current branch, this routes all agent output to the batch branch rather than `main`. After review, the orchestrator merges `batch/<X>` → `main` and checks `main` back out.
- **Impact during this session**: agents ran with the workspace on `main` — batch branches served as fast-forward checkpoints, not isolation boundaries. The test run at the end of each batch provided the safety net.
- **Impact on single-agent batches** (B–E): no change — the agent's worktree branch is the batch branch anyway.

**Clarifications added after initial design:**
- Orchestrator launches all unblocked batches simultaneously — not just the next numbered batch. Initial design implied sequential launching; user clarified all safe parallel work should start at once.
- Worker agents self-review and fix all findings before signaling completion. Keeps human review focused on merge decisions, not catching obvious issues.
- Multi-agent batches use a shared `batch/<X>` feature branch. The orchestrator merges worker branches into it sequentially; user tests and reviews the batch branch as a whole before merging to main. Surfaces intra-batch conflicts before they reach main.

**Branch management failures observed (2026-03-23, Batches B–C):**

1. **Local main staleness** — Batch B was pushed to `origin/main` via `git push origin HEAD:main` from a feature branch. This advanced `origin/main` to `aa24b27` but left local `main` at `15c15c9`. The Batch C agent launched from the stale local `main`, silently missing all Batch B commits. Consequence: `pipeline.py` and `notify.py` were carved from the pre-Batch-B `tasks.py`, introducing regressions in audit log patterns that Batch B had already migrated. Caught by CR, fixed in post-CR commit.
   - **Rule added**: Sync local main (`git pull --ff-only`) before every batch launch. Never push to origin from a feature branch using `HEAD:main`.

2. **`isolation: "worktree"` auto-merges to local branch** — Confirmed again: agents using this parameter commit to the orchestrator's current local branch, not to an isolated feature branch. Batch/x branches are manual fast-forward checkpoints, not isolation boundaries.

3. **`git rebase --continue` clobbers commit messages** — After manual conflict resolution in `tasks.py`, `git rebase --continue` replaced the `#14 refactor:` message with the full diff summary. Attempting to fix it via `git commit --amend` on the wrong HEAD commit (which was actually #19) required `git reset --soft` recovery and two additional commits.
   - **Rule added**: Immediately after `git rebase --continue`, amend the commit message before doing anything else.
- Single-agent batches skip the extra branch — agent's feature branch serves directly.
- Workers signal to the orchestrator, not by opening PRs. No individual agent PRs.
- Regular merge commit when merging batch branch to main (preserves per-agent history).

**Non-obvious decisions:**
- #25 (savepoint correctness fix) leads Batch B's refactor sequence rather than going in Batch A. Rationale: it fixes a race condition in `tasks.py` — the same file that Batch B's mechanical refactors will touch. Fixing it first ensures the refactors inherit correct transaction semantics.
- #27 and #28 (dashboard 404 + delete watch) were batched into a single agent (A5) despite being distinct issues, because they both touch `dashboard/routes.py`. Batching eliminated a merge conflict risk within Batch A.
- #16 (event constants) scored 13/15 — highest in the backlog — because it is a prerequisite for #18 (audit helper) and eliminates silent audit-log typo bugs across 8 files.
- The critical path (Batches B→C→D→E) runs through `tasks.py`. All four batches are single-agent sequential because the file accumulates changes from each batch that the next batch must build on.

---

## Process Log — Session 2026-05-22 (port-pool incident)

**Project:** `cannabis.observer-wordpress` (Bedrock + Sage 11 + Lima VM monorepo)

**Incident:** `/orchestrating-issue-backlog` launched 10 parallel worker agents for Batch A. The host project's `dev.sh worktree create` script allocates ports from a pool of 9 slots (8001–8009) for per-worktree Nginx vhosts. Agents 9–10 (and several others starting near-simultaneously) hit the ceiling.

**Fall-through modes observed:**
- **Majority (A4, A6, A8, A10):** `dev.sh worktree create` printed "port pool exhausted" and fell back to plain `git worktree add`. Lost VM vhost, DB clone, node_modules overlay — but git branch + commits landed correctly on the agent's feature branch.
- **One agent (A9):** Silently fell through to the **main checkout** as its working directory. Modified tracked files in place, ran tests against them (passed — because the modifications WERE the working tree), and was about to run `php -l` when the orchestrator caught it via `git status` on main showing uncommitted modifications.

**Salvage (A9):** Stashed uncommitted work + untracked files (`stash push -u`) in the main checkout, switched to A9's empty feature branch (`feature/batch-a-249-tranche-c6-c9`), popped the stash, committed manually as `e0307c0`. No work lost.

**Rules added (Rule 5, Rule 6):**
- **Rule 5** — Cap per-batch parallelism at the host project's worktree provisioning ceiling. Establish via new Q5 in interview.
- **Rule 6** — Orchestrator runs `git -C <main> status --porcelain` between worker completion signals to detect fall-through. Cheap, mandatory, runs on every signal.

**Recovery procedure documented:** Stash-and-replay salvage with mandatory test re-run post-salvage (the agent's pre-salvage test pass is invalid).

**Step 3 interview** gained Q5 — worktree provisioning mechanics and ceiling.

**Step 7 batch design** gained ceiling-driven chunking: when file-disjoint agent count exceeds the ceiling, split into sub-waves rather than narrowing the batch.

**"Worktrees always" key principle** amended to acknowledge that the `isolation: "worktree"` Agent parameter does not guarantee filesystem isolation if host-project tooling falls through.

**Anecdotal ceiling patterns** (from this incident only — surface the actual ceiling via Q5 per session; do not extrapolate these as defaults):
- In this incident: cannabis.observer-wordpress (Bedrock + Lima + Nginx vhost per worktree) had a 9-slot port pool (8001–8009).
- Adjacent project shapes worth probing during Q5: Docker-Compose projects may be bounded by their port-mapping range, OR may share a single set of services across worktrees (different failure mode — shared state instead of a ceiling). Plain git-worktree-only projects have no ceiling beyond `git worktree add` concurrency.

**Host project follow-up (not yet filed):** widen `dev.sh worktree create` port pool past 8009, recycle stale ports on `worktree destroy`, or fall back cleanly to "no Nginx vhost" without changing cwd. The originating Q2 backlog tracking issue is `CannObserv/cannabis.observer-wordpress#279`; the port-pool work is a separate follow-up to be filed against that project.

---

## Process Log — Session 2026-05-24 (skills repo, six-issue Batch F)

**Project:** `gregoryfoster/skills` (this repo)

**Backlog:** issues #26, #27, #28, #30, #31, #33 — references convention, FastAPI pre-ship fix, worktree-destroy leak fix, structural tests for references, new audit script, doc-check default tightening.

**Interview answers:**
- Q1 Quality: Correctness above all → formula adjusted to `(Foundation × 2) + (Correctness × 3) + Scope`, max 18.
- Q2 Deploy: active production (downstream submodule consumers).
- Q3 Defer: none — ship all 6.
- Q4 Parallelism: maximize within batches.
- Q5 Ceiling: no host-project ceiling (plain `git worktree add` + pytest); cap at batch size (6).

**Shape:** single batch with 6 parallel agents. All issues file-disjoint at minimum scope; ceiling equals batch size, so no chunking needed. Tracking issue: `#34`.

**Non-obvious decisions captured:**

- **Single-owner assignment to resolve a one-line shared-file overlap.** [skills/using-git-worktrees/SKILL.md](../using-git-worktrees/SKILL.md) was the only contested file (between #28 documenting an internal fix and #31 documenting a new script). Resolution: assign SKILL.md edits exclusively to one agent (F4, the larger contributor) rather than serializing two small edits with a rebase. F1 (#28) ceded SKILL.md and relies on commit message + inline script comments to document the internal change. This is cheaper than any merge-order ceremony for ≤2-line overlaps and worth reaching for first.
- **Detection-only as the merge-safe minimum for a paired feature.** #31's issue listed `worktree-create.sh` preamble integration and `pre-ship.sh` wiring as optional. Both were scoped out to keep F4's diff narrow and avoid pulling additional files (`worktree-create.sh`) into the batch. Pattern: when an issue offers a "main thing + optional integration points," ship the main thing in this batch and file follow-ups for the wiring.
- **Variable rubric weight.** First session where Correctness flexed to ×3. Confirmed the existing "unless the user requests different weights" escape hatch is enough — no rubric change needed at the skill level. Worth noting that the weighting choice flipped the ordering: under Correctness ×2 / Foundation ×2, #28 and the convention work (#26) would have been closer; under Correctness ×3, #28 leads clearly because of real downstream forensics.

**Tactical lessons:**

- **`gh issue create` with `--body "$(cat <<'EOF' ... EOF)"` chokes on apostrophes inside the body** (e.g. `skill's`), even though the heredoc is single-quoted. The error surfaces as `unexpected EOF while looking for matching '`'. Switch to `gh issue create --body-file <path>` — sidesteps all shell quoting issues and lets the body include any character. The **same workaround applies to `git commit -m "$(cat <<'EOF' ... EOF)"`** — use `git commit -F <path>` for any commit message containing apostrophes, dollar signs, or backticks. Confirmed again in Session 2026-05-25.
- **Step 8 commit format clarification.** First documented the chicken-and-egg between Step 8's `#<n>` commit prefix and Step 9's issue creation. Promoted to Step 8 instructions in #48.

---

## Process Log — Session 2026-05-25 (skills repo, four-issue Batch H)

**Project:** `gregoryfoster/skills` (this repo)

**Backlog:** issues #41, #42, #43, #44 — all surfaced by the 2026-05-25 `CannObserv/usa-wa` fresh-VM bootstrap of `init-project-fastapi`. New Phase 5d Postgres provisioning; missing `httpx` dev dep; alembic.ini hyphen-DSN; Phase 10 `ln -s` collision producing a permanent dangling symlink in the obra submodule.

**Interview answers:**
- Q1 Quality: Correctness above all → `(Foundation × 2) + (Correctness × 3) + Scope`, max 18.
- Q2 Deploy: **bootstrap skill with SHA-pinned downstream consumers** — see note below; this is a new framing not covered by the existing three Q2 options.
- Q3 Defer: none — ship all 4.
- Q4 Parallelism: bundle into 2 agents (recommended option). #42 isolated, #41+#43+#44 sequential in one branch (#43 first to establish `PROJECT_UNDERSCORE`).
- Q5 Ceiling: no host-project ceiling (plain `git worktree add`).

**Shape:** single batch (`batch/h`) with 2 parallel agents. Tracking issue: `#45`.

**Non-obvious decisions:**

- **Bundle three issues touching the same file into one agent with sequential commits.** #41, #43, #44 all touch `init-project-fastapi/SKILL.md` in different phase blocks. Three parallel agents would have produced (a) merge-conflict surface even in non-overlapping hunks, and (b) intra-batch merge ordering ceremony for #43-before-#41. One agent with three commits eliminates both. Cheaper than any parallel-with-ordering design for a 4-issue batch.
- **#43 leads #41 inside the bundle, not its own earlier batch.** #43's `PROJECT_UNDERSCORE` derivation is a prerequisite for #41's Phase 5d to create the right database. The "correctness-fixes-lead-refactors" rule generalizes: any *prerequisite* fix leads its dependent, even within a single agent. Putting them in one agent (rather than two batches with a gate) gets the same correctness ordering with less ceremony.

**Q2 framing not in the standard options — worth noting:**

The standard Q2 options (pre-production / early production / active production) anchor on whether *running consumers* can absorb churn. For *bootstrap skills* (anything that operators run once on a clean VM to scaffold a new project), there's a fourth shape: the skill itself has SHA-pinned downstream consumers who will only re-bootstrap when they choose to, so structural changes to the skill don't break anyone's running services. This gives pre-production-style runway even though the skill is "in use." Worth surfacing as a Q2 option if this case keeps recurring; for now, recording it here so a future session can recognize the pattern.

**Tactical lessons:**

- **`git commit -m "$(cat <<'EOF' ... EOF)"` has the same apostrophe failure mode as `gh issue create --body`** — see the Session 2026-05-24 lesson above; the workaround is `git commit -F <path>`. Cleaner: write the commit message to `/tmp/<name>-msg.txt` first, then `git commit -F`. Same shape as the `gh issue create --body-file` workaround.
