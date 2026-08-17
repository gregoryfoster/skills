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

                      Note the direction. In experiment 1 wave A adopted first
                      and held the OLDER version, so that run inverts the
                      defaults: --treatment b --control a. Get this backwards
                      and a winning change reads as a losing one — so an arm
                      carrying only older versions than the other is detected
                      and returns INCONCLUSIVE rather than a rejection.

                      wave:/pair: no longer ASSIGN a version (#118/#168). They
                      are rollout order; the arm a run belongs to is the
                      skill_version on its own row. Which wave carries which
                      version is therefore an observation about the ledgers, not
                      a property of the roster — read it off the two header
                      lines rather than assuming a direction.
  --ledger PATH       Ledger path within each repo.
                      Default: .skills/context-metrics.jsonl
  --branch NAME       Branch to read for owner/repo entries.
  --min-pairs N       Fewest informative pairs that can produce a verdict
                      other than INCONCLUSIVE. Minimum 1. Default: 3

                      This governs ADOPTION. A REJECT has its own floor of 3
                      that --min-pairs cannot lower: an adoption is revisited
                      the next time the skill changes, while a rejection is
                      written into rejected-changes.md permanently and shapes
                      every later proposal. Below the rejection floor a failed
                      sweep is INCONCLUSIVE. A tripped SAFETY gate is exempt —
                      one repo that dropped content rejects on its own, with no
                      pairs at all.
  --format FMT        table (default) or json
  -h, --help          Show this help and exit 0.

What it scores
  For each repo, the FIRST curation run recorded under a skill version — the
  first ledger row carrying `skill_version` whose actions are not purely
  `baseline*`. First runs are what get compared, because a repo's first curation
  and its fifth are not the same task, and the roster's pairs are matched on
  starting state precisely so that first-against-first is a fair comparison.

  The before-state is the previous row FOR THE SAME POLICY FILE. A ledger may
  track several, and an untagged run (actions: []) cannot be told from a
  baseline, so it makes the repo unscorable rather than being guessed at.

  A first curation therefore needs a BASELINE ROW to be scorable at all — it is
  the run that creates the ledger, so nothing precedes it by construction. Phase
  1 records that row (`record-telemetry.sh --baseline`) and Phase 7 records the
  curation; both ship in the same commit. When every repo in both arms is
  unscorable for one and the same reason, this script says so as a GATE DEFECT
  rather than reporting an empty experiment (#116).

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
    links_dead_anchors > 0
                        a link resolves to a file but its #fragment names no
                        heading — the breakage a doc split makes, which
                        links_dead alone cannot see
    docs_orphaned rose  demotion created docs nothing points at

  no_loss_warrants is NOT a gate, deliberately. A warranted loss is a line this
  run's own split or a mandated rename forced it to rewrite (#111), and
  rejecting a run for saying so would recreate the choice the field exists to
  remove — the rational move would be to stop recording it. It rides the
  no_loss column as `ok+Nw` instead, so a run that waved eight lines through and
  one that waved none stop reading identically. The defences against a
  ballooning warrant file are per-entry accountability in prove-no-loss.sh's
  own report and the DELTA across runs, the same two the cohort settled on for
  seams_acked.

  Any tripped gate in the treatment arm is an outright REJECT, whatever the token
  numbers say — a change that reduces tokens by losing content is the one failure
  this skill exists to prevent, and no amount of closure buys it back.

  A RECORDED failure and a MISSING verdict are kept apart. Both block adoption;
  only the first is evidence anything went wrong. A `no_loss` that is absent or
  `skipped` yields INCONCLUSIVE, not REJECT — nothing was refuted, the experiment
  was run without its safety check, and filing that in rejected-changes.md would
  record the idea as tested and beaten when it was neither.

  A tripped gate in the CONTROL arm is reported but does not reject: that is the
  current version failing, which is a finding about today rather than a reason to
  refuse tomorrow. A missing verdict there is reported separately again, because
  "failure" would read as the shipped skill having dropped content when in fact
  nobody ran the check.

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
  3  REJECT — a recorded safety gate tripped, or the treatment did not sweep
     over at least the rejection floor of informative pairs
  5  INCONCLUSIVE — nothing was decided: too few informative pairs, a failed
     sweep below the rejection floor, safety unverified, every repo in both arms
     unscorable for one reason, both arms on one version, an arm split across
     versions, or the arms look inverted

Every question of the form "is this even an experiment?" is answered BEFORE any
verdict that would reject, because a REJECT tells the reader to write the change
into rejected-changes.md — a permanent record. Naming a change as refuted when
the comparison was mislabelled, or when no proposal existed, is the worst single
output this script can produce. Treatment-arm safety failures are printed
whatever the verdict, so the reordering masks nothing.
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
  ''|*[!0-9]*) echo "ERROR --min-pairs must be a positive integer" >&2; exit 1 ;;
esac
# Zero is refused rather than clamped. A verdict computed over no pairs is not a
# weaker verdict, it is no verdict, and the sweep test reads `0 == 0` as a win.
[ "$MIN_PAIRS" -ge 1 ] || {
  echo "ERROR --min-pairs must be at least 1: a comparison over zero pairs" >&2
  echo "      would adopt on no evidence at all" >&2
  exit 1; }
if [ "$TREATMENT" = "$CONTROL" ]; then
  echo "ERROR --treatment and --control name the same wave ('$TREATMENT')" >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

# --- shared library -------------------------------------------------------
# After argument parsing, matching the five sibling scripts. The library
# namespaces its own help as ctx_lib_usage() precisely so that sourcing cannot
# replace a caller's usage() — before that rename it did, and only the
# convention of parsing arguments first kept anyone's --help working.
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
# C-runs-when-A-is-true is the intent: both tests must hold, and either one
# failing means the same thing — no library, no measurement, exit 2.
# shellcheck disable=SC2015
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
  # An entry outside the two arms is REPORTED, not dropped. The roll-up already
  # refuses to skip a repo silently on the principle that missing telemetry is
  # itself the finding; a gate that quietly shrinks its own sample is worse,
  # because a typo'd wave: value removes a repo from the experiment with no
  # trace anywhere in the output.
  case "$wave" in
    "$TREATMENT"|"$CONTROL") ;;
    *) printf '%s\t%s\t%s\t%s\n' "$entry" "$wave" "$pair" "OUT_OF_ARM" \
         >>"$TMP/all.jsonl"
       continue ;;
  esac
  # The FULL roster entry is the key, not its basename: OrgA/cli and OrgB/cli
  # would otherwise merge into one record. The reader shortens it for display
  # when it is unambiguous.
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

