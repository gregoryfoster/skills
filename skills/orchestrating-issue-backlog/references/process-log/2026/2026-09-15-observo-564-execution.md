## Session 2026-09-14/15 — CannObserv/observo (#564 execution)

Execution addendum to [2026-09-14-observo.md](2026-09-14-observo.md). Eighteen
issues, fifteen workers, a 2-slot ceiling, one integration branch. Suite
4375 → 4547 passed; fifteen `--no-ff` worker merges, **zero merge conflicts,
zero worktree fall-throughs**, and every gate's count equal to baseline plus
the new tests the worker reported.

Filed upstream as [#289](https://github.com/gregoryfoster/skills/issues/289).
The skill is vendored here as a submodule, so it was drafted in the consuming
repo and nothing in the vendored copy was edited — see lesson 7.

## Lessons

### 1. Exclusion groups plus rolling fill was the runtime form of the plan, and the longest chain set the wall time

The design doc named the never-concurrent sets (one per hub file, one per
shared doc) rather than only fixed wave pairs, so the orchestrator could pull a
later item into a freed slot without re-deriving the conflict map. The gate
suite ran before each refill, which kept concurrent suites at the ceiling.

The cost is the other half: **the longest exclusion chain sets the wall time.**
Four items serialized on one hub file (`fleet_manager.py`) despite being
function-disjoint, because they shared protocol test fakes, while the other
slot drained its queue early and idled.

**Promoted ([#289](https://github.com/gregoryfoster/skills/issues/289)), as the
2026-09-14 entry pre-registered.** That entry held the form "pending execution"
with the safety claim named as a prediction — that a later item can be pulled
forward without re-deriving the conflict map — and this run is the test: zero
conflicts across fifteen merges. Step 7's `Chunk when N > ceiling` bullet
prescribed fixed sub-waves and now carries the exclusion-group form beside
them, with the critical path named at planning time rather than discovered as
an idle slot. The cost half is the promotion's real content: fixed sub-waves
hide the chain, because every wave boundary looks like a gate.

### 2. A decision taken at the approval gate is a hypothesis too

Every one of the fifteen workers corrected its brief or body. Three corrected
the orchestrator's *reasoning* rather than an issue body: a bundle rationale
whose evidence came from a different signal; one leg of a user-approved
decision falsified by production logs; a half-wrong routing handoff. The #554
worker did this unprompted and flagged the deviation explicitly, and the
orchestrator carried it into the final report and the plan's Outcome.

**Promoted ([#289](https://github.com/gregoryfoster/skills/issues/289)), as a
clause on the report-back slot.** Worker step 5's detector is "verify every
file:line, every claimed call site, and every prescribed implementation against
the current tree" — three tree facts. A decision taken at the decide-then-rescore
gate is none of them: it is a product call, so the prescribed verification has
nothing to key on, and the worker has no standing instruction to doubt it.

What makes the gap worth bytes is that this log had twice recorded the
*opposite* reading, which is exactly what would keep an orchestrator from
looking:

- **2026-08-21 skills (#219 execution):** "Decisions survived, prescribed
  implementations did not."
- **2026-08-27 skills (#239 execution):** "Five brief facts decayed same-day —
  decisions survived, numbers didn't."

This is the first counter-example, and it arrived from production logs rather
than from the tree, which is why neither prior session could have found it.

### 3. Per-worker counts made every gate arithmetic

Fifteen of fifteen merges matched baseline + N exactly. Where a worker's branch
predated other merges, it reported a trial merge onto the current tip with its
own count, which made the post-merge gate predictable before running it.

**Carried.** The report-back slot has required the collected count since
2026-08-16, promoted in the #161 pass; #285 recorded the same at planning time.
Fifteen-for-fifteen is a recurrence count, not a change. The trial-merge
refinement is logged here rather than promoted: Worker step 3 already has the
worker merge `batch/<X>`, so a worker that finished before later merges landed
is re-running a step it already knows.

### 4. Handoff sections in later briefs

A worker's fix routinely made text stale in a file another worker owned — a
docstring or a doc sentence still describing the just-fixed gap as open.
Routing these into the *next owner's* brief as a "Handoff from #N" section
cleared all six such cases with no extra agents.

**Promoted ([#289](https://github.com/gregoryfoster/skills/issues/289)), one
clause each on the report-back slot and Orchestrator step 5.** The harvest
point is the merge step, and the raw material is a list the report does not
currently ask for: everything the worker *left alone* because it sat outside
its window. The skill deals with the plan-time face of this (line-window
ownership, `shared-files.md`) and had nothing for the runtime face. Six cases,
zero extra agents, is the measurement that earns it at one sighting; the
alternative is a follow-up issue per case or stale prose shipping inside a
green batch.

### 5. Audit the effects of a behaviour-contract change before merging

A Q0 scope widening (SIGTERM → `STAGE_CANCELLED` for consumers) had
second-order effects the worker reported but could not rank. Before merging,
the orchestrator grepped every app-side path that sends that signal. That
separated the safe cases (whole-`Job` stops) from a real regression risk (a
recovery path would have broken, but none existed) and from operator-only edge
cases. About two minutes, and it decided between merge and hold.

**Held at one sighting — carried in substance.** The report-back slot already
ends "Escalations are evidence, not findings — verify one before acting on it",
and that is what happened: the worker escalated, the orchestrator verified. What
is new is only the *shape* of the verification — grep the senders of the changed
contract, not its definition — and the worker's inability to rank is
structural rather than incidental, since it sees its own window and not the
app-side callers. Recorded here so a second sighting can find it; on a second,
the clause to sharpen is the escalation one, not a new step.

### 6. Tooling gotchas that cost workers time

- **`gh issue view` fails on gh 2.45** (Projects-classic GraphQL). The REST
  form belongs in every brief for this host: `gh api repos/<o>/<r>/issues/<n>`
  and `…/comments`. **Held** — a version-and-host fact, and the skill does not
  pin a `gh` version anywhere.
- **`measure-context.sh --env-file` takes names relative to the repo root.**
  From a worktree, pass `../../.env` or `../../../.env`; an absolute path
  silently falls back to the estimate and `check_context_budget.py` then
  refuses, correctly, with exit 1. Running it *from* the worktree is itself the
  fix, since the repo root is then the worktree. **Not this skill's** — it
  belongs to `curating-context`, and is logged here only because the brief that
  cost the time was an orchestration brief.
- **Worktrees lack the vendored-skill submodule.** Workers must read the skill
  and run its scripts **by absolute path from the main checkout**, with the
  worktree as cwd. **Promoted** as a clause on Worker step 1. `git worktree add`
  does not initialise submodules, and every repo in this cohort vendors its
  skills as one, so a brief that says "follow `skills/<name>/SKILL.md`" names a
  path that does not exist in the tree the worker is standing in. The
  neighbouring consequence — that a test guarded on a vendored path *skips* in a
  worktree, so the Rule 3 baseline differs structurally from the orchestrator's
  checkout — was filed separately as
  [#291](https://github.com/gregoryfoster/skills/issues/291) and is not
  adjudicated here.

### 7. Orchestrator step 5's discovery command has a false-positive mode

`git branch --no-merged batch/<X>` also lists pre-existing unmerged branches
that belong to no worker — here `test/499-dormancy-audit`.

**Promoted ([#289](https://github.com/gregoryfoster/skills/issues/289)), in one
of the two forms the issue offered.** The issue's first remedy — filter on
`worktree-agent-*` — is wrong for this skill, and the step says so two lines
above the command: it exists to catch "both `worktree-agent-*` and
custom-named branches", because `isolation: "worktree"` has produced
agent-chosen branch names. Filtering on the prefix restores the false negative
the command was written to remove, and trades a visible stray for an invisible
lost worker. The snapshot form — diff against `--no-merged` taken when the
batch branch is cut — carries no such cost and is what shipped. This is
Worker step 5's own rule ("the issue body is a proposal") firing on an issue
written by the skill's maintainer about the skill.

### 8. `git branch -d` belongs in the integration worktree

Run it via `git -C <integration worktree>`, where HEAD is the batch branch, so
its merged check is meaningful. From a deploying main checkout (HEAD = `main`)
it would refuse every worker branch.

**Promoted ([#289](https://github.com/gregoryfoster/skills/issues/289)).** This
is a contradiction between two rules the skill already carries, and neither
side is wrong on its own. Orchestrator step 2 says that where the host repo
deploys from the main checkout, that checkout's branch must never move — create
`batch/<X>` without checking it out and integrate in a worktree. Orchestrator
step 5's last bullet then leans on `-d`'s merged-into-HEAD check as "a second
guard against the same merge-safety class". Follow both and HEAD is `main`, so
the guard refuses every branch it is meant to pass and the orchestrator learns
to reach for `-D`, which is the guard's entire failure mode. The fix is where
the command runs, not which flag it uses.

## Other notes

- **Zero fall-throughs across fifteen launches** at a ceiling of 2 with rolling
  fill. Rule 5's slot-reclaim semantics — destroy frees the slot, the next
  create reclaims it — is what makes rolling fill affordable, and this is its
  widest run to date.
- **Q5** unchanged from the planning session: 2 workers, CPU-bound, shared with
  the live service.
- **Vendoring note:** this entry was drafted in the consuming repo and filed
  upstream as an issue. Writing it into the vendored copy would have left the
  main checkout reporting a modified submodule, which is a Rule 6 false
  positive on the next session's baseline sweep. Same conclusion as
  2026-09-16 wordpress reached independently; promoted there.
