# The cadence — putting a measurement on the clock

This skill named "the scheduled weekly run" throughout, and its telemetry, trend
shapes and `delta_days` field all assumed one, but it shipped no scheduling
mechanism and no cohort repo had one. Ten of twelve repos held exactly one
ledger row. A design that compares a repo against its own past needs a past, and
there was none accumulating
([#118](https://github.com/gregoryfoster/skills/issues/118)).

## What goes on the clock is a measurement, not a curation

A curation needs judgement — classify each section, verify each claim, decide
what relocates where. That is an agent run and a reviewed PR. Twelve of those a
week is not a cadence anybody sustains, and putting unreviewed judgement on a
timer is the opposite of what this skill is careful about everywhere else.

What the longitudinal design actually needs is a **time series**, and most of it
comes from measuring rather than curating:

| Candidate metric ([#118](https://github.com/gregoryfoster/skills/issues/118)) | Needs |
|---|---|
| Regrowth rate — `delta_tokens / delta_days` | a measurement |
| Budget adherence — `over_budget` over time | a measurement |
| Seam accrual — `seams` | `check-seams.sh`, which is mechanical — but read *What the scheduled `seams` count means* below before treating it as pure accrual |
| Work to restore — `actions` vs tokens recovered | real curations |
| ~~Live-surface trend — `tokens_live`~~ | **refuted**, see [rejected-changes.md](rejected-changes.md) |

Three of the four surviving metrics need no judgement at all. So the clock runs
the measurement, and the curation stays triggered by what the measurement shows.
The row it writes is a baseline row — the surface as found, no edits — which is
what `record-telemetry.sh --baseline` exists to record.

**The kind is on the tag, not in `--note`.** A scheduled reading and a
pre-curation measurement are both states, but they are not the same state: one is
a surface nobody touched, the other is what a run's edits were measured against.
Mixing them silently is the asymmetry
[#116](https://github.com/gregoryfoster/skills/issues/116) called out when it
refused to recover analysis inputs from freetext. So the cadence records
`baseline:scheduled` (`--baseline=scheduled`) and Phase 1 records
`baseline:pre-curation` (bare `--baseline`). Every reader matches the `baseline`
prefix, so both remain states to `classify_run` and neither counts as a run.

This also keeps the `runs` column honest: baseline rows are states, not runs, so
a year of faithful weekly measurement with no curation reports `0 runs`, and the
`latest` column is where a reader sees the repo is alive. **`cohort-report.sh` is
the dashboard** — twelve Actions tabs are not a place anybody looks.

## The prerequisite that makes or breaks it

**Every repo needs `ANTHROPIC_API_KEY` as a repository secret before this is
worth installing.**

This is not a degradation. Without a credential `measure-context.sh --exact`
falls back to an offline estimate, and `record-telemetry.sh` **refuses the
append and exits 4** against a ledger of exact rows — correctly: an estimate and
an exact count are not comparable. A scheduled job without the secret produces
*nothing*, every week, silently, until somebody opens the Actions tab.

The workflow below runs `--check-credential` as its first step for exactly this
reason: fail loudly at second zero rather than at the last step of the job. That
step spends one free `count_tokens` call rather than checking the secret is
non-empty — a key that authenticates but cannot spend produced exactly the
silent-until-the-end failure this step exists to prevent (#271).

## The ledger needs a union merge, and it needs it first

The ledger is append-only, so a scheduled append and a human commit land on the
**same last line** and git cannot auto-merge them. The push is rejected, the
retry's rebase halts on a conflict, and the week's row is lost with markers left
in the file — verified against a real remote, which is how the first version of
the retry loop was found not to work.

`install-cadence.sh` therefore also ensures:

```
.skills/context-metrics.jsonl merge=union
```

in `.gitattributes`, appending to whatever is already there. With it, the same
race rebases cleanly and both rows survive in order.

The path tracks `--ledger`, and so do the workflow's `git add`, the recorder's
own `--ledger`, and the seam sweep's `--base-ledger` — four places that must name
one file, because a cadence measuring into one path and staging another records
nothing, and a sweep reading a third finds no predecessor and reports an empty
interval every week. The renderer interpolates one variable into all four, so
they cannot drift through the installer; hand-editing the rendered workflow is
the only way to break it, which is why the file says to re-run the installer
instead. Re-running it without the flag reads the ledger back out of the
installed workflow — from the `git add --` line, which is why adding
`--base-ledger` did not disturb it — rather than reverting to the default, and
changing it removes the line it supersedes.

**Commit it before the first concurrent run.** Git resolves a merge using the
attributes in the tree being *replayed onto*, so an attribute added after the
fact does not rescue the conflict that motivated it. That is why the installer
tells you to stage both files together.

The same weekly run rewrites two more files, and each needs its *own* merge.
`measure-context.sh --exact` refreshes `.skills/context-token-ratio` and
`.skills/context-token-counts`, the workflow stages all three paths, and for a
while the installer protected one — so the calibration files lost exactly the
race the ledger was protected against (#173). Union is the wrong answer for
both: it would leave two values for one key and the estimators would read
whichever they hit first, which is worse than a conflict because nothing
reports it. Beyond that the two files part ways:

```
.skills/context-token-ratio merge=ours
.skills/context-token-counts merge=context-counts
```

The counts file merges **per row, newest wins**
([#237](https://github.com/gregoryfoster/skills/issues/237)). It used to carry
`merge=ours`, which keeps the side of whoever *runs* the merge — unrelated to
which side measured more recently — and the cadence bot only ever pushes to
the default branch, so it was structurally always the side that lost: merging
`origin/main` onto a branch silently reverted the week's fresh row, and
nothing went red because the file is a cache (`c7be4eb` is the incident
record). The `context-counts` driver (`merge-token-counts.sh`) merges
one-sided edits — deletions included — as ordinary three-way; on a genuine
collision it keeps, per path, the row whose `bytes` matches the file in the
tree, because that row describes a file that exists. When neither matches it
keeps the current side's row, exactly what `merge=ours` did, leaving the
drift fallback and the next `--exact` run to absorb it.

The ratio file **stays `merge=ours`** — decided with #237, not left over.
Newest-wins has nothing to key on: the file is one repo-wide scalar with no
per-path rows and no recorded byte size, so arbitration would need a
timestamp the format does not carry — a format change every cohort repo would
have to migrate. And the stakes are lower: once counts rows survive merges,
the ratio only prices files never counted exactly, it moves slowly, and a
week-stale copy self-corrects at the next `--exact` run.

**Both attributes name drivers, and neither is a git built-in** — `union` is,
which is why the ledger line works the moment it lands. An attribute naming
an undefined driver is inert: git falls back to the 3-way merge and leaves
markers in files that must never be hand-merged. Two config lines make the
entries above mean anything:

```
git config merge.ours.driver true
git config merge.context-counts.driver "bash 'skills/curating-context/scripts/merge-token-counts.sh' %O %A %B %P"
```

(the installer resolves the script path to wherever the vendored skill's
`scripts/` sits). `install-cadence.sh` sets both in the clone it runs in and
cannot do more: **git config is not versioned**, so a fresh clone of a
correctly installed repo arrives protected on paper and unprotected in fact.
That is why `--check` reports each driver as its own line instead of folding
it into the calibration one — in the second cadence pilot the audit read
green on the attribute while the mechanism behind it was absent (#192) — and
why the workflow's commit step defines both drivers for its own fresh clone.
Run the installer — or the two one-liners — once per checkout.

`--uninstall` removes the attributes along with the workflow, leaving
`.gitattributes` as it found it — the file itself goes only if nothing else was
in it. The recorded rows stay either way: they are the series, and removing the
mechanism that adds to it is not a reason to discard what it already collected.

It leaves both drivers set, deliberately: with nothing pointing at it a
defined driver never runs, `merge.ours.driver` is generic enough that other
`merge=ours` rules may depend on it, and unsetting either could only break
attributes this installer never wrote.

## What the scheduled `seams` count means

Why the count is a standing half plus an interval half, why `--base-ledger`
replaced `--base HEAD`, and what the first run reports when it has no
predecessor: [seam-accounting.md](seam-accounting.md).

## What the drift report covers

Three things, in this order: every **breach**, every **approach**, then the seam
and count sweeps.

Both tiers cover **the policy file and every live reference doc**. The step read
`["policy"]` alone until
[#273](https://github.com/gregoryfoster/skills/issues/273), while
`measure-context.sh` had already computed `over_budget` for every `docs[]` row
and the job discarded it — a hole rather than a delay: on the shell-write path
nothing else reports a doc breach, since the write guard sees only what its
`PostToolUse` matcher intercepts and a `sed -i` escapes it.

The approach tier is a `::notice::` and never says "over". The band, its knob,
and why one tier makes a budget behave as a cliff:
[write-guard-hook.md § When it speaks](write-guard-hook.md#when-it-speaks).

Updating the vendored skill does not re-render an installed workflow, so
`--check` reports one from before this as `drift report: STALE` and exits 3 —
the marker #237 needed for the counts driver, and the only thing that tells an
installed repo it reports the old half.

**A number the run did not count is marked as an estimate**, and the row is not
suppressed: silence about a doc over budget is the failure being fixed, so it
must not be the fix's own shape. Why, and why `tokens_source` is per row:
[measuring-tokens.md](budget-and-metrics/measuring-tokens.md#run-wide-on-policy-per-row-on-docs).

## The workflow

The rendered job, with the annotations that explain each step:
[cadence/workflow.md](cadence/workflow.md). It is the **output** of
`install-cadence.sh --print`, cron placeholder aside, and a test pins them to
each other — an annotated copy that drifts from what actually installs is worse
than no copy.

It follows the house scheduled-job pattern and departs from it in one place;
both are explained there, along with why every step is ordered as it is. What
the job deliberately does *not* do is below.

## Stagger the cron across the cohort

Twelve repos all firing at `0 15 * * 1` produce twelve simultaneous
`count_tokens` bursts and twelve commits in one minute. `install-cadence.sh`
derives a per-repo offset from the repo name so the cohort spreads across the
window without anybody choosing twelve times. Pass `--cron` to override.

GitHub also delays scheduled workflows under load and drops them on repos idle
for 60 days, so treat the series as approximately weekly. `delta_days` records
what actually happened, which is why regrowth is normalised by it rather than
assumed per-week.

## What this does not do

- **It does not curate.** No agent, no judgement, no PR. When a row shows the
  surface over budget or seams accruing, a human or an agent runs
  `curate context` in that repo.
- **It does not gate a merge.** It never runs on `pull_request`. Turning the
  budget into a merge gate is [#88](https://github.com/gregoryfoster/skills/issues/88),
  and its sequencing rule stands: add the gate per repo only *after* that repo is
  under budget, or it is a permanently-red check people learn to bypass.
- **It does not fix the arms problem.** Rows carry `skill_version`, so a series
  can be split by version — but the confounds
  [#118](https://github.com/gregoryfoster/skills/issues/118) names (version
  correlates with time, repo activity drives regrowth) are not addressed by a
  cadence. They need the covariates that issue proposes.
