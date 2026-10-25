#!/usr/bin/env bash
# await-report.sh
# Waits for a cloud worker's report on the tracking issue (#479).
#
# A cloud session can't message the local orchestrator; it can only write to
# GitHub. So the orchestrator polls the issue's comments for the hidden
# marker that opens a worker's report:
#
#   <!-- worker-report session=<id> branch=<branch> sha=<sha> status=<status> -->
#
# and exits on the first one it finds that carries this session's ID and was
# written by the expected author. The repo may be public, so anyone can
# comment, and a marker from anyone else is ignored. Every status ends the
# wait, `blocked` and `question` as surely as `done`: a watch that ended only
# on success would leave a stuck worker looking like a busy one.
#
# The worker pushes after every commit, so with --branch a moving branch SHA
# counts as activity, and --progress prints each new SHA as it lands. With
# neither a report nor a push for --silence seconds, the wait ends with
# `silent` rather than running forever.
#
# Usage: bash await-report.sh --repo O/R --issue N --session ID --author LOGIN
#          [--branch B] [--since ISO8601] [--interval S] [--silence S]
#          [--progress] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" --repo O/R --issue N --session ID --author LOGIN [options]"
  echo ""
  echo "Waits for a cloud worker's report on a GitHub issue: the first comment by"
  echo "LOGIN whose body carries '<!-- worker-report session=ID ... status=S -->'."
  echo ""
  echo "Required:"
  echo "  --repo O/R       the repository holding the tracking issue"
  echo "  --issue N        the tracking issue's number"
  echo "  --session ID     the worker's cloud session ID (cse_... or session_...)"
  echo "  --author LOGIN   the GitHub login the worker posts as"
  echo ""
  echo "Options:"
  echo "  --branch B       the worker's branch; a new SHA on it counts as activity"
  echo "  --since ISO8601  read comments updated at or after this time"
  echo "                   (default: now, so an earlier report isn't taken for this one)"
  echo "  --interval S     seconds between polls (default 60)"
  echo "  --silence S      end with 'silent' after S seconds with no report and no"
  echo "                   push (default 3600)"
  echo "  --progress       print 'push<TAB>SHA' each time the branch moves"
  echo "  --help           show this help"
  echo ""
  echo "Output (stdout, TSV), one final line:"
  echo "  report<TAB>STATUS<TAB>COMMENT_URL<TAB>MARKER_SHA   a report was found"
  echo "  silent<TAB><TAB><TAB>LAST_BRANCH_SHA               the silence limit passed"
  echo ""
  echo "Exit codes:"
  echo "  0  a report was found, whatever its status"
  echo "  2  a bad argument, or gh failed on 5 polls in a row (its stderr is shown)"
  echo "  3  silent: no report and no push within --silence seconds"
}

REPO="" ISSUE="" SESSION="" AUTHOR="" BRANCH="" SINCE="" INTERVAL=60 SILENCE=3600 PROGRESS=0

need() {  # <flag> <value>
  if [ -z "${2:-}" ]; then
    echo "ERROR: $1 needs a value" >&2
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case $1 in
    --help) usage; exit 0 ;;
    --repo) need "$1" "${2:-}"; REPO=$2; shift 2 ;;
    --issue) need "$1" "${2:-}"; ISSUE=$2; shift 2 ;;
    --session) need "$1" "${2:-}"; SESSION=$2; shift 2 ;;
    --author) need "$1" "${2:-}"; AUTHOR=$2; shift 2 ;;
    --branch) need "$1" "${2:-}"; BRANCH=$2; shift 2 ;;
    --since) need "$1" "${2:-}"; SINCE=$2; shift 2 ;;
    --interval) need "$1" "${2:-}"; INTERVAL=$2; shift 2 ;;
    --silence) need "$1" "${2:-}"; SILENCE=$2; shift 2 ;;
    --progress) PROGRESS=1; shift ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

for pair in "--repo:$REPO" "--issue:$ISSUE" "--session:$SESSION" "--author:$AUTHOR"; do
  if [ -z "${pair#*:}" ]; then
    echo "ERROR: ${pair%%:*} is required" >&2
    usage >&2
    exit 2
  fi
done
# The session ID is matched literally inside a regex below, so it may hold
# only the characters a session ID has.
if ! [[ $SESSION =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "ERROR: --session '$SESSION' isn't a session ID" >&2
  exit 2
fi
for pair in "--issue:$ISSUE" "--interval:$INTERVAL" "--silence:$SILENCE"; do
  if ! [[ ${pair#*:} =~ ^[0-9]+$ ]]; then
    echo "ERROR: ${pair%%:*} must be a whole number, got '${pair#*:}'" >&2
    exit 2
  fi
done
if [ -z "$SINCE" ]; then
  SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
fi

# gh's --jq reads these through env, so no value is spliced into the filter.
export AR_AUTHOR=$AUTHOR AR_SESSION=$SESSION
# The marker must open the body (CR 512). The orchestrator posts as the same
# user as the worker, so the author filter can't tell them apart, and a review
# quoting the worker's last marker would otherwise end the wait that follows.
# The $ are jq's, not the shell's: this filter is passed to gh literally.
# shellcheck disable=SC2016
FILTER='[.[] | select(.user.login == env.AR_AUTHOR)
  | select(.body | test("^\\s*<!-- worker-report session=" + env.AR_SESSION + "[ >]"))][0]
  | if . == null then empty else
      (.body | capture("^\\s*<!-- worker-report session=" + env.AR_SESSION
        + "(?<rest>[^>]*)-->").rest) as $m
      | ($m | capture("status=(?<s>[A-Za-z]+)").s // "unknown") as $s
      | ($m | capture("sha=(?<h>[0-9a-f]+)").h // "") as $h
      | "report\t\($s)\t\(.html_url)\t\($h)"
    end'

fails=0 last_err=""
err_file=$(mktemp)
trap 'rm -f "$err_file"' EXIT
last_activity=$(date +%s)
branch_sha=""
if [ -n "$BRANCH" ]; then
  # A branch not pushed yet is a 404. Any failure here reads as no new push,
  # which at worst ends the wait early as silent, never as a report.
  branch_sha=$(gh api "repos/$REPO/branches/$BRANCH" --jq .commit.sha 2>/dev/null || true)
fi

while true; do
  if out=$(gh api "repos/$REPO/issues/$ISSUE/comments?since=$SINCE&per_page=100" --jq "$FILTER" 2>"$err_file"); then
    fails=0
    if [ -n "$out" ]; then
      printf '%s\n' "$out"
      exit 0
    fi
  else
    fails=$((fails + 1))
    last_err=$(cat "$err_file")
    if [ "$fails" -ge 5 ]; then
      echo "ERROR: gh failed on $fails polls in a row; its last error:" >&2
      printf '%s\n' "$last_err" >&2
      exit 2
    fi
  fi

  if [ -n "$BRANCH" ]; then
    sha=$(gh api "repos/$REPO/branches/$BRANCH" --jq .commit.sha 2>/dev/null || true)
    if [ -n "$sha" ] && [ "$sha" != "$branch_sha" ]; then
      branch_sha=$sha
      last_activity=$(date +%s)
      if [ "$PROGRESS" -eq 1 ]; then printf 'push\t%s\n' "$sha"; fi
    fi
  fi

  if [ $(($(date +%s) - last_activity)) -ge "$SILENCE" ]; then
    printf 'silent\t\t\t%s\n' "$branch_sha"
    exit 3
  fi
  sleep "$INTERVAL"
done
