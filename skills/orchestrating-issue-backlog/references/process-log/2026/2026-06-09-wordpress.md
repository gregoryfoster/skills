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