RC=0
python3 - "$TMP/all.jsonl" "$TREATMENT" "$CONTROL" "$MIN_PAIRS" "$FORMAT" <<'PY' || RC=$?
import json
import sys

src, treatment, control, min_pairs, fmt = sys.argv[1:6]
min_pairs = int(min_pairs)

repos = {}
order = []
out_of_arm = []
for raw in open(src, encoding="utf-8"):
    raw = raw.rstrip("\n")
    if not raw or raw.count("\t") < 3:
        continue
    key, wave, pair, payload = raw.split("\t", 3)
    if payload == "OUT_OF_ARM":
        out_of_arm.append((key, wave))
        continue
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

# Repos are keyed by their full roster entry, not by basename: two entries
# sharing a basename (OrgA/cli and OrgB/cli, or two local checkouts of the same
# project) would otherwise merge into one record, concatenating two ledgers and
# reporting one arm as having no attributed run when it has one. The display
# name stays short unless it would be ambiguous, in which case the whole entry
# is shown — a table row that names two different repos identically is worse
# than a wide one.
basenames = {}
for key in order:
    basenames.setdefault(key.rstrip("/").rsplit("/", 1)[-1], []).append(key)
display = {
    key: (short if len(keys) == 1 else key)
    for short, keys in basenames.items() for key in keys
}


def classify_run(row):
    """Which kind of run a ledger row records: a baseline measurement, a
    curation, or something that cannot be told apart from either."""
    acts = row.get("actions") or []
    if not acts:
        # record-telemetry.sh emits actions: [] when --actions was omitted. An
        # untagged run cannot be distinguished from a baseline, and scoring one
        # as a curation would attribute its near-zero closure to the skill
        # version. Surface the tagging gap instead of guessing past it.
        return "untagged"
    if all(a.split(":", 1)[0] == "baseline" for a in acts):
        return "baseline"
    return "curation"


