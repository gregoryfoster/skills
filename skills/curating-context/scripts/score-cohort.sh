#!/usr/bin/env bash
# score-cohort.sh — decide whether a proposed change to curating-context is
# adopted, by scoring one arm of the cohort against the other.
#
# The cohort is this skill's held-out validation split. Every learning folded in
# so far was accepted because it seemed right to whoever proposed it; this script
# exists so that stops being the standard. It reports, it never writes, and it
# never adopts anything — a human reads the verdict and acts on it.
set -euo pipefail

usage() {
  cat <<'USAGE'
score-cohort.sh — paired validation gate for skill changes

Usage:
  score-cohort.sh [--cohort-file PATH] [--treatment WAVE] [--control WAVE]

Options:
  --cohort-file PATH  Roster carrying `wave:` and `pair:` annotations.
                      Default: .skills/cohort
  --treatment WAVE    Wave running the PROPOSED version. Default: a
  --control WAVE      Wave running the CURRENT version. Default: b

                      Note the direction. Wave A adopts FIRST and therefore
                      holds the OLDER version, so the first experiment inverts
                      the defaults: --treatment b --control a. The defaults suit
                      later rounds, once A has caught up and is the arm carrying
                      a proposal. Get this backwards and a winning change reads
                      as a losing one.
  --ledger PATH       Ledger path within each repo.
                      Default: .skills/context-metrics.jsonl
  --branch NAME       Branch to read for owner/repo entries.
  --min-pairs N       Fewest informative pairs that can produce a verdict
                      other than INCONCLUSIVE. Default: 3
  --format FMT        table (default) or json
  -h, --help          Show this help and exit 0.

What it scores
  For each repo, the FIRST curation run recorded under a skill version — the
  first ledger row carrying `skill_version` whose actions are not purely
  `baseline*`. First runs are what get compared, because a repo's first curation
  and its fifth are not the same task, and the roster's pairs are matched on
  starting state precisely so that first-against-first is a fair comparison.

  The effectiveness metric is budget-gap closure:

      gap     = max(0, tokens - budget)
      closure = (gap_before - gap_after) / gap_before

  A fraction, not a token count, because the cohort spans 5,331 to 52,953 tokens
  and an absolute reduction would let the largest repo decide every verdict.
  A repo already under budget has no gap to close; it is scored for safety and
  reported as uninformative for effectiveness rather than counted as a 0 or a 1.

Safety gates (checked before any score)
  A treatment run trips a gate if it dropped content, broke the surface, or left
  it less navigable than it found it:

    no_loss != ok       prove-no-loss.sh did not confirm relocation
    links_dead > 0      the curated surface has broken links
    docs_orphaned rose  demotion created docs nothing points at

  Any tripped gate in the treatment arm is an outright REJECT, whatever the token
  numbers say — a change that reduces tokens by losing content is the one failure
  this skill exists to prevent, and no amount of closure buys it back. Missing
  data is never a pass: a run with no `no_loss` field is unscorable, not ok.

  A tripped gate in the CONTROL arm is reported but does not reject: that is the
  current version failing, which is a finding about today rather than a reason to
  refuse tomorrow.

Adoption rule
  Adopt only if the treatment wins EVERY informative pair. Ties, mixed results,
  and "no measurable difference" are all rejections. With five informative pairs
  a clean sweep is p=0.031 under a one-sided sign test, and anything short of one
  is not distinguishable from noise at this sample size — so a majority rule here
  would be a rule for adopting noise.

  Record every rejection in references/rejected-changes.md with these numbers.

Exit codes:
  0  ADOPT — treatment won every informative pair, no safety gate tripped
  1  usage error, or the roster carries no wave assignment
  2  infrastructure failure (python3 or gh missing, library missing)
  3  REJECT — a safety gate tripped, or the treatment did not sweep
  5  INCONCLUSIVE — too few informative pairs, or both arms ran the same version
USAGE
}

COHORT_FILE=".skills/cohort"
TREATMENT="a"
CONTROL="b"
LEDGER=".skills/context-metrics.jsonl"
BRANCH=""
MIN_PAIRS=3
FORMAT="table"

while [ $# -gt 0 ]; do
  case "$1" in
    --cohort-file) COHORT_FILE="${2:?--cohort-file needs a path}"; shift 2 ;;
    --treatment) TREATMENT="${2:?--treatment needs a wave}"; shift 2 ;;
    --control) CONTROL="${2:?--control needs a wave}"; shift 2 ;;
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch needs a name}"; shift 2 ;;
    --min-pairs) MIN_PAIRS="${2:?--min-pairs needs a number}"; shift 2 ;;
    --format) FORMAT="${2:?--format needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$FORMAT" in
  table|json) ;;
  *) echo "ERROR --format must be table or json" >&2; exit 1 ;;
