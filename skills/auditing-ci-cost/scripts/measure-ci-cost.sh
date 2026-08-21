#!/usr/bin/env bash
# measure-ci-cost.sh — per-job billed-minute census for a GitHub Actions repo.
#
# GitHub bills Actions per JOB, rounded UP to the minute, with a one-minute
# floor. No API returns that number: `/actions/runs/{id}/timing` exposes a
# `billable` block whose `total_ms` reads 0 on every repo measured here, public
# and private alike, while the same runs took 35-99 seconds. So the census is
# computed from job timestamps, which is what this script does.
#
# Requires: gh (authenticated), jq.
set -euo pipefail

REPO=""
DAYS=30
ANOMALY_FACTOR=3
FORMAT=text
CACHE=""
# Tracked so a cached census can say which explicitly-passed flag it is
# overriding. A default that happens to match is not an override.
REPO_SET=0
DAYS_SET=0

usage() {
  cat <<'EOF'
Usage: measure-ci-cost.sh [--repo <owner/name>] [--days N] [--anomaly-factor F]
                          [--cache <path>] [--json]

Computes the per-job billed-minute census GitHub Actions charges for, and
separates anomaly days from the structural baseline.

Options:
  --repo <owner/name>   Repository to measure. Default: the current repo,
                        via `gh repo view`.
  --days N              Lookback window in days (default 30). The runs API
                        retains ~90 days, so larger windows silently truncate.
  --anomaly-factor F    Threshold for an anomaly-day candidate (default 3). A
                        day must clear it on BOTH its billed total and its
                        billed min/JOB, each against the median day. Total
                        alone flags a merely busy day, and subtracting one
                        understates the very spend the audit is hunting.
                        Candidates are never dropped silently — raw and
                        structural totals are always printed together.
  --cache <path>        NDJSON job cache. Populated on the first run; reused
                        (no API calls) on later ones. One census costs one API
                        call per run — 200+ on a busy repo — so re-classifying
                        at a different --anomaly-factor must not refetch.
  --json                Emit the full JSON report instead of the text summary.
  --help                Show this message.

Billing model:
  cost = sum over jobs of max(1, ceil(job_seconds / 60))

  Jobs with conclusion `skipped` are EXCLUDED. A skipped job never occupies a
  runner and is never billed, yet it appears in the jobs list with a zero or
  NEGATIVE duration (observed in cli/cli: started_at 21:51:34 against
  completed_at 21:51:27). Feeding one to `max(1, ceil(...))` bills a full
  phantom minute — which is fatal in a repo whose whole spend is job count,
  because the phantom is indistinguishable from a real one-minute job.

  Re-run attempts are INCLUDED (`filter=all`). The jobs endpoint defaults to
  `filter=latest`, which hides every earlier attempt's jobs even though each
  attempt was billed in full.

  Jobs of a run still in flight are EXCLUDED and counted. Their completed_at
  is null, so no duration exists to bill yet; they are reported as "still
  running" rather than guessed at.

Exit codes:
  0  census produced
  1  usage error
  2  a required tool is missing, or an API call failed
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a value}"; REPO_SET=1; shift 2 ;;
    --days) DAYS="${2:?--days needs a value}"; DAYS_SET=1; shift 2 ;;
    --anomaly-factor) ANOMALY_FACTOR="${2:?--anomaly-factor needs a value}"; shift 2 ;;
    --cache) CACHE="${2:?--cache needs a value}"; shift 2 ;;
    --json) FORMAT=json; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq is required but not on PATH" >&2
  exit 2
}

case "$DAYS" in ''|*[!0-9]*) echo "ERROR: --days must be a positive integer" >&2; exit 1 ;; esac
[ "$DAYS" -gt 0 ] || { echo "ERROR: --days must be a positive integer" >&2; exit 1; }
printf '%s' "$ANOMALY_FACTOR" | jq -e 'type == "number" and . > 0' >/dev/null 2>&1 || {
  echo "ERROR: --anomaly-factor must be a positive number (got '$ANOMALY_FACTOR')" >&2
  exit 1
}