def score_repo(key, info):
    rec = {
        "repo": display[key], "entry": key, "wave": info["wave"],
        "pair": info["pair"], "status": None, "why": None, "why_code": None,
        "before": None,
        "after": None, "budget": None, "closure": None, "no_loss": None,
        "no_loss_warrants": None,
        "skill_version": None, "ts": None, "file": None, "other_files": 0,
        "gates": [], "unverified": [],
    }
    # why_code is the machine-readable twin of `why`, which interpolates repo
    # detail and so cannot be compared across repos. The systematic-defect check
    # below groups on it: twelve repos unscorable for twelve different reasons is
    # a cohort problem, and twelve unscorable for ONE reason is a gate problem.
    if info["status"] != "ok":
        rec["status"] = "unscorable"
        rec["why"] = info["status"]
        rec["why_code"] = info["status"].replace(" ", "_")
        return rec
    # ts is a date, so several runs on one day tie. sorted() is stable, so ties
    # keep ledger order — which is append order, which is the true sequence.
    rows = sorted(info["rows"], key=lambda r: r.get("ts") or "")
    if not rows:
        rec["status"] = "unscorable"
        rec["why"] = "no ledger rows"
        rec["why_code"] = "no_ledger_rows"
        return rec

    # PRIMARY POLICY FILE: the one with the most rows, ties broken by whichever
    # was measured most recently. A ledger may track several — record-telemetry.sh
    # keys its own deltas by file — so "what did this repo do" is not answerable
    # until one file is named.
    #
    # Most-recent alone was the first rule and it was too fragile: one incidental
    # baseline row for docs/GUIDE.md re-defined a repo that had curated AGENTS.md
    # 50,000 -> 6,800 over three runs, dropping it out of the experiment entirely
    # and collapsing the roll-up's headline to 4,000 tokens / 1 run / no net.
    # Row count is what a stray append cannot flip.
    #
    # THIS RULE IS SHARED WITH cohort-report.sh AND MUST STAY IDENTICAL. When the
    # two disagreed, one ledger produced two irreconcilable pictures of the same
    # repo: the gate scored sub/AGENTS.md 9,000 -> 8,900 (a 100-token prune, 3.3%
    # closure) while the roll-up reported AGENTS.md at 7,000, net -43,000. A test
    # pins the two scripts to the same answer.
    counts, last_seen = {}, {}
    for i, r in enumerate(rows):
        f = r.get("file")
        counts[f] = counts.get(f, 0) + 1
        last_seen[f] = i           # rows is ascending by ts, so later index wins
    primary = max(counts, key=lambda f: (counts[f], last_seen[f]))
    rows = [r for r in rows if r.get("file") == primary]
    rec["file"] = primary
    rec["other_files"] = len(counts) - 1

    scored = scored_idx = None
    for i, r in enumerate(rows):
        if not r.get("skill_version"):
            continue
        kind = classify_run(r)
        if kind == "baseline":
            continue
        if kind == "untagged":
            rec["status"] = "unscorable"
            rec["why"] = ("the first attributed run carries no action tags, so it "
                          "cannot be told from a baseline; tag it and re-score")
            rec["why_code"] = "untagged_run"
            return rec
        scored, scored_idx = r, i
        break
    if scored is None:
        extra = (f"; {rec['other_files']} other file(s) in this ledger were not "
                 "scored" if rec["other_files"] else "")
        rec["status"] = "unscorable"
        rec["why"] = (f"no attributed curation run for {primary} yet (only "
                      f"baselines, or no skill_version){extra}")
        rec["why_code"] = "no_attributed_run"
        return rec

    # The before-state is the row before it in the SAME file — carried from the
    # scan rather than looked up with .index(), which matches by dict equality:
    # two byte-identical rows (a same-day re-run with no --note) would resolve to
    # the earlier one and take the before-state a row too early.
    prev = rows[scored_idx - 1] if scored_idx else None

    rec["skill_version"] = scored.get("skill_version")
    rec["ts"] = scored.get("ts")
    rec["after"] = scored.get("tokens")
    rec["budget"] = scored.get("budget")
    rec["no_loss"] = scored.get("no_loss")
    rec["no_loss_warrants"] = scored.get("no_loss_warrants")

    # Safety first, and independent of whether the run is scorable for
    # effectiveness: a run that dropped content is a failure even if its
    # before-row is missing and no closure can be computed.
    #
    # A recorded non-ok verdict and an absent one are kept apart. Both block
    # adoption, but only the first is evidence that anything went wrong, and
    # calling a missing verdict a "failure" in the control-arm report reads as
    # the shipped skill having dropped content when nobody ran the check.
    nl = scored.get("no_loss")
    if nl == "ok":
        pass
    elif nl in (None, "skipped"):
        rec["unverified"].append(f"no_loss={nl or 'not recorded'}")
    else:
        rec["gates"].append(f"no_loss={nl}")
    dead = scored.get("links_dead")
    if isinstance(dead, int) and dead > 0:
        rec["gates"].append(f"links_dead={dead}")
    # The anchor half of the same gate (#120/#124). Same isinstance shape as
    # links_dead above, which is what keeps a row predating the field out of
    # the gate rather than retroactively rejecting every historical run — the
    # field is null there, and null is not a violation.
    dead_anchors = scored.get("links_dead_anchors")
    if isinstance(dead_anchors, int) and dead_anchors > 0:
        rec["gates"].append(f"links_dead_anchors={dead_anchors}")
    if prev is not None:
        a, b = prev.get("docs_orphaned"), scored.get("docs_orphaned")
        if isinstance(a, int) and isinstance(b, int) and b > a:
            rec["gates"].append(f"docs_orphaned {a}->{b}")

    if rec["gates"]:
        rec["status"] = "failed"
        rec["why"] = "; ".join(rec["gates"])
        return rec
    if rec["unverified"]:
        rec["status"] = "unverified"
        rec["why"] = "; ".join(rec["unverified"])
        return rec

    if prev is None:
        rec["status"] = "unscorable"
        rec["why"] = "no row before the first curation, so there is no before-state"
        rec["why_code"] = "no_before_state"
        return rec
    if prev.get("tokens_exact") != scored.get("tokens_exact"):
        rec["status"] = "unscorable"
        rec["why"] = "measurement method changed at the scored run"
        rec["why_code"] = "method_changed"
        return rec
    if not isinstance(prev.get("tokens"), int) or not isinstance(rec["after"], int) \
            or not isinstance(rec["budget"], int):
        rec["status"] = "unscorable"
        rec["why"] = "a token count or budget is missing"
        rec["why_code"] = "missing_counts"
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