esac
case "$MIN_PAIRS" in
  ''|*[!0-9]*) echo "ERROR --min-pairs must be a non-negative integer" >&2; exit 1 ;;
esac
if [ "$TREATMENT" = "$CONTROL" ]; then
  echo "ERROR --treatment and --control name the same wave ('$TREATMENT')" >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

# --- shared library -------------------------------------------------------
# After argument parsing: the library defines no `usage`, but the four sibling
# scripts all source here and matching them keeps the shape reviewable.
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

[ -f "$COHORT_FILE" ] || {
  echo "ERROR no cohort file at $COHORT_FILE" >&2; exit 1; }

ctx_read_roster "$COHORT_FILE" >"$TMP/roster"

# An unannotated roster cannot answer the question this script asks. Say what is
# missing and what it looks like, rather than reporting an empty comparison as
# though the experiment had run and found nothing.
# The flag, rather than `$3 != "" { exit 0 }`: awk's `exit` runs the END block on
# its way out, so an END that exits too has the last word and the early exit is
# discarded. Written the obvious way this reported every annotated roster as
# unannotated.
if ! awk -F"$CTX_US" '$3 != "" { found = 1; exit } END { exit !found }' "$TMP/roster"; then
  cat >&2 <<EOF
ERROR $COHORT_FILE carries no wave assignment, so there are no arms to compare.
      Annotate each entry, e.g.:

        CannObserv/usa-wa                      wave:a pair:1
        CannObserv/cannabis.observer-wordpress wave:b pair:1

      Pairs are matched on starting state; see references/validation-gate.md.
EOF
  exit 1
fi

if awk -F"$CTX_US" '$1 == "repo" { found = 1; exit } END { exit !found }' "$TMP/roster" \
   && ! command -v gh >/dev/null 2>&1; then
  echo "ERROR gh is required to read owner/repo entries" >&2
  exit 2
fi

: >"$TMP/all.jsonl"
while IFS="$CTX_US" read -r kind entry wave pair; do
  [ -n "$wave" ] || continue
  case "$wave" in
    "$TREATMENT"|"$CONTROL") ;;
    *) continue ;;
  esac
  name="$(basename "$entry")"
  RC=0
  ctx_fetch_ledger "$kind" "$entry" "$LEDGER" "$BRANCH" "$TMP/raw" || RC=$?
  case "$RC" in
    3) printf '%s\t%s\t%s\t%s\n' "$name" "$wave" "$pair" "MISSING" >>"$TMP/all.jsonl"
       continue ;;
    0) ;;
    *) printf '%s\t%s\t%s\t%s\n' "$name" "$wave" "$pair" "ERROR" >>"$TMP/all.jsonl"
       continue ;;
  esac
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '%s\t%s\t%s\t%s\n' "$name" "$wave" "$pair" "$line" >>"$TMP/all.jsonl"
  done <"$TMP/raw"
done <"$TMP/roster"

RC=0
python3 - "$TMP/all.jsonl" "$TREATMENT" "$CONTROL" "$MIN_PAIRS" "$FORMAT" <<'PY' || RC=$?
import json
import sys

src, treatment, control, min_pairs, fmt = sys.argv[1:6]
min_pairs = int(min_pairs)

repos = {}
order = []
for raw in open(src, encoding="utf-8"):
    raw = raw.rstrip("\n")
    if not raw or raw.count("\t") < 3:
        continue
    name, wave, pair, payload = raw.split("\t", 3)
    if name not in repos:
        repos[name] = {"rows": [], "status": "ok", "wave": wave, "pair": pair}
        order.append(name)
    if payload in ("MISSING", "ERROR"):
        repos[name]["status"] = "no ledger" if payload == "MISSING" else "unreadable"
        continue
    try:
        repos[name]["rows"].append(json.loads(payload))
    except ValueError:
        repos[name]["status"] = "malformed rows"


def is_baseline(row):
    """A measurement, not a curation. Baseline rows establish the starting
    number and must not be scored as though the skill had done work."""
    acts = row.get("actions") or []
    return bool(acts) and all(a.split(":", 1)[0] == "baseline" for a in acts)


