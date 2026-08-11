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
| Seam accrual — `seams` | `check-seams.sh`, which is mechanical |
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

**Commit it before the first concurrent run.** Git resolves a merge using the
attributes in the tree being *replayed onto*, so an attribute added after the
fact does not rescue the conflict that motivated it. That is why the installer
tells you to stage both files together, and why `--uninstall` leaves the
attribute behind: it is correct for an append-only ledger whether or not
anything is scheduled.

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
      - uses: actions/checkout@v4
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
      - name: Sweep the seams
        run: |
          bash "$SKILL_SCRIPTS/check-seams.sh" --base HEAD >/tmp/seams.txt 2>&1 || true
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
          # Staged separately, and the row is NOT tolerant of failure. One
          # `git add` over both paths stages NOTHING when either is missing —
          # it exits 128 on the unmatched pathspec — so `|| true` turned a
          # missing ratio file into "no new row" and discarded the measurement
          # silently, which is the failure this whole job exists to prevent.
          git add -- ".skills/context-metrics.jsonl"
          if [ -f .skills/context-token-ratio ]; then
            git add -- .skills/context-token-ratio
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
              echo "::error::If the ledger conflicted, .gitattributes is missing"
              echo "::error::`.skills/context-metrics.jsonl merge=union` — re-run install-cadence.sh."
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
- **Its drift warning inherits [#126](https://github.com/gregoryfoster/skills/issues/126).**
  `measure-context.sh` hardcodes the 6,000 budget and does not read
  `.skills/context-budget`, though the write guard and the review delta both do.
  A repo that set a custom budget gets warned — and gets a `budget` field on
  every row — against 6,000 instead. Latent today, since the whole cohort runs
  the default; live the moment somebody runs `install-guard.sh --budget N`.
- **It does not fix the arms problem.** Rows carry `skill_version`, so a series
  can still be split by version — but the confounds
  [#118](https://github.com/gregoryfoster/skills/issues/118) names (version
  correlates with time, repo activity drives regrowth) are not addressed by
  having a cadence. They need the covariates that issue proposes.