records = [score_repo(k, repos[k]) for k in order]
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

# An ADOPT and a REJECT are not symmetric outputs, so they do not share a floor.
# An ADOPT is a decision to ship, revisited every time the skill changes again; a
# REJECT writes into rejected-changes.md, which is permanent by design and shapes
# every future proposal. Experiment 1 came within one flag of writing a rejection
# from two pairs, both of them the honest-shortfall repos and one of them the pair
# the roster itself flags as its weakest match. --min-pairs governs adoption and
# can be lowered; the rejection floor cannot go below REJECT_FLOOR, whatever it is
# set to. Below that a failed sweep is INCONCLUSIVE — pending evidence, which is
# what it actually is.
#
# The SAFETY veto is deliberately not subject to this: a single repo that dropped
# content rejects on its own with no pairs at all, which is why the t_failures
# branch sits above the pair arithmetic and why arm() is wider than the pairing.
REJECT_FLOOR = 3
# The EFFECTIVE floor, for reporting: --min-pairs gates every verdict first, so
# when it is set above REJECT_FLOOR it is what a rejection actually has to clear.
# The branch below is reachable only when min_pairs < REJECT_FLOOR — above that,
# `len(informative) >= min_pairs >= REJECT_FLOOR` and the shortfall test cannot
# fire — so REJECT_FLOOR is the constant that does the work there.
reject_floor = max(min_pairs, REJECT_FLOOR)

# A systematic unscorable — every repo in BOTH arms blocked by one rule. See the
# verdict branch below for why this is separated from "no informative pairs".
SYSTEMIC_HINTS = {
    "no_before_state":
        "every scored run is a FIRST curation, and a first curation is the run "
        "that creates the ledger. Record the Phase 1 measurement as a baseline "
        "row — `record-telemetry.sh --baseline` — so each run carries the "
        "before-state it is scored against (#116).",
    "untagged_run":
        "re-run Phase 7 with --actions naming what each run did; an untagged "
        "row cannot be told from a baseline.",
    "method_changed":
        "supply a credential and re-measure with --exact rather than recording "
        "estimates against exact rows.",
}