def score_repo(name, info):
    rec = {
        "repo": name, "wave": info["wave"], "pair": info["pair"],
        "status": None, "why": None, "before": None, "after": None,
        "budget": None, "closure": None, "no_loss": None,
        "skill_version": None, "ts": None, "gates": [],
    }
    if info["status"] != "ok":
        rec["status"] = "unscorable"
        rec["why"] = info["status"]
        return rec
    # ts is a date, so several runs on one day tie. sorted() is stable, so ties
    # keep ledger order — which is append order, which is the true sequence.
    rows = sorted(info["rows"], key=lambda r: r.get("ts") or "")
    if not rows:
        rec["status"] = "unscorable"
        rec["why"] = "no ledger rows"
        return rec

    scored = prev = None
    for i, r in enumerate(rows):
        if r.get("skill_version") and not is_baseline(r):
            scored = r
            prev = rows[i - 1] if i else None
            break
    if scored is None:
        rec["status"] = "unscorable"
        rec["why"] = "no attributed curation run yet (only baselines, or no skill_version)"
        return rec

    rec["skill_version"] = scored.get("skill_version")
    rec["ts"] = scored.get("ts")
    rec["after"] = scored.get("tokens")
    rec["budget"] = scored.get("budget")
    rec["no_loss"] = scored.get("no_loss")

    # Safety first, and independent of whether the run is scorable for
    # effectiveness: a run that dropped content is a failure even if its
    # before-row is missing and no closure can be computed.
    if scored.get("no_loss") != "ok":
        got = scored.get("no_loss") or "not recorded"
        rec["gates"].append(f"no_loss={got}")
    dead = scored.get("links_dead")
    if isinstance(dead, int) and dead > 0:
        rec["gates"].append(f"links_dead={dead}")
    if prev is not None:
        a, b = prev.get("docs_orphaned"), scored.get("docs_orphaned")
        if isinstance(a, int) and isinstance(b, int) and b > a:
            rec["gates"].append(f"docs_orphaned {a}->{b}")

    if rec["gates"]:
        rec["status"] = "failed"
        rec["why"] = "; ".join(rec["gates"])
        return rec

    if prev is None:
        rec["status"] = "unscorable"
        rec["why"] = "no row before the first curation, so there is no before-state"
        return rec
    if prev.get("tokens_exact") != scored.get("tokens_exact"):
        rec["status"] = "unscorable"
        rec["why"] = "measurement method changed at the scored run"
        return rec
    if not isinstance(prev.get("tokens"), int) or not isinstance(rec["after"], int) \
            or not isinstance(rec["budget"], int):
        rec["status"] = "unscorable"
        rec["why"] = "a token count or budget is missing"
        return rec

    rec["before"] = prev["tokens"]
    gap_before = max(0, rec["before"] - rec["budget"])
    gap_after = max(0, rec["after"] - rec["budget"])
    if gap_before == 0:
        rec["status"] = "scored"
        rec["why"] = "already under budget before the run — no gap to close"
        return rec
    rec["closure"] = (gap_before - gap_after) / gap_before
    rec["status"] = "scored"
    return rec


records = [score_repo(n, repos[n]) for n in order]
by_arm = {treatment: {}, control: {}}
for r in records:
    if r["wave"] in by_arm and r["pair"]:
        by_arm[r["wave"]].setdefault(r["pair"], []).append(r)

pairs = []
for pid in sorted(set(by_arm[treatment]) | set(by_arm[control]),
                  key=lambda p: (len(p), p)):
    t = by_arm[treatment].get(pid, [])
    c = by_arm[control].get(pid, [])
    entry = {"pair": pid, "treatment": t[0] if len(t) == 1 else None,
             "control": c[0] if len(c) == 1 else None,
             "informative": False, "winner": None, "margin": None, "why": None}
    if len(t) != 1 or len(c) != 1:
        entry["why"] = (f"pair {pid} has {len(t)} treatment and {len(c)} control "
                        "repos; a pair needs exactly one of each")
        pairs.append(entry)
        continue
    tr, cr = t[0], c[0]
    if tr["status"] != "scored" or cr["status"] != "scored":
        bad = tr if tr["status"] != "scored" else cr
        entry["why"] = f"{bad['repo']}: {bad['status']} — {bad['why']}"
    elif tr["closure"] is None or cr["closure"] is None:
        side = tr if tr["closure"] is None else cr
        entry["why"] = f"{side['repo']} had no budget gap to close"
    elif tr["closure"] >= 1.0 and cr["closure"] >= 1.0:
        # Closure is capped at 1.0 — a run that cuts far past the budget scores
        # the same as one that lands on it, deliberately, so over-cutting earns
        # nothing. The cost is that when both arms reach budget the metric has no
        # room left to express a difference. Calling that a tie would make the
        # sweep rule unsatisfiable for any pair that starts close to budget, so
        # it is uninformative instead: the metric cannot separate them, which is
        # not the same as their being equal.
        entry["why"] = ("both arms closed the gap completely — closure saturates "
                        "and cannot separate them")
    else:
        entry["informative"] = True
        entry["margin"] = tr["closure"] - cr["closure"]
        if tr["closure"] > cr["closure"]:
            entry["winner"] = "treatment"
        elif cr["closure"] > tr["closure"]:
            entry["winner"] = "control"
        else:
            entry["winner"] = "tie"
    pairs.append(entry)

