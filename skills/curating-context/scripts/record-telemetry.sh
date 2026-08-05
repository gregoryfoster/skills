#!/usr/bin/env bash
# record-telemetry.sh — append one measurement row to the repo's context-metrics
# ledger, computing deltas against the previous row for the same policy file.
#
# The ledger is append-only JSONL committed alongside the file it measures, so a
# repo's curation history travels with the repo and survives a transfer. Reads
# measure-context.sh JSON on stdin.
set -euo pipefail

usage() {
  cat <<'USAGE'
record-telemetry.sh — append a context-metrics row to the repo ledger

Usage:
  measure-context.sh | record-telemetry.sh [options]

Options:
  --ledger PATH    Ledger file. Default: .skills/context-metrics.jsonl
  --actions LIST   Comma-separated action tags applied this run, e.g.
                   "demote:Project Layout,prune:Conventions,fix:dead-link".
                   Recorded verbatim so a later run can correlate a token
                   delta with what produced it.
  --note TEXT      Free-text note for this row (one line).
  --dry-run        Print the row to stdout; do not write the ledger.
  --print-trend    After appending, print the trend for this file to stderr.
  -h, --help       Show this help and exit 0.

Row schema (one JSON object per line):
  ts                UTC date (YYYY-MM-DD)
  repo              basename of the repo root
  file              policy file path
  tokens            policy-file tokens (exact when tokens_exact is true)
  tokens_exact      whether the count came from the count_tokens endpoint
  lines, bytes      policy-file size
  budget            budget in force for this run
  over_budget       tokens > budget
  tokens_live       policy + reachable live reference docs
  docs_total        live reference docs measured
  docs_orphaned     live docs not reachable from the policy file
  links_dead        broken relative links in the curated surface
  top_section       largest section title, and its share of the file
  delta_tokens      change vs the previous row for this file (null if first)
  delta_days        days since the previous row (null if first)
  actions           action tags from --actions
  note              --note text

Exit codes:
  0  row appended (or printed, with --dry-run)
  1  usage error, or stdin was not measure-context.sh JSON
  2  infrastructure failure (unwritable ledger, python3 missing)
USAGE
}

LEDGER=".skills/context-metrics.jsonl"
ACTIONS=""
NOTE=""
DRY=0
TREND=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --actions) ACTIONS="${2-}"; shift 2 ;;
    --note) NOTE="${2-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --print-trend) TREND=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/in.json"
[ -s "$TMP/in.json" ] || { echo "ERROR no measurement on stdin — pipe measure-context.sh into this script" >&2; exit 1; }

# TZ is pinned to UTC so rows from different machines sort and diff consistently.
TODAY="$(TZ=UTC date +%Y-%m-%d)"
REPO_NAME="$(basename "$ROOT")"

mkdir -p "$(dirname "$LEDGER")" || { echo "ERROR cannot create $(dirname "$LEDGER")" >&2; exit 2; }
[ -f "$LEDGER" ] || : >"$LEDGER" || { echo "ERROR cannot create $LEDGER" >&2; exit 2; }

RC=0
python3 - "$TMP/in.json" "$LEDGER" "$TODAY" "$REPO_NAME" "$ACTIONS" "$NOTE" "$DRY" "$TREND" <<'PY' || RC=$?
import datetime as dt
import json
import sys

src, ledger, today, repo, actions, note, dry, trend = sys.argv[1:9]

try:
    m = json.load(open(src, encoding="utf-8"))
    policy, totals, links = m["policy"], m["totals"], m["links"]
except (ValueError, KeyError) as exc:
    print(f"ERROR stdin is not measure-context.sh JSON: {exc}", file=sys.stderr)
    sys.exit(1)

sections = m.get("sections") or []
top = sections[0] if sections else {}

row = {
    "ts": today,
    "repo": repo,
    "file": policy["path"],
    "tokens": policy["tokens"],
    "tokens_exact": policy["tokens_exact"],
    "lines": policy["lines"],
    "bytes": policy["bytes"],
    "budget": policy["budget"],
    "over_budget": policy["over_budget"],
    "tokens_live": totals["tokens_live"],
    "docs_total": totals["files_docs"],
    "docs_orphaned": len(links["orphans"]),
    "links_dead": len(links["dead"]),
    "top_section": top.get("title"),
    "top_section_share": top.get("share"),
    "delta_tokens": None,
    "delta_days": None,
    "actions": [a.strip() for a in actions.split(",") if a.strip()],
    "note": note or None,
}

# Prior rows for the same file, oldest first. A malformed line is skipped rather
# than fatal: the ledger is append-only and a half-written row from an
# interrupted run must not block every future measurement.
history, malformed = [], 0
try:
    for line in open(ledger, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            prev = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if prev.get("file") == row["file"]:
            history.append(prev)
except OSError as exc:
    print(f"ERROR cannot read {ledger}: {exc}", file=sys.stderr)
    sys.exit(2)

if malformed:
    print(f"WARN skipped {malformed} malformed ledger line(s)", file=sys.stderr)

if history:
    last = history[-1]
    if isinstance(last.get("tokens"), int):
        row["delta_tokens"] = row["tokens"] - last["tokens"]
    try:
        row["delta_days"] = (
            dt.date.fromisoformat(today) - dt.date.fromisoformat(last["ts"])
        ).days
    except (ValueError, KeyError, TypeError):
        pass
    # An exact count and an estimate are not comparable — bytes/4 runs 10-20%
    # off on prose-heavy files, so a mixed delta reads as a change that never
    # happened. Flag it rather than silently reporting the artefact.
    if last.get("tokens_exact") != row["tokens_exact"]:
        print(
            "WARN delta_tokens compares an exact count against a bytes/4 estimate "
            "— treat the magnitude as unreliable",
            file=sys.stderr,
        )

line_out = json.dumps(row, sort_keys=True, ensure_ascii=False)

if dry == "1":
    print(line_out)
else:
    try:
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(line_out + "\n")
    except OSError as exc:
        print(f"ERROR cannot append to {ledger}: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"recorded {row['file']}: {row['tokens']} tokens", file=sys.stderr)

if trend == "1":
    series = history + [row]
    print(f"\ntrend for {row['file']} ({len(series)} runs):", file=sys.stderr)
    for r in series[-8:]:
        d = r.get("delta_tokens")
        mark = "" if d is None else f"  ({d:+d})"
        acts = ", ".join(r.get("actions") or []) or "-"
        print(f"  {r['ts']}  {r['tokens']:>7} tok{mark:<12} {acts}", file=sys.stderr)
    first = series[0]
    if len(series) > 1 and isinstance(first.get("tokens"), int):
        net = row["tokens"] - first["tokens"]
        print(f"  net since {first['ts']}: {net:+d} tokens", file=sys.stderr)
PY

exit "$RC"
