# Process Log — orchestrating-issue-backlog

Session-specific institutional memory for the [`orchestrating-issue-backlog`](../SKILL.md) skill. Each entry captures: project, interview answers, batch shape, non-obvious decisions, and tactical lessons. New sessions are appended chronologically; stable patterns get promoted into the SKILL.md body and (optionally) summarized here.

## Index

| Date | Project | Headline |
|---|---|---|
| 2026-03-23 | gregoryfoster/skills (origin session) | Establishing batch branch pattern; Rules 1–4 origins (local-main staleness; `git push HEAD:main` antipattern; `isolation: "worktree"` auto-merge semantics; rebase commit-message clobber) |
| 2026-05-09 | cannabis.observer/power-map | CR-surfaced backlog → 6-agent fully-parallel batch (disjoint by design); strict-subset bundling; grep contested symbols before scoring; `isolation:"worktree"` auto-merge is unreliable — verify per worker |
| 2026-05-11 | cannabis.observer/power-map | Feature-followup backlog clusters on the producing file (single contested template); closed-in-fact grep for every issue; 4 distinct worktree branch-base/completion behaviors; `.claude/worktrees` gitignore + `remove -f -f` |
| 2026-05-22 | cannabis.observer-wordpress | Port-pool incident → Rules 5/6 (per-batch ceiling, runtime fall-through detection) |
| 2026-05-24 | gregoryfoster/skills | Single-owner overlap resolution; rubric weight variance (`Correctness × 3`); `gh issue create --body-file` workaround |
| 2026-05-25 | gregoryfoster/skills | Bundle three same-file issues into one agent (Shape A); bootstrap-skill Q2 framing |
| 2026-06-08 | cannabis.observer-wordpress | Spec-derived backlog → low-discovery / high-formalization mode (1st recurrence of compressed Steps 5/6); workspace-isolation docs-only-worktree pattern; foundation-shared-file read-only rule |
| 2026-06-09 | cannabis.observer-wordpress | Prerequisite-in-parallel pattern (Shape B); followup-backlog mode (2nd recurrence → compressed Steps 5/6); cheap ceiling re-verification; slot-reclaim semantics |
| 2026-06-16 | CannObserv/usa-wa | **Validity-re-analysis gate** (re-validate every issue against a just-merged change *before* scoring → supersede/rescope/defer/close); followup-backlog mode (3rd recurrence); ceiling gated by **shared Postgres test DB**, not git/ports; pervasive shared-file (config/descriptor) co-edits → sequential single-agent tail |
| 2026-06-28 | cannabis.observer-wordpress | **Cross-layer followup backlog → CR-like disjointness** (4th followup recurrence, but the followups span one-bug-per-layer instead of clustering on the producing file → high parallelism, single doc-file overlap); grep narrowed two issues' footprints below their issue-body claims (#407 → 1 transformer, #399 → 2 commands) |
| 2026-06-29 | address-validator | **Foundation ×3** (first Foundation-leading weight — confirms the variable-weight escape hatch covers it, not just Correctness); aggressive same-file bundling (9 issues → 5 agents); single issue whose blast intersects **multiple** parallel agents → isolate in its own gated batch (blast ≠ priority refinement, verify call sites by grep); sub-score commit order inverts for define-then-use |
| 2026-07-08 | CannObserv/power-map | **Shared test infrastructure is a soft conflict zone** — a test-suite-optimization issue (#283) with zero *source*-file overlap still sequenced **last & solo** because it mutates `conftest.py`/session fixtures every other worker's TDD tests depend on; **stability-critical deploy context split a fully-disjoint backlog into 3 gated batches** even though all 6 could run at once (correctness-first won over max-parallelism); closed-in-fact catch via `git log -S` (#20 → resolved by #210) closed **before** the interview; standard equal-weight rubric (no flex) |
| 2026-07-19 | CannObserv/archiver | **Version-freshness hard edge**: a metadata fix (#85 pyproject bump) must precede the issue that *snapshots* it (#92 commits `archiver-openapi.json`, which embeds `info.version`) — a dependency invisible to file-overlap analysis; **route new CI checks to an uncontested job** (lockstep check → lint job, away from the two jobs Batch B edits); shared-test-DB ceiling **2nd recurrence** (after 2026-06-16 usa-wa) — resolved by serializing full-suite runs, orchestrator's batch-branch run authoritative; validator-merges-last ordering (#85 last in batch so its lockstep check validates the batch's final state) |
| 2026-07-23 | CannObserv/cli | **Followup-derived across-the-stack backlog** (5th followup recurrence — CR-like disjointness, single contested file); Shape B for a same-file pair that differs in kind (contained correctness fix #849 in parallel batch, wider design-discovery guard refactor #851 gated behind it); **guard-placement constraint drove the read-only decision** (`LegislativeSessionParamType` off-limits — other consumers legitimately pass child sessions); lightweight-worktree project → no binding ceiling |
| 2026-08-07 | CannObserv/usa-wa | **AR-derived backlog is maximally contested** — the inverse of CR-derived (new provenance flavor); **decompose the top-scored issue** rather than defer it, to dissolve a 3-way conflict (#179 core → Batch A, adoption sweep → Batch F); shared-test-DB ceiling **3rd recurrence**, resolved by **provisioning N slots** (preserves worker self-verification, unlike capping or serializing); **migration-chain rule** (one Alembic-revision-generating agent per batch); Q0 repurposed for *prerequisite* pairs rather than duplicates |
| 2026-08-09 | CannObserv/observo | **AR-derived backlog, 2nd occurrence** (6th low-discovery recurrence — issues carved from an AR completed in the *same session*, so contested files were known before Step 5); **footprint grep reversed the issue bodies' own stated dependency** (#423→#425 filed an hour earlier with an explicit "do these in order" note; grep found 5/6 shared production files → bundle, not sequence); duplicate caught by **files/symbols, not title** (#331 ≡ #425); shared-test-DB ceiling **4th recurrence** — but **avoidable**: the guard validates the *base* DB name before the xdist suffix, so per-agent DBs pass it; **every one of 13 issue bodies carried a material error at implementation time** (directions reliable, specifics not) |
| 2026-08-10 | cannabis.observer-wordpress | **Generated artifact under a byte-for-byte sync test is a hard bundle signal** (openapi.json + `CoRestOpenApiSyncTest` → Shape A, conflict made impossible not just managed); **a CLOSED prerequisite is not a MET prerequisite** (#656 cited "finding 5 of #655" — #655 closed, but finding 5 was a different finding); **design-gate vs file-gate** (#669 gated behind #667 with zero file overlap, on the issue's own "decide the seam once" — paid off: the seam shipped with 4 consumers, 2 invisible until #667 merged); **sync local main before ANALYSIS**, not just before launch — a 7-commit-stale checkout produced a conflict map of a layout that no longer existed; **a grep sizes a footprint, only execution measures a leak** |
| 2026-08-11 | gregoryfoster/skills | **Adoption-feedback backlog → owning-file agent unit** (new provenance shape: 15 defects filed by cohort repos against *one* skill's script family → 7 agents, one per owning script, not one per issue); **a shared test file has two conflict halves and "write a new file" solves only one** — grep the test file for the literal strings each fix rewrites, then partition the modify-half by line window; **semantic dependency inside one file** (#119's flood makes #111's judgment undecidable → Shape B on different regions of the same file); measure a lint-gate issue's debt *distribution* before choosing first-vs-last; verify the repo's real gate surface before honouring an issue's "add it to CI" |
| 2026-08-11 | CannObserv/usa-wa | **A shared-fixture *escape* is a hard conflict zone, not a soft one** — a helper that opens its own engine and `DROP SCHEMA … CASCADE`s outside the savepointed fixture forces its issue solo (destruction, not contention — sharpens the shared-test-DB ceiling, **5th recurrence**); **closed-in-fact grep caught a partially-shipped issue** → rescope-to-residual, a 4th disposition beside keep/close/defer; 6th followup recurrence, across-the-stack; **a "split on headings" target with no headings** — measure structure before scoping a curation issue |
| 2026-08-13 | gregoryfoster/skills | **#144 execution addendum** — the report-back slot caught a material error in 9 of 10 issue bodies (incl. one that *implemented and measured* the suggested fix before rejecting it); **executable content shipped as documentation must be gated by executing it** (a comment-block recipe leaked the whole environment and died on a `.env` comment, under a 12-test suite that only matched its text); a merged fix can be structurally inoperative in a way its own tests confirm (#137); **a ratchet is the wrong instrument for an append-only artifact** — one set on the process log went red within the hour; harness worktrees are cut from `origin/main` (#150) and `worktree-destroy.sh` cannot address their paths (#149) |
| 2026-08-12 | gregoryfoster/skills | **The ceiling was genuinely absent** — 7th Q5 session, first to find neither a worktree-provisioning nor a shared-backing-service limit (negative result worth recording against six positives); **line-window ownership generalized from a test file to a policy file** (`AGENTS.md`, three concurrent writers, separated windows + "no restructuring"); **an issue body's own hedge is a grep target — and so is the orchestrator's own grep** (a loose `\]\(…\)` sweep "disproved" #143's discriminator and was itself refuted by the implementing agent: the match was a bare fragment in an inline code span, not a link — design doc, score and issue comment all retracted); **three instances of the same shape in one session** — a link sweep, two test assertions and a code-review finding, all *absence* claims derived from a model of the artifact rather than from the artifact; **descope to decouple** (deleting a shared sub-problem from one issue removed an ordering constraint entirely); blast radius discovered in a **test assertion about prose**, not in any issue body; **a blocked residual defers rather than rescopes** when its blocker is outside a user-named subset |
| 2026-08-11 | CannObserv/observo | **Mid-orchestration issue surgery** (product decision at the scoring gate → trim #421 to one option, descope the other to a new blocked issue #443, comment the decision onto #436) — decisions changed two scores and one blast radius *before* batch design; **unbounded-sweep issue sized by grep** (#438 "worth a sweep" → 17 files / ~64 sites) and cross-checked against co-batch agents' test footprints to license full-ceiling parallelism; **highest-scored issue placed in the second batch** because batch-A slots are claimed by ordering constraints, not by score; shared-test-DB ceiling **6th recurrence** (carried forward and re-verified with one `psql -l`) |
| 2026-08-13 | CannObserv/cannobserv | **Upstream-blocked backlog: check the sibling repo's blocker states before anything else** — all three blockers closed within 5 days, converting a "blocked" backlog to actionable, with a stale contract pin as the shared consequence; **a shared first step that is not an issue** (the re-pin) modeled as commit 1 of a Shape-A bundle, then read-only for the gated batch; **same-function overlap is the sharpest Shape-A signal yet** (two issues edit `test_write_bodies.py:22-23`); **a clarifying "Other" answer at a decision gate flipped the decision and exposed a latent read-time data drop** (wp/v2 observation adapter silently drops ACF `co_roles` — the issue body's "no such field on either backend" was true of the model, misleading about the data); hybrid preference degenerated to fully-sequential (every pairing shared a file); policy-deferral of a user-named issue (#278, async-parity) confirmed at Q3 |

---

## Session 2026-03-23

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

## Session 2026-05-09 (cannabis.observer/power-map, seven-issue CR-surfaced backlog)

**Backlog:** seven CR-surfaced issues from #131 / #135 work (#122, #124, #125, #132, #133, #134, #136). Output: tracking issue #141, design doc `docs/plans/2026-05-09-stability-and-cleanup-backlog.md`.

**Outcome:** single 6-agent parallel batch — zero contested files between agents. This is the inverse shape of the 2026-03-23 backlog (which had a sequential critical path through `tasks.py`).

**New patterns worth keeping:**

1. **CR-surfaced backlogs tend to be disjoint.** When all the issues in a backlog were discovered during code review of recent feature work (#131 and #135 here), each one tends to live in a different review-pass area — the reviewer found one bug per feature surface. Result: high parallelism is the default, not the exception. Don't assume sequential gates are needed just because past backlogs had them.

2. **"Strict subset" is a stronger bundling signal than "same file."** #124 was a literal subset of #136 section (A) — the same fix closes both. The skill already covers "Bundle when cohesive" for issues that touch the same file. Add: when one issue is a strict subset of another, always bundle into the larger issue's first commit. Two agents on the same fix would create branch contention with zero benefit.

3. **Verify the conflict-zone hypothesis before presenting the score table.** During scoring I ran `grep -rn "is_canonical"` and `grep -rn "?v="` to ground the file-footprint estimates. The `is_canonical` grep revealed that #136 section (A) was 5× larger than #124's body suggested (touched `src/core/ingestion/pipeline.py` + `csv_*.py`, not just the dedup script). If I'd skipped that step, the bundling decision and A1's self-review checks would have been wrong. **Recommended addition to Step 5:** before presenting conflict zones, grep for the contested symbols/keywords to confirm the file footprint matches each issue's stated scope.

4. **Top-level-template vs partial-template is a real disjointness boundary.** #133 (cache-bust) and #125 (DOM-ID audit) both looked like "HIGH-blast admin template work" and looked headed for a sequential gate. They're actually disjoint: cache-bust lives in *top-level* templates that load scripts (`base.html`, `detail.html`); DOM-ID audit lives in *partial* form-row templates (no script tags). Worth checking this distinction explicitly before gating template-heavy issues against each other.

**Execution observations (added after the batch ran):**

5. **`isolation: "worktree"` agent merge behavior is INCONSISTENT — earlier sessions over-generalized.** Of 6 agents launched in one parallel volley:
   - 5 of 6 (A1, A2, A3, A5, A6) stayed on per-agent `worktree-agent-<id>` branches branched from the orchestrator's HEAD at spawn time. Their work did NOT auto-merge to the orchestrator's current branch — the orchestrator had to merge each branch manually with `git merge --no-ff worktree-agent-<id>`.
   - 1 of 6 (A4) committed directly to the orchestrator's current local branch (`batch/2026-05-09-a`), parented at the latest commit at the moment A4 finished — i.e. its base advanced to include earlier siblings' merges. The agent itself reported: "Branch: batch/2026-05-09-a (orchestrator's batch branch — not the per-slot ... merging strategy chose to commit directly into batch branch)".
   - **The 2026-03-23 skill log claimed agents "auto-merge to caller's current branch." That's true for *some* agents in *some* circumstances — possibly the last to complete, or those whose worktree base shifted to overlap the orchestrator's branch. It is NOT reliable.**
   - **Operating rule going forward:** after every worker completion, run `git branch --list "worktree-*"` to discover whether the agent left a branch behind, and merge it if present. Don't assume auto-merge; verify.

6. **Cross-slot scope leaks happen when a template change invalidates an assertion in a file outside the prompt's allowlist.** A2 (#133) had to patch one assertion in `tests/api/admin/test_people_name_templates.py`; A4 (#125) had to patch three assertions in `tests/api/admin/test_orgs_templates.py`. Neither file was in any other slot's named list. Both agents flagged the leak in their report and explained why the change was forced. Net effect: zero merge conflicts, but the orchestrator's "files you may touch" allowlist is *incomplete* by design — anywhere a literal template URL or DOM ID is asserted in a test, that test joins the producing slot's de-facto scope.
   - **Recommended addition to worker prompts:** include a "your changes may also force mechanical updates to assertions referencing the same literals — fix those too, document the file in your report" clause. Cuts ambiguity at completion time.

7. **Test failures pre-existing on `main` vs. failures introduced by the batch — discriminate before reporting.** A1 reported 2 remaining `test_orgs_addresses.py` failures alongside its 15 fixed; the orchestrator confirmed they fail identically on `main` (`KeyError: 'hx-trigger'` in both). They were not in #136's scope and stay deferred. Pattern: when worker self-review surfaces extra failures, the orchestrator must verify they're pre-existing on `main` before greenlighting the batch — the test-suite floor isn't perfect, and what looks like a regression introduced by the batch may already exist upstream.

8. **Final test-suite snapshot for this batch:** `1008 passed, 2 skipped, 2 pre-existing failed` (integration); `109/109 passed` (npm); ESLint + Prettier clean. All 15 failures listed in #136 closed. #122 added 5 new parametrized trigger tests. #134 STYLE.md §33 added.

## Session 2026-05-11 (cannabis.observer/power-map, five name-editor follow-ups)

**Backlog:** five name-editor follow-ups from the #123 / #127 work cluster (#126, #128, #129, #130, #139). Output: tracking issue #143, design doc `docs/plans/2026-05-11-name-editor-followups-backlog.md`. Four issues batched; one (#129) closed-in-fact during scoring.

**Outcome:** One 2-agent parallel batch (#128, #130) then two single-agent sequential batches (#126, #139). Critical path runs through a single contested template, `_name_parts_editor.html`. Different shape from the previous two sessions:

- 2026-03-23: critical path through `tasks.py` across **four** batches (B→C→D→E, all single-agent on the same file).
- 2026-05-09: zero contested files across **six** parallel agents (CR-surfaced bugs are naturally disjoint).
- 2026-05-11: critical path through `_name_parts_editor.html` across **three** batches, plus one isolated parallel slot.

**Pattern: "feature-followup" backlogs cluster on the producing files.** Issues filed against a recently-shipped feature tend to congregate on the same 1–2 files the feature lives in — the implementer left TODOs, the reviewer flagged smells in the same area, the QA pass surfaced UX gaps in the same partial. Expect a single-file critical path with a small number of parallel-safe outliers. This is the inverse of 2026-05-09's CR-surfaced disjointness and distinct from 2026-03-23's deep architectural chain.

**New patterns worth keeping:**

1. **Grep the file's own header comments during the closed-in-fact check.** Issue #129 was verified resolved by reading `src/templates/admin/people/partials/_name_metadata_fields.html` (in `cannabis.observer/power-map`) — the file's docstring explicitly credits #131 for the fix. Adding `grep -rn "Issue #" src/templates/ src/api/admin/` to the closed-in-fact pass surfaces these credits without needing to read entire files. Module/template docstrings are an underused signal — they're how careful contributors annotate which footgun an edit retired. The 2026-05-09 log already established "grep for contested symbols before presenting scores"; expand the recommendation: also grep for `Issue #` in the contested files themselves.

2. **The "closed-in-fact" check should target every issue, not just the high-blast ones.** #129 had Med blast and the highest score (10/15). If I'd skipped grep verification because "high blast = surely still open", I'd have allocated a batch slot to dead work. **Rule:** for every scored issue, grep at least one identifying symbol from its body. Don't trust the issue body's claim about file state.

3. **Mechanical 1-line refactors don't bundle with adjacent UX features even when they touch the same file.** #128 (one-character substitution: `"5"` → `{{ ARRAY_CAP }}`) and #126 (UX feature: arrow buttons + new JS + new vitest) both touch `_name_parts_editor.html`. The skill's "bundle when cohesive" rule could have pulled them into one agent, but separating them gives the user two clean review surfaces (mechanical refactor vs. UX affordance). The bundling rule's real signal is "naturally sequenced (define → use)", not "happens to touch the same file". When in doubt, separate — gates between single-agent batches are cheap.

4. **`_name_parts_editor.html` vs `_name_metadata_fields.html` disjointness boundary.** Both partials cohabit the same name-editor UX, but they don't overlap in this backlog: parts-editor work (#126, #128, #139) and metadata-fields work (#129 if it had been open) are independent. Worth checking this partial-vs-partial distinction explicitly when the backlog spans an editor with split rendering, similar to the "top-level-template vs partial-template" distinction in the 2026-05-09 log.

5. **Pre-production deployment context doesn't change the rubric, but does change the cost calculus on sequencing.** With pre-production runway, three sequential single-agent batches (B, C, then a future fourth if needed) cost almost nothing — the orchestrator round-trips are the only cost, and the user can review three small surfaces. In active production, the same backlog would more aggressively bundle to minimize merge-to-main events. Document the deployment context in the design doc's "Approved approach" section so future readers understand why sequencing was relaxed (or tightened).

**Execution-phase observations (added after the batches ran):**

6. **`isolation: "worktree"` agent behavior is even more variable than the 2026-05-09 log claimed.** Across 4 agents this session:
   - A1 (#128) — branched from `08c756e` (the prior `origin/main` HEAD, predating my orchestration commits); committed to a `worktree-agent-X` branch; orchestrator manually merged.
   - A2 (#130) — branched from same `08c756e`; **left work uncommitted in the worktree's working tree even though the harness reported the task "completed"**; orchestrator manually committed on the agent's branch before merging.
   - B1 (#126) — branched from the *current* local main HEAD (post-orchestration commits); committed to a **custom-named feature branch** (`126-reorder-buttons-name-parts`, not `worktree-agent-X`); orchestrator's working tree shifted onto the agent's branch on completion.
   - C1 (#139) — branched from current local main; committed to the normal `worktree-agent-X` pattern.

   Three distinct branch-base behaviors AND three distinct completion behaviors in one session. The 2026-05-09 model ("agents auto-merge to caller's current branch") is too narrow. The actual behavior space:
   - **Branch base:** `origin/main` HEAD at worktree-creation time, OR the orchestrator's current local HEAD. Possibly depends on whether `origin/main` was reachable when the worktree was set up; possibly depends on harness version.
   - **Branch name:** usually `worktree-agent-X`, occasionally a custom name the agent picks.
   - **Completion:** usually a committed branch ready to merge; occasionally uncommitted work in the worktree directory.
   - **Orchestrator's branch after agent completes:** usually unchanged, occasionally shifted to the agent's branch.

   **Operating rule for every worker completion:**
   1. Check `git branch --show-current` — orchestrator may have shifted off main.
   2. Check `git branch --list "worktree-*"` AND look for custom-named feature branches via `git log --oneline main..HEAD`.
   3. Check the worktree directory at `.claude/worktrees/agent-<id>/` for uncommitted changes — if present, the agent didn't finish committing.
   4. Reconcile: commit any uncommitted work on the agent's branch (with the prescribed message format), then merge into the batch branch (multi-agent) or directly into main (single-agent).

7. **Worktree harness locks are real but force-removable.** Worktree directories under `.claude/worktrees/` are locked by the agent harness daemon (the lock reason names the PID). Standard `git worktree remove` fails with "cannot remove a locked working tree" — but `git worktree remove -f -f` (double-force) succeeds cleanly and doesn't appear to disturb the harness. Cleanup pattern: `git worktree remove -f -f .claude/worktrees/agent-X` then `git worktree prune` then `git branch -D worktree-agent-X` (or the custom name).

8. **The `.claude/worktrees/` path needed an explicit `.gitignore` entry.** Agent harness creates per-agent directories there; default `.gitignore` covered `.worktrees/` (top-level, for user-created worktrees) but not the harness path. Without the entry, the harness's leftover worktree directories show up as untracked and trip `shipping-work-claude`'s check-status gate. One-line fix; worth doing once per project that uses the harness.

9. **Pre-existing test failures stay pre-existing across batches.** The 2 `test_orgs_addresses.py` flash-trigger failures (`KeyError: 'hx-trigger'`) persisted unchanged through all three batches (A → B → C), each time verified by running the same tests on `main`. The 2026-05-09 log already captured "discriminate pre-existing from introduced before reporting"; this session validates that the same 2 failures are stable across many merges — they're real test debt, not flaky. Track as a separate issue when the count crosses a threshold.

10. **CR-surfaced follow-up rate: ≈1 issue per batch.** Each batch's CR rounds surfaced new GH issues that captured real concerns outside the current scope: #144 (asyncpg pool refactor, Batch A CR), #145 (focus preservation, Batch B CR), #146 (aria-label disambiguation, Batch B CR). Pattern: review surfaces something real but out-of-scope; orchestrator files a follow-up issue; comes back later. The cost is low (one `gh issue create` per surface) and the value is preserving design fidelity to what was actually shipped. Plan for it — don't be surprised by the rate.

11. **Pre-existing infrastructure should be discoverable by agents before they reinvent it.** B1 invented `window.__cardstackReorderSync` as an IIFE side-channel (acceptable, but CR flagged it for documentation). C1 hand-duplicated `_NON_DECOMPOSABLE_TYPES` as a local frozenset rather than importing from the canonical normalizer module (CR caught the drift). Worker-agent prompts should explicitly name the established infrastructure to reuse:
    - For Jinja constants from Python: name the `register_X_global` / `inject_X_into_admin_templates` pattern from `src/api/admin/assets.py:60-90`.
    - For canonical sets/enums shared between Python + templates: name `NON_DECOMPOSABLE_TYPES` and `ARRAY_CAP` as exemplars.
    - For HTMX swap design across paired partials: name the `<details id="parts-editor-{{ n.id }}">` + `hx-swap="outerHTML"` shape that #139 used.

12. **The "single contested template" backlog shape held up across 3 batches.** Predicted in the plan (`_name_parts_editor.html` carried the critical path), held up in execution: every batch contributed to that file's evolution AND each batch's CR work fed the next. Batch A's `register_array_cap_global` pattern became the template for Batch C's `register_non_decomposable_types_global`. Batch B's `<details id="parts-editor-{{ n.id }}">` wrapper became the swap target Batch C used. This shape is reproducible — feature-followup backlogs against a recently-shipped subsystem cluster on its producing files AND build on each other's plumbing. The orchestrator can design batches that maximize this lineage (each batch lays groundwork for the next) without explicitly tracking it as a dependency.

---

## Session 2026-05-22 (port-pool incident)

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

## Session 2026-05-24 (skills repo, six-issue Batch F)

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

- **Single-owner assignment to resolve a one-line shared-file overlap.** [skills/using-git-worktrees/SKILL.md](../../using-git-worktrees/SKILL.md) was the only contested file (between #28 documenting an internal fix and #31 documenting a new script). Resolution: assign SKILL.md edits exclusively to one agent (F4, the larger contributor) rather than serializing two small edits with a rebase. F1 (#28) ceded SKILL.md and relies on commit message + inline script comments to document the internal change. This is cheaper than any merge-order ceremony for ≤2-line overlaps and worth reaching for first.
- **Detection-only as the merge-safe minimum for a paired feature.** #31's issue listed `worktree-create.sh` preamble integration and `pre-ship.sh` wiring as optional. Both were scoped out to keep F4's diff narrow and avoid pulling additional files (`worktree-create.sh`) into the batch. Pattern: when an issue offers a "main thing + optional integration points," ship the main thing in this batch and file follow-ups for the wiring.
- **Variable rubric weight.** First session where Correctness flexed to ×3. Confirmed the existing "unless the user requests different weights" escape hatch is enough — no rubric change needed at the skill level. Worth noting that the weighting choice flipped the ordering: under Correctness ×2 / Foundation ×2, #28 and the convention work (#26) would have been closer; under Correctness ×3, #28 leads clearly because of real downstream forensics.

**Tactical lessons:**

- **`gh issue create` with `--body "$(cat <<'EOF' ... EOF)"` chokes on apostrophes inside the body** (e.g. `skill's`), even though the heredoc is single-quoted. The error surfaces as `unexpected EOF while looking for matching '`'. Switch to `gh issue create --body-file <path>` — sidesteps all shell quoting issues and lets the body include any character. The **same workaround applies to `git commit -m "$(cat <<'EOF' ... EOF)"`** — use `git commit -F <path>` for any commit message containing apostrophes, dollar signs, or backticks. Confirmed again in Session 2026-05-25.
- **Step 8 commit format clarification.** First documented the chicken-and-egg between Step 8's `#<n>` commit prefix and Step 9's issue creation. Promoted to Step 8 instructions in #48.

---

## Session 2026-05-25 (skills repo, four-issue Batch H)

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

---

## Session 2026-06-08 (cannabis.observer-wordpress, four-issue spec-derived backlog)

**Project:** `CannObserv/cannabis.observer-wordpress` (Bedrock + Sage 11 + Lima VM monorepo)

**Backlog:** issues #320, #321, #322, #323 — all four filed in the same session, derived from the just-merged `#311` spec ([docs/specs/2026-06-08-311-wp-integration-test-harness-design.md](https://github.com/CannObserv/cannabis.observer-wordpress/blob/main/docs/specs/2026-06-08-311-wp-integration-test-harness-design.md)). Spec recommended wp-phpunit as a new integration tier alongside the existing bootstrap-stub unit tier; the four issues split that work into a foundation (#320) and three downstream test suites (#321 hooks / #322 ETL / #323 REST).

**Interview answers:**
- Q1 Quality: All three dimensions equal → standard formula `(Foundation × 2) + (Correctness × 2) + Scope`, max 15.
- Q2 Deploy: Pre-production (runway). cannabis.observer-wordpress is mid-relaunch.
- Q3 Defer: none — ship all 4.
- Q4 Parallelism: Maximum (3 parallel in Batch B).
- Q5 Ceiling: 9-slot port pool (8001–8009) unchanged from 2026-05-22 — verified by reading the worktree-create output of an in-session worktree (got port 8004). The skill's prior-session ceiling data is reusable for repeat-projects when re-verified cheaply.

**Shape:** two batches. Batch A is #320 alone (foundation, large blast — wires `composer.json`, `phpunit.xml`, `.github/workflows/validate-pr.yml`, `dev.sh`, `AGENTS.md`, `docs/TESTING.md`, new `tests/integration/bootstrap.php`). Batch B is #321/#322/#323 in parallel, all file-disjoint under `tests/integration/`. Tracking issue: `#324`.

**Spec-derived backlog: low-discovery, high-formalization mode.**

The conflict-zone analysis and dependency graph were essentially given by the parent spec — #320 owns the wiring, #321/#322/#323 own only new files under `tests/integration/`. The split was designed in. Surprise count at Step 5: zero.

When a backlog comes from a single recently-filed spec authored in the same session, the skill's discovery-heavy steps (Step 5 conflict zones, Step 6 dependency graph) collapse to "confirm what the spec already shows." The value the skill still delivers in this mode is **formalization**: the design doc becomes a permanent ops manual for the orchestrator runtime (Rules 1–6 checklist, branch strategy, merge policy), not a discovery artifact. Run the skill anyway — the design doc + tracking issue + orchestrator checklist are what get exercised every batch launch, regardless of how much novelty Step 5/6 surfaced.

**Workspace-isolation interaction (cannabis.observer-wordpress-specific):**

This project has a hard workspace-isolation rule in `AGENTS.md` (enforced by a SessionStart hook) that names "spec/plan creation" as in-worktree work. The skill's Step 8 already covers this case ("Use a feature branch + PR when the host project enforces filesystem isolation for plan creation"), but the exact pattern for this project — worktree-based commit + merge-and-destroy — is worth recording so future sessions hit it without re-deriving:

```bash
# In main checkout (orchestrator's normal workspace):
./infrastructure/scripts/dev.sh worktree create <branch> --shared-db  # --shared-db: docs-only

# Write the plan doc inside .worktrees/<branch>/docs/plans/...
# Commit inside the worktree:
git -C .worktrees/<branch> add docs/plans/...
git -C .worktrees/<branch> commit -F /tmp/<branch>-msg.txt  # apostrophe-safe per prior session

# Merge to main from the main checkout:
cd <main checkout>
git pull --ff-only origin main
git merge --no-ff <branch> -m "Merge branch '<branch>'"  # <branch> is a placeholder; for real branch names with apostrophes, use -F /tmp/merge-msg.txt
git push origin main

# Destroy the worktree:
./infrastructure/scripts/dev.sh worktree destroy <branch>
```

`--shared-db` is the right flag for docs-only branches per this project's convention (skips the DB clone; safe because no schema work happens). For implementation worktrees (which Batch A and Batch B agents will use), the orchestrator should let `dev.sh worktree create` provision the full per-worktree DB.

The pattern works because cannabis.observer-wordpress's `dev.sh worktree create` provisions filesystem isolation (Nginx vhost, port slot, node_modules overlay, optional DB clone), and the workspace-isolation hook fires on any commit attempt in the main checkout — so writing the plan inside the worktree and merging from main is the path of least resistance.

**Tactical re-confirmations:**

- **`gh issue create --body "$(cat <<'EOF' ... EOF)"` apostrophe failure** — hit again on the first attempt at filing #320 ("What's not covered yet" inside the body). Switched to `--body-file <path>`. The skill's existing workaround is correct; this is the third recorded session that proves it. The same pattern (write to `/tmp/<name>.md`, then `--body-file`) is now my default reach when any GH body is non-trivial — saves the failed-first-attempt cost.
- **`git commit -F <path>`** for any commit message with apostrophes, dollar signs, backticks. Same workaround shape.

**Non-obvious decisions captured in the design doc:**

- **#320 alone in Batch A despite scoring third** — the two #13-scored issues (#321, #322) have a hard dependency on #320's harness existing. Sequencing follows dependency, not score, per the skill's "blast drives sequencing, not score" rule.
- **No bundling within Batch B** — the three test suites target wholly distinct surfaces (hook dispatcher / WP-CLI lifecycle / REST router). Bundling would force a single reviewer to context-switch across unrelated codebases.
- **`tests/integration/bootstrap.php` is read-only after #320** — if a Batch B agent finds it needs a bootstrap helper, file a small followup PR rather than mutating the foundation file inside an unrelated test branch.
- **`docs/TESTING.md` updates stay with #320** — each Batch B issue could plausibly add a line to TESTING.md's coverage table. Routing those updates as small post-merge doc PRs (rather than three concurrent edits) avoids a contested file appearing in Batch B's diff.

These patterns generalize: when a foundation issue ships a new shared file (here: `tests/integration/bootstrap.php`, `docs/TESTING.md` coverage section), explicitly declare it read-only for the follow-up batch and route necessary edits as separate small PRs after the batch lands. Concurrent edits to a "foundation shared file" by multiple Batch B agents is the failure mode this avoids.

---

## Session 2026-06-09 (cannabis.observer-wordpress, five-issue followup backlog)

**Project:** `CannObserv/cannabis.observer-wordpress`

**Backlog:** issues #325-#329 — five followups filed during the 2026-06-08 #311/#320-#323 shipping cycle. Each is a small carve-out (dev.sh DB provisioning gap, unhandled RuntimeException in a save_post hook, three REST source fixes, integration-tier docs, 10-command per-transformer test coverage).

**Interview answers:**
- Q1 Quality: All three dimensions equal → standard formula `(Foundation × 2) + (Correctness × 2) + Scope`, max 15.
- Q2 Deploy: Pre-production (re-launch runway, same as 2026-06-08).
- Q3 Defer: none — ship all 5.
- Q4 Parallelism: 4 parallel in Batch A, 1 sequenced as Batch B.
- Q5 Ceiling: 9-slot port pool (8001-8009) — re-verified by reading the port off this session's plan-doc worktree (got port 8004). Re-confirming a ceiling cheaply: just read the port number from any in-session `dev.sh worktree create` output. The pool's bounds don't change between sessions; one assignment confirms it.

**Shape:** two batches. Batch A (`batch/c`) is four parallel agents (#325/#326/#327/#328). Batch B is single-agent (#329 alone). Tracking issue: `#330`.

**Followup-backlog mode (now recognized as a recurring shape):**

Second consecutive session where the entire backlog was carved out as deliberate followups from a just-completed shipping cycle. Like the 2026-06-08 spec-derived backlog, Step 5/6 discovery work collapsed to "confirm what the parent shipping cycle already named." The skill still adds value via Step 7's batch design (here: the #326 → #329 sequencing decision is non-obvious; Q4's "bundle in one agent with sequential commits" was the alternative — see below) and Step 8's design-doc formalization (the orchestrator runtime checklist + the Key Decisions section).

When you recognize you're in followup-backlog mode (issues filed in the same session as the work they followed up on), it's reasonable to compress Steps 5/6 into "list contested files + confirm there's nothing surprising" without losing rigor. The contested-file list is still the input to Step 7; the formal "dependency graph" subsection of Step 6 is mostly ceremony when there's one edge.

**Non-obvious decision: "prerequisite in parallel batch, dependent in own batch" vs. "bundle in one agent with sequential commits".**

When two issues share a single file (here #326 touches `CptRowProvisioningIntegrationTest.php` to fill the skipped test; #329 refactors the same file to use a new trait), there are two clean shapes:

- **Shape A: bundle in one agent, sequential commits.** Used in the 2026-05-25 #41+#43+#44 batch. Lower ceremony — no gate between the two pieces, single review. Better when both pieces are small and reviewed together is the natural shape.
- **Shape B: prerequisite in the parallel batch, dependent in its own batch.** Used here. Better when the two pieces have wildly different sizes (here: #326 is ~50 lines, #329 is ~13 new files / ~1500 lines) or when bundling would force one big reviewer context-switch. The cost is one extra batch boundary; the gain is that the smaller prerequisite ships in parallel with three other unrelated issues and the larger dependent gets reviewed on its own merits.

Rough rule for picking between them: bundle when both pieces fit in a single review session (~under 500 lines combined); split when the dependent dwarfs the prerequisite (the test would be: would you review them in separate sittings anyway?).

**Worktree port allocation reuses freed slots:**

Destroying a worktree via `dev.sh worktree destroy <branch>` synchronously frees its Nginx vhost slot and port. The next `worktree create` reclaims the lowest-available port (this session: created `325-followups-plan` at 8004, then destroyed it; the next worker batch will get 8004 again as its first agent's slot). This means the per-batch ceiling check (Rule 5) only needs to count *concurrently-live* worktrees, not lifetime-allocated ones. Already implicit in Rule 5, worth being explicit about: a stale-port-leak failure mode is only possible when destroy fails partway, not under normal operation.

**Tactical re-confirmations:**

- **`git commit -F <path>`** for plan-doc commits — used `/tmp/325-followups-plan-msg.txt` here, no apostrophe issues.
- **`gh issue create --body-file`** for tracking issues — used `/tmp/issue-325-followups-tracking.md` here, no apostrophe issues. Both default reaches now, no failed-first-attempt cost.

**Workspace-isolation worktree pattern** continued to apply (see 2026-06-08 entry for the canonical sequence). Used `--shared-db` again for the docs-only plan branch.

---

## Session 2026-06-16

**Project:** CannObserv/usa-wa (PM sync sidecar hardening backlog). Tracking issue `#17`; plan `docs/plans/2026-06-16-sidecar-backlog.md`.

**Request shape:** user asked to orchestrate #6–9, 12–16 **and** include "a critical analysis of the continued validity of each issue in light of changes to the PM subscription mechanism in #10." #10 closed the same day, having replaced the firehose changes-feed with a server-side per-API-key subscription model.

**Interview answers:** Q1 quality = all equally (standard rubric). Q2 = pre-production. Q4 = hybrid. Q5 = plain `git worktree`, ceiling 3.

**Shape:** 3 batches. A = 3 parallel (#7+#8+#15 bundle, #9, #16). B = 1 agent (#6+#12 bundle). C = 1 agent (#13). Batch→main = regular merge.

### New pattern — the validity-re-analysis gate (worth promoting if it recurs)

When the orchestration request names a recently-merged change and asks whether the backlog is still valid against it, run a **disposition gate before scoring** — an extended Q0. The move: read what the change actually shipped (design doc + diff + grep the live code, not just the issue prose), then classify every in-scope issue as **keep / keep-but-reframe / rescope / defer / close-as-superseded**. Only survivors enter the scored table. This session:

- **keep-but-reframe (#6)** — the issue's *named target* (`reconcile`'s `while True`) became dead code post-#10, but the same risk class *relocated* to two new live loops (`discover`/`list_subscriptions`) the change introduced. The issue is *more* valid, just mis-pointed. Reframing > closing.
- **rescope (#13)** — the change subsumed ~70% of the issue (retired full-list reconcile, de-overloaded `read_source`), leaving a genuine narrow residual (dropped-feed-event recovery). Rewrite to the residual, re-score (dropped from a foundation item to a 5).
- **defer (#14)** — the change cleared *one named* blocker, but the issue's *real* prerequisite (an adapter that doesn't exist) is untouched. Clearing a listed blocker ≠ unblocked.
- **keep (#7/#8/#9/#12/#15/#16)** — write-path / independent issues the change never touched; verified by grepping that the cited functions still exist unchanged.

Surfaced the dispositions to the user via `AskUserQuestion` for the two genuinely-contested ones (#13 rescope-vs-close, #14 defer-vs-score) and proceeded on the clear ones. This is legitimately a "resolve before scoring" gate (HARD-GATE permits clarifying questions), directly analogous to Q0 dup-resolution — redundant/stale issues shouldn't consume ranking or risk a two-agent overlap. **Grounding mattered:** the verdicts only held up because I read the actual post-change source (`reconcile_enabled = False` on all five descriptors; the two new `while True` loops in `pmclient.py`) rather than trusting the issue text, which predated the change.

### Ceiling source: shared infra, not git or ports

First session where the worktree ceiling was gated by a **shared Postgres test DB** (`TEST_DATABASE_URL`) rather than a port pool / vhost slot. Plain `git worktree` provisions nothing, so N concurrent `uv run pytest` runs all hit one Postgres and contend on schema bootstrap. Mitigation recorded in the plan: workers run **targeted package tests** (`--no-cov <pkg>/tests`); the orchestrator runs the full suite once on the batch branch. Generalizes Rule 5 — the ceiling-limiting resource can be any shared backing service the worktrees don't clone, not just the port pool from the 2026-05-22 incident.

### Pervasive shared-file co-edits → sequential tail

The two lowest-scored items (#6+#12, #13) plus #12 pairwise co-edit `config.py` (SidecarSettings) and the org/person descriptor classes — small "registry/settings" files nearly every sidecar issue touches. Rather than lean on second-merge conflict resolution, sequenced them as single-agent Batches B then C (B lands pmclient/match-cap, C edits reconcile on top). Front-loaded all parallelism into the file-disjoint Batch A. Lesson: when a cluster of issues all touch the same small settings/registry file, parallelism within that cluster is a mirage — sequence it and put the parallel width where the files are genuinely disjoint. (Distinct from the 2026-06-08 "foundation shared file read-only" rule, which is about a *new* file shipped by Batch A; here the shared files pre-exist and are co-mutated.)

### Tactical re-confirmations

- `gh issue create --body-file` (`/tmp/sidecar-backlog-body.md`) — no apostrophe issues; default reach.
- `git commit -F -` (heredoc to stdin) for the plan commit — clean. Committed directly on `main` (skill default; no workspace-isolation hook in this repo, unlike cannabis.observer-wordpress).
- Followup-backlog mode again (3rd recurrence): all eight issues were CR carve-outs from the #4/#10 cycle; Steps 5/6 compressed to "confirm the contested files the issues already name."

---

## Session 2026-06-28

**Project:** cannabis.observer-wordpress (InfoSet 5h.x follow-ups). Tracking issue `#416`; plan `docs/plans/2026-06-28-infoset-5h-followups-backlog.md`. Issues #397, #398, #399, #401, #402, #407.

**Interview answers:** Q1 quality = balanced (standard rubric). Q2 = pre-production (confirmed against project memory). Q3 = all six in scope, nothing deferred. Q4 = hybrid gated waves. Q5 = `dev.sh worktree create`, ceiling 9 (port pool 8001-8009; re-confirmed live when the plan worktree landed on 8002). Batch→main = regular merge commit.

**Shape:** 2 waves, 3 parallel agents each, all file-disjoint. Wave A (correctness) = #402, #407, #399. Wave B (reusable/UI) = #397, #398, #401. Only contested file in the whole backlog: `docs/UI.md` (#397+#398, different sections) → intra-batch merge ordering (B1 before B2).

### Followup-derived but cross-layer → CR-like disjointness (taxonomy refinement)

The provenance taxonomy in the SKILL body says **feature-followup backlogs cluster on the producing file(s)** (single-file critical path). This session is the counterexample worth recording: the six issues were all filed during the same 5h.x cycle (#338 smoke test, #340 CR) — textbook followup-derived — yet they were **almost fully file-disjoint**, because the cycle's defects were spread *one per layer* of the InfoSet stack (model fatal #402, ETL transformer #407, CLI verify #399, admin JS #397, admin meta boxes #398, theme #401). The result behaved like a **CR-surfaced** backlog (one bug per surface → high parallelism), not a feature-followup one. Heuristic: followup-derived predicts *where the issues came from*, not *whether they're disjoint* — the disjointness depends on whether the followups all land in **one partial** (clusters) or **across the whole stack** (disjoint). Confirm with the contested-file grep regardless of provenance; don't assume a single-file critical path just because the backlog is followup-derived.

### Grep narrowed two footprints below their issue-body claims

The Step 1-2 / Step 5 footprint grep paid off twice, in the *narrowing* direction (issue bodies overstated scope, the opposite of the usual understate-the-footprint failure):
- **#407** claimed "check whether SegmentTransformer / the Legislation/Rulemaking element transformers share the mis-read." Grep showed `SegmentTransformer` and `InformationSetTransformer` already read `label`/`suffix` and clamp to 200 — only `TimelineTransformer` is buggy. Narrowed the agent to one file and added an explicit "out of scope: don't touch the sibling transformers" line so the worker doesn't go spelunking.
- **#399** claimed a "5h.2-5h.5 sweep." Grep of `verify_element_entity_type_fk` + `COLLATE utf8mb4_unicode_ci` showed rulemaking/infoset/timelineRefs already carry the fix; only `MigrateLegislationsCommand` + `MigrateLegislativeSessionsCommand` have the check-without-fix. And `MigrateTimelines`/`MigrateSegmentsCommand` have **no** Check-4 at all (count 0) — a genuine investigation residual, flagged in the plan rather than assumed.

Lesson: run the closed-in-fact / footprint grep even when no issue looks stale — partial-fix backlogs (some siblings already patched in the originating PR) routinely overstate remaining scope, and the grep both narrows the agent and prevents a worker from re-fixing already-correct code.

### Tactical re-confirmations

- **Workspace-isolation docs-only-worktree pattern** (2026-06-08 canonical sequence) again: `dev.sh worktree create <plan-branch> --shared-db` → write plan inside → `git -C <wt> commit -F /tmp/<branch>-msg.txt` → `git checkout main && git merge --no-ff` → `dev.sh worktree destroy`. `--shared-db` destroy correctly skips the DB drop ("Skipped (shared-db worktree)").
- **Committed the plan without the `#<n>` prefix, then opened the tracking issue** (#416) — the recent-precedent ordering; no blocking on the issue number.
- `gh issue create --body-file` (`/tmp/infoset-5h-followups-tracking-body.md`) — default reach, no heredoc/apostrophe cost.
- Interview ran genuinely one-question-at-a-time via `AskUserQuestion`; Q2/Q5 answers were pre-derivable from project memory + a `dev.sh` grep, so they were framed as confirm-the-default rather than open questions — faster without violating the one-at-a-time rule.

---

## Session 2026-06-29 (address-validator AR backlog wave 2)

**Project:** `CannObserv/address-validator` (FastAPI; uv + ruff + pytest). Second wave of `/reviewing-architecture` findings — issues #133–141 (8 maintainability/cohesion refactors + 1 perf). Tracking issue `#142`.

**Interview answers:**
- Q1 Quality: **maintainability first** → formula flexed to `(Foundation × 3) + (Correctness × 2) + Scope`, max 18. First session where **Foundation** took the ×3 weight (prior sessions weighted Correctness). Confirms the "unless the user requests different weights" escape hatch covers Foundation-leading, not just Correctness-leading — no skill-level rubric change needed.
- Q2 Deploy: early production.
- Q3 Defer: none — all 9.
- Q4 Parallelism: hybrid.
- Q5 Ceiling: **none** — `worktree-create.sh` is plain `git worktree add` into `.worktrees/`; TDD agents run `uv run pytest` only (no per-worktree port pool / Nginx vhost, unlike the 2026-05-22 WordPress incident). Cap = file-disjoint count.
- Q6 Merge: regular merge commit (batch→main); intra-batch fixed FF/regular.

**Shape:** 9 issues → **5 agents** (bundling same-file issues) → **2 batches** (4 parallel + 1 gated). Batch A = {V2, STATUS, STD, ADMIN}; Batch B = {PARSER}.

**Non-obvious decisions captured:**

- **Aggressive cohesive bundling collapsed 9 issues to 5 agents.** The three v2-router-cleanup issues (#133/#134/#135) all rewrite the *same two* router files (`parse.py`, `standardize.py`) — parallel is impossible, so rather than serialize three agents with two gates, bundle them into ONE agent ("v2 router DRY pass") with sequential commits. Same for #137+#138 (both own `parser.py`) and #140+#141 (both own `dashboard.py`). Rule of thumb reinforced: when N issues all rewrite one hot file, one agent with ordered commits beats N agents with gates — and reviews as a coherent unit.

- **A high-scoring issue placed LAST and ALONE because it conflicts with multiple parallel agents.** #138 (score 14, 2nd-highest) went to Batch B by itself. Reason: it moves `set_audit_context`/`set_candidate_data` out of `parse_address` into the *callers* — and `parse_address` is called from all three files the V2 bundle rewrites (`parse.py`, `standardize.py`, `pipeline.py`) *plus* it edits `models.py`, which STATUS edits. So #138 conflicts with **two of the four** Batch-A agents. New nuance on "blast ≠ priority": when a single issue's blast radius intersects multiple otherwise-parallel agents, isolating it in its own gated batch (it rebases onto post-A main and inherits everything) is cheaper than threading it as an ordering constraint through each conflicting agent. Verify the conflict empirically — `grep` the function's call sites before assuming a service-layer change is router-disjoint.

- **Sub-score commit ordering can invert the score order for define-then-use.** ADMIN runs #141 (score 8) before #140 (score 9): #141 establishes the single `{path: label}` map that #140's parallelized queries consume. Score orders *batches/priority*; within a bundle, dependency wins.

- **Correctness-leads-refactor inside a bundle.** PARSER commits #138 (the ContextVar-flow rewrite — a documented sensitive area) before #137 (mechanical 250-line extraction), so the surgical behavior change lands against the known-good structure as a legible diff, and the pure move rebases on top.

**Tactical confirmations:**
- `gh issue create --body-file <path>` used from the start (the 2026-05-24 apostrophe lesson) — clean, no quoting issues.
- Design-doc commit used precedent (a): committed without `#<n>` prefix, then opened the tracking issue.
- `resolve-plans-dir.sh` lives under `skills-vendor/gregoryfoster-skills/skills/writing-plans/scripts/` (vendored submodule), not `skills/` — the SKILL's `bash skills/writing-plans/...` path is a symlink-relative reference that may not resolve from repo root; `find skills skills-vendor -name resolve-plans-dir.sh` locates it. Resolved to `docs/plans/`.

---

## Session 2026-07-08 (power-map CR-followup backlog)

**Project:** `CannObserv/power-map` (FastAPI; uv + ruff + pytest). Six CR/review
followups — #262 (from #260 CR), #277 (from #276), #280/#281/#282/#283 (all from
the #275 Phase 2 CR) — plus #20 requested but closed-in-fact. Tracking issue
`#285`.

**Interview answers:**
- Q1 Quality: **all equal** → standard `(Foundation × 2) + (Correctness × 2) + Scope`, max 15. First session in a while to use the *default* rubric with no weight flex (contrast 2026-06-29 Foundation ×3, 2026-05-24 Correctness ×3).
- Q2 Deploy: **active production, stability-critical.**
- Q3 Defer: none — all 6.
- Q4 Parallelism: **hybrid.**
- Q5 Ceiling: **3** — generic `using-git-worktrees` scripts, no custom port pool; dev server on 8001 is manual. (No shared-resource cap like the 2026-05-22 WordPress port pool or 2026-06-16 usa-wa shared Postgres; the cap is a comfort preference on a single VM.)
- Q6 Merge: regular merge commit (batch→main); intra-batch fixed FF/regular.

**Shape:** 6 issues → **6 agents across 3 gated batches** (A: 3 parallel / B: 2 parallel / C: 1 solo). All six issues are file-disjoint — max parallelism was *available* but not *chosen*.

**Non-obvious decisions captured:**

- **Shared test infrastructure is a soft conflict zone even at zero source-file overlap.** #283 (optimize the ~16-min integration suite) touches no product source and no other issue's files — by the pure contested-file grep it's fully parallel-safe. But its real work mutates `conftest.py` / session-scoped fixtures / the isolation strategy that *every other worker's TDD tests* depend on. Merging it concurrently with five workers who are each adding tests against the old fixtures is a guaranteed churn/rebase mess, and it would be optimizing an incomplete suite. Resolution: sequence it **last & solo**, tuning the fully-merged suite as a read-only baseline. Generalizable rule candidate: *a test-suite-restructuring issue is a soft dependency on all issues that add tests, even when it shares no source file with them — put it last and alone.* (First occurrence; log-only until it recurs.)

- **Stability-critical deploy context can override max-parallelism on a fully-disjoint backlog.** With every issue file-disjoint, the mechanical answer is "one batch, 6 agents (chunked to the ceiling)." But Q2 = active production + Q4 = hybrid turned it into three correctness-ordered gated batches: the data-loss bug (#280, C3) and the two runtime-risk issues (#277, #262, both C2) in Batch A reviewed as a unit *before* any cosmetic/UX cleanup (#281/#282) touches the tree; #283 last. Disjointness enables parallelism; deploy context decides whether to *spend* it. The two prior CR-surfaced power-map sessions (2026-05-09 pre-/early-production) went fully parallel — the difference here is purely the stability posture.

- **#262 grouped with the correctness batch, not the cleanups, despite being "perf."** It's a production request-path change with lost-write/ordering risk if botched (C2), so it belongs where the careful review is — and it fills Batch A to exactly the 3-agent ceiling.

- **Closed-in-fact catch via `git log -S`, closed before the interview.** #20 (dup-count cache stale under multi-worker) described a module-level dict in `orgs.py`; `git log -S dup_count_cache -- src/core/schema.sql` surfaced `#210 feat: move dup count cache to DB so all workers share it`, and the current `org_dups.py`/`people_dups.py` carry a DB-backed `dup_count_cache` table documented as worker-shared. Confirmed the issue's own file reference was stale (the code had moved modules *and* mechanisms). Closed as a Q0-adjacent clarifier (`AskUserQuestion`) before Q1 so the scored backlog reflected reality — the HARD-GATE permits clarifying questions.

**Tactical confirmations:**
- Design-doc commit used precedent (b): opened the tracking issue **first** (#285), then committed the doc with the `#285 docs:` prefix. Committed directly on `main` — no workspace-isolation pre-commit hook here (hooks are ruff/pytest/eslint/prettier/vitest/version-sync/terraform-fmt; the markdown-only commit ran ruff+pytest-unit and passed).
- `gh issue create --body-file` from the start (2026-05-24 apostrophe lesson).
- **Process-log lives in a vendored submodule** (`skills-vendor/gregoryfoster-skills`, reached via the `.claude/skills/...` symlink). Per the project's "don't leave uncommitted edits in vendored skills" rule, this entry is committed *inside the submodule's own git* and flagged for upstream push to `gregoryfoster/skills` — not left as local divergence that `git submodule update` would clobber.

---

## Session 2026-07-19 (archiver CR-followup backlog)

**Project:** `CannObserv/archiver` (FastAPI; uv + ruff + pytest). Five CR/shipping
followups from the #82/#86/#87 cycles — #88/#89 (from #86 CR), #85 (from #82 CR),
#91 (from shipping #86), #92 (spun out of #87). Tracking issue `#93`.

**Interview answers:**
- Q1 Quality: **all equal** → standard `(Foundation × 2) + (Correctness × 2) + Scope`, max 15.
- Q2 Deploy: early production (live on 8020, Watcher consumes; low volume).
- Q3 Defer: none — all 5 in full, including #89's `/health` surfacing and #92's step 4 (attempt-or-document).
- Q4 Parallelism: hybrid.
- Q5 Ceiling: **no worktree script** (plain `git worktree add`); real constraint is the **shared Postgres test DB** (`TEST_DATABASE_URL` — teardown drops the whole `information` schema). Resolution: unlimited edit parallelism, **serialize full-suite runs**; orchestrator's batch-branch run is the authoritative gate. 2nd recurrence of the DB-gated ceiling (after 2026-06-16 usa-wa, which capped agents instead — serialization is the lighter answer when the orchestrator re-runs the suite anyway).
- Q6 Merge: regular merge commit (batch→main); intra-batch fixed FF/regular.

**Shape:** 5 issues → **5 agents across 2 batches** (A: #88/#89/#85 parallel; B: #91/#92 parallel, gated on A). CR-surfaced prior held: implementation surfaces fully disjoint; contention confined to `ci.yml` and `CHANGELOG.md`.

**Non-obvious decisions captured:**

- **Version-freshness hard edge — invisible to file-overlap analysis.** #92 commits `archiver-openapi.json` as contract-of-record; the FastAPI app builds `info.version` from `pyproject.toml`, which #85 bumps (3.2.0 → 4.2.2). Zero shared files between the two issues, yet #85 must merge first or #92's snapshot is born stale and needs immediate regen. Generalizable: **when one issue snapshots/freezes an artifact that another issue's fix feeds into, that's a hard dependency edge no contested-file grep will surface** — hunt for "commits a snapshot / vendors a copy / bakes a version" language in issue bodies and trace what the snapshot embeds.

- **Route new CI checks to an uncontested job.** #85 (option 1) adds a CHANGELOG↔pyproject lockstep check; the naive home (the `changelog` job) is contested by #91, and the `client-drift` job by #92. Placing the check in the **lint** job — where it also fits semantically (static file assertion) — removed #85 from both contested hunks and let it run in Batch A. When an issue's *new* code has placement freedom, spend that freedom on de-conflicting.

- **Validator merges last.** Batch A merge order is #88 → #89 → #85: the first two append CHANGELOG entries; #85 both bumps the version and installs the check that asserts heading↔version agreement, so it merges after the state it validates is final. Same family as 2026-06-29's "sub-score commit order inverts for define-then-use," but at merge-order granularity: **check-installing issues merge after the issues that mutate the checked artifact.**

- **CHANGELOG top-append is a tolerated conflict, not a batch-splitter.** Three Batch-A workers all touch `CHANGELOG.md` top-of-file. Rather than serialize the batch, accept trivial rebase conflicts under an explicit merge order. The one real hazard was #85's option 2 (drop version headings = full-file rewrite conflicting with everyone) — rejected partly *on conflict-shape grounds*, a case of the orchestration analysis feeding back into which fix option gets chosen.

**Tactical confirmations:**
- `gh issue create --body-file` from the start; GH_TOKEN must be re-sourced from `.env` per Bash call (fresh shell each time).
- Design-doc commit used precedent (a): committed on `main` without the `#<n>` prefix, then opened #93.
- Process-log entry committed inside the `gregoryfoster-skills` submodule and pushed upstream (2026-07-08 discipline).

**Execution addendum (both batches shipped same session):**

- **Six issues closed against a five-issue plan.** CR round 2 on batch/b found open #69 closed-in-fact by #92's work (its two blockers had been resolved by #87 and the batch itself). The closed-in-fact grep (Step 1–2) covers the *scoped* issues; a CR pass on each batch is what catches adjacent backlog issues the batch retires. Worth doing deliberately: after each batch, ask "which OPEN issues did this work just complete?"
- **A hermetic consistency gate is not a freshness gate — CR caught the docstring overclaim.** #92's regen-from-snapshot-vs-tree check passes when snapshot and tree are *consistently stale* (regen skipped after an API change). When the spec's producer app lives in the same repo, the fix is a suite test that re-derives the spec from the app and diffs the committed snapshot — hermetic, no live-compare timer needed. Verify such guard tests by perturbing the artifact and watching them fail.
- **Worker completion signals can be non-reports.** One worker stopped with "waiting for the full-suite retry" instead of a completion report (its background pytest outlived its turn). A SendMessage nudge — rerun in foreground, then report — resumed it cleanly. Treat any non-report stop as "nudge, don't diagnose."
- **CHANGELOG top-append conflict handled per protocol**: orchestrator aborted the merge and sent the second worker instructions to `git merge batch/<X>` in its worktree (merge, not rebase — preserves the ancestor check) and fold both entries under one heading. Round-trip cost ~1 min; keeps the conflict-resolution-stays-with-worker rule intact.
- **Vendor `worktree-destroy.sh` assumes `.worktrees/`; Agent-tool worktrees live in `.claude/worktrees/`.** Fallback: `git merge-base --is-ancestor <branch> batch/<X>` (explicit Iron-Law check) → `git worktree remove` → `git branch -d` (second guard). Same safety, no script.
- **Validator-merges-last worked as designed**: #85's lockstep check fired on the batch branch (4.2.2 vs the siblings' new v4.2.3 heading) and the planned one-line orchestrator bump resolved it — the check's failure message doubling as the fix instruction paid off immediately.
- **Worker prompt fences held**: both Batch B workers were told exactly which ci.yml jobs they owned; zero contested-file conflicts materialized (and #92's job needed no ci.yml edit at all — the no-arg checker invocation already covered new registry entries).
- **A worker exceeded its brief usefully**: #91's worker added the job-level `pull-requests: read` permission grant the label lookup needed — omitted from the issue and the worker prompt; without it the fix would have silently 403'd into fail-open. Verification-by-stub (extracting the workflow `run:` block, executing against a stubbed `gh` across 7 scenarios) is a reusable pattern for CI-only logic.

---

## Session 2026-07-23 — CannObserv/cli

First orchestration session in the `cli` repo. Five CR/followup carve-outs from the just-merged #843 historical-biennia (#732) repair cycle (#847, #849, #851, #852, #853).

**Interview answers:**
- Q0 Dups: none — each issue distinct (the #849/#851 same-file relationship is a Step 7 batch-shape question, not a duplicate).
- Q1 Quality: **correctness** (data-integrity guards; correctness breaks score ties).
- Q2 Deploy: **active production** (the #843/#732 backfill runs against prod data now).
- Q3 Defer: none — all 5 in scope.
- Q4 Parallelism: **hybrid**; worktrees yes.
- Q5 Ceiling: **none binding.** `scripts/setup-worktree.sh` is lightweight (cannobserv symlink + `uv sync`) — no port pool / nginx / DB clone. Parallelism bounded only by disjointness + Agent concurrency cap. Contrast with the WordPress/Postgres sibling projects whose ceilings were the whole story.
- Q6 Merge: regular merge commit (batch→main; project preference — squash collapses the per-issue commits `cli` keeps separate, per repo memory); intra-batch fixed FF/regular.

**Shape:** 5 issues → **5 agents across 2 batches.** Batch A (4 parallel, disjoint): #847 `ext/click/logging.py`, #849 `update/legislation_session.py`, #852 `ext/wa_leg/legislation.py`+fixture, #853 docs plan. Batch B (1 agent, gated): #851.

**Backlog provenance confirmed the geometry — followup-derived, across-the-stack.** 5th recurrence of the followup-backlog mode. Like 2026-06-28 (and unlike the one-partial-cluster 2026-05-11), the #843 cycle spread its CR defects one-per-surface — observability / command robustness / guard refactor / test hygiene / docs — so the backlog is near-fully disjoint (CR-like), single contested file. Compressed Steps 5/6 to "confirm the one contested file"; the grep held (no under/overstatement this round — footprints matched issue bodies).

**Non-obvious decisions captured:**

- **Shape B chosen on the "differ in kind" signal, not just file-sharing.** #849 and #851 both touch `update/legislation_session.py` (different regions: house_of_origin ~L74 vs guard L51–58). Bundling (Shape A) was tempting on the shared file, but #849 is a contained correctness fix + test while #851 is a wider design-discovery refactor spanning `add/legislation.py` + a new shared helper + a multi-command audit. Dependent dwarfs prerequisite AND they differ in kind → split. #849 rides the parallel batch; #851 gates behind it and refactors the guard on top of #849's stabilized file. Textbook "correctness fix leads refactor" at the batch-boundary granularity.

- **The refactor target ruled a shared file read-only.** #851's tempting home for the extracted guard is `LegislativeSessionParamType` (every session option inherits it). But that ParamType is also consumed by commands that *legitimately* pass regular-session children (`add legislative_session` resolves a `parent_session`). Putting the biennium guard there would break them. So the guard routes through a shared helper only the *Legislation*-linking commands call, and the design doc's Key Decisions declares `LegislativeSessionParamType` read-only for #851's worker. A read-only-shared-file call (cf. 2026-06-08's foundation-file rule) driven by *consumer semantics*, not by concurrent-edit risk.

- **`add legislation` gap verified before scoring, not assumed.** #851's audit checklist asks "does `add legislation` validate the session is a biennium?" — grepped it (line 133 passes `session=session` with no guard; line 28 uses the plain option). Confirmed the gap is real, which is what lifted #851's Correctness to 3 (silent WSOD reintroduction) and its score to 13. The issue-body checklist item became a verified fact, not a maybe.

**Tactical confirmations:**
- `gh issue create --body-file` from the scratchpad (apostrophe-safe); precedent (a) for the doc commit — committed on `main` without the `#<n>` prefix, then opened #855.
- **The `.claude/skills/…` path is a double symlink into the `gregoryfoster-skills` submodule**, despite CLAUDE.md labelling this skill a "local override." `.claude/skills/orchestrating-issue-backlog` → `../../skills/orchestrating-issue-backlog` → `skills-vendor/gregoryfoster-skills/skills/…`. Editing the process-log from the `cli` working session is a direct edit to *another repo* — the maintainer's rule is **file an issue in that repo instead** (this issue), not commit across the submodule boundary.
- Pre-commit hook runs full pytest (~2 min) even on a docs-only commit; budget the Bash timeout accordingly (repo memory).

---

## Session 2026-08-07 — CannObserv/usa-wa (architecture-review backlog)

Backlog: #178–#189, the twelve findings of the project's **first architectural review**, filed by the
same agent ~1h earlier in the same session, plus #169 folded in. Tracking issue #191, plan
`docs/plans/2026-08-07-architecture-review-backlog.md`. (Source: upstream issue #112.)

**Interview answers:**
- Q0 Pairs: three deliberate prerequisite pairs, not duplicates — **bundle** #179+#178 and #181+#186
  (Shape A), **split** #189/#183 (Shape B).
- Q1 Quality: **Foundation ×3** → `(F×3) + (C×2) + S`, max 18. 2nd Foundation-leading session (after
  2026-06-29 address-validator) — the variable-weight escape hatch continues to hold.
- Q2 Deploy: **early production** (Power Map is a live consumer; 11 daily timers; breakage
  recoverable).
- Q3 Defer: none — all 12 in scope.
- Q4 Parallelism: **hybrid**.
- Q5 Ceiling: **4**, via provisioned test-DB slots (see below).
- Q6 Merge: regular merge commit batch→main (matches repo history); intra-batch fixed FF/regular.

**Shape:** 13 issues → **11 agents across 6 batches.** A(4 parallel) → B(1) → C(2) → D(1) → E(2) → F(1).

### New provenance flavor — AR-derived backlogs are maximally contested, the inverse of CR-derived

A code-review backlog yields one bug per surface and parallelises freely (2026-05-09: 6 agents, zero
contested files). An **architecture**-review backlog is the opposite: every finding is *about*
structure, and structure is shared. Concretely, three issues claimed the same 47 CLI entry modules;
four claimed root `pyproject.toml`; three claimed `docs/ARCHITECTURE.md`. Result: six mostly-serial
batches, not two wide ones. **Do not let "review-derived" imply disjoint — check which kind of
review.** One occurrence at time of writing; see the 2026-08-09 observo entry for the second.

### Shared-test-DB ceiling, 3rd recurrence, third distinct resolution

**[Promotion candidate → Q5 / Rule 5.]** `conftest.py:64-90` runs `DROP SCHEMA … CASCADE` +
`CREATE SCHEMA` for every declared schema at **session** scope against a single `usa_wa_test`, and
`usa_wa_test_owner` has `rolcreatedb=f, rolsuper=f`. Effective ceiling was 1 regardless of worktree
isolation. Resolved by **provisioning four slots** via `sudo -u postgres` + `scripts/grants.sql` —
unlike 2026-06-16 (cap agents) and 2026-07-19 (serialize runs), this preserves both parallelism and
the worker protocol's self-verify-before-signal step, so it is the preferred resolution of the three.

Q5 currently asks only about worktree-*create* tooling (port pools, vhosts, DB clones, node_modules
overlays). Three sessions across two orgs have now found the real ceiling somewhere Q5 does not look:

| Session | Project | Resolution chosen |
|---|---|---|
| 2026-06-16 | CannObserv/usa-wa | Cap agents + workers run targeted package tests only |
| 2026-07-19 | CannObserv/archiver | Serialize full-suite runs; orchestrator's batch-branch run authoritative |
| **2026-08-07** | **CannObserv/usa-wa** | **Provision N databases up front** |

The 2026-06-16 entry already generalized Rule 5 ("the ceiling-limiting resource can be any shared
backing service"), but that generalization lives only here — **Q5's question text never absorbed
it**, so each session rediscovers it during Step 5 instead of during the interview. This session
found it by reading `conftest.py`, not by asking.

**Naming gotcha:** `assert_test_url_safety()` requires the DB name to end in `_test`, so the slots
are `usa_wa_<n>_test`, not `usa_wa_test_<n>` — the obvious name aborts the suite at conftest import.
Read the project's test-DSN guard before naming the slots.

### Migration/revision-chain rule

**[Promotion candidate → Step 7.]** #178 (`runs`) and #180 (`source_coverage`) each generate an
Alembic revision. Two agents in the same batch both compute `down_revision = <current head>`,
producing a forked revision chain that only surfaces at `alembic upgrade head` — after both branches
have merged cleanly. Git sees no conflict: the two migrations are different new files.

Rule adopted: **at most one chain-appending agent per batch** (A4, then C1), named explicitly in the
design doc. Generalizes beyond Alembic to any append-to-a-linear-chain artifact — Django migrations,
`schema_migrations`, changelog files with a "latest" pointer, ADR sequence numbers. Invisible to
file-overlap analysis — same class as 2026-07-19's version-freshness edge.

### Other non-obvious decisions

- **Decomposed the top-scored issue instead of deferring or reordering it.** #179+#178 (harness +
  ledger) scored highest at 17/18, but 24 of its 47 CLI targets sit inside #183's packages and 21
  inside #189's blast — mutually exclusive with both. Neither deferring it (loses the highest-value
  item) nor reordering (three passes over moving files) was acceptable. The issue body's own
  *"migrate opportunistically, one module per PR"* licensed a split: **#179a** (core `job.py` +
  `runs.py` + migration + one pilot adoption) in Batch A, **#179b** (sweep over the remaining ~46
  CLIs) in Batch F against the final layout. New tactic — when the top-scored item is the dominant
  conflict, look for a core/adoption seam inside it before touching the batch order.

- **A cheap issue gating an expensive one.** #187 (three list edits + one fitness test, scored 13 on
  Scope 3) sits in Batch A *specifically* because its registry-parity test must exist before #189
  adds two new packages — otherwise the very omission #187 fixes recurs on the new packages with
  nothing to catch it. Complements 2026-06-29's "blast ≠ priority": here **score ≠ sequencing
  weight** in the other direction — a trivial issue can be a hard gate.

- **#180 → #189 is a mechanics edge, not a priority edge.** #180 collapses seven duplicated floor
  constants into one table. Sequencing it *after* #189's file moves would mean chasing seven
  constants through relocated files; before, #189 moves a single reference. Found by the Step 5 grep,
  not by the issue bodies.

- **A feared conflict that the grep dissolved.** #186 (migrating engine-contract assertions out of
  `test_sidecar.py`) looked certain to collide with #189 (rewriting five committee reconcilers).
  `grep -c 'reconcile_committee\|WSLClient' test_sidecar.py` → **0**; the reconcilers own seven
  separate test files. #181+#186 was scheduled freely as a result. Reinforces the Step 5
  bidirectional-grep rule: it narrows *conflict* claims as well as *scope* claims.

- **Q0 repurposed for prerequisite pairs.** SKILL.md frames Q0 as duplicate resolution, but its
  option set (*bundle / close as dup / score independently*) is exactly the Shape A/B decision. With
  no true duplicates, Q0 resolved three deliberate prerequisite pairs before scoring — which meant
  the score table had 10 rows for 12 issues and the batch design inherited the shapes rather than
  re-deriving them. Worth generalizing Q0's framing to "candidate pairs (duplicate **or**
  prerequisite)".

**Tactical confirmations:**
- Backlog authored by the same agent an hour earlier made closed-in-fact checking trivial, but
  created a distinct risk: **trusting one's own issue bodies**. Re-verified all ten claims against
  `HEAD` anyway (engine.py still 2318 LOC, 29 `create_async_engine` sites, 7 floor constants, sos
  still absent from `pyproject.toml`) — none closed-in-fact, all footprints as stated.
- `gh issue create --body-file` from the scratchpad again (apostrophe-safe).
- Ordering (b) used for the doc commit — tracking issue #191 opened first, so the commit carried the
  `#191` prefix.
- Doc landed via worktree + PR (#192) rather than directly on `main`, matching this repo's
  PR-per-change history; merged before any worker launch so Rule 1's local-main assumption holds.
- `.skills/doctor.sh` must be run inside a fresh worktree before any hook resolves — the
  `.claude/hooks/*` symlinks dangle until submodules are initialized there.

---

## Session 2026-08-09 — CannObserv/observo (architectural-review backlog)

**Backlog:** 12 issues (#422–#433) filed from an architectural review completed earlier in the same
session, plus pre-existing #331. 13 resolved across 6 batches. (Source: upstream issues #114 and
#122.)

**Interview answers:**
- Q1 Quality: `(Foundation × 3) + (Correctness × 2) + Scope`, max 18. Third Foundation-leading
  session (after 2026-06-29 address-validator, 2026-08-07 usa-wa).
- Q2 Deploy: pre-production.
- Q3 Defer: none.
- Q4 Parallelism: hybrid.
- Q5 Ceiling: 3 concurrent agents (see below).
- Q6 Merge: regular merge commits, **read off `git log --merges` rather than asked** — the project
  had an unambiguous `Merge #NNN: …` convention. Worth noting as a way to skip a question.

**Shape:** `A(3 ∥) → B(3 ∥) → C(2 ∥) → D(1) → E(1) → F(1)`. Three fully-parallel waves of independent
correctness/hygiene work, then a four-link single-agent chain for the provider spine, every edge of
which is a shared file. **Second AR-derived backlog** (after 2026-08-07): the wide front half is
CR-like, but the structural spine is a serial chain — consistent with the 2026-08-07 finding that
AR-derived backlogs contest structure.

### Lesson 1 — an issue body's stated *dependency* is not a substitute for the footprint grep

**[Promotion candidate → Step 5.]** #423 (move `providers/` to `shared/`) and #425 (build a capability
registry over them) were filed an hour before this orchestration by the same agent, with an explicit
sequencing note in both bodies: "#423 → #424 → #425 → #426 → #427. Doing them out of order means
redoing work."

The Step 5 grep showed the sequencing advice was wrong in a way the author could not see without
measuring: **five of six production files and nine test files are shared** between them. #423 moves
the import lines; #425 rewrites those same lines into registry calls. Run as separate batches, the
second agent rewrites everything the first just moved, and both edit the same nine test files.
Correct shape was Shape A (one agent, two sequential commits) — which the SKILL's own define→use
heuristic predicts, once the footprint is known.

The existing Step 5 text warns that issue bodies under- and over-state scope. This is a third failure
mode: a body can state a *relationship* between two issues that the file overlap contradicts. A
stated sequential dependency between two issues whose footprints substantially overlap is usually a
**bundling** signal (Shape A) that the author mistook for an ordering constraint.

### Lesson 2 — a shared-test-DB ceiling may be avoidable rather than binding; read the guard

**[Promotion candidate → Q5 / Rule 5.]** Fourth session where a shared Postgres test DB — not git,
ports, or tooling — set the ceiling (2026-06-16 usa-wa, 2026-07-19 archiver, 2026-08-07 usa-wa).
Prior sessions resolved it by capping, serializing, or provisioning. Here it was simply **avoidable**.

`tests/conftest.py` derives the DB name from `PYTEST_XDIST_WORKER` only, so concurrent agents would
race one `observo_test`'s `DROP SCHEMA` bootstrap. But the safety guard reads:

```python
_base_db_name = _base_url.database or ""
assert _base_db_name.endswith("_test"), ...
# ... xdist suffix appended AFTER the guard
```

It validates the **base** name, *before* the xdist suffix is appended. So a per-agent base
(`observo_a1_test`) passes the guard and stays xdist-compatible (`observo_a1_test_gw0`). Three
databases were created once, verified with a real run, and the ceiling stopped being a serialization
constraint. Rule: **read the conftest guard before accepting serialization**, and put the per-agent
`TEST_DATABASE_URL` in every worker prompt.

### Lesson 3 — deriving the ceiling from the suite's CPU duty cycle

No custom worktree tooling, so no provisioning ceiling. The number came from a comment in
`pyproject.toml` recording the suite as **~40 s CPU against ~135 s wall** — a ~30 % duty cycle — on a
**2 vCPU** host. Three concurrent suites ≈ 120 s CPU per 135 s wall ≈ 0.9 cores: comfortable. Four
would have stretched wall time. Generalizes as: where a project records its suite's CPU-vs-wall
ratio, `ceiling ≈ cores ÷ duty_cycle` is a better-grounded answer than a round number.

### Lesson 4 — the duplicate check earned its keep on files, not titles

#331 "Non-TVW provider support: interim handling + evolution path for HLS/file/rtsp jobs" and #425
"Model provider capabilities on ProviderBase". Zero title overlap; #331 does not appear in any
keyword search for "capability". They were matched on **shared touch points** — both name
`archival_poller.py`, `scheduler.py`, `capture.provider_factory_for`, `resolve_provider_event_id`.
#331 turned out to contain the identical proposal plus scope #425 lacked. Resolution was **bundle**,
not close-as-dup, precisely because the older issue carried the extra scope. Clean positive hit for
the existing Step 1–2 guidance.

### Lesson 5 — re-scoping an issue mid-orchestration should be written back to GitHub

**[Promotion candidate → Step 4/5; see also 2026-08-11 observo.]** #422 as filed bundled a live
Job-hang fix with an unrelated derivation touching 9 files, which would have put it in contention
with two refactors and delayed it three batches. Narrowed it to the hang fix and moved the remainder
into #430, which already owned both affected files. Both issue bodies were **edited** with a
prominent re-scope note (not just recorded in the design doc), so the agent that eventually picks up
either one sees the actual boundary rather than the as-filed one. Cheap; worth making the default
when a Step 5 grep changes an issue's scope.

### Execution addendum — issue bodies give reliable directions and unreliable specifics

**[Promotion candidate → Agent Roles / worker prompts.]** Across six batches and 13 issues, **the
implementing agent found a material error in the issue body every single time.** Not once did a body
survive contact with the tree intact. Yet in every case the *direction* was right — the issue named a
real problem and the right general shape of fix.

| Batch | Issue | What the body claimed | What was true |
|---|---|---|---|
| B | #429 | `InMemoryBroker` ignores `min_idle_ms`; converting the tests will produce skips | **Premise false.** It has honoured it since #124 (`in_memory.py:328`); only the *Protocol docstring* said otherwise. Predicted "several skips"; actual **zero** |
| B | #424 | "No application-code change beyond the model annotation" | **9 call sites**, two failing silently — four `is StreamProvider.TVW` identity checks (always false against a `str`), and `{{ job.provider.value }}` in a template (Jinja `Undefined` → renders empty) |
| D | #423 | Fold `tvw_urls.py` into the adapter once it lives in `shared/` | Would drag `httpx` + ~900 lines of adapter into every consumer subprocess **and close a `schemas` ↔ `registry` import cycle** |
| D | #425 | Seven inline `is StreamProvider.TVW` branch points, at these lines; three independent provider factories | **5 of 7 were already `==` value comparisons** (a *previous batch* changed the column type); every line number had moved; two of the three "factories" were already injectable seams |
| E | #426 | Infer media class from the configured `FETCH_*` stages | Would hand a `.vtt` to a `FETCH_VIDEO` pipeline as `video_download_url`. Also prescribed calling `_is_fetchable`, which lives in a package `shared/` **may not import** |
| F | #427 | Sketch of the `FetchSource` model | Omitted `expected_duration_s` / `expected_duration_is_estimate` — typing only the sketched fields would have **silently dropped upstream-truncation reconciliation**. Also had a field name wrong, and put `broker_url` on the envelope where no source payload has ever carried one |

Three of these would have shipped a defect if implemented as written (#426, #427, #423). Two would
have wasted a batch chasing a non-problem or an understated one (#429, #424).

**Why it gets worse as the backlog runs.** Issue bodies are a single snapshot; the backlog is six
sequential mutations of the thing they describe. #425's branch-point table was accurate when filed
and 5/7 stale by the time Batch D ran — because Batch B's #424 changed the column type underneath it.
So staleness is not random: it is *proportional to batch depth*, and it is highest exactly where the
work is hardest (the late single-agent chain on the critical path). An orchestrator who trusts the
late issue bodies most is trusting the ones most likely to be wrong.

Three changes this argues for:

1. **A rule in the worker prompt**: treat the issue body as a **proposal, not a specification**;
   verify every file:line, claimed call site and prescribed implementation against the current tree;
   **report the correction** rather than implementing around it silently. The wording that worked in
   practice named prior failures explicitly — an agent told *that* corrects the body; an agent told a
   generic "verify assumptions" tends to confirm them.
2. **A slot in the report-back template**: "everything in the issue body that turned out to be wrong
   or stale — I want the corrections, not a report that matches the prediction." Without the second
   clause, agents reliably produce a report shaped like agreement.
3. **A line in the design doc's runtime notes**: issue bodies decay as batches land; re-verify the
   specifics of any issue whose files an earlier batch touched.

**Counter-argument, for the record.** One could argue the bodies should simply be more accurate. That
doesn't survive the evidence: #425's table was *correct when written*, and #424's author could not
have known about the nine call sites without running the grep the implementer ran. The specifics are
cheap for the implementer to re-derive and expensive for the reviewer to keep current. The fix is to
stop treating them as authoritative, not to try harder to make them so.

**Note for `reviewing-architecture`.** These bodies came from that skill's findings, and two of its
rules were followed and still produced stale specifics. It requires each finding to **cite** a
module/file/line but not to record **how the citation was obtained** — a finding carrying its grep
alongside its conclusion would let the implementer re-run it. And findings become issue bodies read
*later*, after other findings have landed, so a finding's file:line specifics have a shelf life
measured in merges: lead with the invariant, treat line numbers as evidence-of-the-moment.

---

## Session 2026-08-10 — cannabis.observer-wordpress (CR-followup backlog)

Tracking issue `#687`; plan `docs/plans/2026-08-10-cr-followup-backlog.md`. (Source: upstream issue
#127 and its execution addendum.)

**Interview answers:**
- Q0 Duplicates: #664 closed as dup of #681 (see below).
- Q1 Quality: **Correctness ×3** (3rd Correctness-leading session, after 2026-05-24 and 2026-05-25 —
  both `gregoryfoster/skills`).
- Q2 Deployment: pre-production — **not asked**, answered from project memory (staging live, launch
  epic #421 open, no real users). Stated as an assumption with an invitation to correct.
- Q3 Deferrals: none; #656 scoped to *include* the prerequisite it underscoped.
- Q4 Parallelism: hybrid.
- Q5 Ceiling: **9** (dev.sh port pool 8001-8009) — resolved by grep, not asked, then re-verified when
  the plan worktree drew 8001.
- Q6 Merge: regular merge commit; intra-batch fixed FF/regular.

**Shape:** 6 issues → **5 agents across 2 batches.** Batch A (3 parallel): A1 #681+#666 bundled, A2
#667, A3 #445. Batch B (2 parallel, gated): B1 #656, B2 #669. Peak parallelism 3 against a ceiling of
9 — the ceiling was not binding, which is unusual for this host project.

**Outcome:** all merged (`6c4613aa`, `96ff56f1`), all issues closed, 2 CR rounds, one follow-up filed.

### 1. A generated artifact under a byte-for-byte sync test is a hard bundle signal

**[Promotion candidate → Step 7.]** #681 and #666 both regenerate `plugins/.../openapi.json` via
`dev.sh openapi --write`, and `CoRestOpenApiSyncTest` asserts committed == generated
**byte-for-byte**. That converts a normal parallel-merge conflict into a forced regeneration for
whichever agent lands second — the merge can succeed textually and still fail the build. The pair
failed the usual Shape A heuristics (not a define-to-use sequence; two unrelated routes) but bundling
was still right, because bundling makes the conflict *impossible* rather than *manageable*. Distinct
from the existing "same file" and "naturally sequenced" signals.

### 2. A closed prerequisite is not a met prerequisite

**[Promotion candidate → Step 1–2.]** #656 stated its `co_roles` blocker "is finding 5 of #655 and
should land first or together." #655 was CLOSED, so the cheap read is "prerequisite satisfied,
proceed." Verifying the *cited finding* rather than the *issue state* showed #655's finding 5 was the
theme `getLabel()` delegation — a different finding entirely — and both `get_field('co_roles')` reads
were still live, with `co_roles` in neither `RETIRED_KEYS` nor `DELIBERATE_KEYS`. Unchecked, B1's
agent would have deleted the ACF group and silently broken two theme composers. Rule: when an issue
names a specific finding in another issue as its prerequisite, grep the *finding*, not the issue's
state.

### 3. Design-gate vs file-gate

**[Promotion candidate → Step 7 / Key Principles.]** #669 was gated behind #667 despite
**verified-disjoint file sets** (#667: `co_event_type.php` + `ArchiveEvent.php` + `post-types/event.php`;
#669: `co_event.php` + `FrontPage.php` + three repository/service files). The gate came from #669's own
acceptance — "decide the seam once", naming #667 as a future consumer.

The payoff was larger than predicted: #669 built one prefetch seam serving **four** consumers, and two
of them (`EventAdminColumns::start_time_label()`, `co_event_type::event_ids()`) either did not exist or
were not visible as consumers until #667 merged. Run in parallel, the seam would have shipped with one
consumer and a third connective issue would have been needed. A gate can be justified by *design
coherence* with zero file overlap, and it is the one sanctioned way to let Foundation override a
correctness-first ordering (cost: one batch boundary, not an inverted priority).

### 4. Duplicate detection via the generated artifact

#664 and #681 shared almost no title language. What exposed the overlap was checking the *current
state of the generated contract*: `openapi.json` already published `POST /observations` as
`{event_id, title}`, so one of #664's three claims was closed-in-fact (shipped by #677, `c2d89d22`),
which collapsed the remainder into #681's exact scope. Generalizes the existing "grep the
files/symbols mentioned" rule: for issues asserting facts about a **generated** artifact, read the
artifact — the issue body is a snapshot of when it was filed, and the artifact is regenerated by
unrelated work.

### 5. Sync local main before ANALYSIS, not just before launch

**[Promotion candidate → Rule 1.]** Rule 1 covers batch launch. This session's biggest planning error
happened one step earlier. The conflict analysis identified `docs/TESTING.md` as contested between
three issues and specified an intra-batch merge ordering to manage it. **That file had already been
split into `docs/testing/` by two merged PRs that were on `origin/main` but not on the local `main` I
analysed against** — seven commits stale. The three workers were never in the same file; one ownership
boundary in the design doc was fiction, and every downstream instruction inherited it.

It surfaced only because a worker said so in its report. Nothing in the current skill would have
caught it: Rule 1's `git pull --ff-only` fires at launch, by which point the plan is written and the
tracking issue is filed. A stale checkout produces a conflict map of a repo layout that no longer
exists, and the error is invisible until a worker trips over it.

### 6. A reference grep sizes a footprint; only execution measures a leak

**[Promotion candidate → Step 5, as a boundary on the existing rule.]** For #445 I grepped
*references* to `co_migration_journal` across the integration tier, found 15 classes, and reported the
issue as understating its scope by 2×. The worker ran all 27 classes in isolation and counted
surviving rows: **6 leaked**. The 8 "needs extending" classes already cleaned up via
`reset_*_state()`; one never set `committed_mid_test` at all. The issue's own 2-class measurement was
closer to the truth than the grep-derived estimate that corrected it.

A grep is evidence about *surface*, not about *behaviour*. Where an issue reports a **measured**
number, beating it requires measuring, not counting occurrences. This cuts both ways: the same
session's other correction (#656 above) *was* grep-establishable, because it was about the existence
of a call site, not the frequency of an effect.

### Footprint grep fired in both directions again

- **#445 understated by ~2×** (15 classes referencing `co_migration_journal`, 7 with no guarded
  `tearDown` at all) — moved it from "small tail item" to the largest file count in Batch A. Later
  corrected downward again by the worker's measurement, above.
- **#656 understated** (the misattributed prerequisite).
- Both corrections were recorded in the plan and the tracking issue, so the workers inherit the
  corrected scope rather than the issue bodies'.

### Tactical confirmations

- `gh issue create --body-file` from `/tmp` with an **issue-tagged filename**
  (`/tmp/cr-followup-backlog-tracking-body.md`) — apostrophe-safe, and the tagging avoids the
  stale-cross-project-file hazard.
- Precedent (b) for ordering: opened the tracking issue first (#687), then committed with the `#687`
  prefix and used the number for the branch name (`687-cr-followup-backlog`), matching this repo's
  branch convention. Cleaner than 2026-07-23's precedent (a) when the host repo names branches by
  issue number.
- Docs-only worktree pattern (2026-06-08) held; `--shared-db` destroy correctly skipped both DB drops.
- **Rule 1 earned its keep before any agent launched.** Local `main` was 7 commits behind
  `origin/main` at merge time; the `git pull --ff-only` in the merge step caught it.
- **A stale artifact in the main checkout is a Rule 6 landmine.** Cleared an untracked 491-line copy
  of a merged test file *before* planning. Rule 6's `git status --porcelain` on every worker
  completion assumes a clean baseline; without the sweep it would have reported a dirty main checkout
  on all five completion signals. Worth folding into Step 1–2 hygiene.
- **Two workers corrected my briefs and were right both times** (a `dev.sh openapi` worktree-awareness
  "hazard" I invented; the 15-class figure). Briefs should state findings as *claims to verify*, not
  as facts — both workers were told to verify, and both did. Same finding as the 2026-08-09 observo
  execution addendum, from the orchestrator's side rather than the issue author's.
- **Conflict resolution did not need to go back to a worker.** The one merge conflict
  (`TestGlobalsIsolationTrait.php`) was docblock-only: two workers appending to the same enumerated
  list, with the executable arrays auto-merging correctly. Verified all five globals present exactly
  once before resolving as the union. The skill says conflicts return to the responsible worker; a
  docblock-list union is a reasonable documented exception.
- **Three-dot/two-dot slip.** Ran a collision check as `git diff --name-only batch/b...656-branch`
  *after* merging that branch into `batch/b`, which yields an empty diff and a false all-clear.
  Comparing worker branches for collisions requires the pre-merge base explicitly. Also produced a
  false-positive "OVERLAP" from a sloppy grep (`co_event_type` matched `co_event_types_rest.php`).
- **CR findings that fail OPEN recurred twice** and were the highest-value items in both rounds:
  Batch A's journal watermark defaulting to 0 (would wipe sibling classes' rows and mask the leak it
  exists to catch) and Batch B's process-lived static prefetch map. Neither was a red test; both were
  silently weakened assertions. Possible review-dimension prompt: "does this guard fail open or
  closed?"
- **A CR finding can itself be overstated.** Round 2 item 9 named three test classes; verifying before
  fixing showed only one actually reached a `prime()`. Fixed one, said so.

---

## Session 2026-08-11 — gregoryfoster/skills (curating-context pre-pin bundle)

Third orchestration session in this repo (after 2026-05-24, 2026-05-25). Scope arrived pre-bundled as tracking issue #134: every `curating-context` fix that wave-A/B cohort adoption surfaced, to land **before** twelve cohort repos re-pin their submodule for the cadence rollout. 15 issues → 14 work items → 3 batches. Tracking issue #135, plan `docs/plans/2026-08-11-curating-context-prepin-backlog.md`.

**Interview answers:**
- Q0 Dups: **#120 + #124 bundled into one agent, both left open.** Same defect (the dead-link check strips `#fragments`), but each carried unique specifics — #124 the `dead_anchors` output class and prose-guard carve-outs, #120 the per-file duplicate-slug numbering and archival-subtrees-as-link-sources edge cases. Closing either as a dup would have stranded its half in a closed issue.
- Q1 Quality: **Correctness ×3** → `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Third in this repo (after 2026-05-24 and 2026-05-25).
- Q2 Deploy: **early production.** Twelve repos carry committed pins and the auto-refresh hook propagates daily — but no repo has the cadence workflow installed, so the new code is inert. Propagation passive and currently harmless → wide batches, few gates.
- Q3 Defer: #117, #118, #88, #96, #97 out. **Three additions** to #134's bundle: #100 (its own argued exception), #108, #90.
- Q4a Test routing: **new per-agent test file** rather than appending to the 3,560-line monolith.
- Q4b Parallelism: **hybrid.**
- Q5 Ceiling: **none binding** — no `dev.sh`, no port pool, no DB, no vhosts. Plain `git worktree add`. (Same as 2026-07-23 `cli`.)
- Q6 Merge: regular merge commit batch→main; intra-batch fixed FF/regular. Design doc committed **directly on `main`** (no workspace-isolation hook here).

**Shape:** Batch A — 7 parallel agents (A1 #132 `_context-lib.sh`; A2 #120+#124+#123 `measure-context.sh`; A3 #119 `prove-no-loss.sh` `normalise()` only; A4 #131→#113 `check-seams.sh`; A5 #108 `verify-facts.sh`; A6 #99+#110+#109+#103 install/hook wiring; A7 #100 `skills-submodule-update.sh`), with **A6 merging before A7** on `managing-skills/SKILL.md`. Batch B — 1 agent (#111). Batch C — 2 parallel (#95, #90).

### New provenance shape: the adoption-feedback backlog

Doesn't match any existing entry in the Step 5/6 geometry list. Not CR-surfaced (one bug per surface, naturally disjoint), not spec-derived, not feature-followup. These are defects filed **by consumers of a skill while adopting it**, accumulating over weeks against *one* skill's script family.

**Geometry: the tightest clustering there is.** Fifteen issues, one skill, twelve scripts. Nearly every pair shares a file with some other pair. But it decomposes cleanly on an axis the other shapes don't have — **the owning script**. Two issues in `check-seams.sh`, two in `measure-context.sh`, two in `prove-no-loss.sh`, four in the install/hook path.

**So the natural agent unit is one agent per owning script, not one per issue.** 15 issues → 7 Batch A agents, and the parallelism came from the script family being modular, not from the issues being independent. Worth recognizing early: the instinct on a 15-issue backlog is to ask "how many can run at once?", and the answer here was set by the *skill's* internal file structure, not by the backlog's.

### A shared test file has two conflict halves — and the obvious fix solves only one

`tests/structural/test_context_surface.py`: 3,560 lines, covering every `curating-context` script, with an append-a-new-class-at-EOF convention. Six workers appending at the same line.

Routing new tests to new per-agent files (Q4a) removes the **append** half entirely. It does nothing for the **modify** half — existing assertions that each fix *invalidates*. That half is invisible to source-file overlap analysis and to reading the issue bodies, because the issues describe script changes and say nothing about tests.

**Method that found it:** grep the test file for the literal strings each fix rewrites. The payoff was immediate — `test_context_surface.py:404` hardcodes `"command": "bash .claude/hooks/context-budget-guard.sh"`, which is exactly the string #110 replaces with the `$CLAUDE_PROJECT_DIR` form, and `:371` hardcodes the `.git/context-budget.log` path #109 changes. Neither issue mentions a test.

**Then partition the modify-half by line window before assigning.** Here the five affected agents' regions turned out cleanly separated (:189–241 & :3451–3560, :517–686, :736–925, :2049–2490, :331–415). Distant hunks merge fine, so the file stayed contested without becoming a serializer. Had the windows overlapped, the answer would have been sequencing, not a new file — which is why the mapping has to happen at Step 5, not be discovered at merge time.

Generalizes the 2026-07-08 "shared test infrastructure is a soft conflict zone" finding: there it was `conftest.py` fixtures (a *semantic* shared dependency); here it's assertion text (a *textual* one), and the two need different remedies.

### A semantic dependency between two regions of the same file

#119 and #111 both live in `prove-no-loss.sh`, in different regions — #119 is a one-line regex in `normalise()`, #111 is a fourth verdict plus an ack file plus edits to `record-telemetry.sh` and `score-cohort.sh`.

Pure file-overlap analysis gives two wrong answers: *same file → bundle* (Shape A), or *different regions → parallelize*. The correct edge is neither. #111's whole job is deciding what a genuine unaccounted-for line looks like — **undecidable while #119's bug reports every link-carrying line as LOST** (172 false positives measured). So: Shape B, #119 in the parallel batch, #111 gated behind it.

**Question worth asking whenever two issues touch the same measurement tool: does one's defect corrupt the input the other's design work has to read?** Distinct from the 2026-07-19 archiver "version-freshness hard edge" (there the artifact *embedded* the other issue's output; here it *drowns* it).

### Measure a lint-gate issue's debt distribution, not just its size

#90 (add shellcheck to the structural gate) could plausibly go first — so every worker writes clean code — or last, as one sweep. Running `shellcheck` before deciding settled it: **23 findings, 0 errors**, which on size alone argues "cheap, do it first."

The *distribution* said the opposite. Seven of the 23 are the identical `A && B || C` bootstrap block copy-pasted across seven scripts — precisely the seven scripts Batch A rewrites — and eight more are `SC1091` on the same `_context-lib.sh` source line. Landing #90 first puts a mechanical sweep across seven files directly underneath the seven agents editing them. Last, it validates the bundle's final state (validator-merges-last, 2026-07-19).

**So for any "add a linter/gate" issue: run the tool, then cross-reference the offending files against the batch's file set.** Count is the wrong statistic; overlap is the right one.

### Verify the repo's real gate surface before honouring "add it to CI"

Both #90 and #95 instruct the implementer to add a check "in CI." **This repo has no `.github/workflows/` at all** — the only gate is `.pre-commit-config.yaml` running `pytest tests/structural/`, and AGENTS.md's own precedent (`TestNoBareScriptPaths`, `TestPreShipGateHardening`) is that gates ship as structural tests. Both issues were rewritten in the plan to land as structural tests.

A second constraint fell out of the same check: #95's budget gate wants `measure-context.sh --exact`, which needs `ANTHROPIC_API_KEY` — unavailable in pre-commit. The gate must use the offline estimator (`.skills/context-token-ratio` = 2.65) or run at integration tier. Recorded in Key Decisions so the worker doesn't discover it mid-implementation.

**Same class as the footprint grep, applied to infrastructure rather than to source.** An issue body's claim about *where a check goes* is as unreliable as its claim about which files it touches.

### A pre-bundled backlog is still worth re-scanning for free slots

#134 named 12 issues. Asking Q3 as "what should join?" surfaced **#108** — not in the bundle, same shape as Group A (a measurement script emitting a wrong verdict), and sole owner of `verify-facts.sh`, a file no other issue touches. A free parallel slot at zero added conflict.

The tracking issue's author was optimizing for a **narrative** (why these fixes block the re-pin), not for parallelism. Those are different groupings. **When a backlog arrives pre-bundled, scan the rest of the open backlog for same-shape issues with disjoint footprints before accepting the bundle's boundary.**

### Footprint grep — corrections in both directions again

Four, all reaching the worker prompts (cf. open issue #122, "issue bodies give reliable directions and unreliable specifics"):

- **#132 claims to be latent** ("no cohort repo sets either knob"). This repo sets both — `.skills/context-budget` = 6000, `.skills/context-doc-budget` = 10000. The issue's own repo falsified its severity claim.
- **#131's proposed fix partly exists.** `check-seams.sh:215` already filters `len(k) >= 8`; `Organizations` and `Jurisdictions` are 13 characters and pass. A worker reading only the issue would plausibly bump the threshold and ship nothing.
- **#110 reaches a third skill.** The issue names `curating-context` and `managing-skills`; the grep found `init-project-fastapi/SKILL.md:294` carrying the same cwd-relative pattern.
- **#95's blocker was already cleared and its number is stale.** Body says "should follow #94" (#94 shipped at `3fc7b71`); says 9,235 tokens, #134 says 10,197, file is now 27,996 bytes. C1 re-measures first.

### Tactical

- **Scoring calls that needed stating, not just computing.** #110 scored Correctness **1** because its own body says "it works today" — hardening, not a defect — which dropped it to 10 despite being mechanical; its *High blast* is what actually placed it. Presenting the reasoning inline made the score table's surprises (a "works today" issue at the bottom, #100 above every Group A fix) legible rather than arguable.
- **A rubric lift at the approval gate cost nothing because placement was blast-driven.** The user lifted #95's Correctness 1 → 2 ("every activation pays those tokens"). Score 10 → 13, plan unchanged. Saying so immediately — *this lift does not move the batch* — kept the gate to one round trip. Worth doing generally: when presenting a score table, note which rows' placement is blast-driven, so a rubric argument doesn't read as a plan argument.
- `gh issue create --body-file` from the scratchpad (apostrophe-safe) — confirmed again.
- Design doc committed on `main` using precedent (b): opened #135 first, then committed with the `#135` prefix. Cheap here because the tracking-issue body was already written.
- Pre-commit runs the full structural suite even on a docs-only commit; it passed in ~15s (this repo's suite is fast, unlike the `cli`/WordPress siblings).

### Execution addendum (all three batches shipped same session)

**Outcome:** 15 issues closed across 3 batches, 10 agents, **zero merge conflicts**. Suite 1340 → 1641. Six follow-up issues filed (#136–#141), five of them found *by running the shipped code*, not by reading it.

**A repo-wide harness bug surfaced on the first worker completion and would have hit all seven.** `test_context_surface.py:3200` was the only `subprocess.run` in a 3,560-line file without `env=_clean_env()`. Git exports `GIT_DIR` to hook processes: from the main checkout it is the relative `.git`, which `-C <tmpdir>` re-resolves against the temp repo *by accident* and the test passes; from a linked worktree it is absolute, so the read comes from the shared repo and fails. Every worker commits from a worktree. **Generalises: a batch's first completion signal is the cheapest place to discover an environment defect, because the remaining N−1 workers can be warned.** I fixed it on the batch branch and messaged the six still running — not for their sake but for mine: six agents independently patching the same line would have produced five merge conflicts on a one-line fix.

**Worker prompts should name who else is in each file, not just what the worker owns.** `SKILL.md`'s body was at exactly **500 of a 500-line cap** enforced by the suite. Three Batch A agents needed to edit three different phases of it. Each was told the other two were in flight, each independently discovered the ceiling, each paid for its own addition by tightening its own prose, and each reported "one line of headroom left for the others." Final: 499. No orchestrator intervention. A fence that says only "you own Phase 6" produces three agents each convinced the last line is theirs.

**Escalations from workers are evidence, not findings — check them.** Two of the three escalations that claimed a defect were wrong or already decided:
- B1 reported `--seams 0` records `null`, contradicting the field's contract. It doesn't: the value arrives from argv as the *string* `"0"`, which is truthy, so `int("0")` → 0. B1 reasoned about `if seams` as though it held an int. **No issue filed.**
- B1 asked the orchestrator to decide the version bump; the plan's Key Decision 8 had already assigned it to C1.
- C1's and C2's four escalations were all real and were verified (three by reading the named line, one by reproduction) before filing.

**Verify each merge against a live run, not the completion report.** Every claim in this session was checked by executing the code against a fixture and diffing behaviour with `main`: `main`'s `check-seams` reports `seams: 0` on a genuinely stale shipped docstring where the new one finds it; `main`'s `doctor.sh` exits 0 silently on a dangling hook symlink where the new one exits 1. Two CR findings came out of that discipline and one — a check that could never report success — was found by *running the thing the batch had just normalized*.

**Sequencing a lint gate last paid off on the one file nobody touched.** #90 ran after Batches A and B and found a bug in `install-cadence.sh` that had shipped through #118, a five-round CR and the full suite: `set -- $CRON` splits **and globs**, so in any directory with visible files every valid cron expression was refused — with an error message suggesting the exact expression it had just rejected. It survived because the three tests passing `--cron` run in a freshly-`init`'d tmp repo whose only entry is `.git`: nothing for `*` to match. **A fixture too clean to fail is a fixture that tests nothing**, and a linter is one of the few things that finds it.

**A gate the agent wrote needs its own non-vacuity check.** Both of C2's new gates were tested by breaking them — injecting a real `SC2086`, and stripping the reason above a suppression. The second passed at first, which looked like a hole; it turned out the reason was a *two-line* comment and removing one line correctly still counted. Removing both fails it. Worth doing every time: a gate that cannot fail is indistinguishable from a gate that passes.

**Letting a worker stop at an honest number beat forcing the target.** C1 could not reach #95's 6,000 without deleting procedure, and its brief licensed it to stop and report. It set the ratchet at **7,600** where the file honestly sits (10,902 → 7,574 by relocation only), invoked the skill's own Phase 4 clause that *"an irreducible file is a real finding"*, and made the number bite by pairing it with a +250-per-round edit budget and a test that fails if `SKILL.md` stops naming the 6,000 gap. A gate set at an unreachable threshold gets disabled; one set where the file already sits is theatre.

**GitHub closes only the first issue in a bare `Closes #a #b #c` list.** The Batch A merge closed #132 and left twelve open. Each keyword needs its own (`Closes #a. Closes #b.`) — the Batch C merge did that and closed both. Worth checking issue state after any multi-issue merge rather than assuming.

---

## Session 2026-08-11 — CannObserv/usa-wa (post-#179b followup backlog)

Second orchestration session in `usa-wa` (after 2026-06-16, 2026-08-07). Seven followup issues carved
out of the just-merged #189 / #183 / #185 / #179b shipping cycle (batches A–F, through `aa06590`):
#160, #195, #196, #198, #201, #202, #205. Tracking issue `#207`; plan
`docs/plans/2026-08-11-post-179b-followup-backlog.md`. (Source: upstream issue #129.)

**Interview answers:**
- Q0 Dups: none. #195 and #196 both live in `usa-wa-adapter-legislature` — surfaced as a candidate
  pair on package overlap, then cleared by grep (tests/ vs src/, and `refresh.py` imports
  `meetings.windows`, not `meetings.harvest`). **Package co-location is worth checking and is not, by
  itself, a duplicate signal.**
- Q1 Quality: **correctness-leading (×3)**. `(Foundation × 2) + (Correctness × 3) + Scope`, max 18.
- Q2 Deploy: **early production** (live systemd timers producing to PM, low volume, no external
  consumers).
- Q3 Defer: none — all seven in scope.
- Q4 Parallelism: **hybrid**; worktrees yes.
- Q5 Ceiling: **3**, re-confirmed from 2026-06-16. Plain `git worktree`; the limiting resource is the
  single shared `TEST_DATABASE_URL` Postgres (5th recurrence of the shared-backing-service ceiling).
- Q6 Merge: batch→main via `gh pr create` + merge commit (repo precedent); intra-batch fixed
  `--no-ff`.

**Shape:** 7 issues → **7 agents across 5 batches.** A (3 parallel, `batch/g`): #205, #196, #160.
B: #195. C: #201. D: #198. E: #202. Four of the five gates are forced by distinct causes, not by style.

### New pattern — a shared-fixture *escape* is a hard conflict zone, not a soft one

**[Promotion candidate → Step 5.]** The 2026-07-08 session established that shared **test
infrastructure** (`conftest.py`, session fixtures) is a *soft* conflict zone: zero source overlap,
still sequence it late. This session found the hard version.

`clearinghouse_core.testing.reset_migration_schemas` does `DROP TABLE public.alembic_version` +
`DROP SCHEMA "<each>" CASCADE`, and — per its own docstring — **opens its own engine, deliberately
bypassing the savepointed `db_session` fixture**. So it is not isolated by transaction rollback. Any
worker running it destroys every other worktree's in-flight db-marked test, mid-run.

That is a different severity class from fixture contention. Contention degrades; this one corrupts
other agents' results, and the failure presents as an unrelated worker's mysterious red. It forced
#195 — a Low-blast, single-file, three-line test fix — into a **solo batch**, purely on a database
property with no file-overlap footprint at all.

**Generalization:** when a project's ceiling is gated by a shared backing service, don't stop at
counting the ceiling. Grep for the helpers that *escape* the isolation fixture. Each one is a
serialization edge that no amount of file-disjointness relaxes:

```bash
grep -rnE 'DROP (SCHEMA|DATABASE)|TRUNCATE|create_async_engine|create_engine' \
  --include='*.py' packages/*/tests packages/*/src/*/testing.py
```

### New disposition — rescope-to-residual, from a partially-shipped issue

**[Promotion candidate → Step 1–2 / Q0.]** The closed-in-fact grep caught **#160** as neither open nor
closed. Its headline work had shipped at `db05912` (`ConditionalGetState` + migration,
`fetch_record_conditional` / `get_entity_conditional` / `EntityFetch`, the `If-None-Match` load/store
at `engine/read.py:494-526`, a kill switch, tests) — but a third comment on the issue named further
work, and the replay-backstop path (`_apply_feed_page` → `descriptor.fetch_record`,
`engine/read.py:686`) was genuinely still unconditional.

Neither standard disposition fits. Closing discards real work; batching it whole allocates a slot to
merged code and hands a worker a stale spec. Surfaced it as **Q0** with three options and the user
chose **rescope**: rewrite the issue body down to the verified residual, re-score it as a small item
(it fell from a would-be foundation item to 7/18), then batch normally.

This is the 2026-06-16 validity-re-analysis gate's `rescope` verdict arriving by a different route —
there, a *just-merged change* invalidated the issue; here, the issue's *own* partial delivery did.
Worth naming as a fourth disposition beside keep / close-as-done / defer. **The signal to look for:**
an issue whose body reads as fully open but whose comment thread names follow-on scope — grep the
body's deliverables *and* each comment's, separately.

### Measure the structure before scoping a curation issue

**[Log-only until it recurs.]** #202 asks to bring `docs/MODULES-SYNC.md` under budget, and both the
issue and the `curating-context` skill assume the remedy is "split on top-level headings." The file
has **exactly one heading**; the body is a single ~23 KB indented code-block tree. There is nothing to
split on. The real seam turned out to be the *tree's* top-level entries, which makes the work a
structural re-cut rather than a prose compression — a materially different task, and one a worker
handed only the issue text would have discovered halfway through. `grep -nE '^#{1,4} '` on every doc a
curation issue names, during Step 5, costs nothing and reframed this one.

### Blast ≠ priority, twice in one backlog

- **#198 (12/18, third-highest) → Batch D.** It mutates `[tool.pytest.ini_options] addopts` and the
  coverage profile — the ground every other worker's TDD stands on. Straight application of the
  2026-07-08 soft-conflict rule.
- **#202 (9/18) → Batch E, last.** Not blast radius but **epistemics**: it is a *measurement* pass.
  Running it before #198 and #201 land their doc edits measures a state that will not exist at merge
  time. New framing worth keeping — "this issue's deliverable is an assessment of the final state" is
  its own sequencing argument, distinct from file contention.

### Provenance prediction held (6th followup recurrence)

Followup-derived, across-the-stack — like 2026-06-28 and 2026-07-23, unlike the one-partial cluster of
2026-05-11. Seven issues, seven layers: framework tests (#205), adapter tests (#195), adapter src
(#196), facts + deploy (#201), test config (#198), docs (#202), sync engine (#160). Near-fully
disjoint. Steps 5/6 compressed accordingly — and the compression was still worth running, because the
two findings that shaped the plan (the schema-drop escape, the headingless doc) came out of the
confirming greps, not out of the file-overlap table. Footprint grep found no under- or overstatement
this round.

### Tactical confirmations

- `gh issue create --body-file` from `/tmp` — apostrophe-safe, again. Precedent (b): opened `#207`
  first, then committed the plan with the `#207` prefix. `git commit -F -` for the plan commit;
  committed directly on `main` (skill default — usa-wa has no workspace-isolation hook).
- **The context-budget "hook" is advisory, not a gate.** `.claude/hooks/context-budget-guard.sh` is a
  *PostToolUse* hook that always exits 0 by design (a trap converts any internal failure into a clean
  exit). Issue comments describing it as something that "flags on any branch that touches the file"
  read like a blocker; it is not one. The pre-commit gate is ruff + `lint-imports` +
  `verify-units.sh`. Read the hook before treating a budget overrun as a hard dependency — it
  downgraded a three-way doc collision to a coordination note here.
- **`.claude/skills/orchestrating-issue-backlog/` in usa-wa is an untracked local duplicate** — a real
  directory, byte-identical to the vendored copy, invisible to git and lost on refresh. The canonical
  file is the submodule's, reached via the `skills/` symlink. Same trap as the 2026-07-23 `cli` note,
  different shape: there the `.claude` path was a symlink *into* the submodule; here it is a stale
  copy *beside* it. Verify with `git ls-files` before editing either.

---

## Session 2026-08-11 — CannObserv/observo (test-isolation + ConsumerConfig backlog)

Second orchestration session in `observo` (after 2026-08-09's #434 provider/contracts backlog). Seven
issues: three test-isolation followups from the #434 shipping cycle (#437, #438, #439), two
`ConsumerConfig` carve-outs from #428 (#435, #436), one pre-existing architectural split (#421), one
#426 followup (#441). Tracking issue `#444`. (Source: upstream issue #130.)

**Interview answers:**
- Q0 Dups: none. #437/#438/#439 are the same *family* (xdist distribution exposing latent isolation
  defects) but the issues explicitly cross-reference and disclaim each other; #435/#436 share files but
  are a Step 7 shape question.
- Q1 Quality: **correctness ×3** (`Correctness×3 + Foundation×2 + Scope`, max 18). **Notable
  inversion** — the *same repo* ran Foundation×3 on 2026-08-09 for #434. The weight tracks the
  backlog's character, not the project's.
- Q2 Deploy: **pre-production** (carried; matches #434).
- Q3 Defer: none — all 7 in scope.
- Q4 Parallelism: **hybrid**; worktrees yes.
- Q5 Ceiling: **3**, carried forward from #434 and re-verified cheaply (`observo_a1/a2/a3_test` still
  present via one `psql -l`). Shared-test-DB ceiling, **6th recurrence** — and the cheapest
  re-verification of one yet, because the 2026-08-09 session left the slots provisioned.
- Q6 Merge: `--no-ff` regular merge commits; intra-batch fixed FF/regular.

**Shape:** 7 issues → **7 agents across 3 batches**, 3 / 3 / 1. Every contested-file ordering resolved
by a batch boundary — zero intra-batch merge ordering required.

### New pattern — mid-orchestration issue surgery at the scoring gate

**[Promotion candidate → Step 4; see also 2026-08-09 Lesson 5.]** The two lowest-Scope-Clarity issues
each carried an *undecided question the issue itself flagged as blocking*: #421 ("is operator-gating
intended or an oversight? if intended this is a UI/docs fix, not code") and #436 ("there is an
ordering question that must be answered before the change, not during it"). Both scored Scope = 1.

Rather than let a worker decide (product call) or defer (user wanted all 7), the decisions were
surfaced **as part of the scored-backlog approval gate** and answered by the user in the same turn.
That triggered three GitHub writes *before* batch design:

1. **`gh issue edit 421 --body-file`** — trimmed the body to option A, replacing "Decision needed
   first" with "Decision — resolved <date>", preserving the rejected option's rationale as a pointer.
2. **`gh issue create`** → **#443** for the descoped option B, marked blocked on the out-of-scope #71,
   with an explicit "relationship to #421" section defining how the two mechanisms avoid racing.
3. **`gh issue comment 436`** — recorded the option-1 choice *with the rejection rationale for option
   2* (it would have invalidated a retention rule in a third issue, #367).

**Why this matters:** the decisions changed the inputs to scoring, and the plan would have been wrong
without re-running them. #421 went Scope 1 → 3 and blast Med → Low (three routers left with #443),
moving it from 14 to **16 — top of the table**. #436 went Scope 1 → 2 and blast Med-High → **High**.
Deciding *then* rescoring, rather than scoring around the ambiguity, is the generalizable move.
Distinct from Q0 dup-resolution (which runs *before* scoring); this runs *at* the scoring gate because
you cannot tell which issues need it until you have scored them.

### New pattern — sizing an unbounded sweep, then licensing parallelism with it

**[Promotion candidate → Step 5.]** #438's body said the caplog defect was "worth a sweep." Step 5's
footprint grep turned that into **17 test files / ~64 `caplog.records` sites, none filtered by logger
name** — including a confirmed live instance of the exact failure mode
(`tests/app/test_segment_archiver.py:1128`).

The sweep list then did double duty. Cross-checked against the *other two Batch B agents'* test
footprints (#421's one test file, #435's five) it showed **zero overlap** — which is what licensed
running Batch B at the full ceiling of 3. Had any of #435's five appeared in the sweep, #438 would
have needed its own gated batch.

Generalizable: **an issue whose footprint is a "sweep" or "audit" is not automatically high-blast and
not automatically batch-isolating.** Enumerate the sweep set, then intersect it with co-batch agents'
footprints. The enumeration is cheap (one `grep -rl` + a per-file counter loop) and converts a vague
scoping worry into a parallelism decision. Mirror image of 2026-07-08, where zero *source*-file
overlap still forced isolation because of shared test *infrastructure* — here, a large shared-test-file
surface turned out to be safe once enumerated.

### Blast ≠ priority, third variant: the top-scored issue lands in batch 2

**[Promotion candidate → Key Principles.]** Prior entries cover "high-blast issue waits" (2026-03-23
onward) and "issue whose blast intersects multiple parallel agents gets isolated" (2026-06-29). New
variant: **#421 scored highest (16) and was clean of every contested file, which is exactly why it
went to Batch B.** Batch A's three slots were claimed by the issues that had to land *first* to satisfy
ordering (#437 and #439 each own files #438 later sweeps; #439 owns `transcribe_base.py` before #435
refactors it). A contested-file-free issue is the most *schedulable* thing in a backlog, so it fills
whichever slot would otherwise idle — it does not earn batch A by score. Compactly: **score determines
what gets done, ordering constraints determine when; a zero-conflict issue is a slot-filler, not a
batch-A claimant.**

### Also captured

- **Two-direction footprint grep paid off both ways in one backlog** (cf. 2026-06-28, which had both
  but in separate issues): #438 understated (sweep 17× larger than implied), #421 overstated-by-decision
  (three routers descoped mid-session).
- **Partial-fix detection, 2 of 7.** #438 part 1 and #439's `private_tempdir` workaround had both
  already landed during #434's batches — the issues' own bodies said so, but only the grep confirmed
  the fixes were on `main` rather than still on a batch branch.
- **A "recommended fix" in an issue body underestimated its own scope.** #439 proposes routing the
  concat temp to "the consumer's per-job `scratch_dir`." Grep: **no `scratch_dir` exists anywhere in
  `worker/transcription/`**. Held Scope at 2 instead of 3. Issue-body phrases of the form "X already
  has Y; just use it" are worth one grep each.
- **Verification-mode asymmetry inside a batch is worth calling out in the design doc.** #437 changes
  `pyproject.toml` `addopts` to `--dist loadfile`; its two co-batch agents verify under the *old* mode
  in their own worktrees. The orchestrator's post-merge run on `batch/a` is the first run under the new
  mode and the real gate — so a failure there is plausibly a distribution-mode interaction rather than
  any one agent's defect. Documented so the orchestrator does not misattribute it.
- **Foundation-shared-file read-only rule applied to a config file**, not a source/test-harness file:
  `pyproject.toml` `addopts` declared read-only for Batches B and C once #437 sets it. Extends the
  2026-06-08 rule's scope — the governing property is "one file every agent's verification depends
  on," regardless of file kind.
- `gh issue create/edit/comment --body-file` from the scratchpad throughout. Precedent (b): tracking
  issue #444 opened first, then committed `#444 docs: …` with the prefix.
- `observo`'s pre-commit hook did **not** run the full suite on a docs-only commit — unlike `cli`,
  where the 2026-07-23 entry warns to budget ~2 min. Per-project; do not generalize the timeout advice.

---

## Session 2026-08-12 — gregoryfoster/skills (gate-correctness + cohort-adoption backlog)

Second orchestration session in this repo in two days (after 2026-08-11's `curating-context` pre-pin
bundle, #135). The user named a **subset** — "GH 105, 107, 115, 117, 136–143" — rather than "the
backlog", which turned out to matter: one issue's blocker sat outside the named set. Twelve issues,
eight agents, two batches. Tracking issue `#144`.

**Provenance was mixed, and the mix produced disjointness.** #136–#141 are followup-derived from
#135's Batch C but decompose on the *owning script* axis; #142/#143 are CR-surfaced from #112;
#105/#107/#115 are adoption-feedback from cohort repos. The originating cycle spread defects
one-per-layer, so the followup provenance produced the CR-like shape (cf. 2026-06-28) rather than a
single-file critical path.

**Interview answers:**
- **Q0**: two bundles and two dispositions, all four resolved before scoring. #107+#115 → Shape A
  (#115 splits the Code Exploration Policy template, #107 adds a *degraded variant* of the thing #115
  just split — done independently the second agent overwrites the first). #136+#137+#139 → Shape A
  (all in `prove-no-loss.sh`; #136 and #137 both edit `normalise()`). #141's stated "#136 blocks it"
  → honored. #117 → **deferred**.
- **Q1 Quality: correctness ×3** (`Foundation×2 + Correctness×3 + Scope`, max 18). Nine of eleven work
  items are *gates that judge other work*; the failure mode is not "a bug ships" but "the gate that
  would have caught it is distrusted and bypassed."
- **Q2 Deployment: active production** — eleven cohort repos vendor these skills via `skills-vendor`
  auto-refresh.
- **Q3 Deferrals**: none beyond #117.
- **Q4 Parallelism**: hybrid.
- **Q5 Ceiling: 4, from host CPU/RAM — and *nothing else*.** See below.

**Batch shape:** A1 (PNL #136+#137+#139, SOCRATI #107+#115, RA #142, SHELL #140) → A2 (SEAMS #138,
SHIP #105, LINKS #143, merging last) → B (BUDGET #141, solo). Both sub-waves merge into one
`batch/a`; regular merge commit to `main`.

### The ceiling was genuinely absent — the first such session in seven

Q5's text says six sessions across three projects found the real ceiling in sub-question 2 (a shared
backing service), not sub-question 1. This is the seventh, and it found **neither**:
`worktree-create.sh` is plain `git worktree` with no port pool or DB clone, and the structural suite
is hermetic (per-test `tmp_path` git repos, `ANTHROPIC_API_KEY` stripped). Verified with one grep —
no match for `docker|POSTGRES|DATABASE_URL|PORT_POOL` under `scripts/` or `tests/`.

Worth recording as a **negative result**, because the accumulated weight of six positives makes it
tempting to keep hunting until a ceiling is found. The check stays cheap and sometimes correctly
returns "none — cap on host resources." The ceiling still bound: 7 disjoint agents against 4 slots
forced the sub-wave chunking.

### Line-window ownership generalized from a test file to a policy file

2026-08-11 (this repo) established mapping owned line-windows inside one large shared test file. The
same technique carried `AGENTS.md` — a 257-line policy file three Batch A agents needed to edit:
SHELL owns `:116–119` (the shellcheck bullet), SHIP owns `:134` (the pre-ship bullet), LINKS owns
`~:170–175` (the structural-rules list). Separated windows, so three concurrent writers merge cleanly
and the file never became a serialization point.

The governing property is the same as the read-only-foundation rule's: it is about *whether the
windows overlap*, not about what kind of file it is. Promoted as a clause in Step 5 item 2. The one
addition a policy file needs that a test file does not: **"no restructuring, additions within the
window only"** — a reorder produces a clean-merging diff that silently reshuffles another agent's
window.

`test_context_surface.py` (3,636 lines) split the same way — PNL 736–1443, SEAMS 2029–2502 — with one
genuinely shared point declared read-only for both: a `parametrize` list at `:2509–2514` naming
*both* `prove-no-loss.sh` and `check-seams.sh`. Neither issue changes an invocation path, so neither
agent has cause to touch it. Naming the shared line is cheaper than sequencing around it.

### An issue body's own hedge is a Step 5 grep target — and the orchestrator's grep needs auditing too

#143 proposed a discriminator (check only `./`- and `../`-prefixed link targets) and closed with
*"Worth confirming before committing to it."* Confirming it took one sweep, which reported a fifth,
relative-prefixed carve-out at `curating-context/SKILL.md:250` — `](../tests/x.py)`, apparently the
exact string the discriminator was built to catch. Scope Clarity was cut 3 → 2, the finding was
written into the design doc, and it was commented onto the issue as a correction.

**It was wrong, and the implementing agent (LINKS) refuted it.** That string is not a markdown link:
it is a bare `](…)` fragment inside an inline code span, with no `[label]`, in prose quoting a link's
*form*. Any extractor requiring the real `[label](target)` grammar never sees it. The planning sweep
used a loose `\]\((\.{1,2}/[^)\s]+)\)` that matched fragments. Verified after the fact: the loose
regex returns `['../tests/x.py']` on that line; a `[label]`-requiring regex returns nothing.

The agent's own survey found **8 dead links across 5 files, none relative-prefixed** — so the issue's
discriminator would in fact have cleared the current tree. It was still the wrong shape, for a reason
neither the issue nor the orchestrator identified: **all 8 sit inside a code fence or an inline code
span**. The real distinction is the *context a link sits in*, not its target string; a target-string
rule passes today and breaks the first time someone writes a fenced example with a `../` prefix. The
agent shipped fence + code-span masking with an exemption registry that ships **empty**, and closed
the loop by finding the identical defect in `measure-context.sh:533` — which is why that script
reports four phantom dead links for this file, the source of the batch's "4 dead links, up from 2"
observation.

Two rules, and the second is the one that cost something:

1. When an issue body **flags its own claim as unverified** — "worth confirming", "I think",
   "assuming" — that sentence is a grep target. The author located the risk and didn't spend the
   minute. Distinct from the bidirectional footprint grep, which hunts claims stated *confidently*.
2. **Audit the instrument before publishing the correction.** An orchestrator's throwaway regex is
   exactly as falsifiable as the issue body it audits, and more dangerous, because it arrives
   labelled as a correction — it re-scored an issue, altered a design doc, and was commented onto
   GitHub before anyone checked it. Match the artifact's real grammar (markdown links need
   `[label](target)`; code spans and fences are not prose), and state the instrument alongside the
   finding so the next reader can falsify it. Retracting took three file edits and a follow-up
   comment; the check would have taken thirty seconds.

### A decision at the scoring gate can remove a dependency edge, not just clarify scope

2026-08-11 (observo) established mid-orchestration issue surgery — trimming an issue and descoping the
remainder to a new issue. This session found the adjacent move: **descope to decouple.** #141's body
flagged that a per-skill gate asserting `links.dead == []` would trip on seven pre-existing false dead
links — the same illustrative-placeholder class that had just broken #143's discriminator. Deciding
that **#141 simply does not assert on dead links** did three things at once: raised its Scope Clarity
1 → 3, removed a would-be ordering constraint against #143 entirely, and prevented two incompatible
placeholder-exemption mechanisms landing in one batch.

The general form: when two issues are converging on the same unsolved sub-problem, deleting it from
one of them is often cheaper than sequencing them.

### Blast radius came from a test assertion on *prose*, not from any issue body

#141 reads as a mid-sized parameterization job — its own body says "the mechanical work of extending
it to all ~20 skills is small," and the gate does parameterize cleanly on `(skill_dir, ratchet)`. What
makes it High-blast is four lines away:

```python
# test_skill_self_budget.py:164
assert f"{SKILL_MD_RATCHET:,}-token ratchet" in SKILL_MD.read_text()
```

Each skill must **name its own ratchet in prose**. Generalized, that edits all 18 `SKILL.md` files and
intersects *every other agent in the backlog*. It forced the 2026-06-29 isolate-in-its-own-batch rule
on an issue whose score (13) would otherwise have seated it mid-table.

Extends 2026-08-11's semantic-dependency finding: the coupling was not a shared symbol or a shared
fixture but an **assertion about documentation content**. Reading the test that a "small
parameterization" generalizes is worth the minute — the assertions describe the real contract, and
some of them are about prose.

### A blocked residual defers rather than rescopes

2026-08-11 (usa-wa) added rescope-to-residual as a fourth disposition. #117 is that shape — proposal 4
shipped in #125 (`689b21e`), proposals 1–3 open — but the residual is itself blocked, on #118 settling
the arm-label question, and **#118 was not in the named set**. So the fourth disposition has a branch:
rescope when the residual is schedulable, **defer when the residual's blocker is out of scope**. Any
slot allocated to it would have been dead work.

This only arises because the user named a subset. When the ask is "the backlog", a blocker is almost
always inside it; when the ask enumerates issue numbers, check each survivor's blockers against the
named set specifically.

### The instrument defect recurred twice more, in a code review of the same batch

The retraction above was not a one-off. Reviewing `batch/a` produced two more findings of the
identical shape, which makes it a pattern rather than an accident:

- **Two replacement test assertions checked for the words `set -f` and `xargs`** to prove the old
  unsafe recipe was gone. Both failed immediately: the words survive in the *prose explaining their
  removal*. The fix was to assert on the construct (`export $(`, a line whose command is `set -f`)
  rather than on the vocabulary. Caught by running the suite — the system working.
- **A finding claimed the stub `shipping-work` variant defined `load_env()` but never called it.**
  It did call it, two lines below, in the same block. The claim was reasoned from a true premise
  (the stub has no delegate to `exec`) instead of read off the file, and the "fix" duplicated the
  call sites. Caught only because the duplicate was visible in the verification grep.

Three instances in one session — a link sweep, two test assertions, a code-review finding. The
common shape: **a claim about an artifact, derived from a model of the artifact rather than from the
artifact.** The link regex modelled markdown as `](…)`; the assertions modelled a comment block as
code; the finding modelled the stub from its architecture. Each was confidently phrased and each
arrived as a correction to someone else's work, which is what made them expensive — a wrong finding
costs the retraction *plus* whatever the recipient changed on its authority.

Operationally the rule is narrow and cheap: **before publishing a claim that something is absent,
grep for it.** Absence claims are the dangerous half — a false *presence* claim dies the moment
someone opens the file, but a false absence claim looks like diligence. All three here were absence
claims ("no `[label]`-less fragment is a non-link", "the word is gone", "the call is missing").

### Also captured

- **Twelve closed-in-fact greps, twelve live issues** — the first session in a while where the sweep
  found nothing already-shipped. It still paid: two of the twelve greps turned up *other* corrections
  (#143's discriminator, #141's real blast radius). The grep's yield is not only the closed-in-fact
  verdict.
- **Verification-mode asymmetry, 2nd recurrence** (after 2026-08-11 observo's `--dist loadfile`). Here
  *two* agents add gates — #140's shellcheck version floor and #143's link gate — that exist in no
  sibling's worktree. Every agent self-verifies under the old gate set, so the orchestrator's
  `batch/a` run is the first execution of the combined tree under the new ones. Recorded in Key
  Decisions with the explicit warning not to attribute a failure there to the last-merged agent.
- **Scope changes written back to three issues before any agent existed** (#143 the disproven
  discriminator, #141 the two settled decisions, #117 the deferral and its unblocking path), each
  preserving the rejected option's rationale rather than deleting it. Continues 2026-08-09 / 2026-08-11.
- **No chain-appending artifact in the whole backlog** — no migrations, no numbered ADRs. Worth
  checking for and recording the negative, so the design doc says so rather than leaving a reader to
  wonder whether it was considered.
- Precedent (b) again: tracking issue `#144` opened first, then committed `#144 docs: …` with the prefix.
- `gh issue comment --body-file` from `/tmp` throughout; the #117 comment contains apostrophes and
  backticks that would have broken a heredoc form.

---

## Session 2026-08-13

**Project:** CannObserv/cannobserv (shared Python library, uv workspace). User-named subset: #278, #295, #296, #297. Tracking issue #329; plan `docs/plans/2026-08-13-co-v1-oracle-followups-backlog.md`.

**Interview:** Correctness ×3 (2nd Correctness-leading weight, after 2026-05-24); early production; #278 deferred at Q3 by the project's standing async-parity policy; hybrid parallelism; ceiling 3 (generic worktree scripts, no host provisioning — never bound).

**Batch shape:** two sequential single-agent batches. Batch A = Shape-A bundle: foundation re-pin commit → #296 (retire waivers) → #297 (collapse walker). Batch B = #295 (task-performers read + two model extensions), gated on A's PR merge. PR + regular merge per repo precedent; no `batch/<X>` branches.

### Upstream-blocked backlog: the sibling repo's blocker states are the first grep

New provenance flavor: three of four issues were filed as **blocked on another repo's issues** (wp#663/664/666), each opening with "actionable the moment that ships and the pin refreshes." The orchestration-triggering fact was not local — all three upstream issues closed within a 5-day window (verified via `gh issue view --repo` before the interview), and the local contract pin predated every fix. For this shape, check blocker states **before** scoring: they decide which issues are actionable at all, and the closure dates tell you the shared vendored artifact (here `openapi.pinned.json`) is stale — which surfaces the foundation step.

### A shared first step that is not an issue

All three issues' step 1 was the same script run (`sync_openapi.py --write`). Modeled as **commit 1 of the Batch A bundle**, verifying all three upstream expectations at once (including Batch B's — the params check), then declared read-only for Batch B. Running it per-issue would have produced provenance churn and cross-batch conflicts on the pin. Generalization of the foundation-shared-file read-only rule (2026-06-08) to a foundation *artifact refresh*.

### Same-function overlap is the sharpest Shape-A signal yet

#296 (waiver filter) and #297 (walker call) edit **adjacent lines in one function** (`test_write_bodies.py:22-23`) — beyond same-file into same-lines. Combined with the issues' own "sequence together" notes and the retire-then-collapse define→use order (emptying the dict first moots #297's waiver-rekeying step), bundling was overdetermined. Continues the 2026-08-10 hard-bundle-signal thread (generated artifact + sync test).

### A clarifying "Other" answer flipped a decision and exposed a latent data drop

The #295 issue body framed decision 2 as "observation has no such field on either backend" — add speculatively or leave out. I recommended leave-out (early production, no speculative model changes). The user answered with a *question*: "Legacy production Observations include a task/performer list — is that the same thing?" Greps confirmed it is: production observation posts carry the ACF `co_roles` repeater, the wp/v2 event/event_type adapters map it, and the **observation adapter silently drops it on read**. The issue body's claim was true of the *model* but misleading about the *data*. Decision flipped to add-on-both-backends, and the "speculative" change turned out to fix a real read-time loss. Lessons: (1) an "Other" answer phrased as domain knowledge is a grep target, not a preference to be slotted into the offered options — verify before locking; (2) a "no such field" claim in an issue body describes the code, not necessarily the upstream data; the recommended option was wrong because the option framing inherited that gap.

### Also captured

- Hybrid preference **degenerated to fully sequential** — every issue pairing shared a file (`_manifest.py` adjacent sections, `test_write_bodies.py` same lines, CHANGELOG, the pin). Small-N backlogs from a single followup cycle may have no file-safe parallelism at all; say so plainly rather than manufacturing a parallel batch.
- Policy-deferral of a **user-named** issue: #278 was in the named set but AGENTS.md's async-parity policy says defer; Q3 confirmed the policy holds. Naming an issue in the subset is not an override of a standing policy — ask.
- Planning-time resolution of both flagged build-time decisions (label column → carry both; observation roles → both backends) moved MINOR public-model calls from worker discretion to the design doc's Key Decisions — right call under this repo's API-stability tracking rule.
- Precedent (a): plan committed without prefix, then #329 opened.
- `gh issue create --body-file` from the scratchpad; body contained backticks throughout.

### Post-gate addendum (same day): a nomenclature decision reopened after approval

After the plan shipped, the user reopened #295's naming: the `roles` model field predates the
project's Roles CPT and now collides with the real Role entity — replace with Task/Performer
nomenclature (`task_performers` field, `get_task_performers` facade, `task_label`+`performer_label`
columns), justified by "there are no downstream consumers so we can do this right." The audit
**half-confirmed** that claim: the *new* surfaces had none, but the *existing* `EventModel.roles` /
`EventTypeModel.roles` had production consumers in the adjacent `cli` checkout (cancellation
stripping, event-add seeding, an export command, direct `TaskPerformerModel(task=...)` construction).
Lessons: (1) a user's no-consumers assertion spans whatever *they* mean by the surface — grep the
adjacent downstream checkouts before accepting it for the surfaces the rename actually touches, and
surface the split (new-surface-free vs existing-field-consumed) so the breaking half is a deliberate
choice; (2) post-gate decision changes flow through the same write-back circuit as mid-orchestration
surgery (2026-08-11 observo): plan Key Decisions + issue comment + tracking-issue body, before any
agent exists. The user chose the full rename with a cli adoption issue at ship time (adopt-a-release
covers it); the plan gained Key Decision 9.

---

## Session 2026-08-13 — gregoryfoster/skills (#144 execution addendum)

Execution record for the backlog planned in the 2026-08-12 entry. Eleven issues, nine agents
(eight in Batch A across two sub-waves, one in Batch B), two CR rounds. All merged; `main` at
`d08d0a0`, suite 1644 → 2004.

### The report-back slot is the highest-yield instruction in the worker prompt

**Nine of ten Batch A issue bodies carried a material error**, and every one surfaced because the
prompt demanded corrections and said *"I want the corrections, not a report that matches the
prediction."* The phrasing matters: an agent told a generic "verify your assumptions" reliably
produces a report shaped like agreement.

What it caught, by kind:

- **A false premise** — #115's "`init-socraticode` already writes to `docs/`" (it does not;
  `init-project-fastapi` writes `docs/SKILLS.md`). Its whole "the destination is not new
  machinery" argument collapsed.
- **A fix not implementable where the issue said** — #136's "skip frontmatter in `normalise()`";
  `normalise()` is per-line and frontmatter is document-level.
- **A wrong failure mode** — #140 predicted spurious `SC1091`; an old shellcheck actually rejects
  the whole invocation and lints *nothing*.
- **A right line number on the wrong concept** — #142's `:122` is a verification bullet, not the
  format template. Implementing it literally would have shipped a half-fix.
- **A suggested fix that measurement showed insufficient** — #138's basename derivation, which the
  agent *implemented and measured* at 314 → 97 with 95 residual before rejecting it.

The last one is the shape to ask for: not "the issue is wrong" but "I did what it said and here is
the number." Cheap to demand, and unarguable.

### Two defects existed only in execution, not in reading

#105's ported recipe passed a 12-test suite that asserted its *text*. Running it found that
`export $(cat … | xargs)` dumps the entire environment (73 `declare -x` lines, secrets included)
when both files are absent, and dies with `'#': not a valid identifier` on any `.env` carrying a
comment — killing the wrapper before `exec`, so the gate never runs. Both had been shipped advice.

**Rule: when a skill ships executable content as documentation — a recipe in a comment, a template
in a fence — the gate must execute it, not match it.** The follow-up added 24 execution tests that
lift the recipe out of the comment block and run it, and they were proven red against the prior
implementation rather than assumed to work.

A corollary found the same day: proving redness requires the *actual* prior implementation. Deleting
one line of the new parser did **not** turn the tests red, because the identifier check catches
comments as a second line of defence. Defence-in-depth is good design and a bad regression proof.

### A merged fix can be structurally incomplete in a way its own tests confirm

#137 shipped, green, with new tests. It was then found to be inoperative for the case that motivated
it: the erasable prefix was built from the repo-relative `--docs-dir`, so it could never match a
skill's own `](references/X.md)` links. It worked only for the cohort's canonical shape.

It surfaced because a *later agent pointed a real run at it* — the trim agent's demotions produced
3 LOST, exactly the case #137 exists to fix, and it reported that instead of papering over it with
warrants (which is what the prompt told it to do). **Where a batch fixes a gate, schedule something
that exercises the gate afterwards**; an agent's own tests verify the code it wrote, not the
behaviour the issue described.

### The instrument defect, three times — see the 2026-08-12 entry

The retracted link sweep, two test assertions checking for words that survive in prose explaining
their removal, and a code-review finding claiming a call site was absent when it was two lines below
the definition. All *absence* claims derived from a model of the artifact rather than the artifact.
Journalled in full there; noted here because two of the three happened during execution rather than
planning, so the rule is not planning-specific.

### Harness facts worth carrying (both now filed)

- **Worktrees are cut from `origin/main`, not the orchestrator's checked-out branch** — invisible in
  sub-wave 1 because `batch/<X>` is `main` then, and increasingly wrong afterwards. Two A2 agents
  detected it independently; both recovered only because their prompts quoted an expected test
  baseline they could compare against. **Quote the expected baseline in every worker prompt** — one
  line, and it is what makes a stale tree self-announcing (#150).
- **`worktree-destroy.sh` cannot address harness worktree paths**, so the skill's own teardown step
  never runs; the Iron Law has to be reproduced by hand with `git merge-base --is-ancestor` plus
  `git branch -d` (#149).
- **The `.venv` symlink**: every agent hit it. Put it in the prompt as its own command — chained onto
  a `source` with `&&`, the sandbox refuses the compound and the symlink silently never gets made.

### A ratchet is the wrong instrument for an append-only artifact

Batch B set a per-doc ceiling on this very file at 60,750 against a measured 60,748, flagging it as
"the least comfortable line". **It went red within the hour** — a concurrent session appended one
entry. A ratchet says "this may not grow"; a ledger's contract is that it grows, and the only way to
stay green is to raise the integer every session, which is the loosening-by-editing a ratchet exists
to prevent. Now an explicit exemption with the reasoning recorded, and the split filed as #152.

Generalisable: before ratcheting a file, ask whether its *purpose* is to accumulate. If so, the
gate belongs on the index or on per-entry size, not on the total.

### Also captured

- **Sub-wave chunking held.** 7 file-disjoint agents against a ceiling of 4 → A1 (4) then A2 (3),
  each merging into one `batch/a`. Slot reclaim was synchronous; no leak across five teardowns.
- **The AGENTS.md line-window ownership worked exactly as designed** — three agents, three separated
  windows, zero conflicts, +18/−2. The "additions within your window only, no restructuring" clause
  is what made it safe; a reorder merges cleanly and silently reshuffles someone else's window.
- **Verification-mode asymmetry, 3rd recurrence.** Two Batch A agents added gates that existed in no
  sibling's worktree, so the orchestrator's post-merge run was the first execution of the combined
  tree under them. Recorded in the design doc in advance, which is what kept it from being
  misattributed.
- **A concurrent session pushed to `main` twice mid-ship**, once between the merge and the push.
  `git push` rejection is the cheap detector; the expensive version is a batch branch cut from a
  `main` that moved. Re-pull immediately before every push, not just before every batch.
