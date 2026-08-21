# Measuring billed minutes

GitHub bills Actions **per job**, rounded **up** to the minute, with a
**one-minute floor**:

```
cost = Σ over jobs of max(1, ceil(job_seconds / 60))
```

Nothing in the API returns that number. It has to be computed from job
timestamps, which is what `measure-ci-cost.sh` does. This document is the
record of *why* it does it that way — every correction below was established by
running the call, not by reading the documentation for it.

## Why not the obvious sources

| Source | Why it fails |
|---|---|
| The Actions usage UI | Org- or account-level totals. No per-job, per-workflow or per-day breakdown, so it can tell you the bill is 600 minutes and nothing about which job to delete. |
| `/repos/{o}/{r}/actions/runs/{id}/timing` | Returns `billable.<OS>.total_ms` **and** a per-job `billable.<OS>.job_runs[]` array. Both read **0**. Measured across two private repos and one public one: five consecutive runs of `cannabis.observer-wordpress` reported `run_duration_ms` of 35,000–99,000 with `total_ms` 0 every time. A census built on it reports zero spend and no error. |
| `/repos/{o}/{r}/actions/workflows/{id}/timing` | Same `billable` block, same zeros. |

Note the shape of that second row: `/timing` is not *coarse*, which is what
[#212](https://github.com/gregoryfoster/skills/issues/212) predicted — it is
*empty*. The per-job breakdown the issue says is missing does exist. It is the
values that are absent, and that is worse, because the structure invites trust.

## The census

`measure-ci-cost.sh --repo <owner/name> --days 30 --cache <path>` performs the
whole census. Three details in it are load-bearing and are the ones a
hand-rolled version gets wrong.

### 1. `filter=all`, or every re-run attempt vanishes

```
gh api "repos/{o}/{r}/actions/runs/{id}/jobs?filter=all&per_page=100" --paginate
```

The endpoint defaults to `filter=latest`. Measured on run `32311306786` of
`CannObserv/cannabis.observer-wordpress`:

| Query | `total_count` |
|---|---|
| default | 1 |
| `?filter=all` | 2 |

The hidden row is attempt 1 — 2m36s, billed 3 minutes. Attempt 2 ran 89s and
billed 2. The default therefore reports 2 minutes for a run that cost 5, and
the shortfall lands entirely on runs someone already had a reason to re-run,
which is to say on the flakiest part of the suite.

### 2. Exclude `conclusion: skipped`, or bill phantom minutes

A job skipped by an `if:` condition still appears in the jobs list. Its
duration is zero — or **negative**. Observed in `cli/cli`:

```
skipped  started_at 2026-08-20T21:51:34Z  completed_at 2026-08-20T21:51:27Z
```

That is −7 seconds. `max(1, ceil(-7/60))` is `max(1, 0)` = **1 billed minute**
for a job that never occupied a runner. One `cli/cli` run carried six of them.

This is not a rounding nuisance. In a repo whose entire spend is job count, a
phantom one-minute job is indistinguishable in the census from a real
one-minute job, so it survives Phase 2 and reaches Phase 4 as a deletion
candidate that saves nothing.

The script excludes `skipped` and reports the count separately, alongside any
non-skipped job with a non-positive duration — a combination that should be
zero and is worth looking at when it is not.

### 3. `created=>=DATE`, or `--paginate` walks the whole retention window

```
gh api "repos/{o}/{r}/actions/runs?per_page=100&created=%3E%3D2026-07-22" --paginate
```

The filter is supported and it matters: `cannabis.observer-wordpress` reports
`total_count` 933 unfiltered and 250 for a 30-day window. Without it the census
costs one API call per run for every run GitHub still retains.

Retention is the reason the window is ~30 days in practice. Both source audits
used 30, which is enough to see a trend and not enough to see a seasonal one —
an acknowledged limit, not a resolved question.

## Separating anomaly days

The gate exists because of one measured day. `CannObserv/cannobserv`, 30 days
to 2026-08-21:

```
RAW           588 billed min over 414 jobs
ANOMALY DAY   2026-08-06 — 196 min over 24 jobs (8.17 min/job)
STRUCTURAL    392 billed min over 390 jobs
```

2026-08-06 was a GitHub Actions incident that hung jobs for ~900s before
cancelling them. Quoting 588 overstates the structural baseline by **33%**, and
the part that actually costs you is the second-order effect: the raw p99 is
**902s** and the structural p99 is **47s**. 902 reads as a duration problem in
a repo where duration has no lever whatsoever.

That is also why the script computes every percentile from the *structural*
population and reports the raw p99 only beside the anomaly. A p99 of 902
printed under the heading "structural" is the same error as the raw total, one
level down, and harder to notice.

`cannabis.observer-wordpress` shows the same day, independently: 254 min over
31 jobs at 8.19 min/job against its own 1.89 min/job median, and the same 902s
raw p99 against a 167s structural one. One incident, two repos, one signature.

### The rule, and why the obvious rule is wrong

The obvious rule — flag a day whose billed total exceeds `factor ×` the median
day — over-flags. In the same cannobserv window, 2026-08-17 billed 46 minutes
against a 15-minute median day, tripping a 3× threshold, and it was an entirely
ordinary busy day: 44 jobs at **1.05 min/job**. Subtracting it would have
understated the real spend by 46 minutes, which is the failure mode the gate
exists to prevent, pointed the other way.

So a day is an anomaly candidate only when it is **both** unusually large *and*
structurally unlike the others:

```
day_billed      >  factor × median(day_billed)
day_mean_billed >  factor × median(day_mean_billed)
```

The second test is what separates a platform incident (8.17 min/job against a
1.00 median) from a busy Tuesday (1.05 against the same median). The script
applies both, prints the five busiest days with their per-job means either way,
and **never drops a day silently** — raw and structural totals are always
reported together.

A flagged day is a *candidate*. Confirm it against the GitHub status history
before excluding it: an anomaly you cannot attribute to an incident is a
finding, not noise.

## Two repos, one tool, opposite answers

Re-measured for this skill with the shipped script, 30 days to 2026-08-21:

| | `cannabis.observer-wordpress` | `cannobserv` |
|---|---|---|
| structural billed | 704 min / 380 jobs | 392 min / 390 jobs |
| **mean billed/job** | **1.85** | **1.01** |
| p50 / p90 / p99 seconds | 63 / 136 / 167 | 28 / 38 / 47 |
| jobs under 60s | 40% | 99% |
| **cost shape** | **duration** | **job-count** |
| top line item | `PHP lint + tests` — 399 min over 145 runs, median 128s | `version-sync` — 146 min over 146 runs, median **7s** |

The two top line items are the whole argument. One bills 2.75 min per run
because it *runs* for 128 seconds; caching and narrowing it are real money.
The other bills exactly 1.00 min per run because it runs for 7 seconds and the
floor charges a minute anyway — no amount of speeding it up recovers anything,
and the only lever is to stop running it. An agent that brought the first
repo's playbook to the second would have spent the audit profiling a
seven-second job.

## Thresholds

The script classifies on the structural mean:

| mean billed/job | shape |
|---|---|
| ≤ 1.10 | `job-count` |
| ≥ 1.40 | `duration` |
| between | `mixed` — classify row by row in `by_job`, treating `median_seconds < 60` rows as job-count |

The band is deliberately wide in the middle. A repo landing in `mixed` has no
single lever and the per-job table is the honest answer.

## Cost of the census

One API call per run, plus one paginated listing. A 30-day window on a busy
repo is 200–250 calls and a couple of minutes. `--cache <path>` writes the
NDJSON and reuses it, so re-classifying at a different `--anomaly-factor` is
free — the cache's first record carries the repo, window and day count, so a
re-run can never quote a baseline whose provenance it has forgotten, and the
file is moved into place only after the last run is fetched, so a census that
died partway cannot be reused as a complete one.
