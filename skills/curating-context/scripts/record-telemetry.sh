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
  --allow-method-change
                   Append even when this row's measurement method differs from
                   the ledger's latest row for the same file. Refused by default:
                   an estimate row and an exact row are not comparable, so mixing
                   them leaves every delta null and resets the trend baseline.
                   The usual cause is a missing credential, and the usual fix is
                   to supply one rather than to record the row.
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
  delta_tokens      change vs the previous row for this file. Null on the first
                    row, and null when the measurement method changed since the
                    previous row — see delta_unavailable
  delta_days        days since the previous row (null if first)
  delta_unavailable present only when delta_tokens was suppressed; says why
  actions           action tags from --actions
  note              --note text

Exit codes:
  0  row appended (or printed, with --dry-run)
  1  usage error, or stdin was not measure-context.sh JSON
  2  infrastructure failure (unwritable ledger, python3 missing)
  4  refused: measurement method differs from the previous row for this file
     (pass --allow-method-change to record it anyway)
USAGE
}

LEDGER=".skills/context-metrics.jsonl"
ACTIONS=""
NOTE=""
DRY=0
TREND=0
ALLOW_METHOD_CHANGE=0

# --actions and --note accept an empty value deliberately, so they cannot use
# ${2:?...} for arity — and a bare `shift 2` at the end of argv fails under
# `set -e` with no message at all.
need_arg() {
  [ "$1" -ge 2 ] || { echo "ERROR $2 needs a value" >&2; exit 1; }
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --actions) need_arg "$#" --actions; ACTIONS="$2"; shift 2 ;;
    --note) need_arg "$#" --note; NOTE="$2"; shift 2 ;;
    --allow-method-change) ALLOW_METHOD_CHANGE=1; shift ;;
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
python3 - "$TMP/in.json" "$LEDGER" "$TODAY" "$REPO_NAME" "$ACTIONS" "$NOTE" "$DRY" "$TREND" "$ALLOW_METHOD_CHANGE" <<'PY' || RC=$?
import datetime as dt
import json
import sys

src, ledger, today, repo, actions, note, dry, trend, allow_method = sys.argv[1:10]

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
    try:
        row["delta_days"] = (
            dt.date.fromisoformat(today) - dt.date.fromisoformat(last["ts"])
        ).days
    except (ValueError, KeyError, TypeError):
        pass
    # An exact count and an offline estimate are not comparable. Measured on this
    # cohort the uncalibrated bytes/4 heuristic under-reported by ~60%, so a
    # mixed-method delta can invent a change of that magnitude out of nothing.
    # Leave delta_tokens null and say why: a number this untrustworthy should not
    # be recorded at all, because every downstream reader — the trend printout,
    # the cohort roll-up's "best reduction" column — treats it as a measurement.
    if last.get("tokens_exact") != row["tokens_exact"]:
        # Refuse by default rather than record an uncomparable row. Warning and
        # writing anyway was the earlier behaviour, and it made the mismatch a
        # thing every future reader had to notice: one interactive run without a
        # credential, appended to a ledger of exact rows, nulls its own delta,
        # resets the trend baseline, and blanks `net` in the cohort roll-up. The
        # cause is almost always a missing credential, and the fix is to supply
        # one — not to keep the row.
        would_refuse = allow_method != "1"
        if would_refuse and dry == "1":
            # A preview must describe what the real command would do, not what
            # --allow-method-change would do. Without this, --dry-run printed
            # "This row is the new baseline" and a clean row, and then the actual
            # append refused with exit 4 — the preview answering for the wrong
            # branch of the very decision it was consulted about.
            row["would_be_refused"] = (
                "the real append would exit 4: measurement method differs from "
                f"the last row for {row['file']} ({last.get('ts')}). "
                "Supply a credential, or pass --allow-method-change."
            )
            print(
                "WARN --dry-run: the real append would be REFUSED (exit 4) — this "
                "row is tokens_exact="
                f"{row['tokens_exact']} and the last row for {row['file']} is "
                f"tokens_exact={last.get('tokens_exact')}. Fix the cause (supply a "
                "credential) or pass --allow-method-change to start a new baseline.",
                file=sys.stderr,
            )
        if would_refuse and dry != "1":
            print(
                "ERROR refusing to append: this row is "
                f"tokens_exact={row['tokens_exact']} but the last row for "
                f"{row['file']} ({last.get('ts')}) is "
                f"tokens_exact={last.get('tokens_exact')}. An exact count and an "
                "offline estimate are not comparable, so recording this would "
                "null every delta from here on.\n"
                "  Fix the cause: run measure-context.sh --exact with a "
                "credential (ANTHROPIC_API_KEY, an `ant auth login` profile, or "
                "the key in a repo-root .env).\n"
                "  Or record it deliberately: re-run with --allow-method-change, "
                "which starts a new baseline.",
                file=sys.stderr,
            )
            sys.exit(4)
        row["delta_unavailable"] = (
            f"method changed: previous row tokens_exact={last.get('tokens_exact')}, "
            f"this row tokens_exact={row['tokens_exact']}"
        )
        print(
            "WARN measurement method changed since the previous row; delta_tokens "
            "left null (an exact count and an offline estimate are not comparable). "
            "This row is the new baseline.",
            file=sys.stderr,
        )
    elif isinstance(last.get("tokens"), int):
        row["delta_tokens"] = row["tokens"] - last["tokens"]

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
    # Net is only meaningful over rows measured the same way. Walk back from the
    # newest row while the method matches and anchor there — otherwise the net
    # silently spans the same method change delta_tokens just refused to report.
    anchor = None
    for r in reversed(series[:-1]):
        if r.get("tokens_exact") != row["tokens_exact"]:
            break
        anchor = r
    if anchor is not None and isinstance(anchor.get("tokens"), int):
        net = row["tokens"] - anchor["tokens"]
        print(f"  net since {anchor['ts']}: {net:+d} tokens", file=sys.stderr)
    elif len(series) > 1:
        print(
            "  net: not comparable — every prior row used a different measurement "
            "method. This row is the new baseline.",
            file=sys.stderr,
        )
PY

exit "$RC"
