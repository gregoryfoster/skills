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

Carried forward from the two source audits and the field runs since. Each row
names the cost shape it was rejected *under* — the same lever can be live in
the other shape, which is the whole reason Phase 2 exists. A row rejected on a
public repo names that instead, since there no shape makes minutes cost money.

| Non-lever | Rejected under | Reason |
|---|---|---|
| Speeding up a fast job | `job-count` | A job running 7s and a job running 55s bill identically: one minute. Optimising inside the floor recovers exactly nothing. `cannobserv`'s largest single line item was a 7-second job billing 146 minutes over 146 runs. |
| Splitting a workflow by path | `job-count` | A split **adds** billed minutes: each new job pays the floor on every run where both halves fire. Worth ~208 min/mo in the duration-shaped repo and negative in the count-shaped one. |
| Adding a dependency cache | `job-count` | Cache restore is itself several seconds and the job still bills one minute. Live in `duration` — a cold Pint cache was worth ~60 min/mo in `wp#726`. |
| Merging jobs to cut count | `duration` | Merging serialises work that was parallel, and the merged job bills the sum of the parts rounded once. Saves at most one floor-minute per run and costs wall-clock on every run. |
| Larger / faster runners | either | Billed at a multiplier that is at least as large as the speedup, and the floor still applies. On a public repo it also turns unbilled minutes into billed ones: a larger runner bills there too. Never a cost lever; sometimes a latency one, which is a different audit. |
| `concurrency:` cancel-in-progress | either | A real lever on re-push-heavy repos, but it is an **attribution** finding, not a duration or count one — measure re-push frequency in Phase 3 first. Rejected as a blanket recommendation, not on its merits. |
| Dropping a matrix leg | either | Cuts cost proportionally and cuts coverage proportionally. Not a cost finding unless the leg is provably redundant; that argument belongs to the test suite, not the audit. |
| `/timing` as the measurement | either | `billable.<OS>.total_ms` reads 0 on every repo probed, public and private. See [measurement.md](measurement.md). |
| Blanket `**.md` in `paths-ignore` | either | Package metadata can make a README a build input. See trap 4 in [traps.md](traps.md). |
| Reading GitHub's glob docs instead of probing | either | The implementation is more lenient than the prose. See trap 6. |
| A shallow checkout to save fetch time | either | It costs coverage, silently. A shallow submodule checkout (`actions/checkout`'s default depth, with `submodules: recursive`) turned 8 of power-map's pin-ancestry tests into skips that read green; `fetch-depth: 0` cost about 23 MiB of history. See trap 9 in [traps.md](traps.md). |
| Local-gate attestation | public; `job-count`; bot or fork PRs | Live only in a private, `duration`-shaped repo whose PRs come from people who just ran the same gate locally ([#602](https://github.com/gregoryfoster/skills/issues/602)). Rejected on power-map because it's public, so there was nothing to save. Its costs, and the step that ships it: [below](#local-gate-attestation-where-it-is-live). |
| Cutting minutes on a public repo | public, standard runners | No minute is billed, so a cut saves no money by itself ([#597](https://github.com/gregoryfoster/skills/issues/597)). CannObserv/power-map's census read 65 min over 54 jobs, 50 of them Dependabot's own (event `dynamic`), and invited a path filter whose replay showed 3 false skips out of 3: risk, for nothing. What costs there is PR latency, the owner's concurrent-job limit, shared across its repos, and Dependabot's fan-out. A cut is a lever only through one of those. |

## Local-gate attestation: where it is live

In a private, `duration`-shaped repo, a PR's developer has usually just run
the same gate locally (`shipping-work`'s pre-ship, or `pre-commit run
--all-files`). Running it again on a runner bills the whole duration again for
evidence that already exists. The lever: a green local gate posts a commit
status on the exact head SHA, and CI skips its heavy tier when one is there, or
runs only the cheap tiers (lint, format, guards).

It's live only when all three hold: the repo is **private**, the cost shape is
**`duration`**, and the PRs come from **people** who ran the gate. Measure the
saving with the census before and after; a saving quoted without that is an
estimate.

Its costs, which are why it is opt-in:

- It trusts the operator's machine. Unpinned tools, a dirty venv or local-only
  data can pass locally and fail on a clean runner, and only a clean runner
  proves the lockfile reproduces.
- Dependabot's PRs and forks' PRs come from no local gate, so they still need
  the full run.
- The local gate ran on the branch head, not on the merge with the base that a
  `pull_request` run tests. CI must read the status on
  `github.event.pull_request.head.sha`, since `github.sha` is the merge commit.
- The ship step gains a GitHub write, made with the operator's own `gh`
  login, and the CI job's token needs `statuses: read`.
- It is never a required status by itself: a bot's PR never gets one. Branch
  protection requires the runner job, which reads it.

**Shipped, and opt-in.** `shipping-work`'s `push.sh` does this for a repo
that commits `.skills/attest-local-gate` as `on`: it asks the gate about the
tree before it pushes, then posts `gate/local` = `success` on the pushed SHA
and reads it back ([#688](https://github.com/gregoryfoster/skills/issues/688)).
The knob, the token and the workflow step to copy are in
[its reference](../../shipping-work/references/attestation.md). The step
keeps three rules: read the combined status, never `/statuses`; read
`pull_request.head.sha`, never `github.sha`; and never trust the status for a
bot's PR or a fork's.

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
