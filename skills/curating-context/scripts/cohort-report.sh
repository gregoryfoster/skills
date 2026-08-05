#!/usr/bin/env bash
# cohort-report.sh — roll up per-repo context-metrics ledgers into one table, so
# the cohort's aggregate trend and the most effective optimisations are visible
# without opening twelve repos.
#
# Reads each repo's ledger over `gh api` (no clone needed) or from a local path.
set -euo pipefail

usage() {
  cat <<'USAGE'
cohort-report.sh — cross-repo context-budget roll-up

Usage:
  cohort-report.sh --repos "owner/a owner/b ..." [options]
  cohort-report.sh --local "/path/to/repo1 /path/to/repo2" [options]
  cohort-report.sh --cohort-file PATH [options]

Options:
  --repos LIST       Space-separated owner/repo slugs, read via gh api.
  --local LIST       Space-separated local repo roots, read from disk.
  --cohort-file PATH File of owner/repo slugs or local paths, one per line;
                     blank lines and # comments ignored. Default, when no
                     --repos/--local is given: .skills/cohort
  --ledger PATH      Ledger path within each repo.
                     Default: .skills/context-metrics.jsonl
  --branch NAME      Branch to read for --repos. Default: the repo's default.
  --format FMT       table (default) or tsv or json
  -h, --help         Show this help and exit 0.

Columns:
  repo, latest run date, current tokens, net change, runs recorded, orphaned
  docs, dead links, and the action tags that accompanied this repo's largest
  single reduction. That last column is the point of the roll-up: it names which
  optimisation actually paid, per repo.

  `net` is anchored at the oldest run that used the SAME measurement method as
  the latest one, not at the first run ever recorded — an exact count and an
  offline estimate differ by ~60% on this content, so a net spanning that change
  would report a large move for a file that never changed. When no comparable
  anchor exists the cell is "-" and a footer names the repo.

A repo with no ledger is reported as "no ledger" rather than skipped silently —
missing telemetry is itself the finding on a weekly cadence.

Exit codes:
  0  report produced (repos without ledgers are reported, not fatal)
  1  usage error, or no repos resolved
  2  infrastructure failure (gh missing when required, python3 missing)
USAGE
}

REPOS=""
LOCALS=""
COHORT_FILE=""
LEDGER=".skills/context-metrics.jsonl"
BRANCH=""
FORMAT="table"

while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS="${2:?--repos needs a list}"; shift 2 ;;
    --local) LOCALS="${2:?--local needs a list}"; shift 2 ;;
    --cohort-file) COHORT_FILE="${2:?--cohort-file needs a path}"; shift 2 ;;
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch needs a name}"; shift 2 ;;
    --format) FORMAT="${2:?--format needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$FORMAT" in
  table|tsv|json) ;;
  *) echo "ERROR --format must be table, tsv, or json" >&2; exit 1 ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

# Default source: the cohort roster file, so a scheduled run needs no arguments.
if [ -z "$REPOS" ] && [ -z "$LOCALS" ] && [ -z "$COHORT_FILE" ]; then
  COHORT_FILE=".skills/cohort"
fi
if [ -n "$COHORT_FILE" ]; then
  if [ ! -f "$COHORT_FILE" ]; then
    echo "ERROR no cohort file at $COHORT_FILE (pass --repos or --local instead)" >&2
    exit 1
  fi
  while IFS= read -r entry; do
    entry="${entry%%#*}"
    entry="$(printf '%s' "$entry" | tr -d '[:space:]')"
    [ -n "$entry" ] || continue
    case "$entry" in
      /*|.*|~*) LOCALS="$LOCALS $entry" ;;
      *) REPOS="$REPOS $entry" ;;
    esac
  done <"$COHORT_FILE"
fi

if [ -z "$REPOS$LOCALS" ]; then
  echo "ERROR no repos resolved" >&2
  exit 1
fi

: >"$TMP/all.jsonl"

# Local ledgers first — no network, so a partial network failure still yields
# whatever is on disk.
for d in $LOCALS; do
  name="$(basename "$d")"
  if [ -f "$d/$LEDGER" ]; then
    # Stamp the source repo onto each row: a ledger's own `repo` field is the
    # basename recorded at write time, which drifts if a checkout is renamed.
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      printf '%s\t%s\n' "$name" "$line" >>"$TMP/all.jsonl"
    done <"$d/$LEDGER"
  else
    printf '%s\t%s\n' "$name" "MISSING" >>"$TMP/all.jsonl"
  fi
done

if [ -n "$REPOS" ]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR gh is required for --repos (use --local for on-disk repos)" >&2
    exit 2
  fi
  for slug in $REPOS; do
    name="${slug##*/}"
    ref=""
    [ -n "$BRANCH" ] && ref="?ref=$BRANCH"
    # gh api prints nothing AND exits non-zero on 404, so an empty-output test
    # alone cannot tell "absent" from "empty". Capture both and grep the body
    # for a 404 marker before deciding.
    GH_RC=0
    gh api "repos/$slug/contents/$LEDGER$ref" -H "Accept: application/vnd.github.raw" \
      >"$TMP/raw" 2>"$TMP/gh.err" || GH_RC=$?
    if [ "$GH_RC" -ne 0 ]; then
      if grep -q '404' "$TMP/gh.err"; then
        printf '%s\t%s\n' "$name" "MISSING" >>"$TMP/all.jsonl"
      else
        echo "WARN $slug: gh api failed (exit $GH_RC): $(tr -d '\n' <"$TMP/gh.err")" >&2
        printf '%s\t%s\n' "$name" "ERROR" >>"$TMP/all.jsonl"
      fi
      continue
    fi
    if [ ! -s "$TMP/raw" ]; then
      printf '%s\t%s\n' "$name" "MISSING" >>"$TMP/all.jsonl"
      continue
    fi
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      printf '%s\t%s\n' "$name" "$line" >>"$TMP/all.jsonl"
    done <"$TMP/raw"
  done