# Every record IS in an arm: the shell layer diverts entries whose wave is
# neither into out_of_arm before they reach here, so there is nothing to filter.
arm_records = records
# "No repo in either arm can satisfy this rule" is an inference from BREADTH, and
# at two repos it is not supported — the likelier reading is two non-compliant
# repos, which is a finding about the cohort and needs a different fix.
#
# Counted PER ARM, not over the roster. A roster total let 3 treatment repos and
# 1 control repo clear a floor of 4 and print the defect, which is the same thin
# evidence the floor exists to refuse — one arm carrying a single repo says
# nothing about whether the rule is satisfiable.
SYSTEMIC_MIN_PER_ARM = 2
t_arm_n = sum(1 for r in records if r["wave"] == treatment)
c_arm_n = sum(1 for r in records if r["wave"] == control)
systemic = systemic_hint = None
if min(t_arm_n, c_arm_n) >= SYSTEMIC_MIN_PER_ARM \
        and all(r["status"] == "unscorable" for r in arm_records):
    codes = {r["why_code"] for r in arm_records}
    if len(codes) == 1:
        code_one = next(iter(codes))
        # Prefer the sentence when every repo produced the same one; fall back to
        # the code when `why` interpolates per-repo detail (a file name, a count)
        # and quoting one repo's version would misreport it as everyone's.
        whys = {r["why"] for r in arm_records}
        systemic = next(iter(whys)) if len(whys) == 1 else code_one
        systemic_hint = SYSTEMIC_HINTS.get(code_one)


def arm(wave, status):
    """Every repo in the arm, INCLUDING ones in no pair — deliberately wider
    than the pairing.

    Safety is not a property of a comparison. Content lost under the proposed
    version is lost whether or not that repo had a partner, so an unpaired repo
    can veto adoption on its own while contributing nothing to any closure. It
    stays visible: it is listed under "not in any pair" and again in the
    treatment-arm failures block. Do not narrow this to paired repos.
    """
    return [r for r in records if r["wave"] == wave and r["status"] == status]


t_failures = arm(treatment, "failed")
t_unverified = arm(treatment, "unverified")
c_failures = arm(control, "failed")
c_unverified = arm(control, "unverified")


def versions_in(wave):
    m = {}
    for r in records:
        if r["wave"] == wave and r["skill_version"]:
            m.setdefault(r["skill_version"], []).append(r["repo"])
    return m


t_by_version, c_by_version = versions_in(treatment), versions_in(control)
t_versions, c_versions = sorted(t_by_version), sorted(c_by_version)


def version_canon(v):
    """One version, one spelling: 1.2, 1.2.0 and v1.2 are the same release.

    Two cosmetic differences are normalised away and no others: a leading v, and
    trailing zero components. Deliberately NOT the numeric key below, which is
    lossy — it maps every non-numeric component to 0, so 2.0-alpha and 2.0-beta
    would collapse into one version and two genuinely different prereleases
    would be reported as no experiment at all.

    The v guard checks that a digit follows, so a release actually named vNext
    is left alone.
    """
    s = str(v).strip()
    if s[:1] in ("v", "V") and s[1:2].isdigit():
        s = s[1:]
    parts = s.split(".")
    while len(parts) > 1 and parts[-1] in ("0", ""):
        parts.pop()
    return ".".join(parts)


def version_key(v):
    """Numeric components as a tuple, so 1.10 sorts ABOVE 1.9. Used only to
    decide whether the arms look inverted, never who wins: a non-numeric
    component reads as 0, which is fine for refusing to score and not fine for
    scoring.

    Derived from the canonical form so the two cannot disagree. They did: v1.2
    keyed to (0, 2) against 1.2's (1, 2), and the gate reported the arms as
    inverted for one release spelled two ways — a confidently wrong diagnosis
    pointing at the flags, which were not the problem. Deriving it also settles
    1.2.0 vs 1.2, which keyed unequal and could trip the same test.
    """
    return tuple(int(p) if p.isdigit() else 0
                 for p in version_canon(v).split("."))


# Every "is this even an experiment?" test compares CANONICAL versions. Comparing
# the raw strings let 1.2 and 1.2.0 read as two different versions, and the gate
# returned ADOPT for a comparison of a release against itself — finding 32's
# mirror, a positive verdict out of a non-experiment.
t_canon = {version_canon(v) for v in t_versions}
c_canon = {version_canon(v) for v in c_versions}

