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
| 2026-06-29 | address-validator | **Foundation ×3** (first Foundation-leading weight — confirms the variable-weight escape hatch covers it, not just Correctness); aggressive same-file bundling (9 issues → 5 agents); single issue whose blast intersects **multiple** parallel agents → isolate in its own gated batch (blast≠priority refinement, verify call sites by grep); sub-score commit order inverts for define-then-use |

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

1. **Grep the file's own header comments during the closed-in-fact check.** Issue #129 was verified resolved by reading [_name_metadata_fields.html](src/templates/admin/people/partials/_name_metadata_fields.html) — the file's docstring explicitly credits #131 for the fix. Adding `grep -rn "Issue #" src/templates/ src/api/admin/` to the closed-in-fact pass surfaces these credits without needing to read entire files. Module/template docstrings are an underused signal — they're how careful contributors annotate which footgun an edit retired. The 2026-05-09 log already established "grep for contested symbols before presenting scores"; expand the recommendation: also grep for `Issue #` in the contested files themselves.

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

- **Single-owner assignment to resolve a one-line shared-file overlap.** [skills/using-git-worktrees/SKILL.md](../using-git-worktrees/SKILL.md) was the only contested file (between #28 documenting an internal fix and #31 documenting a new script). Resolution: assign SKILL.md edits exclusively to one agent (F4, the larger contributor) rather than serializing two small edits with a rebase. F1 (#28) ceded SKILL.md and relies on commit message + inline script comments to document the internal change. This is cheaper than any merge-order ceremony for ≤2-line overlaps and worth reaching for first.
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
