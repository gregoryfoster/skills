# The cadence — putting a measurement on the clock

This skill named "the scheduled weekly run" in six places, and its telemetry,
trend shapes and `delta_days` field all assumed one, but it shipped no
scheduling mechanism and no cohort repo had one. Ten of twelve repos held
exactly one ledger row. A design that compares a repo against its own past
needs a past, and there was none accumulating
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
falls back to an offline estimate, and `record-telemetry.sh` then **refuses the
append and exits 4** against a ledger of exact rows — correctly, because an
estimate and an exact count are not comparable. A scheduled job without the
secret therefore produces *nothing*, every week, silently, until somebody opens
the Actions tab.

The workflow below runs `--check-credential` as its first step for exactly this
reason: fail loudly at second zero rather than at the last step of the job.

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

The same weekly run rewrites two more files, and they need a *different* merge.
`measure-context.sh --exact` refreshes `.skills/context-token-ratio` and
`.skills/context-token-counts`, the workflow stages all three paths, and for a
while the installer protected one — so the calibration files lost exactly the
race the ledger was protected against (#173). Union is the wrong answer here:
it would leave two values for one path and the estimators would read whichever
they hit first, which is worse than a conflict because nothing reports it.
These are pure functions of the tree at measurement time, so on a collision the
answer is always *recompute*, never *reconcile*:

```
.skills/context-token-ratio merge=ours
.skills/context-token-counts merge=ours
```

**And `ours` is the one merge driver git does not define for you.** `union` is
built in, which is why the ledger line above works the moment it lands. `ours`
is not, and an attribute naming a driver that does not exist is inert — git
falls back to the 3-way merge and leaves conflict markers in a file that is
regenerated and must never be hand-merged. The driver is one line, and it is
what makes the two entries above mean anything:

```
git config merge.ours.driver true
```

`install-cadence.sh` sets that in the clone it runs in, and it cannot do more:
**git config is not versioned**, so unlike the attributes it does not travel
with the commit. A fresh clone of a correctly installed repo therefore arrives
protected on paper and unprotected in fact, which is why `--check` reports the
driver as its own line instead of folding it into the calibration one. The tree
and the config are two independent ways to lose the same file, and in the second
cadence pilot the audit read green on the attribute while the mechanism behind
it was absent (#192). Run the installer — or the one-liner — once per checkout.

`--uninstall` removes the attribute along with the workflow, leaving
`.gitattributes` as it found it — the file itself goes only if nothing else was
in it. The recorded rows stay either way: they are the series, and removing the
mechanism that adds to it is not a reason to discard what it already collected.

It leaves `merge.ours.driver` set, deliberately. The driver is generic, any
other `merge=ours` rule in the repo depends on it, and with nothing pointing at
it a defined driver simply never runs — so unsetting it could only break
attributes this installer never wrote.

## What the scheduled `seams` count means

The cadence used to sweep with `--base HEAD`. `check-seams.sh` reads the base
policy file with `git show "$BASE:$REL"` and compares it against the policy file
in the **working tree**, so on a clean CI checkout those are the same content
and the diff is empty. *moved-title* — references to a title that left the
policy file — is computed from that diff and was therefore **zero in every
scheduled run, in every repo, forever, by construction**. A curation that
relocated a section and left danglers behind contributed nothing to any weekly
row, because by the next run the relocation was already in `HEAD`
([#169](https://github.com/gregoryfoster/skills/issues/169)).

Do not read that as a promise that the next scheduled row now re-reports a
curation's own relocations. Since [#206](https://github.com/gregoryfoster/skills/issues/206)
a curation row's `repo_commit` is backfilled to the commit that ships it, so
the next interval starts *after* that work — deliberately, because Phase 6.5
already judged it. The class's live scope is relocations made outside a
`curating-context` run.

**Two classes, not one.** The source sweep is gated on the same set — `if src
and moved:` — so an empty `moved` skipped every tracked file outside the docs
tree and the report printed *"N tracked source file(s) not swept"*. The
scheduled run had never opened a source file in any repo, which also takes
`source-back-reference` with it: the class [#113](https://github.com/gregoryfoster/skills/issues/113)
added after 16 stale docstrings shipped across 13 files under a clean exit.

The sweep now passes `--base-ledger`, which takes its base from the **newest
ledger row carrying a `repo_commit`** — the state of the tree at the last
recorded measurement. So each week's sweep spans the interval since the week
before.

**`seams` is a sum of two different quantities, and always was.** Widening the
base widens only half of it:

| Class | Scope |
|---|---|
| back-references — the policy file named in a live reference doc | **standing**: read off the live surface, identical under any base |
| duplicate headings, provenance baked into a heading | **standing**, likewise |
| moved-title — a reference to a title that left the policy file | **interval**: since the previous measurement |
| source refs in tracked source outside the docs tree | **interval**: gated on the same "something moved" set |

So the honest reading of a scheduled row is *"seams standing on the surface,
plus seams accrued since the last measurement"* — not a pure accrual, and not a
pure state. `check-seams.sh --help` says the same thing next to the exit codes,
and the report's `seam_base:` line names the revision each count started from.

**The interval half is a flow, not a stock — sum it, do not read the latest.**
A moved-title hit is a *pulse*. If week 2 reports one and nobody fixes it, week
3's base is week 2's commit, the title left the policy file before that, and the
hit is gone from week 3's count with the dangler still in the tree. The standing
half behaves the opposite way: a back-reference persists in every row until
somebody fixes or acknowledges it. So a reader comparing two rows is comparing a
stock plus a flow, and anything aggregating `seams` across a series should
**sum** the interval contribution rather than take the latest value.

**The first run has no predecessor, and says so.** With no ledger, no rows, or
no row carrying a `repo_commit` — which is every repo adopting the cadence, and
every ledger written before the field existed — the base is `HEAD`, the interval
is empty, the two interval classes contribute nothing, and the report prints a
`note:` saying exactly that. The row that run feeds records its own
`repo_commit`, so the *second* scheduled run is the first one with a real
interval. A recorded commit that is not in the repo's history — a rewrite, a
shallow clone — falls back the same way with a `WARN` naming the commit, rather
than failing the sweep and losing the classes that do not need a base.

**The interval start is derivable, not stored twice.** The row records only
`repo_commit`; the base a given row's sweep used is the *previous* row's
`repo_commit`, and `null` there means that row's sweep had an empty interval.
The one case where that inference is wrong is the loud fallback above.

## The workflow

Follows the house scheduled-job pattern from
[vendoring-openapi-client's live-drift guard](../../vendoring-openapi-client/references/live-drift.md):
`schedule` plus `workflow_dispatch`, and drift surfaced as a warning rather than
a gate. This job **never blocks a merge** — it does not run on pull requests at
all. The PR-time gate is a separate concern
([#88](https://github.com/gregoryfoster/skills/issues/88)).

It departs from that pattern in one place: **no `continue-on-error`.** The
live-drift guard uses it because a drifted upstream is not the consumer's fault.
Here a failing job means the repo is not measuring at all, which is exactly what
somebody needs to see — and swallowing it would undo the credential preflight's
whole purpose. Drift itself never fails the job, so red always means the
mechanism broke, never that the surface grew.

This block is the **rendered output** of `install-cadence.sh --print`, cron
placeholder aside, and a test pins them to each other — an annotated copy that
drifts from what actually installs is worse than no copy.

```yaml
name: context-cadence

# Weekly measurement of the agent-context surface (#118). Records one `baseline`
# telemetry row so regrowth, budget adherence and seam accrual accumulate as a
# per-repo series.
#
# It does NOT curate. Curation needs judgement — classify each section, verify
# each claim, decide what relocates where — and that stays agent-triggered,
# prompted by what these rows show. Rationale and the annotated template:
# curating-context/references/cadence.md
#
# Generated by install-cadence.sh. Re-run it rather than editing by hand.
#
# REQUIRES the ANTHROPIC_API_KEY repository secret. Without it --exact degrades
# to an offline estimate and record-telemetry.sh refuses the append, so the job
# records NOTHING, silently, every week. The credential is preflighted first.

on:
  schedule:
    - cron: '<CRON>'
  workflow_dispatch:

# contents: write because the job appends one JSONL line and pushes it. That is
# append-only telemetry, not code.
permissions:
  contents: write

concurrency:
  group: context-cadence
  cancel-in-progress: false

jobs:
  measure:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    # NOT continue-on-error. A red run here means "this repo is not measuring",
    # which is true and worth seeing — the credential preflight exists to make
    # that failure loud, and continue-on-error would restore the silence at the
    # one level a human actually looks at. Drift is reported as ::warning::
    # below and never fails the job, so red always means the mechanism broke,
    # never that the surface grew.
    steps:
      # submodules: recursive is load-bearing — the skill is vendored under
      # skills-vendor/ and reached through a symlink, which dangles without it.
      # fetch-depth: 0 because the push path rebases when a human commit lands
      # during the measurement, and rebasing on a depth-1 clone lacks the history
      # to replay onto.
      # @v5, not @v4: v4 targets Node 20, which runners now force onto Node 24
      # with a deprecation warning on every run. Twelve repos are about to adopt
      # this template, and sweeping twelve for a warning we could have not
      # written is the avoidable version of the problem (#163).
      - uses: actions/checkout@v5
        with:
          submodules: recursive
          fetch-depth: 0

      - name: Heal vendored symlinks
        run: '[ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh'

      - name: Resolve the skill scripts
        run: |
          N=curating-context S=measure-context.sh SD=
          for d in scripts ".claude/skills/$N/scripts" "skills/$N/scripts"; do
            [ -f "$d/$S" ] && { SD="$d"; break; }
          done
          echo "SKILL_SCRIPTS=${SD:?curating-context scripts not found}" >>"$GITHUB_ENV"

      # FIRST, not last: without a credential every later step does its work and
      # the append is refused at the end.
      - name: Preflight the credential
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: bash "$SKILL_SCRIPTS/measure-context.sh" --check-credential

      # Exits 3 when there are new seams, which is a finding rather than a
      # failure here — the count goes on the row either way.
      #
      # --base-ledger, NOT --base HEAD. On a clean checkout the policy file at
      # HEAD and the one in the working tree are the same content, so the diff
      # is empty and the one class that needs a base — moved-title — was zero
      # in every scheduled run, in every repo, forever (#169). The ledger's
      # newest repo_commit is the previous measurement, so the sweep spans the
      # interval since it. With no such row the report SAYS the interval is
      # empty rather than presenting a standing count as a week's accrual.
      - name: Sweep the seams
        run: |
          bash "$SKILL_SCRIPTS/check-seams.sh" --base-ledger ".skills/context-metrics.jsonl" >/tmp/seams.txt 2>&1 || true
          tail -20 /tmp/seams.txt
          echo "SEAMS=$(sed -n 's/^seams: \([0-9]*\)$/\1/p' /tmp/seams.txt | tail -1)" >>"$GITHUB_ENV"
          echo "SEAMS_ACKED=$(sed -n 's/^seams_acked: \([0-9]*\)$/\1/p' /tmp/seams.txt | tail -1)" >>"$GITHUB_ENV"

      # Measured ONCE — the drift report below reads this file rather than
      # re-running --exact, which would disagree with the row just recorded.
      - name: Measure and record
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          bash "$SKILL_SCRIPTS/measure-context.sh" --exact >/tmp/ctx.json
          bash "$SKILL_SCRIPTS/record-telemetry.sh" --baseline=scheduled \
              --ledger ".skills/context-metrics.jsonl" \
              ${SEAMS:+--seams "$SEAMS"} ${SEAMS_ACKED:+--seams-acked "$SEAMS_ACKED"} \
              --print-trend </tmp/ctx.json

      - name: Commit the row
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          # `ours` is the one built-in merge driver git does NOT define for you:
          # the .gitattributes entry alone is inert, and the calibration files
          # would conflict exactly as if it were absent. `true` is the whole
          # driver — it succeeds without writing, which leaves the branch's copy
          # in place, and the next --exact run recomputes both (#173).
          git config merge.ours.driver true
          # Staged separately, and the row is NOT tolerant of failure. One
          # `git add` over both paths stages NOTHING when either is missing —
          # it exits 128 on the unmatched pathspec — so `|| true` turned a
          # missing ratio file into "no new row" and discarded the measurement
          # silently, which is the failure this whole job exists to prevent.
          git add -- ".skills/context-metrics.jsonl"
          if [ -f .skills/context-token-ratio ]; then
            git add -- .skills/context-token-ratio
          fi
          # The per-file calibration the same --exact run refreshes (#145).
          # Unstaged it would be recomputed and discarded every week, and the
          # estimators between runs would stay on the repo-wide ratio forever —
          # a feature that writes a file nobody ever commits is a feature that
          # does not exist.
          if [ -f .skills/context-token-counts ]; then
            git add -- .skills/context-token-counts
          fi
          if git diff --cached --quiet; then
            echo "no new row — nothing to commit"
            exit 0
          fi
          git commit -m "chore: weekly context measurement"
          # A human push landing during the measurement makes this a
          # non-fast-forward. The ledger is append-only JSONL, so rebasing is
          # safe by construction; without it the week's row is simply lost.
          # GITHUB_REF_NAME is authoritative; git branch --show-current is
          # empty on a detached HEAD and `git push origin ""` fails opaquely.
          BRANCH="${GITHUB_REF_NAME:-$(git branch --show-current)}"
          # --- push ---
          for attempt in 1 2 3; do
            git push origin "HEAD:$BRANCH" && exit 0
            echo "push rejected (attempt $attempt) — rebasing onto origin/$BRANCH"
            # A failing rebase is fatal and must SAY so. As a bare command under
            # bash -e it killed the step before this loop could retry or reach
            # the error line below, making "3 attempts" really one.
            git pull --rebase --autostash origin "$BRANCH" || {
              echo "::error::rebase onto origin/$BRANCH failed — the row was not pushed."
              # Name the file that actually conflicted rather than asserting it
              # was the ledger. Blaming a ledger attribute that is present and
              # correct sent the reader to the one file that was protected,
              # while the calibration files were the unprotected ones (#173).
              #
              # \\` — escaped for BOTH layers. A single \` renders a live
              # backtick into the workflow, where bash runs the attribute line
              # as a command and the substitution eats the very filename this
              # message exists to name (#171). The seams ::warning:: below has
              # always had this right; this line did not.
              git diff --name-only --diff-filter=U | sed 's/^/::error::  conflicted: /'
              echo "::error::Re-run install-cadence.sh, then confirm with --check that"
              echo "::error::every staged path carries a merge attribute:"
              echo "::error::  \`.skills/context-metrics.jsonl merge=union\`"
              echo "::error::  \`.skills/context-token-ratio merge=ours\`"
              echo "::error::  \`.skills/context-token-counts merge=ours\`"
              exit 1
            }
          done
          echo "::error::could not push the measurement row after 3 attempts"
          exit 1

      # always(), so a failed push does not swallow the warnings. Those are the
      # only output a human reads, and losing them on exactly the runs that went
      # wrong inverts the intent.
      - name: Report drift
        if: always()
        run: |
          # always() makes this reachable when the measurement never ran — the
          # missing-credential case, which is exactly the failure this design
          # exists to make legible. A FileNotFoundError stacked on top of the
          # real preflight error helps nobody.
          if [ ! -f /tmp/ctx.json ]; then
            echo "no measurement was taken — see the failing step above"
            exit 0
          fi
          python3 - /tmp/ctx.json <<'PY'
          import json, sys
          p = json.load(open(sys.argv[1]))["policy"]
          if p["over_budget"]:
              print(f"::warning::{p['path']} is {p['tokens']} tokens against a "
                    f"{p['budget']} budget. Run `curate context` in this repo.")
          PY
          if [ "${SEAMS:-0}" -gt 0 ]; then
            echo "::warning::$SEAMS unacknowledged cross-reference seam(s). Run \`curate context\`."
          fi
```

Its header comment restates § *What goes on the clock is a measurement, not a
curation* and § *The prerequisite that makes or breaks it* on purpose: the job
installs into repos where the `.yml` is the only thing anybody reads, with no
path back to this doc. The pin above is what keeps that copy in step.

## Stagger the cron across the cohort

Twelve repos all firing at `0 15 * * 1` produce twelve simultaneous
`count_tokens` bursts and twelve commits in one minute. `install-cadence.sh`
derives a per-repo offset from the repo name so the cohort spreads across the
window without anybody choosing twelve times. Pass `--cron` to override.

GitHub also delays scheduled workflows under load and drops them entirely on
repos with no activity for 60 days, so treat the series as approximately weekly.
`delta_days` records what actually happened, which is why regrowth is normalised
by it rather than assumed to be per-week.

## What this does not do

- **It does not curate.** No agent, no judgement, no PR. When a row shows the
  surface over budget or seams accruing, a human or an agent runs
  `curate context` in that repo.
- **It does not gate a merge.** It never runs on `pull_request`. Turning the
  budget into a merge gate is [#88](https://github.com/gregoryfoster/skills/issues/88),
  and its sequencing rule stands: add the gate per repo only *after* that repo is
  under budget, or it is a permanently-red check people learn to bypass.
- **It does not fix the arms problem.** Rows carry `skill_version`, so a series
  can still be split by version — but the confounds
  [#118](https://github.com/gregoryfoster/skills/issues/118) names (version
  correlates with time, repo activity drives regrowth) are not addressed by
  having a cadence. They need the covariates that issue proposes.