# The scored run is each repo's FIRST attributed curation, and that never moves.
# Six releases on, this table still reports experiment 1's arms — `wave b: 1.3`
# against `wave a: 1.2` — off rows written in August, with nothing saying those
# versions are spent. That is the failure #168 raises against the roster's
# wave:/pair: annotations, a reader taking an annotation as describing reality,
# sitting in the script instead. wave:/pair: are rollout order now, not a version
# assignment (#118/#168): nothing has ever held an arm at a version, because
# .skills/skills-pin is installed in none of the twelve and a pin could not label
# a scored run anyway — the cadence writes baseline:scheduled and classify_run()
# skips it.
#
# DERIVED from the ledgers already fetched, never asserted, so it cannot go stale
# the way the claim it replaces did. If the newest version recorded anywhere in
# either arm is newer than every version being scored, the comparison is
# historical and the notice names both.
ledger_versions = {r.get("skill_version") for info in repos.values()
                   for r in info["rows"] if r.get("skill_version")}
newest_in_ledgers = max(ledger_versions, key=version_key, default=None)
scored_versions = t_versions + c_versions
arms_are_historical = bool(
    newest_in_ledgers and scored_versions
    and version_key(newest_in_ledgers) > max(map(version_key, scored_versions)))


# Wave A adopts first and therefore holds the OLDER version, so the first
# experiment runs `--treatment b --control a` — and running the script bare
# inverts it, turning a winning change into a losing one. Detectable, so detect
# it rather than relying on three places in the docs saying so.
inverted = bool(t_versions and c_versions
                and max(map(version_key, t_versions))
                < min(map(version_key, c_versions)))

# Order matters, and it is the opposite of the obvious one. Every question of
# the form "is this even an experiment?" is asked BEFORE any verdict that would
# reject, because a REJECT tells the reader to write the change into
# rejected-changes.md — a permanent record that shapes future proposals. Naming
# a change as refuted when the comparison was mislabelled, or when there was no
# proposal at all, is the worst single output this script can produce. Treatment
# safety failures are still printed in the body whatever the verdict, so nothing
# is masked by the reordering.
verdict, code, reasons = None, 0, []
inversion_is_the_verdict = False
if not t_versions:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"no attributed curation run in the treatment arm (wave "
                   f"{treatment}) yet — nothing has been measured to compare")
elif not c_versions:
    # The symmetric case, and the EXPECTED intermediate state during the first
    # experiment: wave B adopts the proposal before wave A has re-run. Without
    # this branch it fell through to "no informative pairs", which is true and
    # sends the reader to look at pair scoring instead of at adoption progress.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"no attributed curation run in the control arm (wave "
                   f"{control}) yet — the treatment has nothing to be compared "
                   "against. Expected while the arms are still catching up")
elif len(t_canon) > 1 or len(c_canon) > 1:
    # "Adopt only if strictly better" presumes ONE proposal. An arm split across
    # versions names no coherent change, and a sweep could be carried by
    # whichever version happened to draw the easier pairs.
    #
    # Ahead of the inverted-arms test on purpose: an arm that is not internally
    # coherent cannot meaningfully be called older or newer than the other, and
    # reporting inversion first walked the reader through two diagnoses — swap
    # the flags, hit the split — to reach one problem.
    verdict, code = "INCONCLUSIVE", 5
    split = t_by_version if len(t_canon) > 1 else c_by_version
    which = treatment if len(t_canon) > 1 else control
    reasons.append(
        f"wave {which} is split across versions, so there is no single change to "
        "adopt: "
        + "; ".join(f"{v} ({', '.join(sorted(split[v]))})" for v in sorted(split))
        + " — bring the arm onto one version and re-score")
elif t_canon == c_canon:
    verdict, code = "INCONCLUSIVE", 5
    spelling = ""
    if set(t_versions) != set(c_versions):
        spelling = (f" — recorded as {', '.join(t_versions)} and "
                    f"{', '.join(c_versions)}, which canonicalise to the same "
                    "release; worth making the spelling uniform")
    reasons.append(f"both arms ran the same version ({', '.join(sorted(t_canon))})"
                   f"{spelling}; this is a baseline, not a comparison")
    if t_failures:
        # Real, and worth acting on, but it is a finding about the shipped
        # version rather than grounds to reject a proposal that does not exist.
        reasons.append("a safety gate did trip under that version — see the "
                       "treatment-arm failures above; that is a finding about "
                       "what is shipped, not a rejection of anything proposed")
elif inverted:
    # Detection alone was not enough: the WARN printed at the top and the verdict
    # then rejected the winning change and told the reader to file it as refuted,
    # twenty lines below the warning saying not to trust the result.
    inversion_is_the_verdict = True
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"the arms look inverted — wave {treatment} carries only "
                   f"older versions ({', '.join(t_versions)}) than wave "
                   f"{control} ({', '.join(c_versions)}). Re-run with "
                   f"--treatment {control} --control {treatment}; as scored "
                   "here a winning change reads as a losing one")