SINCE=""
JOBS_NDJSON="$CACHE"
if [ -n "$CACHE" ] && [ -s "$CACHE" ]; then
  echo "Reusing cached job census at $CACHE (no API calls)" >&2
  # The cache's first record states what window it covers, so a re-classified
  # report can never quote a baseline whose provenance it has forgotten.
  META=$(head -n 1 "$CACHE" | jq -r 'if has("meta") then
           "\(.meta.repo)\t\(.meta.since)\t\(.meta.days)" else "" end') || META=""
  if [ -z "$META" ]; then
    echo "ERROR: $CACHE has no meta record — it was not written by this script" >&2
    exit 2
  fi
  CACHED_REPO=$(printf '%s' "$META" | cut -f1)
  CACHED_SINCE=$(printf '%s' "$META" | cut -f2)
  CACHED_DAYS=$(printf '%s' "$META" | cut -f3)
  # A cache answers for the repo and window it was fetched against, so an
  # explicit --repo/--days cannot be honoured here. Say so rather than
  # silently answering a different question than the one asked — a census
  # labelled with the wrong repo is the exact failure this skill exists to
  # find, and it would be reporting it from inside its own tool.
  if [ "$REPO_SET" = 1 ] && [ "$REPO" != "$CACHED_REPO" ]; then
    echo "WARN: --repo $REPO ignored; $CACHE holds $CACHED_REPO. Delete the" \
         "cache or drop --cache to measure $REPO." >&2
  fi
  if [ "$DAYS_SET" = 1 ] && [ "$DAYS" != "$CACHED_DAYS" ]; then
    echo "WARN: --days $DAYS ignored; $CACHE covers ${CACHED_DAYS}d since" \
         "$CACHED_SINCE. Re-fetch to change the window." >&2
  fi
  REPO="$CACHED_REPO"
  SINCE="$CACHED_SINCE"
  DAYS="$CACHED_DAYS"
else
  command -v gh >/dev/null 2>&1 || {
    echo "ERROR: gh is required to fetch a census but is not on PATH" >&2
    exit 2
  }
  if [ -z "$REPO" ]; then
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner) || {
      echo "ERROR: no --repo given and 'gh repo view' failed here" >&2
      exit 2
    }
  fi

  # BSD date (macOS) and GNU date disagree on relative-date syntax; try both.
  SINCE=$(date -u -v-"${DAYS}"d +%Y-%m-%d 2>/dev/null \
          || date -u -d "${DAYS} days ago" +%Y-%m-%d) || {
    echo "ERROR: could not compute the window start date" >&2
    exit 2
  }

  RUNS_JSON=$(mktemp) || exit 2
  # Always fetch into a temp, even when --cache names a destination. A run that
  # dies partway would otherwise leave a cache carrying a valid meta record and
  # a truncated job list, which the next invocation reuses as complete and
  # reports as a baseline. The move below is what makes the cache mean "whole".
  PARTIAL=$(mktemp) || exit 2
  JOBS_NDJSON="$PARTIAL"
  trap 'rm -f "$RUNS_JSON" "$PARTIAL"' EXIT

  echo "Measuring $REPO since $SINCE ..." >&2

  # `created=>=DATE` is a supported filter on this endpoint and is what keeps
  # --paginate from walking the whole retention window. Verified against a repo
  # with 933 total runs: the filter returned 250.
  RUNS_RC=0
  gh api "repos/$REPO/actions/runs?per_page=100&created=%3E%3D$SINCE" --paginate \
    -q '.workflow_runs[] | {run_id: .id, event: .event}' \
    >"$RUNS_JSON" || RUNS_RC=$?
  if [ "$RUNS_RC" -ne 0 ]; then
    echo "ERROR: listing workflow runs for $REPO failed (gh exit $RUNS_RC)" >&2
    exit 2
  fi

  RUN_COUNT=$(grep -c '"run_id"' "$RUNS_JSON" || true)
  if [ "${RUN_COUNT:-0}" -eq 0 ]; then
    echo "ERROR: no workflow runs in the last $DAYS days for $REPO — nothing to measure" >&2
    exit 2
  fi
  echo "  $RUN_COUNT runs; fetching jobs ..." >&2

  jq -nc --arg repo "$REPO" --arg since "$SINCE" --argjson days "$DAYS" \
    '{meta: {repo: $repo, since: $since, days: $days}}' >"$JOBS_NDJSON" \
    || { echo "ERROR: cannot write $JOBS_NDJSON" >&2; exit 2; }
  i=0
  while IFS= read -r run; do
    i=$((i + 1))
    if [ $((i % 25)) -eq 0 ]; then echo "  ... $i/$RUN_COUNT" >&2; fi
    run_id=$(printf '%s' "$run" | jq -r .run_id)
    JOBS_RC=0
    # filter=all, not the default filter=latest: every re-run attempt was billed
    # and the default hides all but the last one.
    gh api "repos/$REPO/actions/runs/$run_id/jobs?filter=all&per_page=100" --paginate \
      -q '.jobs[] | {job: .name, workflow: .workflow_name, attempt: .run_attempt,
                     conclusion: .conclusion, started: .started_at,
                     completed: .completed_at, branch: .head_branch}' \
      | jq -c --argjson run "$run" '. + {event: $run.event, run_id: $run.run_id}' \
      >>"$JOBS_NDJSON" || JOBS_RC=$?
    if [ "$JOBS_RC" -ne 0 ]; then
      echo "ERROR: fetching jobs for run $run_id failed (exit $JOBS_RC) — a partial" \
           "census would understate the baseline, so this is fatal" >&2
      exit 2
    fi
  done <"$RUNS_JSON"

  if [ -n "$CACHE" ]; then
    if mv "$PARTIAL" "$CACHE"; then
      JOBS_NDJSON="$CACHE"
      echo "  cached at $CACHE" >&2
    else
      echo "ERROR: could not write the cache to $CACHE" >&2
      exit 2
    fi
  fi