informative = [p for p in pairs if p["informative"]]
wins = [p for p in informative if p["winner"] == "treatment"]
t_failures = [r for r in records if r["wave"] == treatment and r["status"] == "failed"]
c_failures = [r for r in records if r["wave"] == control and r["status"] == "failed"]

t_versions = sorted({r["skill_version"] for r in records
                     if r["wave"] == treatment and r["skill_version"]})
c_versions = sorted({r["skill_version"] for r in records
                     if r["wave"] == control and r["skill_version"]})

verdict, code, reasons = None, 0, []
if t_failures:
    verdict, code = "REJECT", 3
    reasons.append("a safety gate tripped in the treatment arm: "
                   + "; ".join(f"{r['repo']} ({r['why']})" for r in t_failures))
elif not t_versions:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"no attributed curation run in the treatment arm (wave "
                   f"{treatment}) yet — nothing has been measured to compare")
elif t_versions == c_versions:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"both arms ran the same version ({', '.join(t_versions)}); "
                   "this is a baseline, not a comparison")
elif len(informative) < min_pairs:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"{len(informative)} informative pair(s), minimum {min_pairs}")
elif len(wins) == len(informative):
    verdict, code = "ADOPT", 0
    p = 0.5 ** len(informative)
    short = 5 - len(informative)
    caveat = ("" if p <= 0.05 else
              " — above 0.05, so this sweep is suggestive rather than "
              f"significant; {short} more informative "
              f"{'pair' if short == 1 else 'pairs'} would reach the "
              "conventional threshold")
    reasons.append(f"the treatment won all {len(informative)} informative pairs "
                   f"(p={p:.3f}, one-sided sign test){caveat}")
else:
    verdict, code = "REJECT", 3
    lost = [f"pair {p['pair']} -> {p['winner']}" for p in informative
            if p["winner"] != "treatment"]
    reasons.append(f"the treatment won {len(wins)} of {len(informative)} "
                   f"informative pairs; adoption requires all ({'; '.join(lost)})")

if fmt == "json":
    print(json.dumps({
        "treatment_wave": treatment, "control_wave": control,
        "treatment_versions": t_versions, "control_versions": c_versions,
        "repos": records, "pairs": pairs,
        "informative_pairs": len(informative), "treatment_wins": len(wins),
        "min_pairs": min_pairs, "verdict": verdict, "reasons": reasons,
        "control_arm_failures": [r["repo"] for r in c_failures],
    }, indent=2))
    sys.exit(code)


def pct(v):
    return "-" if v is None else f"{v * 100:.1f}%"


def num(v):
    return "-" if not isinstance(v, int) else str(v)


w = max([len(r["repo"]) for r in records] + [4])
print(f"treatment wave {treatment}: {', '.join(t_versions) or 'no attributed runs'}")
print(f"control   wave {control}: {', '.join(c_versions) or 'no attributed runs'}")
print()
print(f"{'pair':>4}  {'arm':<3} {'repo':<{w}} {'before':>8} {'after':>8} "
      f"{'budget':>7} {'closure':>8}  no_loss")
print("-" * (w + 48))
for p in pairs:
    for tag, r in (("T", p["treatment"]), ("C", p["control"])):
        if r is None:
            print(f"{p['pair']:>4}  {tag:<3} (missing)")
            continue
        print(f"{p['pair']:>4}  {tag:<3} {r['repo']:<{w}} {num(r['before']):>8} "
              f"{num(r['after']):>8} {num(r['budget']):>7} {pct(r['closure']):>8}"
              f"  {r['no_loss'] or '-'}")
    if p["informative"]:
        margin = p["margin"] * 100
        print(f"{'':>4}  -> {p['winner']} ({margin:+.1f}pp)")
    else:
        print(f"{'':>4}  -> uninformative: {p['why']}")
print()

unassigned = [r for r in records if not r["pair"]]
if unassigned:
    print("not in any pair: "
          + ", ".join(f"{r['repo']} (wave {r['wave']})" for r in unassigned))
if c_failures:
    print("control-arm safety failures (reported, not a reason to reject the "
          "proposal):")
    for r in c_failures:
        print(f"  {r['repo']}: {r['why']}")
    print()

print(f"verdict: {verdict}")
for reason in reasons:
    print(f"  {reason}")
if verdict == "REJECT":
    print("  record this in references/rejected-changes.md with the numbers "
          "above — a rejection nobody wrote down gets re-proposed.")
elif verdict == "INCONCLUSIVE":
    print("  this is not a rejection and does not belong in "
          "rejected-changes.md. Nothing has been decided; the proposal is "
          "still pending evidence.")
sys.exit(code)
PY

exit "$RC"
