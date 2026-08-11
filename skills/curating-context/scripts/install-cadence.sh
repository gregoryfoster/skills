#!/usr/bin/env bash
# install-cadence.sh — wire the weekly context measurement into a repo as a
# scheduled GitHub Actions workflow.
#
# The thing on the clock is a MEASUREMENT, not a curation. It records one
# `baseline` telemetry row so regrowth, budget adherence and seam accrual
# accumulate as a per-repo series; curation needs judgement and stays
# agent-triggered, prompted by what these rows show. Rationale, and the template
# this renders with its annotations: references/cadence.md (#118).
#
# Idempotent: a re-run rewrites the workflow in place and reports whether
# anything changed. It never commits.
set -euo pipefail

usage() {
  cat <<'USAGE'
install-cadence.sh — install the weekly context-measurement workflow

Usage:
  install-cadence.sh [options]

Options:
  --cron EXPR      Five-field cron for the schedule. Default: a weekly slot
                   derived from the repo name, so a twelve-repo cohort spreads
                   across the window instead of firing at once.
  --file PATH      Workflow path. Default: .github/workflows/context-cadence.yml
  --check          Report whether the workflow is installed; change nothing.
                   Exit 0 installed, 3 not installed.
  --uninstall      Remove the workflow file.
  --print          Write the rendered workflow to stdout and exit; touch nothing.
  -h, --help       Show this help and exit 0.

What it does:
  Renders .github/workflows/context-cadence.yml, which weekly:
    1. checks out with submodules (the skill is reached through a symlink into
       skills-vendor/, which dangles without them),
    2. preflights the credential FIRST,
    3. sweeps seams, measures once with --exact, records a `baseline` row,
    4. commits that one JSONL line to the default branch,
    5. emits ::warning:: when the surface is over budget or seams accrued.

  It never runs on pull_request and never blocks a merge. Turning the budget
  into a merge gate is a different job (#88), with its own sequencing rule.

REQUIRED, or the job records nothing at all:
  ANTHROPIC_API_KEY must exist as a repository secret. Without it --exact
  degrades to an offline estimate and record-telemetry.sh REFUSES the append
  (exit 4) against a ledger of exact rows. The failure is silence, not a bad
  number, which is why the workflow preflights the credential in its first step.

    gh secret set ANTHROPIC_API_KEY --repo <owner>/<repo>

It does not commit. Review the diff and commit with your normal gate.

Exit codes:
  0  installed, uninstalled, unchanged, or printed
  1  usage error, or not in a git repo
  3  --check only: the workflow is not installed
USAGE
}

CRON=""
WF_PATH=".github/workflows/context-cadence.yml"
MODE="install"

while [ $# -gt 0 ]; do
  case "$1" in
    --cron) CRON="${2:?--cron needs a cron expression}"; shift 2 ;;
    --file) WF_PATH="${2:?--file needs a path}"; shift 2 ;;
    --check) MODE="check"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --print) MODE="print"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Five whitespace-separated fields. Deliberately shallow — the point is to catch
# a prose string or a six-field spec, not to reimplement cron.
if [ -n "$CRON" ]; then
  set -- $CRON
  [ "$#" -eq 5 ] || {
    echo "ERROR --cron needs five fields (got $#): '$CRON'" >&2
    echo "      e.g. --cron '0 15 * * 1'" >&2
    exit 1; }
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR not inside a git repository" >&2; exit 1; }
WF="$ROOT/$WF_PATH"

if [ "$MODE" = "check" ]; then
  if [ -f "$WF" ]; then
    echo "installed: $WF_PATH"
    sed -n 's/^ *- cron: *\(.*\)$/  schedule: \1/p' "$WF"
    exit 0
  fi
  echo "not installed: no $WF_PATH"
  exit 3
fi

if [ "$MODE" = "uninstall" ]; then
  if [ -f "$WF" ]; then
    rm -f "$WF"
    echo "uninstalled: removed $WF_PATH"
  else
    echo "nothing to remove: no $WF_PATH"
  fi
  echo "note: the recorded rows were left in place — they are the series."
  exit 0
fi

# Stagger the cohort. Twelve repos on one cron produce twelve simultaneous
# count_tokens bursts and twelve commits in the same minute; worse, they all
# land in GitHub's most contended slot (the top of the hour), where scheduled
# runs are delayed most. Derive an offset from the repo name so the spread needs
# no per-repo decision and is stable across re-runs of this installer.
if [ -z "$CRON" ]; then
  # The ORIGIN basename, not the checkout directory. #102 fixed this same latent
  # bug in record-telemetry.sh, where a worktree path recorded
  # `feat-161-curating-context` as the repo; here it would only make two repos
  # draw the same slot, but the precedence should not differ between scripts.
  ORIGIN="$(git remote get-url origin 2>/dev/null)" || ORIGIN=""
  if [ -n "$ORIGIN" ]; then
    NAME="${ORIGIN%/}"; NAME="${NAME##*[/:]}"; NAME="${NAME%.git}"
  else
    NAME="$(basename "$ROOT")"
  fi
  # cksum is POSIX and stable across platforms, unlike $RANDOM or md5/md5sum.
  H="$(printf '%s' "$NAME" | cksum | cut -d' ' -f1)"
  MIN=$(( H % 60 ))
  HOUR=$(( 13 + (H / 60) % 6 ))   # 13:00-18:00 UTC — inside a working day
  DOW=$(( 1 + (H / 360) % 5 ))    # Mon-Fri; weekends delay hardest
  CRON="$MIN $HOUR * * $DOW"
