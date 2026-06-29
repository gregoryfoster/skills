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
10. **Capture session learnings** — append a session entry to `references/process-log.md`; promote patterns into this skill only when they recur or introduce a new rule

---

## Process

### Step 1–2: Context gathering

Fetch issues and read project context before asking any questions. Go into the interview knowing:
- Rough categories of issues (architectural, bug, feature, infra)
- Which files are most frequently touched across issues
- Which issues are already **closed-in-fact**. For *every* issue (not just the obviously-stale ones), grep at least one identifying symbol from its body, plus `Issue #<n>` in the files it names — module/template docstrings often credit the PR that retired a footgun. Don't trust the issue body's claim about current file state. Cross-reference recent commits. Surface any closed-in-fact issue in the score table so a batch slot isn't allocated to dead work (process-log 2026-05-11: the highest-scored issue in a backlog was already resolved).
- Pairs of issues that may describe the same underlying bug or fix — check title overlap, body keywords, and **files/symbols mentioned** (files/symbols catches duplicates that don't share title language). If a candidate pair is found, surface as Q0 in Step 3 — resolving before scoring avoids redundant ranking and accidental two-agent overlap.

### Step 3: Interview (one question at a time)

These questions establish everything needed. Ask them in order; do not stack multiple questions.

**Q0 (conditional) — Resolve any candidate duplicate pairs surfaced in Step 1–2.**
> For each candidate pair: **bundle** (one agent handles both — see the "Bundle related issues" rule in Step 7), **close one as dup**, or **score independently** (two separate work items — Step 7 decides batch shape)?

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

1. Grep the contested symbols/keywords to confirm each issue's *real* file footprint matches its stated scope — the grep runs in **both** directions. Issue bodies frequently **understate** scope (process-log 2026-05-09: a fix scoped to a single dedup script was actually 5× larger, spanning the ingestion pipeline). They also **overstate** it: **partial-fix backlogs**, where some siblings were already patched in the originating PR, routinely overstate remaining scope (process-log 2026-06-28: #407's claimed sibling transformers were already correct → narrowed to one file; #399's claimed "5h.2-5h.5 sweep" was mostly already patched → narrowed to two commands). A wrong footprint in either direction corrupts the bundling decision and the workers' self-review checks; narrowing also prevents a worker re-fixing already-correct code, so run the grep even when no issue looks stale. Then list each contested file and the issues that touch it
2. Determine required merge order within each file (usually: smaller targeted fixes first, wide refactors last, features after foundations)
3. Derive a dependency graph showing which issues must precede which

Present the conflict zones and dependency graph. Get approval.

**Low-discovery backlog mode (compressed Steps 5/6).** Two recurring backlog shapes already name their contested files before the orchestrator arrives, collapsing Steps 5/6 to "confirm what the parent artifact already shows":

- **Spec-derived** — issues carved out of a just-merged design spec. The spec already declares the foundation file(s) and the downstream split.
- **Followup-derived** — issues filed during a just-completed shipping cycle as deliberate carve-outs. The shipping cycle's PRs already named the contested files.

Recognize either flavor when the backlog issues were filed in the same session as the artifact they're derived from. Compress Steps 5/6 to "list contested files + confirm there's nothing surprising"; the formal dependency-graph subsection is mostly ceremony when there's one edge. Run the skill anyway — its value moves to Step 7 (batch shape, including the Shape A vs. Shape B decision) and Step 8 (design-doc as a permanent ops manual for the orchestrator runtime: Rules 1–6 checklist, branch strategy, Key Decisions).

**Backlog provenance is a prior on batch geometry — confirm it with the grep, don't trust it.** Recognizing a backlog's origin front-runs the Step 7 batch shape, but it predicts *where issues came from*, not *whether they're disjoint* — always confirm via the contested-file grep (Step 5), never substitute the prior for it:

- **CR-surfaced** (issues found while reviewing recent feature work) tend to be **naturally disjoint** — the reviewer found one bug per surface — so high parallelism is the default, not the exception (process-log 2026-05-09: 6 agents, zero contested files). Don't impose sequential gates just because past backlogs had them.
- **Feature-followup** (issues filed against a just-shipped feature) cluster *or* disperse depending on **where the cycle's defects landed**, not on the fact that they're followups. When the followups all land in one partial (the implementer's TODOs, the reviewer's smells, and the QA gaps on the same file) expect a single-file critical path with a few parallel-safe outliers (process-log 2026-05-11: critical path through one template across three batches). But when the originating cycle spread defects **one-per-layer** across the stack, the same followup provenance produces a **CR-like, near-fully-disjoint** backlog (process-log 2026-06-28: six 5h.x followups across model / ETL / CLI / admin JS / admin meta / theme → high parallelism, single doc-file overlap). Heuristic: one-partial → clusters; across-the-stack → disjoint. Don't assume a single-file critical path just because the backlog is followup-derived.
- **Spec-derived** and **deep-architectural-chain** backlogs sit between: the spec or the shared core file dictates a foundation-then-split shape.

### Step 7: Batch design

Group issues into **merge batches**. The core principle: within a batch, all agents work on branches with disjoint file coverage so PRs can be merged in any order. Between batches, a gate ensures prior work is merged and stable before the next batch begins.

**Batch design rules:**
- **Batch 0 / Batch A**: truly isolated issues — each touches files no other issue in this batch touches. Maximum agent count.
- **Cap parallel agents at the project's worktree provisioning ceiling** (Q5 / Rule 5). The effective per-batch parallelism is `min(file-disjoint count, project worktree ceiling)`. Exceeding the ceiling produces silent fall-through, not a graceful error — see Rule 5.
- **Chunk when N > ceiling**: if a batch has more file-disjoint agents than the ceiling permits, split it into sub-waves (A1 ≤ ceiling, A2 launches after A1's worktrees free). Agents within a sub-wave run in parallel up to the ceiling; sub-waves themselves run sequentially, each merging into the same `batch/<X>` branch. Narrowing the batch (dropping issues) is the fallback only when chunking would create new file conflicts across sub-waves.
- **Subsequent batches**: ordered by the dependency chain of contested files. One agent per batch on the critical path; parallelize only where file coverage is genuinely disjoint.
- **Pick a shape for same-file issue pairs** — when two issues share a file (typically a small prerequisite + a larger dependent), there are two clean shapes:
  - **Shape A — bundle in one agent with sequential commits.** Touch the same file(s), both pieces small enough that reviewing together is the natural shape (e.g. define constants then use them; fix protocol then add config models). Lower ceremony — no gate, single review.
  - **Shape B — prerequisite in the parallel batch, dependent in its own batch.** Pieces have wildly different sizes (small ~50-line prerequisite, large multi-file/~1500-line dependent) or bundling would force one big reviewer context-switch. Cost: one extra batch boundary. Gain: the small prerequisite ships in parallel with unrelated work; the large dependent gets reviewed on its own merits.
  - **Heuristic for picking**: the real signal is whether the pieces are *naturally sequenced* (define → use), not merely that they share a file. Bundle when both pieces fit a single review session (≈ under 500 lines combined) AND form one define→use sequence; split when the dependent dwarfs the prerequisite, OR when the pieces differ in kind even if both are small — e.g. a mechanical 1-line refactor and a UX feature on the same file are better as two clean review surfaces than one bundle, and gates between single-agent batches are cheap (process-log 2026-05-11). Test: would you review them in separate sittings anyway?
- **Correctness fixes first within a batch**: if a targeted bug fix touches a file that later gets a wide refactor, put the bug fix at the head of the refactor agent's commit sequence, not in an earlier parallel slot.
- **Foundation shared files are read-only for the follow-up batch.** When a Batch A foundation issue ships a new shared file (e.g. a test harness bootstrap, a coverage index, a base class) that downstream Batch B agents could plausibly want to extend, explicitly declare it read-only in the design doc's Key Decisions section and route necessary edits as small post-merge PRs after Batch B lands. Prevents the "three concurrent edits to one foundation file" failure mode by removing the temptation to amend it in flight.
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

Use a feature branch + PR when the host project enforces filesystem isolation for plan creation (e.g. a workspace-isolation pre-commit hook that names "spec/plan creation" as an in-worktree activity), or when the user wants a review checkpoint before launching agents. Ask if the project's conventions aren't already clear. In that case, choose one of:
- **Merge the doc PR before launching workers** (cleanest; workers' local main sees the doc on disk), OR
- **Include the plan in the Agent tool's prompt when launching each worker** (workers don't actually need the doc on disk to function; acceptable if the user wants the doc PR to land alongside the batch branch), OR
- **Write the plan inside a docs-only worktree, then merge from main** — for projects whose worktree-create tooling supports a lightweight "no DB clone / docs-only" flag (e.g. `--shared-db` in cannabis.observer-wordpress). Provision the worktree, write the plan inside it, and commit with `git -C <worktree> commit -F /tmp/<branch>-msg.txt` (apostrophe-safe). Then `git merge --no-ff <branch>` from the main checkout and destroy the worktree.

**Commit format.**

```
#<n> docs: add <topic> backlog orchestration plan
```

The `#<n>` prefix is the tracking issue number, which doesn't exist until Step 9. Two viable orderings: (a) commit without the `#<n>` prefix, then open the issue (recent precedent in this repo); (b) open the issue first, then commit with the prefix. Either works — don't block waiting for an issue number.

### Step 9: GitHub tracking issue

Write the body to a temp file and pass `--body-file`. Apostrophes in the body break the heredoc form even under single quotes (see process-log Sessions 2026-05-24 / 2026-05-25 / 2026-06-08 / 2026-06-09).

```bash
cat > /tmp/<topic>-tracking-body.md <<'EOF'
## Summary
<2–3 sentences>

## Design doc
`docs/plans/YYYY-MM-DD-<topic>-backlog.md`

## Scope
**Batch A — N parallel agents**
- #n Issue title
...

**Batch B — 1 agent (after A merged)**
- #n, #m Issue titles
...

**Deferred:** #n, #m (reason)
EOF

gh issue create \
  --title "<topic>: prioritized backlog clearance (<N> batches, <M> issues)" \
  --body-file /tmp/<topic>-tracking-body.md
```

Report the issue number.

### Step 10: Process documentation

After the plan is approved and committed, capture any adjustments made during this session:
- Did the user adjust rubric weights? Document the new formula.
- Were any standard questions skipped or reordered? Note why.
- Did any conflict analysis surface surprises? Record the pattern.
- Were any rubric dimensions inadequate for this project type? Flag for skill revision.

**Where to capture them.** Append a new session entry to [`references/process-log.md`](references/process-log.md) and update its index table (date, project, headline). The log is the default destination — it preserves chronology and session-specific context. Promote a pattern into the body of this skill only when it has recurred across sessions OR introduces a new rule/step that future orchestrators need at runtime. Don't double-write: once promoted, leave the originating log entry intact as the historical record, but trim it if the body now carries the load.

---

## Agent Roles

### Branch strategy

Each **multi-agent batch** gets a shared integration branch (e.g. `batch/a`, `batch/f`). The orchestrator creates this branch and checks it out **before spawning any agents** — it is the merge *target* for every worker in the batch. Worker agents use `isolation: "worktree"` for an isolated working directory, but **do not assume their completed work auto-merges onto the batch branch** — the harness's post-completion behavior is inconsistent (see Rule 3). The orchestrator reconciles and merges each worker explicitly on its completion signal (Orchestrator step 5).

**Single-agent batches** do not need a separate batch branch — the agent's feature branch serves directly.

The human review happens against the **batch branch**: run tests, inspect the combined diff, then merge to `main`. After merge, the orchestrator checks `main` back out, pulls to sync, and uses it as the base for the next batch branch.

**Intra-batch worker→batch integration must be fast-forward or regular-merge — not squash or rebase.** The orchestrator destroys completed workers' worktrees via `worktree-destroy.sh --base batch/<X>` (Orchestrator step 5), which verifies the worker branch is an ancestor of `batch/<X>`. Squash merges drop the parent link and rebase rewrites commits; both break the ancestor check and force the orchestrator to descope the destroy, defeating the merge-safety gate. This is a separate decision from the batch-branch→main merge strategy below (which the user picks).

Ask the user their preferred **batch→main** merge strategy (regular, squash, rebase) and record it in the design doc. The intra-batch strategy is fixed at FF/regular-merge regardless.

### Orchestrator agent

The orchestrator reads the batch plan and manages progression. It:
1. **Sync local main before every batch launch** — `git checkout main && git pull --ff-only`. Agents worktree from local main; if local main is stale, agents base their work on the wrong commit.
2. **Check out the batch branch before spawning agents** — `git checkout -b batch/<X>`. This makes `batch/<X>` the intended merge target. Worker output does NOT reliably auto-merge there — the orchestrator reconciles and merges each worker explicitly on completion (step 5, Rule 3).
3. **Verify worktree slot availability** — before launching, check that consumed slots + planned agents ≤ project ceiling (Rule 5). Prefer the host project's own slot-status command if it exists (e.g., a `dev.sh worktree status` or listing files in the port-pool directory) — this reports the **actual** resource consumption. If only the git-worktree count is available, use `bash skills/using-git-worktrees/scripts/worktree-list.sh --porcelain | grep -c '^worktree '` (minus 1 for the main checkout) as a **lower-bound** proxy and apply a safety margin (e.g., treat the effective ceiling as `ceiling - 1`) to absorb port leaks from previously-destroyed worktrees whose project-side cleanup didn't run.
4. Launches all worker agents whose batch gate is currently satisfied simultaneously
5. **On each worker completion signal** (reconcile, then merge — do not assume auto-merge; Rule 3):
   - Run `git -C <main> status --porcelain` (Rule 6). Any output → halt the batch and salvage.
   - Locate the worker's work: run `git branch --no-merged batch/<X>` to surface every local branch carrying commits not yet on the batch branch — this catches both `worktree-agent-*` and custom-named branches regardless of the orchestrator's current checkout (don't rely on `git log batch/<X>..HEAD`, which only sees a branch if the workspace shifted onto it). Also check `git branch --show-current` (the workspace may have shifted off `batch/<X>`) and the worktree directory (e.g. `.claude/worktrees/agent-<id>/`) for uncommitted changes; if work was left uncommitted, commit it on the worker's branch with the prescribed message format first.
   - Merge the worker's branch into `batch/<X>` if it isn't already an ancestor (`git merge --no-ff <agent-branch>`), respecting any intra-batch ordering; merge conflicts return to the responsible worker agent to resolve.
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

1. **Confirm your auto-provisioned worktree** — you are launched inside an isolated worktree created by `isolation: "worktree"` (typically on a `worktree-agent-<id>` branch); do NOT create your own. Work on the branch you're on — the orchestrator discovers and merges it by content, not by name (Orchestrator step 5). Worktree mechanics: [`using-git-worktrees`](../using-git-worktrees/).
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
- **Pick a shape for same-file pairs** — bundle (Shape A: one agent, sequential commits) when both pieces fit in a single review session and form a define→use sequence; split (Shape B: prerequisite in parallel batch, dependent in its own) when the dependent dwarfs the prerequisite or the pieces differ in kind (e.g. mechanical refactor + UX feature). See Step 7 batch design rules.
- **Worktrees always — and verify the host project can provision them** — use `isolation: "worktree"` for all worker agents; each gets an isolated working directory. Pre-create and check out the batch branch first so it is the merge target — but reconcile and merge each worker explicitly, since the parameter's auto-merge behavior is unreliable (Rule 3). The Agent tool parameter does NOT guarantee filesystem isolation if the host project's worktree-create script falls through (port pool exhausted, docker port collision, etc.); cap per-batch agents at the project's provisioning ceiling (Rule 5) and detect fall-through at runtime (Rule 6).
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
git merge --ff-only batch/x   # or rebase; whatever the agreed strategy is
git push origin main
```

If local `main` is already up to date with the merged batch (the human merged `batch/<X>` → `main` per Rule 3), just:
```bash
git push origin main   # from local main after verifying it is up to date
```

### Rule 3 — Do not assume `isolation: "worktree"` auto-merges; verify and merge per worker

The `isolation: "worktree"` Agent tool parameter creates a temporary worktree and runs the agent in it. Its post-completion behavior is **inconsistent** — it is NOT reliable that the agent's work auto-merges onto the orchestrator's current branch. Observed across sessions (process-log 2026-05-09, 2026-05-11), parallel volleys produced all of:
- work left on a per-agent `worktree-agent-<id>` branch, un-merged (most common);
- work committed directly onto the orchestrator's current branch (occasional);
- work on a custom-named feature branch the agent picked;
- work left **uncommitted** in the worktree directory despite a "completed" signal.

Branch base also varies: some agents branch from `origin/main` HEAD at worktree-creation time, others from the orchestrator's current local HEAD.

**Operating rule: the orchestrator owns the merge.** Check out the batch branch *before* spawning agents so it is the intended merge target, but treat every worker completion as "reconcile, then merge explicitly" — never "assume it landed."

**Canonical pattern for multi-agent batches:**

```bash
git checkout main
git pull --ff-only               # sync (Rule 1)
git checkout -b batch/f          # batch branch = merge target
# spawn all worker agents with isolation: "worktree"
# reconcile + merge each one explicitly as it completes (see Orchestrator step 5)
```

**On each worker completion signal, the orchestrator reconciles before trusting the result** — never assume the work landed. Because the branch may be `worktree-agent-*`, a custom name, or absent (work left uncommitted in the worktree), the orchestrator discovers the worker's actual output, commits anything left uncommitted, merges it into `batch/<X>` explicitly, then cleans up. The full runtime checklist is **Orchestrator step 5** — the single authoritative copy; follow it on every completion rather than duplicating it here.

After human review and merge approval:

```bash
git checkout main
git merge --ff-only batch/f      # or rebase/squash per agreed strategy
git push origin main
# sync local main before next batch (Rule 1)
```

Consequences of this model:
- Per-agent worktree branches may persist after completion — the orchestrator merges and cleans them up; never assume they auto-merged
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

**Slot-reclaim semantics**: a well-behaved host-project `worktree destroy` synchronously frees its slot (port, vhost, DB clone) and the next `worktree create` reclaims the lowest-available number. The ceiling check therefore counts *concurrently-live* worktrees, not lifetime-allocated — a stale-slot leak is only possible when `destroy` fails partway, not under normal operation. This is what makes chunking work: destroying a sub-wave's completed worktrees before launching the next is sufficient; you don't need a wider pool.

**Recording the ceiling**: capture it in the design doc's "Approved approach" section so subsequent sessions inherit it without re-interviewing. To cheaply *re-verify* an established ceiling in a follow-up session, just read the port number off any in-session `worktree create` output (e.g. the plan-doc worktree) — the pool's bounds don't change between sessions, so one assignment confirms it. Avoids re-interviewing or re-grepping the host script.

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

## Process Logs

Session-specific institutional memory — interview answers, batch shapes, non-obvious decisions, and tactical lessons — lives in [`references/process-log.md`](references/process-log.md). Several rules and patterns in this document originated there:

- Rules 5/6 (per-batch ceiling, runtime fall-through detection) — 2026-05-22 port-pool incident
- Rule 3 revision (auto-merge is unreliable → verify-and-merge per worker; reconciliation checklist) — 2026-05-09, 2026-05-11
- Step 1–2 closed-in-fact grep per issue + Step 5 footprint grep (bidirectional: understated *and* overstated — partial-fix backlogs overstate) — 2026-05-09, 2026-05-11, 2026-06-28
- Step 5/6 backlog-provenance geometry (CR-surfaced → disjoint; feature-followup → one-partial clusters / across-the-stack disperses) — 2026-05-09, 2026-05-11, 2026-06-28
- Step 7 Shape A/B distinction (bundle vs. split same-file pairs) — 2026-05-25, 2026-06-09; "differ in kind" refinement — 2026-05-11
- Steps 5/6 "low-discovery backlog mode" — 2026-06-08 (spec-derived), 2026-06-09 (followup-derived)
- Step 7 "foundation shared files are read-only" rule — 2026-06-08
- Step 8 docs-only-worktree authoring option — 2026-06-08
- Step 9 `--body-file` over heredoc — confirmed across 2026-05-24, 2026-05-25, 2026-06-08, 2026-06-09
- Rule 5 slot-reclaim semantics + cheap ceiling re-verification — 2026-06-09
- Rubric variable-weight escape hatch — confirmed for **Foundation**-leading (×3), not just Correctness — 2026-05-24 (Correctness ×3), 2026-06-29 (Foundation ×3)
- Blast ≠ priority refinement: a single issue whose blast intersects **multiple** otherwise-parallel agents → isolate in its own gated batch (grep call sites to verify) — 2026-06-29

When closing out a backlog orchestration session (Step 10), append a new entry to the reference file and update its index table. Promote any stable cross-session pattern into the body of this skill; leave one-off tactical details in the log.
