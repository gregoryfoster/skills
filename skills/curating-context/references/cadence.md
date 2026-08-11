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
The row it writes is a `baseline` row — the surface as found, no edits — which is
exactly what `record-telemetry.sh --baseline` exists to record.

This also keeps the `runs` column honest: `baseline` rows are states, not runs, so
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

## The workflow

Follows the house scheduled-job pattern from
[vendoring-openapi-client's live-drift guard](../../vendoring-openapi-client/references/live-drift.md):
`schedule` plus `workflow_dispatch`, `continue-on-error`, and a failure mode that
is "drifted", never "broken". This job **never blocks a merge** — it does not run
on pull requests at all. The PR-time gate is a separate concern
([#88](https://github.com/gregoryfoster/skills/issues/88)).

`install-cadence.sh` renders this; the template is here so the rendered file can
be read against its rationale.

```yaml
name: context-cadence

# Weekly measurement of the agent-context surface (#118). Writes one `baseline`
# telemetry row so regrowth, budget adherence and seam accrual accumulate as a
# per-repo series. It does NOT curate — curation needs judgement and stays
# agent-triggered, prompted by what these rows show.

on:
  schedule:
    - cron: '<CRON>'      # weekly; stagger across the cohort, see below
  workflow_dispatch:

# contents: write because the job appends one JSONL line and pushes it. That is
# telemetry, not code: append-only, one line, and the ledger is the artifact the
# whole cohort design reads.
permissions:
  contents: write

concurrency:
  group: context-cadence
  cancel-in-progress: false

jobs:
  measure:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    # Surfacing a measurement must never look like a broken repo.
    continue-on-error: true
    steps:
      # submodules: recursive is load-bearing. The skill is vendored as a
      # submodule under skills-vendor/ and reached through a symlink in
      # .claude/skills/; without this the symlink dangles and every step fails
      # with "No such file or directory".
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

      # FIRST, not last. Without a credential the measurement degrades to an
      # estimate and record-telemetry.sh refuses the append (exit 4), so the job
      # would otherwise do eight minutes of work and record nothing.
      - name: Preflight the credential
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: bash "$SKILL_SCRIPTS/measure-context.sh" --check-credential

      # Exits 3 when there are new seams, which is a finding rather than a
      # failure here — the count goes on the row either way. The two counts are
      # the last two lines it prints, named exactly as record-telemetry's flags.
      - name: Sweep the seams
        run: |
          bash "$SKILL_SCRIPTS/check-seams.sh" --base HEAD >/tmp/seams.txt 2>&1 || true
          tail -20 /tmp/seams.txt
          echo "SEAMS=$(sed -n 's/^seams: \([0-9]*\)$/\1/p' /tmp/seams.txt | tail -1)" >>"$GITHUB_ENV"
          echo "SEAMS_ACKED=$(sed -n 's/^seams_acked: \([0-9]*\)$/\1/p' /tmp/seams.txt | tail -1)" >>"$GITHUB_ENV"

      # Measured ONCE. The drift report below reads this file rather than
      # re-running --exact, which would double the count_tokens calls and could
      # disagree with the row that was just recorded.
      - name: Measure and record
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          bash "$SKILL_SCRIPTS/measure-context.sh" --exact >/tmp/ctx.json
          bash "$SKILL_SCRIPTS/record-telemetry.sh" --baseline \
              ${SEAMS:+--seams "$SEAMS"} ${SEAMS_ACKED:+--seams-acked "$SEAMS_ACKED"} \
              --note "scheduled cadence" --print-trend </tmp/ctx.json

      - name: Commit the row
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if git diff --quiet -- .skills/context-metrics.jsonl; then
            echo "no new row — nothing to commit"; exit 0
          fi
          git add .skills/context-metrics.jsonl .skills/context-token-ratio
          git commit -m "chore: weekly context measurement"
          git push

      # Warnings, not a failing gate. The row is the point; this is the nudge.
      # Reads the measurement already taken — never re-measures.
      - name: Report drift
        if: always()
        run: |
          python3 - /tmp/ctx.json <<'EOF'
          import json, sys
          p = json.load(open(sys.argv[1]))["policy"]
          if p["over_budget"]:
              print(f"::warning::{p['path']} is {p['tokens']} tokens against a "
                    f"{p['budget']} budget. Run `curate context` in this repo.")
          EOF
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