elif t_failures:
    verdict, code = "REJECT", 3
    # Named in the body rather than enumerated twice. The body block is what
    # keeps failures visible under the INCONCLUSIVE paths above, so it must not
    # look redundant enough to delete.
    reasons.append("a safety gate tripped in the treatment arm — see the "
                   "treatment-arm failures above")
elif t_unverified:
    # Blocks adoption, like a failure, but is NOT a rejection: nothing was
    # refuted, the experiment was run without its safety check. Filing that in
    # rejected-changes.md would record the idea as tested and beaten when it was
    # neither.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append("safety could not be verified in the treatment arm: "
                   + "; ".join(f"{r['repo']} ({r['why']})" for r in t_unverified)
                   + " — re-run those curations with --no-loss and re-score")
elif systemic is not None:
    # A SYSTEMATIC unscorable is a defect in the gate, not an empty experiment,
    # and the two read identically from below: both arrive at "no informative
    # pairs", which sends the reader to look at pair scoring. Experiment 1 came
    # back with all twelve repos unscorable for one reason — the before-state is
    # the previous ledger row, and a first curation is the run that creates the
    # ledger (#116) — and the only visible signal was the same line repeated
    # twelve times above a verdict that reads as "nothing has happened yet".
    #
    # The test is deliberately strict: every repo in BOTH arms, one reason. A
    # mixed bag of reasons is cohort non-compliance and each repo needs its own
    # fix; one reason across both arms is a rule that no repo can satisfy.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(
        f"GATE DEFECT — all {len(arm_records)} repos in both arms are unscorable "
        f"for the SAME reason: {systemic}")
    reasons.append(
        "a rule no repo in either arm can satisfy is a defect in this gate, not "
        "a finding about the cohort. Nothing was measured, so nothing about the "
        "proposal is in question — fix the gate and re-score")
    if systemic_hint:
        reasons.append(systemic_hint)
elif not informative:
    # Independent of --min-pairs. With --min-pairs 0 the sweep test below reads
    # `0 == 0` and adopts on no evidence whatever — a vacuous pass in the one
    # control that exists to prevent them.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append("no informative pairs — every pair was uninformative, so "
                   "nothing was measured")
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
    lost = [f"pair {p['pair']} -> {p['winner']}" for p in informative
            if p["winner"] != "treatment"]
    shortfall = (f"the treatment won {len(wins)} of {len(informative)} "
                 f"informative pairs; adoption requires all ({'; '.join(lost)})")
    if len(informative) < REJECT_FLOOR:
        # Blocks adoption exactly as a rejection would, but does not write one
        # down. See REJECT_FLOOR above: the asymmetry is between a decision that
        # gets revisited and a record that does not.
        verdict, code = "INCONCLUSIVE", 5
        reasons.append(shortfall)
        reasons.append(
            f"but {len(informative)} informative pair(s) is below the rejection "
            f"floor of {REJECT_FLOOR}, so this is not recorded as a refutation. "
            "A rejection is permanent and shapes every later proposal; adoption "
            "is revisited the next time the skill changes, so the two do not "
            "share a floor. The proposal is blocked and still pending evidence")
    else:
        verdict, code = "REJECT", 3
        reasons.append(shortfall)

# Only when inversion is what actually stopped the run. A split arm also trips
# the older-than test — an incoherent arm compares older than anything — and
# printing both banners walks the reader through two diagnoses for one problem.
inversion_warning = (
    f"WARN wave {treatment} carries only older versions than wave {control} "
    f"({', '.join(t_versions)} vs {', '.join(c_versions)}). The arms look "
    f"inverted: wave A adopts first and holds the older version, so the first "
    f"experiment runs --treatment {control} --control {treatment}. As scored "
    f"here, a winning change reads as a losing one."
) if inversion_is_the_verdict else None

