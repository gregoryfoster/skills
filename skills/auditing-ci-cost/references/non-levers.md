# Non-levers

A **non-lever** is an optimisation that looks obvious, was considered, and was
rejected with a reason. Both source audits produced this section deliberately,
because without it the next audit re-derives the same dead end and the one
after that re-derives it again.

Two rules:

1. **Every audit ends with one.** It is a required output of Phase 6, not a
   nicety. An empty non-levers section means the audit only wrote down what it
   liked.
2. **A rejection carries its reason and its evidence.** "We didn't do X" is a
   note. "X saves nothing because the mean billed is 1.00" is a non-lever, and
   it is checkable when the shape changes.

## The catalogue so far

Carried forward from the two audits. Each row names the cost shape it was
rejected *under* — the same lever can be live in the other shape, which is the
whole reason Phase 2 exists.

| Non-lever | Rejected under | Reason |
|---|---|---|
| Speeding up a fast job | `job-count` | A job running 7s and a job running 55s bill identically: one minute. Optimising inside the floor recovers exactly nothing. `cannobserv`'s largest single line item was a 7-second job billing 146 minutes over 146 runs. |
| Splitting a workflow by path | `job-count` | A split **adds** billed minutes: each new job pays the floor on every run where both halves fire. Worth ~208 min/mo in the duration-shaped repo and negative in the count-shaped one. |
| Adding a dependency cache | `job-count` | Cache restore is itself several seconds and the job still bills one minute. Live in `duration` — a cold Pint cache was worth ~60 min/mo in `wp#726`. |
| Merging jobs to cut count | `duration` | Merging serialises work that was parallel, and the merged job bills the sum of the parts rounded once. Saves at most one floor-minute per run and costs wall-clock on every run. |
| Larger / faster runners | either | Billed at a multiplier that is at least as large as the speedup, and the floor still applies. Never a cost lever; sometimes a latency one, which is a different audit. |
| `concurrency:` cancel-in-progress | either | A real lever on re-push-heavy repos, but it is an **attribution** finding, not a duration or count one — measure re-push frequency in Phase 3 first. Rejected as a blanket recommendation, not on its merits. |
| Dropping a matrix leg | either | Cuts cost proportionally and cuts coverage proportionally. Not a cost finding unless the leg is provably redundant; that argument belongs to the test suite, not the audit. |
| `/timing` as the measurement | either | `billable.<OS>.total_ms` reads 0 on every repo probed, public and private. See [measurement.md](measurement.md). |
| Blanket `**.md` in `paths-ignore` | either | Package metadata can make a README a build input. See trap 4 in [traps.md](traps.md). |
| Reading GitHub's glob docs instead of probing | either | The implementation is more lenient than the prose. See trap 6. |

## Writing a new row

Put it in the audit's own report, in this shape, and add it here if it
generalises:

```
N. <lever> — REJECTED (<cost shape>)
   Estimated saving if it worked: <minutes/mo>
   Why it does not: <the measurement that kills it>
```

The estimated saving is not decoration. A non-lever with a large notional
saving is the one someone will propose again, and recording the number is what
makes the rejection survive the proposal.
