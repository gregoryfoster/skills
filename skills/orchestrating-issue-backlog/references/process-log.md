# Process Log — orchestrating-issue-backlog

Session-specific institutional memory for the [`orchestrating-issue-backlog`](../SKILL.md) skill. Each entry captures: project, interview answers, batch shape, non-obvious decisions, and tactical lessons. New sessions are appended chronologically; stable patterns get promoted into the SKILL.md body and (optionally) summarized here.

## Index

| Date | Project | Headline |
|---|---|---|
| 2026-03-23 | gregoryfoster/skills (origin session) | Establishing batch branch pattern; Rules 1–4 origins (local-main staleness; `git push HEAD:main` antipattern; `isolation: "worktree"` auto-merge semantics; rebase commit-message clobber) |
| 2026-05-22 | cannabis.observer-wordpress | Port-pool incident → Rules 5/6 (per-batch ceiling, runtime fall-through detection) |
| 2026-05-24 | gregoryfoster/skills | Single-owner overlap resolution; rubric weight variance (`Correctness × 3`); `gh issue create --body-file` workaround |
| 2026-05-25 | gregoryfoster/skills | Bundle three same-file issues into one agent (Shape A); bootstrap-skill Q2 framing |
| 2026-06-08 | cannabis.observer-wordpress | Spec-derived backlog → low-discovery / high-formalization mode (1st recurrence of compressed Steps 5/6); workspace-isolation docs-only-worktree pattern; foundation-shared-file read-only rule |
| 2026-06-09 | cannabis.observer-wordpress | Prerequisite-in-parallel pattern (Shape B); followup-backlog mode (2nd recurrence → compressed Steps 5/6); cheap ceiling re-verification; slot-reclaim semantics |

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
