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

Create a task for each item and complete them in order. Item numbers match the `Step N` headings below; item 0 runs before the numbered sequence, like Q0.

0. **Sync local main** — `git checkout main && git pull --ff-only`; clear any untracked stray from the checkout (Rule 1)
1. **Fetch all open issues** — `gh issue list --state open --limit 50 --json number,title,labels,body`
2. **Explore project context** — read AGENTS.md, recent commits, existing design docs
3. **Interview user** — establish rubrics and constraints (one question at a time)
4. **Score all issues** — apply rubrics, present table, get approval
5. **Analyze conflict zones** — identify files touched by multiple issues; build dependency graph
6. **Present dependency analysis** — get approval before batch design
7. **Design batch plan** — assign issues to merge batches; get approval
8. **Write design doc** — `docs/plans/YYYY-MM-DD-<topic>-backlog.md`; commit
9. **Open GitHub tracking issue** — link to design doc; list batches
10. **Capture session learnings** — journal the session via `references/process-log.md`; promote only what recurs or adds a rule

---

## Process

### Step 1–2: Context gathering

**Sync `main` before analysing, not just before launching** (Rule 1, which carries both the commands and why a stale checkout corrupts the plan), then clear any untracked stray from the main checkout. The stray sweep is Rule 6 hygiene — its fall-through detection assumes a clean baseline, or it reports a dirty tree on every completion signal.

