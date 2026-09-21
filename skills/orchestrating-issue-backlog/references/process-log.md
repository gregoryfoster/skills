# Process Log — orchestrating-issue-backlog

Session-specific institutional memory for the [`orchestrating-issue-backlog`](../SKILL.md) skill. Each entry captures: project, interview answers, batch shape, non-obvious decisions, and tactical lessons. New sessions are appended chronologically; stable patterns get promoted into the skill — its body, or the reference that owns the step — and listed under "Rules promoted into the skill" below.

**This file is the root of the index.** Each session is its own entry file under
`process-log/<year>/`, named `<date>-<project>.md`, and each year's rows live in
that year's own index, `process-log/<year>/index.md`. Journaling a session means
two things: write the entry file, and add one row to that year's index — see
"Adding an entry" at the foot of this file.

## Years

- **2026** — [session index](process-log/2026/index.md)

---

## Rules promoted into the skill

Which sessions each of the skill's rules came from, wherever it now lives —
[`SKILL.md`](../SKILL.md) or one of its references. Moved here from its Process
Logs section in the #285 curation: it is provenance, not runtime instruction.
Step and Q numbers refer to `SKILL.md`; Rule and Worker-step numbers to
[`execution.md`](execution.md).

- Rules 5/6 (per-batch ceiling, runtime fall-through detection) — 2026-05-22 port-pool incident; Rule 5 slot-reclaim semantics + cheap ceiling re-verification — 2026-06-09
- Rule 3 revision (verify-and-merge per worker; reconciliation checklist) — 2026-05-09, 2026-05-11; **the main checkout's branch never moves where the repo deploys from it** — 2026-08-13 usa-wa
- Step 1–2 closed-in-fact grep per issue (**zero hits is ambiguous, not exculpatory**), closed-prerequisite check, rescope-to-residual with its defer branch, generated-artifact read — 2026-05-09, 2026-05-11, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13 observo, 2026-08-13 power-map
- Step 5: footprint grep, bidirectional (bodies understate *and*, in partial-fix backlogs, overstate); test-surface grep and line-window ownership, generalized to any large shared file then to function/region granularity; the no-file-overlap dependency edge; the shared-fixture-*escape* grep (hard conflict zone, vs. 2026-07-08's soft one); stated-*relationships*-are-hypotheses; grep-sizes-surface-not-behaviour; sweep enumeration; an issue body's own hedge as a grep target — 2026-05-09, 2026-06-28, 2026-07-08, 2026-08-09, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13 cli
- Step 5/6 backlog-provenance geometry (CR-surfaced, AR-surfaced, feature-followup, adoption-feedback) — 2026-05-09, 2026-05-11, 2026-06-28, 2026-08-07, 2026-08-09, 2026-08-11
- Steps 5/6 "low-discovery backlog mode" — 2026-06-08 (spec-derived), 2026-06-09 (followup-derived)
- Step 7: Shape A/B distinction (bundle vs. split same-file pairs) with its "differ in kind" refinement — 2026-05-11, 2026-05-25, 2026-06-09; "foundation shared files are read-only" — 2026-06-08; chain-appending rule — 2026-08-07; byte-for-byte-sync-test bundle signal + design-gate-with-no-file-overlap — 2026-08-10, the bundle signal then **restated as one regenerator per batch** (bundle *or* separate batches) — 2026-09-16 wordpress
- Step 8 docs-only-worktree authoring option — 2026-06-08; Step 9 `--body-file` over heredoc — 2026-05-24, 2026-05-25, 2026-06-08, 2026-06-09
- Step 4: rubric variable-weight escape hatch, confirmed for **Foundation**-leading (×3) as well as Correctness — 2026-05-24 (Correctness), 2026-06-29 (Foundation). Key Principles "blast ≠ priority" — isolate an issue whose blast intersects **multiple** otherwise-parallel agents, plus its three further variants — 2026-06-29, 2026-08-07, 2026-08-11
- Q5 shared-backing-service sub-question + the provision / serialize / cap resolution ladder + read-the-guard clause, incl. its can-the-role-create-them half — 2026-06-16, 2026-07-19, 2026-08-07, 2026-08-09, 2026-08-11 usa-wa, 2026-08-11 observo, 2026-08-13 usa-wa, 2026-08-13 observo, 2026-08-13 power-map, 2026-08-17 watcher, 2026-08-28 power-map — and accept "no ceiling" as an answer, 2026-08-12 / 2026-08-18
- Worker step 5 "issue body is a proposal, not a specification" + the report-back corrections slot + Step 8 body-decay note — 2026-08-09, 2026-08-10
- Step 4 decide-then-rescore at the approval gate + write scope changes back to GitHub — 2026-08-09, 2026-08-11; decisions move the *graph*, not only scores — 2026-08-23, 2026-08-28 power-map
- Step 4 measure an empirical decision at the gate rather than ask — 2026-08-21, 2026-08-27, 2026-09-14 observo
- Step 5 item 2 ([`shared-files.md`](shared-files.md)) where a shared fixture hides — `conftest.py`, module-local fixtures, test fakes of a protocol the backlog changes — 2026-07-08, 2026-08-13 power-map, 2026-09-14 observo
- Step 7 ([`batch-design.md`](batch-design.md)) a budget-tight file is single-writer — 2026-08-16, 2026-08-18, 2026-09-14 observo
- Step 7 ([`batch-design.md`](batch-design.md)) exclusion groups plus a queue as the chunking form past a small ceiling, and the longest chain as the critical path — 2026-09-14 observo (held, pre-registered), 2026-09-15 observo execution (confirmed)
- Q5 ([`shared-backing-services.md`](shared-backing-services.md)) the **capacity** half — what hardware runs the verification — plus the Rule 5 clause that the cheap re-verification confirms only the provisioning pool — 2026-08-12, 2026-09-14 observo, 2026-09-16 wordpress
- Step 5 item 2 ([`shared-files.md`](shared-files.md)) an assertion vacuous **as filed**, by layer rather than by a moved column — 2026-08-14 observo, 2026-08-21, 2026-09-16 wordpress
- Steps 1–2 ([`issue-audit.md`](issue-audit.md)) where the issue names no contract doc, the policy file does, and it is newer than the thread's last word — 2026-08-13 observo, 2026-09-16 wordpress
- Branch strategy / Orchestrator step 5 / Worker step 1 ([`execution.md`](execution.md)) the batch branch as a **verification artifact** where the host ships per-item PRs (2026-09-16 wordpress); the `--no-merged` snapshot, `git branch -d` run where HEAD is the batch branch, and the handoff harvest (2026-09-15 observo execution); a worktree has no initialised submodules, so a vendored skill is read by absolute path from the main checkout (2026-09-15 observo execution)
- Report-back slot ([`execution.md`](execution.md)) a decision taken at the gate is a hypothesis too — 2026-08-21 and 2026-08-27 recorded the converse, reversed 2026-09-15 observo execution
- Step 10 ("Adding an entry", below) a vendored copy is not where the entry goes — 2026-09-14 observo, 2026-09-15 observo execution, 2026-09-16 wordpress
- Step 7 count the table's items before approval, and quote that count ([`batch-design.md`](batch-design.md)) — 2026-09-14 observo (found by 2026-09-15 observo execution), 2026-09-16 observo; pairing as a constraint problem once the conflict matrix is dense — 2026-09-16 observo
- Rule 3 ([`execution.md`](execution.md)) measure the briefed baseline in a tree cut the way the workers' are, and name the delta; that delta's skipped tests as a finder for a verification-mode asymmetry ([`batch-design.md`](batch-design.md)) — 2026-09-16 observo
- Steps 1–2 ([`issue-audit.md`](issue-audit.md)) a closed upstream prerequisite is not a landed one: resolve the gate against the dependency's changelog, not the issue's state — 2026-08-20, 2026-09-17 cli
- Q5's third sub-question, the commit hook's own parallelism ([`shared-backing-services.md`](shared-backing-services.md)), and Worker step 6's pointer to it — 2026-09-17 cli

---
## Adding an entry

**First: is this skill vendored here?** Where the host repo consumes it as a git
submodule, the entry does **not** go in the vendored copy — draft it locally and
file it upstream as an issue against the skill's own repo. Writing it in place
leaves the host's main checkout reporting a modified submodule pointer, which is
output from Rule 6's `git status --porcelain` and therefore a fall-through
signal, and it survives into the next session's Step 1–2 stray sweep. The
upstream maintainer adds the entry and adjudicates the promotions in one pass
(2026-09-14 observo, 2026-09-15 observo, 2026-09-16 wordpress — all three filed
this way).

1. Write `process-log/<year>/<date>-<project>.md`, opening with a
   `## Session <date>` heading. Use the year the session ran; create the
   directory for a new year.
2. Add one row to `process-log/<year>/index.md`, linking the date cell at the
   entry as a bare filename — the index sits beside its entries. For a new year,
   create that index from the previous year's and add it to the Years list above.
   An index nothing links is an unreachable file the suite fails on.

Never grow an index with an entry body. An index is bounded by one row per
session; the ledger it indexes is not, which is why they are separate files
([#152](https://github.com/gregoryfoster/skills/issues/152)). Keep the row to a
headline — an index is the artifact an agent loads to orient, and it stops
working the moment it is dense enough that finding a session means opening
entries speculatively.

**Row length is the budget.** Every file here, a year index included, is bound by
the repo's 10,000-token per-doc budget, and a year index is the one doc every
session of that year appends to. Splitting by year (#183/#197) bounded the file;
it did not create headroom, because 2026's first five months already fill it. At
~7 sessions a month the affordable row is about **400 bytes** — the length of the
shorter rows in the 2026 index, not the 700-plus-byte rows it also holds. Write
the row that size, and put the rest in the entry file. **When a new row would put
the index over budget, trim the longest older rows back to about 400 bytes** —
their detail is in the entry files — **and do not split the year**: the answer the
2026-08-19 crossing measured (`tests/structural/test_skill_self_budget.py`).