fi

[ -s "$JOBS_NDJSON" ] || {
  echo "ERROR: no jobs in the census — nothing to measure" >&2
  exit 2
}

REPORT_RC=0
REPORT=$(jq -s --argjson factor "$ANOMALY_FACTOR" --arg repo "$REPO" \
  --arg since "$SINCE" --argjson days "$DAYS" '
  def ceil_min: if . <= 0 then 0 else ((. + 59) / 60 | floor) end;
  def pct($p): if length == 0 then 0 else sort | .[((length - 1) * $p / 100) | floor] end;
  def median: if length == 0 then 0 else sort | .[(length / 2) | floor] end;

  # A job belonging to a run still in flight has completed_at: null, and the
  # runs listing carries no status filter, so every census of an active repo
  # contains some. fromdateiso8601 on null aborts the whole report with
  # "strptime/1 requires string inputs" — a repo busy enough to audit is the
  # likeliest to hit it. Partition them out and count them; they are billing
  # right now and their final duration is not knowable yet, so the honest
  # move is to exclude and surface, never to guess.
  [ .[] | select(has("meta") | not) ] as $rows
  | ($rows | map(select((.started | type) == "string"
                        and (.completed | type) == "string"))) as $timed
  | (($rows | length) - ($timed | length)) as $unfinished
  | ($timed | map(. + {secs: ((.completed | fromdateiso8601)
                             - (.started | fromdateiso8601))}))
  | map(. + {billed: (if .conclusion == "skipped" then 0 else (.secs | ceil_min) end),
             day: .started[0:10]})
  | . as $all
  | ($all | map(select(.billed > 0))) as $billable
  | ($all | map(select(.conclusion == "skipped")) | length) as $skipped
  | ($all | map(select(.conclusion != "skipped" and .secs <= 0)) | length) as $zero
  | ($billable | group_by(.day)
      | map({day: .[0].day, billed: (map(.billed) | add), jobs: length,
             mean_billed: ((map(.billed) | add) * 100 / length | round / 100)}))
    as $day_table
  | ($day_table | map(.billed) | median) as $median_day
  | ($day_table | map(.mean_billed) | median) as $median_day_mean
  # An anomaly day is BOTH unusually large AND structurally unlike the others.
  # Total alone is not enough: a merely busy day trips it (2026-08-17 in
  # CannObserv/cannobserv billed 46 min against a 15-min median day — 3.1x — at
  # a perfectly normal 1.05 min/job), and subtracting a busy day from the
  # baseline understates the very spend the audit exists to find. The incident
  # day next to it billed 196 min over 24 jobs: 8.17 min/job against a 1.00
  # median. That second test is what tells them apart.
  | ($day_table | map(select(.billed > ($median_day * $factor)
                             and .mean_billed > ($median_day_mean * $factor))))
    as $anomalies
  | ($anomalies | map(.day)) as $anomaly_days
  | ($billable | map(select(.day as $d | $anomaly_days | index($d) | not))) as $structural
  | ($structural | map(.billed) | add // 0) as $struct_billed
  | ($structural | length) as $struct_jobs
  # Percentiles come from $structural, NOT $billable. Reporting a raw p99 under
  # a "structural" label is the same error the anomaly gate exists to stop, one
  # level down: the incident day in CannObserv/cannobserv drags p99 from 39s to
  # 902s, and 902 next to the word "structural" reads as a duration problem in a
  # repo where duration has no lever. The raw p99 is still reported — beside the
  # anomaly, where it is evidence of the incident rather than of the baseline.
  | ($structural | map(.secs)) as $secs
  | {
    repo: $repo, since: $since, days: $days,
    raw: {jobs: ($billable | length), billed_minutes: ($billable | map(.billed) | add // 0),
          p99_seconds: ($billable | map(.secs) | pct(99))},
    excluded: {skipped_jobs: $skipped, zero_or_negative_duration_jobs: $zero,
               unfinished_jobs: $unfinished},
    anomaly_days: ($anomalies | sort_by(-.billed)),
    median_day_billed: $median_day,
    median_day_mean_billed: $median_day_mean,
    busiest_days: ($day_table | sort_by(-.billed) | .[:5]),
    structural: {
      jobs: $struct_jobs,
      billed_minutes: $struct_billed,
      actual_minutes: (($structural | map(.secs) | add // 0) / 60 | floor),
      mean_billed_per_job: (if $struct_jobs == 0 then 0
                            else (($struct_billed * 100 / $struct_jobs) | round / 100) end),
      p50_seconds: ($secs | pct(50)), p90_seconds: ($secs | pct(90)),
      p99_seconds: ($secs | pct(99)),
      under_the_floor: (if $struct_jobs == 0 then 0
                        else (($structural | map(select(.secs < 60)) | length) * 100
                              / $struct_jobs | round) end)
    },
    cost_shape: (if $struct_jobs == 0 then "unknown"
                 elif ($struct_billed / $struct_jobs) <= 1.10 then "job-count"
                 elif ($struct_billed / $struct_jobs) >= 1.40 then "duration"
                 else "mixed" end),
    by_workflow: ($structural | group_by(.workflow)
      | map({workflow: .[0].workflow, jobs: length, billed: (map(.billed) | add)})
      | sort_by(-.billed)),
    by_job: ($structural | group_by(.workflow + " / " + .job)
      | map({job: (.[0].workflow + " / " + .[0].job), runs: length,
             billed: (map(.billed) | add),
             median_seconds: (map(.secs) | median)})
      | sort_by(-.billed)),
    by_event: ($structural | group_by(.event)
      | map({event: .[0].event, jobs: length, billed: (map(.billed) | add)})
      | sort_by(-.billed))
  }' "$JOBS_NDJSON") || REPORT_RC=$?
if [ "$REPORT_RC" -ne 0 ]; then
  echo "ERROR: computing the census failed (jq exit $REPORT_RC)" >&2
  exit 2
fi

if [ "$FORMAT" = json ]; then
  printf '%s\n' "$REPORT"
  exit 0
fi

printf '%s' "$REPORT" | jq -r '
  def pad($n): tostring | . + (" " * ($n - length));
  "CI cost census — \(.repo), \(.days)d since \(.since)",
  "",
  "RAW              \(.raw.billed_minutes) billed min over \(.raw.jobs) jobs",
  (if (.anomaly_days | length) > 0 then
     "ANOMALY DAYS     \(.anomaly_days | map(.day + " (" + (.billed|tostring) + " min, "
                          + (.mean_billed|tostring) + " min/job)") | join(", "))",
     "                 median day: \(.median_day_billed) min at \(.median_day_mean_billed) min/job.",
     "                 Quoting RAW as the baseline would overstate it by " +
       "\(((.raw.billed_minutes - .structural.billed_minutes) * 100 / .raw.billed_minutes) | round)%",
     "                 AND point at the wrong lever: raw p99 is \(.raw.p99_seconds)s against a",
     "                 structural p99 of \(.structural.p99_seconds)s. Confirm each day against",
     "                 the GitHub status history before excluding it."
   else "ANOMALY DAYS     none — no day is both >\(.median_day_billed) min and above " +
        "\(.median_day_mean_billed) min/job by the factor" end),
  "STRUCTURAL       \(.structural.billed_minutes) billed min over \(.structural.jobs) jobs" +
    " (\(.structural.actual_minutes) min actually ran)",
  "EXCLUDED         \(.excluded.skipped_jobs) skipped, " +
    "\(.excluded.zero_or_negative_duration_jobs) zero/negative-duration, " +
    "\(.excluded.unfinished_jobs) still running",
  "",
  "BUSIEST DAYS     \(.busiest_days | map(.day + " " + (.billed|tostring) + "m/"
                       + (.mean_billed|tostring) + "pj") | join("  "))",
  "",
  "mean billed/job  \(.structural.mean_billed_per_job)",
  "p50/p90/p99 s    \(.structural.p50_seconds) / \(.structural.p90_seconds) / \(.structural.p99_seconds)",
  "under 60s        \(.structural.under_the_floor)% of jobs",
  "",
  "COST SHAPE       \(.cost_shape | ascii_upcase)",
  (if .cost_shape == "job-count" then
     "  Every job sits inside the one-minute floor. Duration tuning has NO lever.",
     "  Delete and MERGE jobs. Never split a workflow — a split adds a whole",
     "  billed minute per new job and saves nothing."
   elif .cost_shape == "duration" then
     "  Jobs are billed well above the floor, so seconds convert to minutes.",
     "  Cache, narrow, and split. Look for jobs just over a minute boundary.",
     "  Merging jobs here buys little and costs parallelism."
   elif .cost_shape == "mixed" then
     "  Neither lever dominates. Read by_job below: treat rows whose",
     "  median_seconds < 60 as job-count and the rest as duration."
   else "  No billable jobs in the window." end),
  "",
  "TOP JOBS BY BILLED MINUTES (structural)",
  "  \("billed" | pad(8))\("runs" | pad(6))\("med s" | pad(7))job",
  (.by_job[:12][] | "  \(.billed | pad(8))\(.runs | pad(6))\(.median_seconds | pad(7))\(.job)"),
  "",
  "BY EVENT",
  (.by_event[] | "  \(.billed | pad(8))\(.jobs | pad(6))\(.event)")
'
