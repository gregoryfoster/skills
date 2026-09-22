## Session 2026-09-16/21 — CannObserv/cannabis.observer-wordpress (`#908` execution)

Execution addendum to [2026-09-16-wordpress.md](2026-09-16-wordpress.md). Fourteen issues,
thirteen work items, five batches of 3/3/3/3/1 at a ceiling of 3, one PR per work item, with
`batch/<x>` as a throwaway integration branch. All fourteen issues closed. Sixteen PRs merged:
thirteen from the batches plus three post-merge docs corrections. Plugin unit tests went from
3357 to 3597 and integration from 2257 to 2760. The run filed 35 follow-up issues. Batches ran
2026-09-16 to 2026-09-18, and the tail ran to 2026-09-21.

Filed upstream as [#314](https://github.com/gregoryfoster/skills/issues/314), drafted in the
consuming repo; nothing in the vendored submodule was edited. The consumer is private and this
log is public, so **no identifiers from the consuming repo appear below** (finding 6). Its issue
references are in backticks so they do not autolink here.

## Lessons

### 1. Review the fix commits as new code, and verify prescribed fixes by mutation

Batch D ran three review rounds, each scoped to the **previous round's fix commits**. Round 1
found one real bug among 18 findings. Round 2 found:
- a bug **in round 1's correction**: a census figure round 1 had fixed was itself off by one,
  because the instrument (a single-line grep) missed a statement wrapped across two lines;
- a regression **manufactured by round 1's widening**: a new error message told clients to resend
  a field in a container their type ignores, and a client that obeyed got a 201 with the value
  silently dropped — the defect the PR existed to close.

Round 3 found two guards that failed open, both by asking what the guard cannot see.

Across the chain, **three prescribed fixes would have shipped the defect class they were written
to close**; two were caught by mutation (remove the fix, confirm the new assertion goes red)
rather than inspection. Batch D closed at 47 findings, 45 applied, 2 held.

A fix round is where an unreviewed change lands under cover of "it was only a review fix". The
skill already treats an issue body as a proposal; a review finding's suggested fix is one too.

**Promoted ([#314](https://github.com/gregoryfoster/skills/issues/314)), as a paragraph after
the Orchestrator protocol in [`execution.md`](../../execution.md).** Fourth sighting, first
promotion. 2026-08-17 skills (#182 execution) found a defect introduced by the fix for another in
every one of four CR rounds; 2026-08-17 watcher (#268 execution) found the orchestrator's own CR
finding wrong the same way; 2026-08-21 skills (#219 execution) found a finding hiding a second
defect one layer down. Each was logged as a property of its run's review and none was promoted.
What this run adds is the instrument: mutation caught two of the three before they shipped.

### 2. A measurement work item needs its tool's version pinned

One work item's deliverable was a measurement of a code-graph tool's output, taken after the PR
merged. The first measurement was taken against a graph **two releases old**. The marketplace
plugin, the running server and the registry's latest were three different versions: the server
floats with `npx` and is fixed at session start. The user caught it and asked for a version check
and a from-scratch rebuild before anything was re-asserted.

The corrected measurement then took **three more docs PRs**, each correcting a claim carried
forward untested. One was a limitation the issue body had marked "not in scope", read as "still
true". Another was a claim the previous correction had not re-checked.

Grep-level footprint checks do not catch this. The failure is in the instrument, not the tree.

**Promoted ([#314](https://github.com/gregoryfoster/skills/issues/314)), as a clause on Worker
step 5.** One sighting of this shape, but the family is established: Worker step 4 already asks
for the interpreter that produces a baseline, because a number is meaningless without it
(2026-08-27 skills selection surface). A measured deliverable is the same claim with a floating
instrument, and "not in scope" in a body is a claim about the tree like any other.

### 3. The tail outlived the batches, and the merges went unrecorded

The tracking issue carried a comment at every batch state change through Batch D's third review
round. It recorded neither Batch D's merge nor Batch E's. The measurement tail then ran three more
days as unplanned work: three docs PRs, four upstream items on the tool's repo, and a handoff
issue. When the run closed, the missing merge comments had to be rebuilt from `gh pr view`. One
held review finding had stayed "held" for three days with no final disposition.

The comment record was what made the close-out possible at all: the run spanned several context
compactions, and the tracking issue was the only complete account.

**Promoted ([#314](https://github.com/gregoryfoster/skills/issues/314)), in three places in
[`execution.md`](../../execution.md):** the post-merge tail recorded in the design doc as work
items with an owner (Branch strategy), the merge comment on the tracking issue as part of
Orchestrator step 10, and a closing step 11 that gives every held finding a final disposition.
The tail half is a third sighting — 2026-08-13 usa-wa planned an ops tail, and its execution
addendum found it was where the backlog's claims got falsified — and neither earlier entry was
promoted. The comment half is new here, and cheap enough to take at one sighting: it is the only
record a compacted orchestrator can rebuild from.

### 4. The orchestrator's launch re-verification was wrong twice (confirms a promoted rule)

Twice a launch-time scope note from the orchestrator was wrong, and both times the implementing
worker caught it. In one, the orchestrator had read one verb's argument registration as another's
on the same route. Both were retracted on the issue. This is a third sighting of *a decision taken
at the gate is a hypothesis too*, now from the orchestrator's own re-verification rather than a
user decision. No change proposed. The worker's report-back slot is doing its job.

Workers also corrected four issue bodies materially. One prescribed fix would have been a fatal
error on every paginated list: a built-in called with more arguments than it accepts. That was
verified by running it, not by argument.

**Confirmed — no change.** Added to that rule's provenance in
[`process-log.md`](../../process-log.md).

### 5. Count arithmetic held at every gate (confirms a promoted rule)

Each combined gate reconciled exactly as baseline plus the new tests each worker reported, across
all five batches. One refinement: integration **assertion** counts drifted by 2 between identical
runs, depending on data, so reconcile on **test** counts.

**Confirmed, and the refinement promoted
([#314](https://github.com/gregoryfoster/skills/issues/314)) as a clause in the report-back
slot:** tests, not assertions. The slot's `N passed, M skipped` is pytest's shape; a PHPUnit
host prints both counts, and only one of them is stable.

### 6. A private consumer's process-log entries leak into this public log

This repo is public. The consuming repo is private. Four entries already in `process-log/2026/`
from this consumer name its classes, functions and file paths: 2026-06-09 (1 name), 2026-06-28
(6 names, 2 paths), 2026-08-10 (8 names, 2 paths) and 2026-09-16 (5 names, 2 paths). `#292`'s
body carried the same five names and two paths; it has since been amended, with a cleanup note
listing what remains. Class and test names are the private repo's code identifiers, so they are
exactly what a private consumer's policy protects. A leak cannot be edited away: an issue body
keeps a public revision history, and a landed file stays in git history.

Check the consumer's visibility before drafting. A private consumer's entry describes mechanisms
("a registry scan", "the pagination gate"), not names. The consumer's name and issue numbers are
fine; issue references go in backticks so they don't autolink here.

**Promoted ([#314](https://github.com/gregoryfoster/skills/issues/314)), as the second check
at the head of "Adding an entry" in [`process-log.md`](../../process-log.md).** One sighting,
promoted because the failure is irreversible and nothing else in the procedure asks: the first
check there already sends every vendoring consumer's entry upstream to this repo, which is what
makes the question reachable. The four existing entries it counts are untouched by this landing.

## Other notes

- **A worker's push exposed a pre-existing hook hazard.** Git exports `GIT_DIR` to hooks run from
  a linked worktree, so a pre-push hook that spawns the worktree script initialized submodules
  into the *pushing* worktree. The worker fixed it in the same PR, since the fix sat in its
  window, and the orchestrator healed the affected worktree. **Recorded.** The same hazard is
  this repo's own `GIT_DIR` scrub rule (#189); nothing orchestration-specific to promote.
- **A locally built copy of the third-party tool shared the live index store.** It stamps the
  release's version string, so it rebuilt the consuming repo's graph from unreleased code and
  nothing could tell for about 38 hours. That is a tooling hazard rather than an orchestration
  one, recorded in the consumer.
- **Documentation budgets ended at the ceiling**: the consumer's policy file at 5,996 / 6,000 and
  its tool-reference doc at 10,000 / 10,000. This confirms *a budget-tight file is
  single-writer*. The run's only policy-file editor per batch was named in the plan, and it held.
  **Added to that rule's provenance.**
