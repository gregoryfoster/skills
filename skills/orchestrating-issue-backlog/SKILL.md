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
10. **Capture session learnings** — journal the session via `references/process-log.md`; promote patterns into this skill only when they recur or introduce a new rule

---

## Process

### Step 1–2: Context gathering

**Sync `main` before analysing, not just before launching** (Rule 1) — `git checkout main && git pull --ff-only`, then clear any untracked stray from the main checkout. Rule 1 carries why a stale checkout corrupts the plan. The stray sweep is Rule 6 hygiene — its fall-through detection assumes a clean baseline, or it reports a dirty tree on every completion signal.

Then fetch issues and read project context before asking any questions. Go into the interview knowing:
- Rough categories of issues (architectural, bug, feature, infra)
- Which files are most frequently touched across issues
- Which issues are already **closed-in-fact**. For *every* issue (not just the obviously-stale ones), grep at least one identifying symbol from its body, plus `Issue #<n>` in the files it names — module/template docstrings often credit the PR that retired a footgun. Don't trust the issue body's claim about current file state. Cross-reference recent commits. Surface any closed-in-fact issue in the score table so a batch slot isn't allocated to dead work (process-log 2026-05-11: the highest-scored issue in a backlog was already resolved). **Zero hits is ambiguous, not exculpatory** — it means "not done" *or* "done under another name". Disambiguate by reading the doc the issue names as its contract; a deliberately-deferred issue exists precisely to stay greppable while the architecture moves underneath it (2026-08-13 observo: #109's symbol had zero hits repo-wide, and its cited anchor had moved to a doc naming its approach as the *rejected* path). Docstrings cut both ways — one naming pending follow-ups by number confirms an issue is open in fact (2026-08-13 power-map).
- **A closed prerequisite is not a met prerequisite.** When an issue names a specific *finding inside* another issue as its blocker, grep the finding, not the issue's state (process-log 2026-08-10: #655 was closed, but its "finding 5" was a different finding and the blocker was still live — the cheap read would have had a worker delete a live ACF field group).
- **Neither open nor closed → rescope-to-residual.** An issue whose *headline* work already shipped but whose comment thread names follow-on scope is a fourth disposition beside keep / close-as-done / defer: rewrite the body down to the verified residual and re-score it as the smaller item it now is (process-log 2026-08-11 usa-wa: a would-be foundation item fell to 7/18). Signal to look for: grep the body's deliverables **and** each comment's, separately — a body can read as fully open while the thread has moved past it. Same verdict as the 2026-06-16 validity-re-analysis gate, reached by a different route (there a just-merged change invalidated the issue; here its own partial delivery did). **Rescope only when the residual is schedulable — defer when the residual's own blocker sits outside the set being orchestrated.** This bites when the user names specific issue numbers rather than "the backlog": check each survivor's blockers against the *named* set, not against the repo's open issues (process-log 2026-08-12: #117's residual was blocked on an issue the user hadn't named, so any slot given it was dead work).
- For issues asserting facts about a **generated** artifact (an OpenAPI snapshot, a lockfile, a compiled schema), read the artifact. The body is a snapshot of filing time; the artifact is regenerated by unrelated work (process-log 2026-08-10: reading `openapi.json` showed one claim already shipped and collapsed the remainder into a duplicate that shared no title language).
- Pairs of issues that may describe the same underlying bug or fix, **or a deliberate prerequisite relationship** — check title overlap, body keywords, and **files/symbols mentioned** (files/symbols catches pairs that don't share title language). If a candidate pair is found, surface as Q0 in Step 3 — resolving before scoring avoids redundant ranking and accidental two-agent overlap, and lets the batch design inherit the pair's shape rather than re-derive it.

### Step 3: Interview (one question at a time)

These questions establish everything needed. Ask them in order; do not stack multiple questions.

**Q0 (conditional) — Resolve any candidate pairs surfaced in Step 1–2 (duplicate *or* prerequisite), plus any rescope-to-residual verdicts.**
> For each candidate pair: **bundle** (one agent handles both — see the "Bundle related issues" rule in Step 7), **close one as dup**, or **score independently** (two separate work items — Step 7 decides batch shape)?
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

Nine sessions across four projects have found the real ceiling in sub-question 2, not 1 (dates on the Q5 line under Process Logs). **Ask it explicitly — don't wait to rediscover it in Step 5.** But accept "none" as an answer: one session found neither, and the accumulated positives make it tempting to keep hunting until a ceiling appears (process-log 2026-08-12: plain `git worktree` plus a hermetic suite → the cap was host CPU/RAM alone, confirmed by one grep for `docker|POSTGRES|DATABASE_URL|PORT_POOL`).

For a shared test database specifically: read the suite's session-scoped fixture and its DSN guard before accepting any ceiling.
- If the fixture is destructive (`DROP SCHEMA … CASCADE`, `drop_all`, truncate-all), concurrent runs corrupt each other and the ceiling is 1 until slots are provisioned.
- **Read the guard before accepting serialization.** If it validates a *base* DB name before a worker suffix is appended, per-agent databases pass it and the ceiling reverts to the host's CPU/RAM limit (process-log 2026-08-09: `observo_a1_test` passed the `endswith("_test")` assert *and* stayed xdist-compatible as `observo_a1_test_gw0`).

Three resolutions, in preference order:
1. **Provision N slots up front** (N = desired ceiling). The only option preserving both parallelism *and* worker self-verification (Worker steps 7–9 run before the completion signal). Check whether the test role can create them — usually not, so it is a one-time superuser step. Verify with one real run, then put the per-agent DSN in every worker prompt.
2. **Serialize the verification gate** — workers implement in parallel, the orchestrator runs the suite. Cheap, but workers can no longer self-verify before signalling.
3. **Cap agents at 1 per batch.** Always available, wastes all disjointness.

**Naming gotcha:** provisioned slot names must satisfy the suite's own safety guard. A guard like usa-wa's `assert_test_url_safety()`, requiring a `_test` *suffix*, means the obvious `db_test_1 … _4` aborts at conftest import; the slots have to be `db_1_test … db_4_test` (process-log 2026-08-07).

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

**Decide-then-rescore at the approval gate.** When an issue scores Scope Clarity 1 *because the issue itself names an unresolved decision*, surface that decision at this gate and re-score after it is answered — don't score around the ambiguity, and don't let a worker make what is really a product call. Distinct from Q0, which runs *before* scoring; you cannot tell which issues need this until you have scored them. Two such decisions moved one issue from 14 to 16 (top of the table) and another's blast from Med to High before any batch design happened (process-log 2026-08-11 observo).

**Write scope changes back to GitHub, not just into the design doc.** Whenever the gate or a Step 5 grep changes an issue's boundary — a rescope, a descope into a new issue, a decision recorded — `gh issue edit`/`create`/`comment` it, preserving the rejected option's rationale as a pointer rather than deleting it. The agent that eventually picks the issue up sees the real boundary rather than the as-filed one (process-log 2026-08-09, 2026-08-11 observo).

Get approval before moving to conflict analysis.

### Step 5–6: Conflict zone analysis

Identify files touched by 2+ issues — these drive sequencing decisions:

1. Grep the contested symbols/keywords to confirm each issue's *real* file footprint matches its stated scope — the grep runs in **both** directions. Issue bodies frequently **understate** scope (process-log 2026-05-09: a fix scoped to a single dedup script was actually 5× larger, spanning the ingestion pipeline). They also **overstate** it: **partial-fix backlogs**, where some siblings were already patched in the originating PR, routinely overstate remaining scope (process-log 2026-06-28: #407's claimed sibling transformers were already correct → narrowed to one file; #399's claimed "5h.2-5h.5 sweep" was mostly already patched → narrowed to two commands). A wrong footprint in either direction corrupts the bundling decision and the workers' self-review checks; narrowing also prevents a worker re-fixing already-correct code, so run the grep even when no issue looks stale. Then list each contested file and the issues that touch it. Three refinements:
   - **Issue bodies also state *relationships*** — "depends on #N", "do these in order". Treat those as hypotheses, not facts: a stated sequential dependency between two issues whose footprints substantially overlap is usually a **bundling** signal (Shape A) that the author mistook for an ordering constraint. Grep before honoring a stated order (process-log 2026-08-09: two issues filed an hour earlier by the same author carried an explicit "do these in order" note; 5 of 6 production files and 9 test files were shared, so the second agent would have rewritten everything the first just moved).
   - **A grep sizes a *surface*; only execution measures a *behaviour*.** Where an issue reports a **measured** number, beating it requires measuring, not counting occurrences (process-log 2026-08-10: a reference grep found 15 classes and "corrected" an issue's 2-class claim as a 2× understatement; running them in isolation showed **6** actually leaked, and the issue's own number was closer). The grep is authoritative about existence of a call site, not about frequency of an effect.
   - **An issue body's own hedge is a grep target — but write the grep to the artifact's real grammar, or you become the next wrong claim.** Where a body flags its own claim as unverified ("worth confirming before committing to it", "I think", "assuming"), the author located the risk and didn't spend the minute; spend it. Then check your own instrument before reporting: an orchestrator's quick regex is exactly as falsifiable as the issue body it is auditing, and it carries more authority because it arrives as a *correction* (process-log 2026-08-12: a loose `\]\(…\)` sweep of #143's hedge reported a carve-out the issue missed; the implementing agent showed the match was a bare fragment inside inline code, and a correct `[label](target)` extractor found nothing — the re-scoring, design doc and issue comment were all retracted). Distinct from the bidirectional footprint grep, which hunts claims the body states *confidently*.
   - **Size an unbounded "sweep" or "audit" issue, then intersect it.** Such an issue is neither automatically high-blast nor automatically batch-isolating. Enumerate the set (one `grep -rl` plus a per-file counter), then intersect it with co-batch agents' footprints — zero overlap licenses full-ceiling parallelism (process-log 2026-08-11 observo: "worth a sweep" resolved to 17 files / ~64 sites, disjoint from both co-batch agents')
2. **Grep the test surface for the literal strings each fix rewrites.** A large shared test file is two conflict zones, and only one is visible from source-file overlap. The **append** half (every worker adding a test class at EOF) is solved by routing new tests to a new per-agent file. The **modify** half — existing assertions that a fix *invalidates* — is invisible to both the source grep and the issue bodies, which describe script changes and say nothing about tests. Grep the test file for the exact strings, paths and JSON keys each issue changes (process-log 2026-08-11 skills: a 3,560-line test file hardcoded the literal hook command one issue rewrote and the literal log path another changed; neither issue mentioned a test). Then **map each agent's owned line-window before assigning**: separated windows merge cleanly and the file stays contested without serializing the batch, but overlapping windows mean sequencing — which has to be decided here, not discovered at merge time. The technique is not test-specific — the governing property is whether the windows overlap, not the file's kind, so it carries any large shared file including the policy file itself (2026-08-12: three Batch A agents wrote `AGENTS.md` in three separated windows). A non-test file needs one extra clause: **no restructuring, additions within the window only** — a reorder merges cleanly and silently reshuffles another agent's window. Name any genuinely shared line **read-only for both** rather than sequencing around it (2026-08-12: one `parametrize` list naming both contested scripts). When the file-level pass returns *everything touches everything*, escalate to function/region granularity before concluding the backlog is serial — a hub file is usually a set of independent regions (2026-08-13 cli: ten work items on one 525-line file ran 4-wide). Distinct from a shared *fixture* dependency (process-log 2026-07-08: `conftest.py`), which is semantic and needs sequencing rather than a new file
3. **Where a shared backing service sets the ceiling (Q5), grep for the helpers that *escape* the isolation fixture.** A helper that opens its own engine/connection and destroys shared state is a *hard* conflict zone — not the **soft** fixture dependency item 2 ends by naming: it does not degrade other agents, it corrupts them mid-run, and the failure presents as an unrelated worker's mysterious red. It forces its issue solo on a database property with no file-overlap footprint at all (process-log 2026-08-11 usa-wa: a `reset_migration_schemas` helper documented as deliberately bypassing the savepointed `db_session` fixture forced a three-line test fix into its own batch). One grep, run alongside the contested-file grep:
   ```bash
   grep -rnE 'DROP (SCHEMA|DATABASE)|TRUNCATE|create_async_engine|create_engine' --include='*.py' <test trees> <testing helper modules>
   ```
4. Determine required merge order within each file (usually: smaller targeted fixes first, wide refactors last, features after foundations)
5. Derive a dependency graph showing which issues must precede which. Look for edges that **no file overlap can show**: two issues in different regions of the same measurement tool are not independent when one's defect corrupts the input the other's design work must read (process-log 2026-08-11 skills: a normaliser bug reporting every link-carrying line as LOST made the sibling issue's verdict design undecidable → Shape B on regions of one file)

Present the conflict zones and dependency graph. Get approval.

**Low-discovery backlog mode (compressed Steps 5/6).** Two recurring backlog shapes already name their contested files before the orchestrator arrives, collapsing Steps 5/6 to "confirm what the parent artifact already shows":

- **Spec-derived** — issues carved out of a just-merged design spec. The spec already declares the foundation file(s) and the downstream split.
- **Followup-derived** — issues filed during a just-completed shipping cycle as deliberate carve-outs. The shipping cycle's PRs already named the contested files.

Recognize either flavor when the backlog issues were filed in the same session as the artifact they're derived from. Compress Steps 5/6 to "list contested files + confirm there's nothing surprising"; the formal dependency-graph subsection is mostly ceremony when there's one edge. Run the skill anyway — its value moves to Step 7 (batch shape, including the Shape A vs. Shape B decision) and Step 8 (design-doc as a permanent ops manual for the orchestrator runtime: Rules 1–6 checklist, branch strategy, Key Decisions).

**Backlog provenance is a prior on batch geometry — confirm it with the grep, don't trust it.** Recognizing a backlog's origin front-runs the Step 7 batch shape, but it predicts *where issues came from*, not *whether they're disjoint* — always confirm via the contested-file grep (Step 5), never substitute the prior for it:

- **AR-surfaced** (issues carved from an *architectural* review) are the **inverse of CR-surfaced, and the trap in this list**: every finding is *about* structure, and structure is shared. Expect many mostly-serial batches, not two wide ones (process-log 2026-08-07: three issues claimed the same 47 CLI entry modules, four claimed root `pyproject.toml`, three claimed `docs/ARCHITECTURE.md` → six batches; 2026-08-09: three parallel waves front-loaded, then a four-link single-agent chain through the provider spine, every edge a shared file). **Do not let "review-derived" imply disjoint — check which kind of review.**
- **CR-surfaced** (issues found while reviewing recent feature work) tend to be **naturally disjoint** — the reviewer found one bug per surface — so high parallelism is the default, not the exception (process-log 2026-05-09: 6 agents, zero contested files). Don't impose sequential gates just because past backlogs had them.
- **Feature-followup** (issues filed against a just-shipped feature) cluster *or* disperse depending on **where the cycle's defects landed**, not on the fact that they're followups. When the followups all land in one partial (the implementer's TODOs, the reviewer's smells, and the QA gaps on the same file) expect a single-file critical path with a few parallel-safe outliers (process-log 2026-05-11: critical path through one template across three batches). But when the originating cycle spread defects **one-per-layer** across the stack, the same followup provenance produces a **CR-like, near-fully-disjoint** backlog (process-log 2026-06-28: six 5h.x followups across model / ETL / CLI / admin JS / admin meta / theme → high parallelism, single doc-file overlap). Heuristic: one-partial → clusters; across-the-stack → disjoint. Don't assume a single-file critical path just because the backlog is followup-derived.
- **Spec-derived** and **deep-architectural-chain** backlogs sit between: the spec or the shared core file dictates a foundation-then-split shape.
- **Adoption-feedback** (defects filed by consumers of a shared library/skill while adopting it, accumulating over weeks against *one* component's file family) is the **tightest clustering shape** — nearly every pair of issues shares a file with some other pair. But it decomposes on an axis the others lack: **the owning file**. The natural agent unit is therefore one agent per owning file, not one per issue (process-log 2026-08-11 skills: 15 issues → 7 parallel agents, grouped by which script each defect lived in). The parallelism comes from the *component's* modularity, not the backlog's independence — so derive the agent count from the file map, not from the issue count.

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
- **At most one chain-appending agent per batch.** Migrations (Alembic `down_revision`, Django dependency lists), sequence-numbered ADRs, and any "append to a linear chain" artifact fork **silently** when two agents generate one in the same batch: both compute the same predecessor, git reports no conflict because the files are different and new, and the break appears only when the chain is replayed (process-log 2026-08-07). Identify chain artifacts during Step 5 and name the owning agent in the design doc.
- **A generated artifact under a byte-for-byte sync test is a hard bundle signal.** When two issues both regenerate the same committed artifact *and* a test pins committed == generated exactly, bundle them (Shape A) regardless of the define→use heuristic — the merge can succeed textually and still fail the build, forcing whichever agent lands second to regenerate. Bundling makes the conflict *impossible* rather than *manageable* (process-log 2026-08-10: two unrelated REST routes, both regenerating `openapi.json` under a byte-for-byte sync test).
- **A gate can be justified by design coherence with zero file overlap.** When one issue's own acceptance says "decide the seam once" and names another as a future consumer, gate it behind that consumer even if the file sets are verified disjoint — otherwise the seam ships with one consumer and a third connective issue becomes necessary (process-log 2026-08-10: the gated seam ended up serving **four** consumers, two of which did not exist as consumers until the gating issue merged). This is the one sanctioned way for Foundation to override a correctness-first ordering; the cost is one batch boundary, not an inverted priority.
- **Correctness fixes first within a batch**: if a targeted bug fix touches a file that later gets a wide refactor, put the bug fix at the head of the refactor agent's commit sequence, not in an earlier parallel slot.
- **Foundation shared files are read-only for the follow-up batch.** The governing property is "one file every agent's verification depends on," regardless of file *kind* — a test harness bootstrap, a coverage index, a base class, or a config file such as `pyproject.toml`'s `addopts` (process-log 2026-08-11 observo). When a Batch A foundation issue ships or mutates one that downstream Batch B agents could plausibly want to extend, explicitly declare it read-only in the design doc's Key Decisions section and route necessary edits as small post-merge PRs after Batch B lands. Prevents the "three concurrent edits to one foundation file" failure mode by removing the temptation to amend it in flight.
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
- **Key decisions** — rationale for non-obvious choices (e.g. why a correctness fix leads a refactor batch); name any read-only shared files, the batch's single chain-appending agent, and any verification-mode asymmetry (an agent that changes the test runner's config verifies under the *old* mode in its own worktree, so the orchestrator's post-merge run is the first under the new one — say so, or a distribution-mode interaction gets misattributed to one agent's defect)
- **Runtime note on issue-body decay** — issue bodies are a snapshot; the backlog is N sequential mutations of what they describe. Re-verify the specifics of any issue whose files an earlier batch touched — the later the batch, the staler the body
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

The `#<n>` prefix is the tracking issue number, which doesn't exist until Step 9. Two orderings work: (a) commit unprefixed, then open the issue; (b) open the issue first, then commit with the prefix (the recent precedent). Don't block waiting for a number.

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

**Where to capture them.** Write a session entry file under `references/process-log/<year>/`, plus one row (date, project, headline) in the index that is [`references/process-log.md`](references/process-log.md). The log is the default destination — it preserves chronology and session-specific context. Promote a pattern into the body of this skill only when it has recurred across sessions OR introduces a new rule/step that future orchestrators need at runtime. Don't double-write: once promoted, leave the originating log entry intact as the historical record, but trim it if the body now carries the load.

---

## Agent Roles

### Branch strategy

Each **multi-agent batch** gets a shared integration branch (e.g. `batch/a`, `batch/f`), created **before any agent is spawned** (Orchestrator step 2, which also says when it may not be checked out). It is the merge *target* for every worker, **not the base their worktrees are cut from**, and worker output does not reliably auto-merge back (Rule 3) — the orchestrator reconciles and merges each worker explicitly (Orchestrator step 5).

**Single-agent batches** do not need a separate batch branch — the agent's feature branch serves directly.

The human review happens against the **batch branch**: run tests, inspect the combined diff, then merge to `main`. After merge, the orchestrator checks `main` back out, pulls to sync, and uses it as the base for the next batch branch.

**Intra-batch worker→batch integration must be fast-forward or regular-merge — not squash or rebase.** The orchestrator destroys completed workers' worktrees via `worktree-destroy.sh --base batch/<X>` (Orchestrator step 5), which verifies the worker branch is an ancestor of `batch/<X>`. Squash merges drop the parent link and rebase rewrites commits; both break the ancestor check and force the orchestrator to descope the destroy, defeating the merge-safety gate. Separate from the batch→main strategy below, which the user picks.

Ask the user their preferred **batch→main** merge strategy (regular, squash, rebase) and record it in the design doc. The intra-batch strategy is fixed at FF/regular-merge regardless.

### Orchestrator agent

The orchestrator reads the batch plan and manages progression. It:
1. **Sync local main before every batch launch** — `git checkout main && git pull --ff-only`. The pull advances `origin/main` too, which is the ref agents' worktrees are actually cut from (Rule 3).
2. **Create the batch branch before spawning agents** — `git checkout -b batch/<X>`. This makes it the merge target only — workers still branch from `origin/main` and must merge it in themselves (Rule 3). **But where the host repo deploys from the main checkout, that checkout's branch must never move.** Grep the deploy units for a checkout guard (`ExecStartPre=.*assert.*main`) before Batch A; where one exists, `git branch batch/<X> main` *without* checking out and integrate in a worktree, and give a single-agent batch no local branch at all — push the worker's own branch as the feature branch. Same caution at wrap-up: run `systemctl is-enabled` and `systemctl cat` before any repo-documented restart, because a unit that is inactive *and* disabled while its preset is enabled is a deliberate hold, not a fault (process-log 2026-08-13 usa-wa: this step stopped production across three separate batches; a documented restart then resurrected a held daemon 94 seconds into an incident).
3. **Verify worktree slot availability** — before launching, check that consumed slots + planned agents ≤ project ceiling (Rule 5). Prefer the host project's own slot-status command (e.g. `dev.sh worktree status`, or listing the port-pool directory) — it reports **actual** resource consumption. Otherwise use `bash skills/using-git-worktrees/scripts/worktree-list.sh --porcelain | grep -c '^worktree '` (minus 1 for the main checkout) as a **lower-bound** proxy, with a safety margin of `ceiling - 1` to absorb port leaks from destroys whose project-side cleanup didn't run.
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

1. **Confirm your auto-provisioned worktree** — you are launched inside one created by `isolation: "worktree"` (typically on a `worktree-agent-<id>` branch); do NOT create your own. Work on the branch you are on — the orchestrator discovers and merges it by content, not name (Orchestrator step 5). Mechanics: [`using-git-worktrees`](../using-git-worktrees/).
2. **Pre-flight: verify isolation** — confirm cwd is an isolated worktree, not the main checkout. Use either:
   - `[ -f "$(git rev-parse --show-toplevel)/.git" ]` — in a linked worktree, `.git` is a *file* pointing to the worktree's git-dir; in the main checkout it's a *directory*. Cheapest reliable check.
   - Or compare resolved paths: `[ "$(realpath "$(git rev-parse --git-dir)")" != "$(realpath "$(git rev-parse --git-common-dir)")" ]`. Do not compare the raw `git rev-parse` outputs without `realpath` — git may return one as absolute and the other as relative depending on cwd, producing false-unequal results that mask a fall-through.

   If the check fails, abort and signal the orchestrator that worktree provisioning fell through (Rule 5/6) — do NOT modify files in the main checkout.
3. **Merge the batch branch** — `git merge batch/<X>`; expect a fast-forward, stop and report anything else. Your worktree is cut from `origin/main`, not the orchestrator's checkout (Rule 3), so after sub-wave 1 it is missing work already on `batch/<X>`. After step 2, never before — a merge writes files.
4. **Verify your brief's baseline** — the expected test count on `batch/<X>` and the interpreter that produces it. If the suite disagrees, STOP and report; do not reconcile to it. If the brief names none, ask before implementing. Catches what step 3 cannot: a brief written against the wrong tree still merges cleanly.
5. **Treat the issue body as a proposal, not a specification.** Verify every file:line, every claimed call site, and every prescribed implementation against the current tree before acting. Where the body is wrong, **report the correction** — do not implement around it silently. Across one 13-issue backlog the implementing agent found a material error in the body **every single time**; three would have shipped a defect as written, and staleness rose with batch depth because earlier batches moved the code the later bodies describe (process-log 2026-08-09). The direction is reliable; the specifics are not. Name those prior failures concretely in each worker prompt.
6. **Implement with TDD** — red → green → refactor
7. **Run full test suite** — all tests must pass
8. **Run linter** — no violations
9. **Self-review diff** — check: correctness, test coverage, project conventions, no unintended side effects outside issue scope
10. **Address findings** — fix before signaling; do not signal with known issues
11. **Signal completion** — notify orchestrator the branch is ready to merge into the batch branch. The orchestrator destroys the worktree after merge (see Orchestrator step 5); the worker does NOT destroy it itself (premature destruction can race with the merge).

**Required report-back slot: everything in the issue body that turned out to be wrong or stale.** Phrase it with the second clause — *"I want the corrections, not a report that matches the prediction"* — because without it agents reliably produce a report shaped like agreement. This is what surfaces the body-decay corrections above; it is also how the orchestrator learns its own briefs were wrong, which happens (process-log 2026-08-10: two workers corrected the orchestrator's brief and were right both times). Escalations are evidence, not findings — verify one before acting on it.

**No PR is opened by the worker.** The orchestrator merges into the batch branch; the user reviews the batch branch as a whole.

## Key Principles

- **One question at a time** — stacking questions gets partial answers
- **Approval gates are real** — do not proceed past a section without explicit user sign-off
- **Blast radius ≠ priority** — a high-blast issue may score high but still wait for lower-priority isolates to merge first. Three variants: **score determines what gets done, ordering constraints determine when** — a zero-conflict issue is the most *schedulable* thing in a backlog, so it fills whichever slot would otherwise idle rather than earning Batch A by score (2026-08-11 observo); a **trivial issue can be a hard gate** when its guard must exist before a later issue widens the surface it guards (2026-08-07); and an issue whose deliverable is a **measurement of the final state** sequences last on epistemics, not contention — run early, it measures a state that won't exist at merge time (2026-08-11 usa-wa)
- **Correctness fixes lead refactors** — if a bug fix and a structural refactor both touch the same file, fix the bug in the first commit of the refactor branch, not in a separate earlier batch
- **Pick a shape for same-file pairs** — bundle (Shape A) or split (Shape B); the heuristic is in Step 7's batch design rules.
- **Worktrees always — and verify the host project can provision them** — `isolation: "worktree"` for every worker. The batch branch is the merge *target*, not the base: brief each worker to merge it itself and reconcile each explicitly rather than trusting auto-merge (Rule 3). The parameter does NOT guarantee filesystem isolation if the host project's worktree-create script falls through; cap per-batch agents at the provisioning ceiling (Rule 5) and detect fall-through at runtime (Rule 6).
- **Deferred is a decision** — explicitly name what is out of scope and why; don't silently omit
- **Batch feature branches for multi-agent batches** — one integration point to test and review, surfacing intra-batch conflicts at the batch branch rather than at main; a single-agent batch skips it and uses the agent's own branch
- **No worker PRs** — workers signal to the orchestrator, which merges into the batch branch and returns any conflict to the responsible worker; the user reviews the batch branch
- **Self-review before signal** — worker agents resolve all findings before signaling; no known issues at signal time
- **Orchestrator launches all unblocked batches** — not just the next one in sequence; if two independent batches become unblocked simultaneously, launch both
- **Regular merge commit to main** — preserves per-agent commit history; ask user preference at design time

## Branch Hygiene Rules

These rules prevent the class of failures that produced the Batch B→C conflict:

### Rule 1 — Sync local main before conflict analysis AND before every agent launch

`git push origin HEAD:main` from a feature branch advances `origin/main` but does **not** move local `main`. The orchestrator then analyses, plans, and merges against a tree that is behind. (Agents branch from `origin/main`, not local `main` — Rule 3.)

The same staleness corrupts the *plan*, one step earlier and less visibly: a stale checkout produces a conflict map of a repo layout that no longer exists, and every downstream instruction inherits the fiction (process-log 2026-08-10: three workers were assigned an ownership boundary in a file that two merged PRs had already split apart; it surfaced only because a worker said so in its report). **So sync at Step 1–2 as well** — by launch time the plan is written and the tracking issue is filed.

**Before analysing the backlog, and before launching any batch:**
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

The `isolation: "worktree"` parameter runs the agent in a temporary worktree. Its post-completion behavior is **inconsistent** — parallel volleys have produced all four of: an un-merged `worktree-agent-<id>` branch (most common), a commit straight onto the orchestrator's current branch, a custom-named branch the agent picked, and work left **uncommitted** despite a "completed" signal (process-log 2026-05-09, 2026-05-11).

**The base, by contrast, does not vary: worktrees are cut from `origin/main`, independent of the orchestrator's checked-out branch.** Sub-wave 1 hides this — `batch/<X>` still equals `main` — and by sub-wave 2 the batch branch carries everything merged since, so the gap widens with batch depth. Rule 1 does not cover it: local `main` can be current and the agent's tree still wrong. Two obligations follow, both the orchestrator's:
- **Brief every worker to `git merge batch/<X>`** — worker protocol step 3, immediately after the isolation pre-flight. Expect a fast-forward.
- **Give every worker prompt the expected test count on `batch/<X>`**, plus "stop if it does not match" — the only detector that has caught this. In #144 Batch A two of four agents found it because a briefed `1740 passed` read `1644` in their tree; one had been told to trim a file to a target measured on a version it lacked. The other two would have edited a tree missing eight merged issues. Give a number, not an exhortation to "verify your assumptions" — that gets confirmation.

**Operating rule: the orchestrator owns the merge** — reconcile, then merge explicitly, on every completion signal. The runtime checklist is **Orchestrator step 5**, the single authoritative copy; follow it there rather than duplicating it here. Canonical pattern:

```bash
git checkout main
git pull --ff-only               # sync (Rule 1); also advances origin/main
git checkout -b batch/f          # merge TARGET; workers still branch from origin/main
                                 # deploys from this checkout? `git branch batch/f main`
                                 # instead — never move it (Orchestrator step 2)
# spawn workers, each briefed to `git merge batch/f` first + the batch-branch baseline
# reconcile + merge each one explicitly as it completes (see Orchestrator step 5)
```

`main` moves only when the human merges the batch branch, via Rule 2's push sequence.

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

When Rule 6 fires — or a worker's pre-flight isolation check (Worker step 2) does — halt the batch's completion signals and follow the salvage procedure in [`references/recovery.md`](references/recovery.md). The procedure preserves the worker's intended commits, replays uncommitted modifications onto the correct feature branch, and re-runs verification (the agent's pre-salvage test pass is invalid — it ran against the main checkout's working tree, not an isolated copy).

Do not relaunch a salvaged agent in the same wave that hit the ceiling. Resolve the ceiling first (destroy a completed worktree, widen the host-project pool, or chunk the remaining work into smaller sub-waves per Step 7).

---

## Process Logs

Session-specific institutional memory — interview answers, batch shapes, non-obvious decisions, and tactical lessons — lives in [`references/process-log.md`](references/process-log.md). Several rules and patterns in this document originated there:

- Rules 5/6 (per-batch ceiling, runtime fall-through detection) — 2026-05-22 port-pool incident; Rule 5 slot-reclaim semantics + cheap ceiling re-verification — 2026-06-09
- Rule 3 revision (auto-merge is unreliable → verify-and-merge per worker; reconciliation checklist) — 2026-05-09, 2026-05-11; **the main checkout's branch never moves where the repo deploys from it** (Orchestrator step 2) — 2026-08-13 usa-wa
- Step 1–2 closed-in-fact grep per issue (and its false negative: **zero hits is ambiguous, not exculpatory**), closed-prerequisite check, rescope-to-residual disposition — with the defer branch when the residual's blocker sits outside a user-named subset — and the generated-artifact read — 2026-05-09, 2026-05-11, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13 observo, 2026-08-13 power-map
- Step 5 footprint grep, bidirectional (bodies understate *and* — in partial-fix backlogs — overstate) — 2026-05-09, 2026-06-28
- Step 5/6 backlog-provenance geometry (CR-surfaced → disjoint; **AR-surfaced** → its inverse, because structure is shared; feature-followup → one-partial clusters / across-the-stack disperses; adoption-feedback → tightest clustering, one agent per owning file) — 2026-05-09, 2026-05-11, 2026-06-28, 2026-08-07, 2026-08-09, 2026-08-11
- Step 5 test-surface grep (a shared test file's *modify* half is invisible to source overlap) and line-window ownership — generalized to any large shared file, and down to function/region granularity when nothing is file-disjoint — plus the no-file-overlap dependency edge — 2026-07-08, 2026-08-11, 2026-08-12, 2026-08-13 cli
- Step 7 Shape A/B distinction (bundle vs. split same-file pairs) — 2026-05-25, 2026-06-09; "differ in kind" refinement — 2026-05-11
- Steps 5/6 "low-discovery backlog mode" — 2026-06-08 (spec-derived), 2026-06-09 (followup-derived)
- Step 7 "foundation shared files are read-only" — 2026-06-08; chain-appending rule (one migration/ADR/sequence-generating agent per batch) — 2026-08-07; byte-for-byte-sync-test bundle signal + design-gate-with-no-file-overlap — 2026-08-10
- Step 8 docs-only-worktree authoring option — 2026-06-08; Step 9 `--body-file` over heredoc — confirmed across 2026-05-24, 2026-05-25, 2026-06-08, 2026-06-09
- Step 4 rubric variable-weight escape hatch — confirmed for **Foundation**-leading (×3), not just Correctness — 2026-05-24 (Correctness ×3), 2026-06-29 (Foundation ×3)
- Step 4 / Key Principles "blast ≠ priority" refinement: a single issue whose blast intersects **multiple** otherwise-parallel agents → isolate in its own gated batch (grep call sites to verify) — 2026-06-29; further variants (zero-conflict issue is a slot-filler; a trivial issue can be a hard gate; a measurement issue sequences last on epistemics) — 2026-08-07, 2026-08-11
- Q5 shared-backing-service sub-question + the provision / serialize / cap resolution ladder + read-the-guard clause — 2026-06-16, 2026-07-19, 2026-08-07, 2026-08-09, 2026-08-11 usa-wa, 2026-08-11 observo, 2026-08-13 usa-wa, 2026-08-13 observo, 2026-08-13 power-map (nine recurrences across four projects; the ceiling was in a shared service, not the worktree tooling, in all nine) — and accept "no ceiling" as an answer, 2026-08-12's first negative result
- Worker step 5 "issue body is a proposal, not a specification" + the report-back corrections slot + Step 8 body-decay note — 2026-08-09 (13/13 bodies materially wrong), 2026-08-10
- Rule 1 extended to fire before conflict analysis, not only before launch — 2026-08-10
- Step 5 shared-fixture-*escape* grep (hard conflict zone, vs. 2026-07-08's soft one) — 2026-08-11
- Step 5 stated-*relationships*-are-hypotheses, grep-sizes-surface-not-behaviour, sweep enumeration, and an issue body's own hedge ("worth confirming") as a grep target — 2026-08-09, 2026-08-10, 2026-08-11, 2026-08-12
- Step 4 decide-then-rescore at the approval gate + write scope changes back to GitHub — 2026-08-09, 2026-08-11

Closing out a session (Step 10) writes an entry file and an index row. Promote any stable cross-session pattern into the body of this skill; leave one-off tactical details in the log.

**Self-budget:** held to a **23,110-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — a named exception to the repo's
6,000-token standard, set at current size so this file cannot grow. Raised once,
from 22,900; that test's comment carries the argument.
