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
                     blank lines and # comments ignored. An entry may carry
                     `wave:` and `pair:` annotations, which this script reports
                     and score-cohort.sh acts on. Default, when no
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

  `runs` counts CURATION rows, not ledger rows. A run writes two — the Phase 1
  `baseline` for the surface as found and the Phase 7 curation — so a row count
  reports every repo as having run twice as often as it did. A repo that
  measured and stopped shows 0 runs and `(baseline only)`.

  `net` is anchored at the oldest run that used the SAME measurement method as
  the latest one, not at the first run ever recorded — an exact count and an
  offline estimate differ by ~60% on this content, so a net spanning that change
  would report a large move for a file that never changed. When no comparable
  anchor exists the cell is "-" and a footer names the repo and the reason.

  tsv and json carry two more fields than the table has room for:
    net_from   the date of the run `net` is measured against
    net_why    why `net` is absent: the method changed since the previous run,
               or a row is missing its token count

A repo with no ledger is reported as "no ledger" rather than skipped silently —
missing telemetry is itself the finding on a weekly cadence.

Exit codes:
  0  report produced (repos without ledgers are reported, not fatal)
  1  usage error, or no repos resolved
  2  infrastructure failure (gh missing when required, python3 missing,
     _context-lib.sh missing)
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

# --- shared library -------------------------------------------------------
# After argument parsing, deliberately: the roster parser and the ledger fetch
# are shared with score-cohort.sh so the two cannot disagree about which repo is
# in which arm of the experiment.
_self="${BASH_SOURCE[0]}"
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 10 ]; do
  _t="$(readlink "$_self" 2>/dev/null)" || break
  case "$_t" in
    /*) _self="$_t" ;;
    *) _self="$(dirname "$_self")/$_t" ;;
  esac
  _n=$(( _n + 1 ))
done
_libdir="$(cd "$(dirname "$_self")" 2>/dev/null && pwd -P)" || _libdir=""
[ -n "$_libdir" ] && [ -f "$_libdir/_context-lib.sh" ] || {
  echo "ERROR _context-lib.sh not found next to $_self" >&2; exit 2; }
# shellcheck source=_context-lib.sh
. "$_libdir/_context-lib.sh"

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

# Default source: the cohort roster file, so a scheduled run needs no arguments.
if [ -z "$REPOS" ] && [ -z "$LOCALS" ] && [ -z "$COHORT_FILE" ]; then
  COHORT_FILE=".skills/cohort"
fi
: >"$TMP/roster"
for d in $LOCALS; do
  printf 'local%s%s%s%s\n' "$CTX_US" "$d" "$CTX_US" "$CTX_US" >>"$TMP/roster"
done
for s in $REPOS; do
  printf 'repo%s%s%s%s\n' "$CTX_US" "$s" "$CTX_US" "$CTX_US" >>"$TMP/roster"
done
if [ -n "$COHORT_FILE" ]; then
  if [ ! -f "$COHORT_FILE" ]; then
    echo "ERROR no cohort file at $COHORT_FILE (pass --repos or --local instead)" >&2
    exit 1
  fi
  ctx_read_roster "$COHORT_FILE" >>"$TMP/roster"
fi

if [ ! -s "$TMP/roster" ]; then
  echo "ERROR no repos resolved" >&2
  exit 1
fi

if grep -q "^repo$CTX_US" "$TMP/roster" && ! command -v gh >/dev/null 2>&1; then
  echo "ERROR gh is required to read owner/repo entries (use --local for on-disk repos)" >&2
  exit 2
fi

: >"$TMP/all.jsonl"

# Local entries first — no network, so a partial network failure still yields
# whatever is on disk. Two passes rather than one, because a roster file
# interleaves the two kinds in whatever order its author wrote them.
for want in local repo; do
  while IFS="$CTX_US" read -r kind entry wave pair; do
    [ "$kind" = "$want" ] || continue
    # A ledger's own `repo` field is the basename recorded at write time, which
    # drifts if a checkout is renamed. Stamp the roster entry on instead — and
    # the wave and pair with it, so the arm a repo belongs to is visible in the
    # roll-up rather than only inside the gate.
    #
    # The FULL entry, not its basename: two entries sharing one (OrgA/cli and
    # OrgB/cli, or two checkouts of the same project) would merge into a single
    # record whose rows come from both ledgers. The reader shortens it for
    # display when no other entry shares the basename.
    RC=0
    ctx_fetch_ledger "$kind" "$entry" "$LEDGER" "$BRANCH" "$TMP/raw" || RC=$?
    case "$RC" in
      3) printf '%s\t%s\t%s\t%s\n' "$entry" "$wave" "$pair" "MISSING" >>"$TMP/all.jsonl"
         continue ;;
      0) ;;
      *) printf '%s\t%s\t%s\t%s\n' "$entry" "$wave" "$pair" "ERROR" >>"$TMP/all.jsonl"
         continue ;;
    esac
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      printf '%s\t%s\t%s\t%s\n' "$entry" "$wave" "$pair" "$line" >>"$TMP/all.jsonl"
    done <"$TMP/raw"
  done <"$TMP/roster"
done

python3 - "$TMP/all.jsonl" "$FORMAT" <<'PY'
import json
import sys

src, fmt = sys.argv[1], sys.argv[2]

repos = {}
order = []
for raw in open(src, encoding="utf-8"):
    raw = raw.rstrip("\n")
    if not raw or raw.count("\t") < 3:
        continue
    key, wave, pair, payload = raw.split("\t", 3)
    if key not in repos:
        repos[key] = {"rows": [], "status": "ok", "wave": wave, "pair": pair}
        order.append(key)
    if payload in ("MISSING", "ERROR"):
        repos[key]["status"] = "no ledger" if payload == "MISSING" else "unreadable"
        continue
    try:
        repos[key]["rows"].append(json.loads(payload))
    except ValueError:
        repos[key]["status"] = "malformed rows"

# Short display names, unless two roster entries share a basename — in which
# case both are shown in full. A table naming two different repos identically is
# worse than a wide one.
basenames = {}
for key in order:
    basenames.setdefault(key.rstrip("/").rsplit("/", 1)[-1], []).append(key)
display = {
    key: (short if len(keys) == 1 else key)
    for short, keys in basenames.items() for key in keys
}


def is_curation_row(row):
    """Whether a row records a RUN rather than a state.

    A curation run writes TWO rows — the Phase 1 `baseline` for the surface as
    found, and the Phase 7 curation — so a row count is twice the run count.
    Counting rows reported one curation as two runs, in the column a reader
    consults to answer "is this repo actually running?" (#116).

    THIS RULE IS SHARED WITH score-cohort.sh's classify_run() and
    record-telemetry.sh's is_curation_row(), and MUST STAY IDENTICAL. The
    neighbouring primary-file rule diverged between exactly these two scripts
    once and produced two irreconcilable pictures of one repo, so
    TestCurationRuleIsOneRule feeds a single mixed ledger through all three and
    pins them to one answer. An untagged row (actions: []) counts as a run:
    something happened that nobody tagged, which is a tagging gap rather than a
    measurement. Only an explicit `baseline*` row is a state.
    """
    acts = row.get("actions") or []
    return not (acts and all(a.split(":", 1)[0] == "baseline" for a in acts))


records = []
for key in order:
    info = repos[key]
    name = display[key]
    rows = sorted(info["rows"], key=lambda r: r.get("ts") or "")
    if not rows:
        records.append({
            "repo": name, "status": info["status"], "latest": None, "tokens": None,
            "net": None, "net_from": None, "net_why": None, "runs": 0,
            "orphans": None, "dead": None, "skill_version": None,
            "wave": info["wave"] or None, "pair": info["pair"] or None,
            "best_actions": None, "best_delta": None,
        })
        continue
    # PRIMARY POLICY FILE: the one with the most rows, ties broken by whichever
    # was measured most recently. A ledger may track more than one
    # (record-telemetry.sh keys its own deltas by file), and mixing them makes
    # `net` span two files and report a change for one that never moved — the
    # class of error the method-change anchoring exists to prevent.
    #
    # Most-recent alone was the first rule and it was too fragile: one incidental
    # baseline row for docs/GUIDE.md collapsed a repo that had curated AGENTS.md
    # 50,000 -> 6,800 to a headline of 4,000 tokens, 1 run and no net — and that
    # 4,000 then fed the cohort total. Row count is what a stray append cannot
    # flip.
    #
    # THIS RULE IS SHARED WITH score-cohort.sh AND MUST STAY IDENTICAL. When the
    # two disagreed, one ledger produced two irreconcilable pictures of the same
    # repo: the gate scored a 100-token prune on a secondary file while this
    # reported the 43,000-token curation on the primary one. A test pins them.
    #
    # `runs` counts runs for this file, which is also the more useful number.
    counts, last_seen = {}, {}
    for i, r in enumerate(rows):
        f = r.get("file")
        counts[f] = counts.get(f, 0) + 1
        last_seen[f] = i           # rows is ascending by ts, so later index wins
    primary = max(counts, key=lambda f: (counts[f], last_seen[f]))
    rows = [r for r in rows if r.get("file") == primary]
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
        "runs": sum(1 for r in rows if is_curation_row(r)),
        "orphans": latest.get("docs_orphaned"),
        "dead": latest.get("links_dead"),
        "skill_version": latest.get("skill_version"),
        "wave": info["wave"] or None,
        "pair": info["pair"] or None,
        "best_actions": ", ".join(best.get("actions") or []) or "(untagged)" if best else None,
        "best_delta": best.get("delta_tokens") if best else None,
    })

if fmt == "json":
    print(json.dumps(records, indent=2))
    sys.exit(0)

records.sort(key=lambda r: -(r["tokens"] or 0))

if fmt == "tsv":
    print("repo\tlatest\ttokens\tnet\tnet_from\tnet_why\truns\torphans\tdead"
          "\tskill_version\twave\tpair\tbest_delta\tbest_actions")
    for r in records:
        print("\t".join("" if r[k] is None else str(r[k]) for k in
              ("repo", "latest", "tokens", "net", "net_from", "net_why", "runs",
               "orphans", "dead", "skill_version", "wave", "pair", "best_delta",
               "best_actions")))
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
    elif r["runs"] == 0:
        # Zero RUNS, not zero rows: a repo that measured and stopped has a
        # baseline row and nothing else. Before runs counted curations this read
        # `== 1`, which meant the same thing when a single row was all a
        # measurement-only visit produced.
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
# An A/B needs at least two versions in play; a uniform cohort is a baseline, not
# an experiment. Say which is which rather than leaving it to be inferred.
versions = {}
for r in records:
    if r["skill_version"]:
        versions.setdefault(r["skill_version"], []).append(r["repo"])
if versions:
    print("\nskill versions in play:")
    for v in sorted(versions):
        print(f"  {v}: {', '.join(sorted(versions[v]))}")
    if len(versions) == 1:
        print("  one version across the cohort — a baseline, not a comparison.")

# The roster's wave assignment, if it carries one. Printed here rather than only
# inside score-cohort.sh because the split is a property of the cohort, and the
# roll-up is where someone looks to see what the cohort is doing.
waves = {}
for r in records:
    if r["wave"]:
        waves.setdefault(r["wave"], []).append(r["repo"])
if waves:
    print("\nvalidation split (roster wave assignment):")
    for wv in sorted(waves):
        arm = sorted(waves[wv])
        adopted = sorted(
            r["repo"] for r in records
            if r["wave"] == wv and r["skill_version"]
        )
        print(f"  wave {wv}: {len(arm)} repos, {len(adopted)} adopted"
              f"{' — ' + ', '.join(adopted) if adopted else ''}")
    unassigned = [r["repo"] for r in records if not r["wave"]]
    if unassigned:
        print(f"  unassigned: {', '.join(sorted(unassigned))}")
    print("  score the arms against each other with score-cohort.sh.")
untagged = [r["repo"] for r in records if r["runs"] and not r["skill_version"]]
if untagged:
    print(f"\nno skill_version recorded (rows predate the field): {', '.join(untagged)}")

unexplained = [r for r in records if r["net"] is None and r["net_why"]]
if unexplained:
    print("\nnet not comparable:")
    for r in unexplained:
        print(f"  {r['repo']}: {r['net_why']}")
    print("  a method change makes the newest row that repo's baseline; net "
          "returns once two rows share a method.")
PY