fi

render() {
  cat <<YAML
name: context-cadence

# Weekly measurement of the agent-context surface (#118). Records one \`baseline\`
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
    - cron: '$CRON'
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
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Heal vendored symlinks
        run: '[ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh'

      - name: Resolve the skill scripts
        run: |
          N=curating-context S=measure-context.sh SD=
          for d in scripts ".claude/skills/\$N/scripts" "skills/\$N/scripts"; do
            [ -f "\$d/\$S" ] && { SD="\$d"; break; }
          done
          echo "SKILL_SCRIPTS=\${SD:?curating-context scripts not found}" >>"\$GITHUB_ENV"

      # FIRST, not last: without a credential every later step does its work and
      # the append is refused at the end.
      - name: Preflight the credential
        env:
          ANTHROPIC_API_KEY: \${{ secrets.ANTHROPIC_API_KEY }}
        run: bash "\$SKILL_SCRIPTS/measure-context.sh" --check-credential

      # Exits 3 when there are new seams, which is a finding rather than a
      # failure here — the count goes on the row either way.
      - name: Sweep the seams
        run: |
          bash "\$SKILL_SCRIPTS/check-seams.sh" --base HEAD >/tmp/seams.txt 2>&1 || true
          tail -20 /tmp/seams.txt
          echo "SEAMS=\$(sed -n 's/^seams: \([0-9]*\)\$/\1/p' /tmp/seams.txt | tail -1)" >>"\$GITHUB_ENV"
          echo "SEAMS_ACKED=\$(sed -n 's/^seams_acked: \([0-9]*\)\$/\1/p' /tmp/seams.txt | tail -1)" >>"\$GITHUB_ENV"

      # Measured ONCE — the drift report below reads this file rather than
      # re-running --exact, which would disagree with the row just recorded.
      - name: Measure and record
        env:
          ANTHROPIC_API_KEY: \${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          bash "\$SKILL_SCRIPTS/measure-context.sh" --exact >/tmp/ctx.json
          bash "\$SKILL_SCRIPTS/record-telemetry.sh" --baseline=scheduled \\
              \${SEAMS:+--seams "\$SEAMS"} \${SEAMS_ACKED:+--seams-acked "\$SEAMS_ACKED"} \\
              --print-trend </tmp/ctx.json

      - name: Commit the row
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          # Staged separately, and the row is NOT tolerant of failure. One
          # \`git add\` over both paths stages NOTHING when either is missing —
          # it exits 128 on the unmatched pathspec — so \`|| true\` turned a
          # missing ratio file into "no new row" and discarded the measurement
          # silently, which is the failure this whole job exists to prevent.
          git add -- .skills/context-metrics.jsonl
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
          BRANCH="\$(git branch --show-current)"
          for attempt in 1 2 3; do
            git push origin "\$BRANCH" && exit 0
            echo "push rejected (attempt \$attempt) — rebasing onto origin/\$BRANCH"
            git pull --rebase --autostash origin "\$BRANCH"
          done
          echo "::error::could not push the measurement row after 3 attempts"
          exit 1

      # always(), so a failed push does not swallow the warnings. Those are the
      # only output a human reads, and losing them on exactly the runs that went
      # wrong inverts the intent.
      - name: Report drift
        if: always()
        run: |
          python3 - /tmp/ctx.json <<'PY'
          import json, sys
          p = json.load(open(sys.argv[1]))["policy"]
          if p["over_budget"]:
              print(f"::warning::{p['path']} is {p['tokens']} tokens against a "
                    f"{p['budget']} budget. Run \`curate context\` in this repo.")
          PY
          if [ "\${SEAMS:-0}" -gt 0 ]; then
            echo "::warning::\$SEAMS unacknowledged cross-reference seam(s). Run \\\`curate context\\\`."
          fi
YAML
}

if [ "$MODE" = "print" ]; then
  render
  exit 0
fi

mkdir -p "$(dirname "$WF")"
if [ -f "$WF" ] && render | cmp -s - "$WF"; then
  echo "unchanged: $WF_PATH is already current (schedule: $CRON)"
  exit 0
fi
EXISTED=no
[ -f "$WF" ] && EXISTED=yes
render >"$WF"
if [ "$EXISTED" = yes ]; then
  echo "updated: $WF_PATH (schedule: $CRON)"
else
  echo "installed: $WF_PATH (schedule: $CRON)"
fi

cat <<NEXT

The secret is REQUIRED — without it this job records nothing, silently:
  gh secret set ANTHROPIC_API_KEY

Not committed — review and commit with your normal gate:
  git add $WF_PATH
  git commit -m "chore: schedule the weekly context measurement"

Then run it once by hand before trusting the schedule:
  gh workflow run context-cadence.yml
NEXT
