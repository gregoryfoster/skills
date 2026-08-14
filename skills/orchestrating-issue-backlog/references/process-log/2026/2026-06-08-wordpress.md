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