fi

python3 - "$TMP/all.jsonl" "$FORMAT" <<'PY'
import json
import sys

src, fmt = sys.argv[1], sys.argv[2]

repos = {}
order = []
for raw in open(src, encoding="utf-8"):
    raw = raw.rstrip("\n")
    if not raw or "\t" not in raw:
        continue
    name, payload = raw.split("\t", 1)
    if name not in repos:
        repos[name] = {"rows": [], "status": "ok"}
        order.append(name)
    if payload in ("MISSING", "ERROR"):
        repos[name]["status"] = "no ledger" if payload == "MISSING" else "unreadable"
        continue
    try:
        repos[name]["rows"].append(json.loads(payload))
    except ValueError:
        repos[name]["status"] = "malformed rows"

records = []
for name in order:
    info = repos[name]
    rows = sorted(info["rows"], key=lambda r: r.get("ts") or "")
    if not rows:
        records.append({
            "repo": name, "status": info["status"], "latest": None, "tokens": None,
            "net": None, "net_from": None, "net_why": None, "runs": 0,
            "orphans": None, "dead": None,
            "best_actions": None, "best_delta": None,
        })
        continue
    latest = rows[-1]
    # The best single reduction and what accompanied it — the roll-up's reason
    # for existing: which optimisation actually moved the number, per repo.
    best = None
    for r in rows:
        d = r.get("delta_tokens")
        if isinstance(d, int) and d < 0 and (best is None or d < best.get("delta_tokens", 0)):
            best = r
    # `net` must not span a measurement-method change. record-telemetry.sh
    # suppresses delta_tokens across one because an exact count and an offline
    # estimate are incomparable — the uncalibrated heuristic under-reported this
    # cohort by ~60%, so a mixed net invents a change of that size for a file
    # that never moved. Anchor at the OLDEST row contiguously matching the latest
    # row's method: the same walk-back --print-trend performs. Both operands are
    # checked, so an odd-but-parseable row (a badly resolved merge conflict in
    # the committed ledger) degrades one cell instead of raising.
    net = None
    net_from = None
    net_why = None
    if not isinstance(latest.get("tokens"), int):
        net_why = "latest row has no token count"
    elif len(rows) > 1:
        anchor = None
        for r in reversed(rows[:-1]):
            if r.get("tokens_exact") != latest.get("tokens_exact"):
                break
            anchor = r
        if anchor is None:
            net_why = "measurement method changed since the previous run"
        elif not isinstance(anchor.get("tokens"), int):
            net_why = "anchor row has no token count"
        else:
            net = latest["tokens"] - anchor["tokens"]
            net_from = anchor.get("ts")

    records.append({
        "repo": name,
        "status": info["status"],
        "latest": latest.get("ts"),
        "tokens": latest.get("tokens"),
        "net": net,
        "net_from": net_from,
        "net_why": net_why,
        "runs": len(rows),
        "orphans": latest.get("docs_orphaned"),
        "dead": latest.get("links_dead"),
        "best_actions": ", ".join(best.get("actions") or []) or "(untagged)" if best else None,
        "best_delta": best.get("delta_tokens") if best else None,
    })

if fmt == "json":
    print(json.dumps(records, indent=2))
    sys.exit(0)

records.sort(key=lambda r: -(r["tokens"] or 0))

if fmt == "tsv":
    print("repo\tlatest\ttokens\tnet\tnet_from\tnet_why\truns\torphans\tdead"
          "\tbest_delta\tbest_actions")
    for r in records:
        print("\t".join("" if r[k] is None else str(r[k]) for k in
              ("repo", "latest", "tokens", "net", "net_from", "net_why", "runs",
               "orphans", "dead", "best_delta", "best_actions")))
    sys.exit(0)

def cell(v, dash="-"):
    return dash if v is None else str(v)

w = max([len(r["repo"]) for r in records] + [4])
print(f"{'repo':<{w}}  {'latest':<10} {'tokens':>8} {'net':>8} {'runs':>4} "
      f"{'orph':>4} {'dead':>4}  best reduction")
print("-" * (w + 58))
total = 0
for r in records:
    if r["tokens"]:
        total += r["tokens"]
    net = r["net"]
    best = "-"
    if r["best_delta"] is not None:
        best = f"{r['best_delta']:+d}  {r['best_actions']}"
    elif r["runs"] == 1:
        best = "(baseline only)"
    elif r["status"] != "ok":
        best = r["status"]
    print(f"{r['repo']:<{w}}  {cell(r['latest']):<10} {cell(r['tokens']):>8} "
          f"{'-' if net is None else format(net, '+d'):>8} {r['runs']:>4} "
          f"{cell(r['orphans']):>4} {cell(r['dead']):>4}  {best}")
print("-" * (w + 58))
measured = [r for r in records if r["tokens"]]
print(f"{'cohort':<{w}}  {'':<10} {total:>8} tokens across {len(measured)} "
      f"measured repo(s)")
stale = [r["repo"] for r in records if r["status"] != "ok"]
if stale:
    print(f"\nno usable ledger: {', '.join(stale)}")
# A dash in `net` has two very different causes. Say which, rather than letting a
# suppressed comparison read as "no change recorded yet".
unexplained = [r for r in records if r["net"] is None and r["net_why"]]
if unexplained:
    print("\nnet not comparable:")
    for r in unexplained:
        print(f"  {r['repo']}: {r['net_why']}")
    print("  a method change makes the newest row that repo's baseline; net "
          "returns once two rows share a method.")
PY
