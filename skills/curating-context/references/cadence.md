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

The workflow runs `--check-credential` as its first step for exactly this
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
own `--ledger`, the seam sweep's `--base-ledger` and the delta check's — every
one must name one file, because a cadence measuring into one path and staging
another records nothing, and a sweep reading a third finds no predecessor and
reports an empty interval every week. The renderer interpolates one variable
into every one, so they cannot drift through the installer; hand-editing the
rendered workflow is the only way to break it, which is why the file says to
re-run the installer instead. Re-running it without the flag reads the ledger back out of the
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
which side measured more recently — and the cadence bot then only ever pushed
to the default branch (in [`pr` mode](#under-a-pr-only-ruleset-merge_mode-pr)
it pushes a branch of its own), so it was structurally always the side that lost: merging
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

## The delta check

The job's last step runs `record-telemetry.sh --repair --dry-run` and turns
any output into a `::warning::`, with the JSON lines beneath it. The union merge
above is what makes it necessary: a curation branch that merges or rebases the
default branch in while it is open puts this job's row between rows it was
never measured beside, and nothing conflicts. The row that now follows a new
neighbour keeps deltas describing the old one. Three of the first cohort's
thirteen ledgers had one when the #319 sweep looked
([#325](https://github.com/gregoryfoster/skills/issues/325)).

Phase 7 repairs the interleave a branch's own merge causes
([telemetry.md](telemetry.md#merging-the-default-branch-in)); this step catches
the one no branch can, a row that lands after the branch's last merge and is
interleaved by the curation's own merge. It **reports and never repairs**: the
job appends and never rewrites, and the repair is a commit for whoever reads
the warning.

`--check` reports a workflow rendered before this as `delta check: STALE` and
exits 3, the same marker the drift report carries.

## A SHA-pinned checkout, and what a re-render keeps

The job holds `contents: write` and `ANTHROPIC_API_KEY`, and `pull-requests:
write` under `pr`, so the template renders `actions/checkout` as a full commit
SHA with its version in a comment, `@<sha40> # vX.Y.Z`, never a tag whoever
controls it can move ([#675](https://github.com/gregoryfoster/skills/issues/675)).
The SHA is measured with `git ls-remote https://github.com/actions/checkout
refs/tags/v<version>`, not copied.

Dependabot's `github-actions` ecosystem bumps every `uses:` under
`.github/workflows/`, this generated file included, and a re-render used to
write the template's pin back over the bump without a word
([#373](https://github.com/gregoryfoster/skills/issues/373)). So a
re-render:
- keeps an installed SHA pin verbatim, with its comment;
- keeps an installed tag above the template's version (`@v8`, `@v7.1`), since
  the pin would be a downgrade;
- pins an installed tag at or below it (`@v7` reads as 7.0.0), with a
  `pinned:` line. This one can step back. A bare `@v7` runs the newest v7
  release, so once checkout ships one past the template's pin, pinning moves
  the job to an older commit until Dependabot or the next skills bump moves
  the pin. Both lines say so. The trade is taken because the moving tag is
  the hazard #675 removes, and a known commit that is a release behind is
  safer than one whoever controls the tag can swap;
- replaces a ref that is neither (a branch, a pre-release tag), with a
  `replaced:` line on stderr.

`--check` prints a `checkout pin:` line saying which it is: `tag` for a tag
the re-render pins, `DOWNGRADE` for the last case. On a kept tag it says the
tag can still move, and on a kept SHA pin it names a comment below the
template's version, or one that gives the template's version over a
different commit. It is not a guarantee, so it never sets exit 3. `--print`
reads the installed line too, which is what lets this repo's parity test pass
a Dependabot bump of `context-cadence.yml`.

That bump moves the installed file, never the template inside
`install-cadence.sh`, so `test_cadence_checkout_pin.py` holds the template's
`TEMPLATE_CHECKOUT_SHA` and `TEMPLATE_CHECKOUT_VERSION` to this repo's
installed line. The push that lands the bump moves both, and
`cadence/workflow.md`'s copy, with it. That is how the pin reaches consumers:
through the submodule refresh, then a re-render.

## `--check` says when a re-render would change the file

Each line above checks one known half, so a template change none of them
names read as current. The checkout pin moving from `@v5` to `@v7` was the case
found, on a host whose workflow went through weeks of skill bumps unchanged
([#647](https://github.com/gregoryfoster/skills/issues/647)). `--check` now
ends the workflow's lines with `re-render:`. It renders what `--print` would
write, keeping the installed schedule and ledger, and compares that with the
installed file:
- `none` means a re-render writes the file back unchanged;
- `behind` gives how many lines a re-render would change;
- `unknown` means the render itself failed.

A Dependabot-moved pin isn't drift, since a re-render keeps it (#373). Nor is
a custom `--cron`: a plain re-run keeps the installed schedule too (#664), so
`behind` names a plain re-run. Like the pin line, `re-render:` never sets the exit code, because
consumers' CI may call `--check` and a newer template is not a broken install.
`managing-skills`' refresh hook reads `behind` after a bump, and
`shipping-work`'s doc-check does too on a branch that changes
`.skills/merge_mode`. Each says to re-render, and neither re-renders.

The knob is read from the primary checkout (#612), so a plain re-render on
the branch that flips it renders the old mode. `--merge-mode pr|direct`
renders for the mode named instead
([#674](https://github.com/gregoryfoster/skills/issues/674)), so that branch
carries its own re-render and the knob and its render land in one PR: commit
the knob, run `install-cadence.sh --merge-mode <mode>` there, and `--check
--merge-mode <mode>` reads `re-render: none`. The knob is still read: `--check`
judges the workflow against the flag and names what the primary reads under
its `merge mode:` line, and an install or `--print` says so on stderr when
the two differ. An unusable knob isn't refused under the flag, which reads
nothing from it. The doc-check reads the knob as the branch commits it and
runs that `--check`, so it says when the branch already carries the render.
Re-rendering after the merge still works, but until it lands the default
branch holds a knob its workflow wasn't rendered for: under `pr`, a scheduled
run in that window pushes directly, and a PR-only ruleset refuses it.

## Under a PR-only ruleset: `merge_mode` `pr`

A default branch with a PR-only ruleset and no bypass refuses this job's push,
and a repository ruleset won't take the GitHub Actions app as a bypass actor.
So the push loop retried the refusal three times as a non-fast-forward and the
week's row was lost
([#560](https://github.com/gregoryfoster/skills/issues/560)). The answer is
[#342](https://github.com/gregoryfoster/skills/issues/342)'s knob,
`.skills/merge_mode`, with no knob of its own: under such a rule a `direct`
ship is refused too, so a repo that needs one needs the other.

- **`direct` or absent: nothing changes.** `install-cadence.sh` renders
  today's workflow, byte for byte, and the job does what it did.
- **`pr`: the same workflow plus five insertions,** none removed or
  rewritten. `pull-requests: write`; a `Read the merge mode` step before the
  credential preflight, which reads the committed knob with `merge-mode.sh`'s
  grammar and fails on an unusable one, and a `Hold the run to the default
  branch` step after it (below); a `Take in the measurement PR's
  rows` step after the preflight (below); `GH_TOKEN` on the commit step; and,
  after `# --- push ---`, a path that pushes `context/weekly-measurement` and
  opens or updates one PR into the default branch.
- **Only on the default branch.** The PR path merges the measurement
  branch into the branch the run is on and pushes the result, and
  `workflow_dispatch:` can name any branch. Dispatched on `feature/x`, the
  row carried `feature/x`'s commits into the open PR into the default
  branch, unreviewed under a bot's title, and opened a second PR into
  `feature/x` ([#683](https://github.com/gregoryfoster/skills/issues/683)).
  So a `pr` run stops before the credential is spent unless it is on the
  default branch, read from `origin` (`git ls-remote --symref origin HEAD`)
  rather than the event, and unread is a refusal. The run's full
  `GITHUB_REF` is compared with `refs/heads/<default>`, so a tag named like
  the default branch doesn't pass. It binds the workflow as
  rendered: a branch that edits its own copy is past it, as anyone with
  write access already is. `direct` is not held. Its row lands on the
  dispatched branch itself and is reviewed in that branch's own PR; no
  branch's commits reach another's.
- **One PR, not one a week.** While the branch carries rows no finished PR
  took (an open PR's, or a run's whose PR was never opened), each run merges
  its row *into* that branch. Those rows stay first and in order, the default
  branch comes in with the row, and the push is a fast-forward, so the PR
  never conflicts with its base. When no PR is open and the branch's tip was
  the head of a PR that merged or closed, the branch restarts at the default
  branch plus the row. A merged PR's rows are already there, and a squash
  merge would otherwise carry them twice; a closed PR was a no. An open PR
  always wins, even when a closed one shares its head. Only this repo's PRs
  count: `gh pr list --head` matches a branch *name*, so a fork's PR from a
  branch of the same name is filtered out by `isCrossRepository`.
- **Each row is measured after the one before it.** The job checks out the
  default branch, whose ledger lacks the open PR's rows. Measured there,
  every row after the first took its `delta_days` and `delta_tokens`, and
  the seam sweep its `--base-ledger` interval, from the last *merged* row:
  [the delta check](#the-delta-check) warned on every run while the PR was
  open, and the merge landed the wrong deltas. So when the push would keep
  the branch, the take-in step merges it in before the sweep, deciding
  which PR with the fragment the push runs, written once in the installer
  ([#683](https://github.com/gregoryfoster/skills/issues/683)). It merges with `--no-commit`: `HEAD`
  stays the default branch's tip, so the row's `repo_commit` is a commit
  that branch keeps even after a squash merge, and the commit step records
  the merge with the row. The push decides again, since a PR can merge
  mid-run. When the PR it took in has ended by then (squash-merged, with
  or without its branch deleted, or closed), the row is refused. Pushed,
  it would have reopened those rows in a new PR whose merge base is the old
  default tip, the squash's rows shown again; reproduced on
  [#683](https://github.com/gregoryfoster/skills/issues/683). A fresh
  run measures after them: dispatch it (`gh workflow run
  context-cadence.yml`) or let the next scheduled run, never GitHub's
  *Re-run jobs*, which reuses the run's `GITHUB_SHA`, so checkout gives it
  the commit from before the merge again. A PR merged with a merge commit
  is the exception: its tip is in the default branch's history, so the
  branch restarts with the row merged into the default branch's new tip.
  Into it, as the open-PR path merges into the PR's branch: the row then
  follows any row that landed mid-run, and the PR has one merge base, the
  default tip, so its diff is the row alone. `record-telemetry.sh --repair` after the fact was the other way,
  and it can't do this: it rewrites deltas, never the observed `seams`.
- **A refused push is reported once.** On the PR's branch a refusal is a
  rule or a concurrent push, not a race a rebase fixes. A `GH013` or
  protected-branch refusal is named as one, and nothing is retried.

**The knob is read twice, on purpose.** The permissions block is static, so
the installer reads the primary checkout's knob and renders by it: widening
the token for every consumer would have changed every direct repo's
workflow. A `pr` render then follows the *committed* knob at run time.
Switched back to `direct`, it pushes to the default branch without a
re-render, and `--check` prints a `merge mode:` line saying so. Switched to
`pr` under a direct render, the runs keep pushing to the default branch, so
`--check` reports `STALE` and exits 3. Re-running the installer re-renders
either way. The job reads the checked-out file, so a `pr` knob not committed
as it reads (untracked, only staged, or edited after a `direct` commit)
renders the PR path and then runs `direct`; the installer and `--check` say
so.

**What GitHub needs, and what it won't do** [GitHub's documented behaviour;
not measured here]:

- **Actions must be allowed to open PRs:** Settings → Actions → General →
  Workflow permissions → *Allow GitHub Actions to create and approve pull
  requests* (an organization can hold it off). Off, the branch is still
  pushed, the job fails naming the setting, and the next run keeps that row.
- **A PR opened with `GITHUB_TOKEN` starts no `pull_request` workflow,** and
  neither does a later run's push to it. A required check never reports, so a
  ruleset requiring one won't merge the PR until a human acts. The remedy is
  in the PR's body: close and reopen it, which a human does and which starts
  the checks. *Known limit:* a GitHub App token would avoid it, at the cost
  of a secret this job doesn't otherwise need.
- **The late merge is safe where git merges it, not on GitHub's button.** The
  union attribute is in the tree, and the runner defines the other two
  drivers, so every merge *this job* makes is clean. GitHub's merge has no
  config, so `context-counts` can't run there, and its handling of `union` is
  undocumented. If the PR shows a conflict, run the workflow by hand: its
  merge brings the default branch in with every driver.

## The workflow

The rendered job, step by step, with the annotations that explain each one —
including why the pattern it follows is departed from in one place, and what
the pin between it and `install-cadence.sh` is protecting:
[cadence/workflow.md](cadence/workflow.md). What the job deliberately does
*not* do is below.

## Stagger the cron across the cohort

Twelve repos all firing at `0 15 * * 1` produce twelve simultaneous
`count_tokens` bursts and twelve commits in one minute. `install-cadence.sh`
derives a per-repo offset from the repo name so the cohort spreads across the
window without anybody choosing twelve times. Pass `--cron` to override. A
re-run keeps an installed schedule, even a slot derived under an older formula
or repo name, and says when it differs from today's slot. `--cron derived`
moves back to that slot (#664).

GitHub also delays scheduled workflows under load and drops them on repos idle
for 60 days, so treat the series as approximately weekly. `delta_days` records
what actually happened, which is why regrowth is normalised by it rather than
assumed per-week.

## What this does not do

- **It does not curate.** No agent, no judgement, and no PR beyond `pr`
  mode's measurement PR. When a row shows the
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