if fmt == "json":
    print(json.dumps({
        "treatment_wave": treatment, "control_wave": control,
        "treatment_versions": t_versions, "control_versions": c_versions,
        "repos": records, "pairs": pairs,
        "informative_pairs": len(informative), "treatment_wins": len(wins),
        "min_pairs": min_pairs, "reject_floor": reject_floor,
        "systemic_unscorable": systemic,
        # Populated whichever way it lands: a reader distinguishing "no newer
        # version exists" from "the field was not computed" needs the version
        # either way, and null would collapse the two.
        "newest_version_in_ledgers": newest_in_ledgers,
        "arms_are_historical": arms_are_historical,
        "verdict": verdict, "reasons": reasons,
        "treatment_arm_failures": [r["repo"] for r in t_failures],
        "treatment_arm_unverified": [r["repo"] for r in t_unverified],
        "control_arm_failures": [r["repo"] for r in c_failures],
        "control_arm_unverified": [r["repo"] for r in c_unverified],
        "arms_may_be_inverted": inverted,
        "out_of_arm": [{"entry": k, "wave": w or None} for k, w in out_of_arm],
    }, indent=2))
    sys.exit(code)


def pct(v):
    return "-" if v is None else f"{v * 100:.1f}%"


def num(v):
    return "-" if not isinstance(v, int) else str(v)


def no_loss_cell(r):
    """The no_loss column, qualified by how much of it was judged (#111).

    Same isinstance shape the links_dead gates use, for the same reason: the
    field is null on every row predating it, and rendering that as `ok+0w`
    would claim the run measured and warranted nothing. Suppressed at 0 too —
    a run with an explicit zero is making the same claim a bare `ok` makes.
    """
    n = r.get("no_loss_warrants")
    base = r["no_loss"] or "-"
    return f"{base}+{n}w" if isinstance(n, int) and n > 0 else base


w = max([len(r["repo"]) for r in records] + [4])
print(f"treatment wave {treatment}: {', '.join(t_versions) or 'no attributed runs'}")
print(f"control   wave {control}: {', '.join(c_versions) or 'no attributed runs'}")
# Above the inversion warning on purpose: "these versions are spent" is context
# for reading the whole table, where the inversion warning is about one comparison
# within it. It never touches the verdict — a historical table is not a reason to
# reject anything, and a notice that moved an exit code would be a gate.
if arms_are_historical:
    print()
    print(f"NOTE the arms above are HISTORICAL. The scored run is each repo's "
          f"first attributed\n"
          f"     curation, which never moves, and these ledgers already carry "
          f"{newest_in_ledgers}. This is\n"
          f"     the experiment that ran, not the cohort as it is now. "
          f"wave:/pair: are rollout\n"
          f"     order, not a version assignment in force (#168).")
if inversion_warning:
    print()
    print(inversion_warning)
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
              f"  {no_loss_cell(r)}")
    if p["informative"]:
        margin = p["margin"] * 100
        print(f"{'':>4}  -> {p['winner']} ({margin:+.1f}pp)")
    else:
        print(f"{'':>4}  -> uninformative: {p['why']}")
print()

# Which file each score is actually about. The table has no room for a column,
# and without this a multi-file ledger reads as though its whole history were in
# view — two repos showing 50,000 -> 7,000 with no sign that a prune on a
# secondary file was excluded from both.
multi = [r for r in records if r["other_files"]]
if multi:
    print("multi-file ledgers — the file scored, and how many were not:")
    for r in multi:
        print(f"  {r['repo']}: {r['file']} "
              f"(+{r['other_files']} other file(s) not scored)")
    print()

unassigned = [r for r in records if not r["pair"]]
if unassigned:
    print("not in any pair: "
          + ", ".join(f"{r['repo']} (wave {r['wave']})" for r in unassigned))
if out_of_arm:
    print(f"not in either arm (wave is neither {treatment} nor {control}): "
          + ", ".join(f"{k} (wave {w or 'unassigned'})" for k, w in out_of_arm))
if unassigned or out_of_arm:
    print()
# Printed whatever the verdict, so that reordering the verdict checks — which
# put "is this even an experiment?" ahead of any REJECT — cannot mask a real
# safety failure behind an INCONCLUSIVE.
if t_failures:
    print("treatment-arm safety failures:")
    for r in t_failures:
        print(f"  {r['repo']}: {r['why']}")
    print()
if t_unverified:
    print("treatment-arm runs with no safety verdict (the check was not run):")
    for r in t_unverified:
        print(f"  {r['repo']}: {r['why']}")
    print()
if c_failures:
    print("control-arm safety failures (reported, not a reason to reject the "
          "proposal):")
    for r in c_failures:
        print(f"  {r['repo']}: {r['why']}")
    print()
if c_unverified:
    # Kept out of the block above on purpose. "Failure" there means the current
    # version did something wrong; this means nobody checked.
    print("control-arm runs with no safety verdict (not a failure — the check "
          "was not run):")
    for r in c_unverified:
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
