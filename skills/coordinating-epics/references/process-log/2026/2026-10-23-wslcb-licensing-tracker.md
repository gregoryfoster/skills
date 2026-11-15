## Session 2026-10-23 — CannObserv/wslcb-licensing-tracker#205

The epic was adopted, not created. An approved design, a task-level plan and five phase children already existed, with an "Order" paragraph in a hand-off section. The coordinator brought the body onto the template in one `--adopt-live --lint-all` call. It ran 7 check-ins (2026-10-22 to 2026-10-23) and closed on an empty re-scan. A follow-up issue was filed at close for one dated and one triggered check. The host has **no test CI**: the gate was the local suite with a test DB URL, run by the coordinator at every check-in.

### Shape

- **Way in:** inherited, from a plan's phase table plus its "settled after approval" decisions.
- **Children:** 5 planned plus 1 slotted: a DB-constraint follow-up from the first child's code review, placed by "a guard goes before what it guards". 1 follow-up was filed at close.
- **Parallelism:** the operator pulled the last child's first two tasks (a paid gold-set eval and the constants it sets) forward, alongside the slotted child. The coordinator had recommended it because those tasks had the longest lead time.
- **External dependency:** a dead-man monitor on a sibling repo, requested as soon as the child that defined its fields merged. The answer flipped the wait: the sibling then waited on our first `ok`.

### Findings

1. **The pre-flight must read the env fallback of every tool the child runs.** `alembic/env.py` fell back to the shared prod DB when `DATABASE_URL` was unset. The plan's "round-trip against the test DB" would have migrated prod outside its gate. Every later brief repeated the hazard for dev servers.
2. **Find out whether a merge is live before the migration it needs.** Here, timer units ran `python -m` from the deploy checkout, so a merge was live at the next run. The brief measured the ingest windows from the journal and put the merge→migrate ordering to the operator as a decision.
3. **A brief hazard that the implementer refines is a good outcome; record the refinement.** The implementer:
   - decoupled a version constant the brief flagged;
   - changed one alert rule for one origin (a leaked lock would otherwise report `ok`);
   - added a field so a badge could show mixed provenance.

   Each landed as a "Deviation" note on the epic line.
4. **Measure the base rates before briefing an evaluation.** A keyword pass showed two of four subtypes could never reach the plan's evidence floor, and that the supplement pool had no source for the third. The brief proposed a fail-closed rule for insufficient evidence and required blind labeling. The implementer split the supplement so labels were committed before any paid call.
5. **A cost estimate in the epic body goes stale when a later child changes the request shape.** One question per name became two. Correct it in place, struck through, in every section that quotes it. The editor's line-per-ref rule pushed the correction into a section rewrite.
6. **Coordinator-sourced counts go stale too.** A by-type count posted in an early harvest reached a later brief, and the implementer inferred phantom rows from it. Re-measure before quoting, and correct your own comment on the issue where it misled.
7. **Fold the final operator child into one runbook, and apply your own tiebreaks to its steps.** The safety net (timer + monitor, flag off) went before the capability (enable + backfill). That armed the dead-man before any paid call, and it matched the sequence the sibling had agreed.
8. **A sibling's "before the first run" requirements are claims to trace in your own code.** The requirement here was that every alert carry all template variables. The coordinator traced all three alert paths and the test guard before the first check-in.
9. **The operator's spot-check went further than the runbook asked: all 115 changes instead of 30.** It found 5 high-confidence errors that the review queue, by design, never surfaces. Record that as an accepted limitation in the summary, not as a defect.
10. **Sibling agents coordinating live (a status agent and a build agent) left their record on our child issue.** The coordinator read it at the next scan rather than relying on the channel.

### Rules this run supports

- Run the gate yourself at every check-in when the host has no CI, and compare the skip set by identity. Two installed-copy skips turned into passes when the units were installed.
- A check dated after the end goes to a filed issue, so it doesn't hold the epic open.
