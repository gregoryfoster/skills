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