Then fetch issues and read project context before asking any questions. Go into the interview knowing:
- Rough categories of issues (architectural, bug, feature, infra)
- Which files are most frequently touched across issues
- Which issues are already **closed-in-fact**. For *every* issue (not just the obviously-stale ones), grep at least one identifying symbol from its body, plus `Issue #<n>` in the files it names — module/template docstrings often credit the PR that retired a footgun. Don't trust the issue body's claim about current file state. Cross-reference recent commits. Surface any closed-in-fact issue in the score table so a batch slot isn't allocated to dead work (process-log 2026-05-11: the highest-scored issue in a backlog was already resolved). **Zero hits is ambiguous, not exculpatory** — it means "not done" *or* "done under another name". Disambiguate by reading the doc the issue names as its contract; a deliberately-deferred issue exists precisely to stay greppable while the architecture moves underneath it (2026-08-13 observo: #109's symbol had zero hits repo-wide, and its cited anchor had moved to a doc naming its approach as the *rejected* path). Docstrings cut both ways — one naming pending follow-ups by number confirms an issue is open in fact (2026-08-13 power-map).
- **Dispositions that need more than that grep** — an issue blocked on a *finding inside* another issue, a partially-shipped issue (**rescope-to-residual**, a fourth disposition beside keep / close / defer), and a claim about a **generated** artifact: [references/issue-audit.md](references/issue-audit.md).
- Pairs of issues that may describe the same underlying bug or fix, **or a deliberate prerequisite relationship** — check title overlap, body keywords, and **files/symbols mentioned** (files/symbols catches pairs that don't share title language). If a candidate pair is found, surface as Q0 in Step 3 — resolving before scoring avoids redundant ranking and accidental two-agent overlap, and lets the batch design inherit the pair's shape rather than re-derive it.

### Step 3: Interview (one question at a time)

These questions establish everything needed. Ask them in order; do not stack multiple questions.

**Q0 (conditional) — Resolve any candidate pairs surfaced in Step 1–2 (duplicate *or* prerequisite), plus any rescope-to-residual verdicts.**
> For each candidate pair: **bundle** (one agent handles both — Shape A in Step 7), **close one as dup**, or **score independently** (two separate work items — Step 7 decides batch shape)?
> For each partially-shipped issue: **rescope to the verified residual** (rewrite the body down to what is genuinely still open, then re-score it as the smaller item it now is), **close as done**, or **defer**?

Skip Q0 entirely if Step 1–2 flagged neither a candidate pair nor a partially-shipped issue. The HARD-GATE permits this question because it gates *priorities*, not clarifying questions. Close any agreed-upon dups via `gh issue close <issue> --comment 'duplicate of #<survivor>'` before moving to Q1 so the scored backlog reflects the resolved state and the closed issue records the dup link.

**Q1 — What does "quality" mean here?**
> Which matters most: testability, correctness, maintainability, or all roughly equally?

**Q2 — What is the deployment context?**
> Pre-production (runway to build it right), early production (real users, low volume), or active production (stability required)?

**Q3 — Are any issue categories explicitly deferred?**
> e.g. "Phase 7 fetchers are not a priority right now" — establishes what to exclude from scoring

**Q4 — Parallelism preference?**
> Maximize parallel agents, sequential waves, or hybrid (parallel within batches, gates between)?
> Follow up: worktrees for branch isolation? (almost always yes)

**Q5 — Concurrency ceiling: worktree provisioning *and* shared backing services?**

Two sub-questions, both capping the per-batch agent count regardless of file-disjointness. Ask them together; either can independently set the ceiling.

> 1. Does the host project have a custom worktree-create script (e.g. `dev.sh worktree create`)? What concurrent ceiling does it support, and what does it provision beyond plain `git worktree add` — Nginx vhosts, DB clones, port pools, node_modules overlays? If the user doesn't know, ask them to grep the script for port-pool size or docker-compose port ranges first.
> 2. **What backing services do the worktrees NOT clone?** A shared test database, a shared Redis, a shared search index, a single dev-server port. Plain `git worktree` clones *none* of these, so a project with **no** worktree script can still have a hard ceiling of 1.

The real ceiling is far more often in sub-question 2 than in 1. **Ask it explicitly — don't wait to rediscover it in Step 5.** But accept "none" as an answer: some repos have neither, and the accumulated positives make it tempting to keep hunting until a ceiling appears (process-log 2026-08-12: plain `git worktree` plus a hermetic suite → the cap was host CPU/RAM alone, confirmed by one grep for `docker|POSTGRES|DATABASE_URL|PORT_POOL`). A grep hit is not a ceiling until you read the path: in a repo whose product is templates, the escape greps hit its own documentation of the hazard (2026-08-18 skills).

For a shared test database, read the suite's fixture and DSN guard, and check the role can create slots, before accepting any ceiling — then choose from the provision / serialize / cap ladder: [references/shared-backing-services.md](references/shared-backing-services.md).

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

Present the scored table sorted by score descending. Include a blast column (Low/Med/High).

**Decide-then-rescore at the approval gate.** When an issue scores Scope Clarity 1 *because the issue itself names an unresolved decision*, surface that decision at this gate and re-score after it is answered — don't score around the ambiguity, and don't let a worker make what is really a product call. Distinct from Q0, which runs *before* scoring; you cannot tell which issues need this until you have scored them. Two such decisions moved one issue from 14 to 16 (top of the table) and another's blast from Med to High before any batch design happened (process-log 2026-08-11 observo). **Where the decision is empirical, measure it here instead of asking** — "measure first", a named decider or an unrun recommendation is usually minutes from evidence that can falsify the body (2026-08-21, 2026-08-27, 2026-09-14 observo). **A decision can also move the dependency *graph*, not just a score — ask of each option whether it creates or removes a conflict edge.** One option put a second issue on the same response schema, which is the whole reason it gated into a later batch, and a rejected option would have put another onto a shared schema file, collapsing a three-agent batch to two-plus-a-gate (2026-08-28 power-map); another removed an issue from the backlog's most contested file entirely, dissolving the rationale that had bundled it while the bundle survived on a new one (2026-08-23). The footprints are unmeasurable until the option is named, so **re-derive each Q0 bundle's rationale after this gate** — nothing goes red when a plan's stated reason stops being true.

**Write scope changes back to GitHub, not just into the design doc.** Whenever the gate or a Step 5 grep changes an issue's boundary — a rescope, a descope into a new issue, a decision recorded — `gh issue edit`/`create`/`comment` it, preserving the rejected option's rationale as a pointer rather than deleting it. The agent that eventually picks the issue up sees the real boundary rather than the as-filed one (process-log 2026-08-09, 2026-08-11 observo).

Get approval before moving to conflict analysis.

### Step 5–6: Conflict zone analysis

Identify files touched by 2+ issues — these drive sequencing decisions:

1. Grep the contested symbols/keywords to confirm each issue's *real* file footprint matches its stated scope — the grep runs in **both** directions. Issue bodies frequently **understate** scope (process-log 2026-05-09: a fix scoped to a single dedup script was actually 5× larger, spanning the ingestion pipeline). They also **overstate** it: **partial-fix backlogs**, where some siblings were already patched in the originating PR, routinely overstate remaining scope (process-log 2026-06-28: #407's claimed sibling transformers were already correct → narrowed to one file; #399's claimed "5h.2-5h.5 sweep" was mostly already patched → narrowed to two commands). A wrong footprint in either direction corrupts the bundling decision and the workers' self-review checks; narrowing also prevents a worker re-fixing already-correct code, so run the grep even when no issue looks stale. Then list each contested file and the issues that touch it. Refinements for each kind of claim a body makes — a stated relationship, a measured number, a hedge on its own claim, an unbounded sweep — are in [references/issue-audit.md](references/issue-audit.md).
2. **Grep the test surface for the literal strings each fix rewrites** — and for the assertions a fix makes *vacuous*, which stay green — then map each agent's owned line-window in any file two agents share. The procedure, and where a shared fixture hides: [references/shared-files.md](references/shared-files.md).
3. **Where a shared backing service sets the ceiling (Q5), grep for the helpers that *escape* the isolation fixture** — a *hard* conflict zone that forces its issue solo. The grep, and why: [references/shared-backing-services.md](references/shared-backing-services.md).
4. Determine required merge order within each file (usually: smaller targeted fixes first, wide refactors last, features after foundations)
5. Derive a dependency graph showing which issues must precede which. Look for edges that **no file overlap can show**: two issues in different regions of the same measurement tool are not independent when one's defect corrupts the input the other's design work must read (process-log 2026-08-11 skills: a normaliser bug reporting every link-carrying line as LOST made the sibling issue's verdict design undecidable → Shape B on regions of one file)

Present the conflict zones and dependency graph. Get approval.

**Priors on batch geometry, to confirm with the grep rather than trust:** a **low-discovery** backlog (spec- or followup-derived) compresses Steps 5/6, and a backlog's **provenance** — AR-surfaced, CR-surfaced, feature-followup, adoption-feedback — predicts its shape. Both: [references/batch-design.md](references/batch-design.md).

### Step 7: Batch design

Group issues into **merge batches**. The core principle: within a batch, all agents work on branches with disjoint file coverage so PRs can be merged in any order. Between batches, a gate ensures prior work is merged and stable before the next batch begins.

**Batch design rules:**
- **Batch 0 / Batch A**: truly isolated issues — each touches files no other issue in this batch touches. Maximum agent count.
- **Cap parallel agents at the project's worktree provisioning ceiling** (Q5 / Rule 5). The effective per-batch parallelism is `min(file-disjoint count, project worktree ceiling)`.
- **Chunk when N > ceiling**: if a batch has more file-disjoint agents than the ceiling permits, split it into sub-waves (A1 ≤ ceiling, A2 launches after A1's worktrees free). Agents within a sub-wave run in parallel up to the ceiling; sub-waves themselves run sequentially, each merging into the same `batch/<X>` branch. Narrowing the batch (dropping issues) is the fallback only when chunking would create new file conflicts across sub-waves.
- **Subsequent batches**: ordered by the dependency chain of contested files. One agent per batch on the critical path; parallelize only where file coverage is genuinely disjoint.
- **Pick a shape for same-file issue pairs** — when two issues share a file (typically a small prerequisite + a larger dependent), there are two clean shapes:
  - **Shape A — bundle in one agent with sequential commits.** Touch the same file(s), both pieces small enough that reviewing together is the natural shape (e.g. define constants then use them; fix protocol then add config models). Lower ceremony — no gate, single review.
  - **Shape B — prerequisite in the parallel batch, dependent in its own batch.** Pieces have wildly different sizes (small ~50-line prerequisite, large multi-file/~1500-line dependent) or bundling would force one big reviewer context-switch. Cost: one extra batch boundary. Gain: the small prerequisite ships in parallel with unrelated work; the large dependent gets reviewed on its own merits.
  - **Heuristic for picking**: the real signal is whether the pieces are *naturally sequenced* (define → use), not merely that they share a file. Bundle when both pieces fit a single review session (≈ under 500 lines combined) AND form one define→use sequence; split when the dependent dwarfs the prerequisite, OR when the pieces differ in kind even if both are small — e.g. a mechanical 1-line refactor and a UX feature on the same file are better as two clean review surfaces than one bundle, and gates between single-agent batches are cheap (process-log 2026-05-11). Test: would you review them in separate sittings anyway?
- **Special cases force a shape, whatever the file map says** — a chain-appending artifact such as a migration, a generated artifact under a byte-for-byte sync test, a design-coherence gate with no file overlap, a foundation shared file, a budget-tight file. Check each: [references/batch-design.md](references/batch-design.md).
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

Read [references/execution.md](references/execution.md) before writing it: the doc records the batch→main merge strategy that file has you ask for, and carries its Rules 1–6 as the runtime's checklist.

Sections:
- **Goal** — one paragraph
- **Approved approach** — summary
- **Prioritization rubrics** — table + formula
- **Scored backlog** — full table
- **Conflict zones** — contested files and their required merge order
- **Dependency graph** — ASCII or text
- **Batch execution plan** — per-batch table with agents, issues, files, gate condition
- **Key decisions** — rationale for non-obvious choices (e.g. why a correctness fix leads a refactor batch); name any read-only shared files, the batch's single chain-appending agent, and any verification-mode asymmetry (an agent that changes the test runner's config verifies under the *old* mode in its own worktree, so the orchestrator's post-merge run is the first under the new one — say so, or a distribution-mode interaction gets misattributed to one agent's defect)
- **Runtime note on issue-body decay** — the backlog is N sequential mutations of what the bodies describe, so re-verify the specifics of any issue whose files an earlier batch touched (Worker step 5); the later the batch, the staler the body
- **Deferred items** — what was explicitly excluded and why
- **Out of scope** — anything that came up but was ruled out

**Where to commit.** Default: directly on `main` — it matches the orchestrator's "workers branch from local main" assumption (Rule 1) and avoids an extra merge gate before launching agents. Use a feature branch + PR when the host project enforces filesystem isolation for plan creation (e.g. a workspace-isolation pre-commit hook naming "spec/plan creation" as an in-worktree activity), or when the user wants a review checkpoint first; ask if the conventions aren't already clear. The three routes for that case — merge-then-launch, plan-in-the-prompt, and the docs-only worktree — are in [`references/design-doc-authoring.md`](references/design-doc-authoring.md).

**Commit format:** `#<n> docs: add <topic> backlog orchestration plan`, where `#<n>` is the Step 9 tracking issue — open it first, or commit unprefixed; don't block on the number.

### Step 9: GitHub tracking issue

Write the body to a temp file and pass `--body-file`. Apostrophes in the body break the heredoc form even under single quotes (process-log 2026-05-24 onward).

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

After the plan is approved and committed, capture this session's adjustments: rubric weights the user changed (document the new formula), standard questions skipped or reordered (note why), surprises the conflict analysis surfaced (record the pattern), and rubric dimensions that proved inadequate for this project type (flag for skill revision).

**Where to capture them.** Write a session entry file under `references/process-log/<year>/`, plus one row (date, project, headline) in that year's own `index.md` beside it — the layout rules are in [`references/process-log.md`](references/process-log.md). The log is the default destination — it preserves chronology and session-specific context. Promote a pattern into the body of this skill only when it has recurred across sessions OR introduces a new rule/step that future orchestrators need at runtime. Don't double-write: once promoted, leave the originating log entry intact as the historical record, but trim it if the body now carries the load.

---

## Executing the plan

The branch strategy, the orchestrator and worker protocols, Branch Hygiene Rules 1–6 and the recovery procedure are in [references/execution.md](references/execution.md), and the Rule, Orchestrator-step and Worker-step numbers this file cites refer to it. Read it before Step 8 — the design doc records the batch→main merge strategy it asks for — and before launching any batch.

## Key Principles

- **One question at a time** — stacking questions gets partial answers
- **Approval gates are real** — do not proceed past a section without explicit user sign-off
- **Blast radius ≠ priority** — a high-blast issue may score high but still wait for lower-priority isolates to merge first. Three variants: **score determines what gets done, ordering constraints determine when** — a zero-conflict issue is the most *schedulable* thing in a backlog, so it fills whichever slot would otherwise idle rather than earning Batch A by score (2026-08-11 observo); a **trivial issue can be a hard gate** when its guard must exist before a later issue widens the surface it guards (2026-08-07); and an issue whose deliverable is a **measurement of the final state** sequences last on epistemics, not contention — run early, it measures a state that won't exist at merge time (2026-08-11 usa-wa)
- **Worktrees always — and verify the host project can provision them** — `isolation: "worktree"` for every worker; the batch branch is the merge *target*, not the base, so brief each worker to merge it and reconcile each explicitly (Rule 3). The parameter does NOT guarantee filesystem isolation: cap per-batch agents at the provisioning ceiling (Rule 5) and detect fall-through at runtime (Rule 6).
- **Deferred is a decision** — explicitly name what is out of scope and why; don't silently omit
- **Orchestrator launches all unblocked batches** — not just the next one in sequence; if two independent batches become unblocked simultaneously, launch both

---

## Detail Docs

- [references/execution.md](references/execution.md) — running the approved plan: branch strategy, orchestrator and worker protocols, Branch Hygiene Rules 1–6, recovery
- [references/issue-audit.md](references/issue-audit.md) — what an issue body claims, checked: blocked on a finding, rescope-to-residual, generated artifacts, the footprint-grep refinements
- [references/shared-files.md](references/shared-files.md) — two issues on one file: the test-surface grep, vacuous assertions, line-window ownership, where shared fixtures hide
- [references/shared-backing-services.md](references/shared-backing-services.md) — a shared test database as the ceiling: fixture and guard checks, the resolution ladder, the escape grep
- [references/batch-design.md](references/batch-design.md) — the special cases that force a batch shape, backlog-provenance priors, low-discovery mode
- [references/design-doc-authoring.md](references/design-doc-authoring.md) — committing the plan when `main` is not writable
- [references/recovery.md](references/recovery.md) — salvaging a worker that fell through into the main checkout
- [references/process-log.md](references/process-log.md) — the session journal, and the rules promoted from it

## Process Logs

Session memory lives in [`references/process-log.md`](references/process-log.md), which also records which rules in this file originated there.

**Self-budget:** held to a **9,800-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — a named exception to the repo's
6,000-token standard, set so this file cannot grow. Came down from 23,110
when the #285 curation moved the execution protocol and the conditional
hazards into references/; that test's comment carries the argument.
