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

                      A registration (--experiment) carries its own floor. Left
                      unset, that floor is used; set, the STRICTER of the two
                      wins. The floor is a pre-registered parameter of the
                      experiment, so a flag may tighten it and may not loosen
                      it — loosening after the pair count is known is the same
                      move as choosing the metric after seeing the rows.
  --experiment NN     Score against the COMMITTED registration numbered NN --
                      .skills/experiments/NN-<slug>.yml. It names the primary
                      metric, which direction is better, the two versions the
                      arms are expected to carry, and the pair floor. Without
                      it the gate scores budget-gap closure, the default
                      pre-registered in references/validation-gate.md.
  --experiments-dir DIR
                      Where registrations live. Default: .skills/experiments

  There is NO --metric flag, deliberately. A flag naming a metric lets the same
  run be repeated until the answer is agreeable, which is the identical failure
  to picking the before-state after seeing the after-values. The metric comes
  from a committed file whose git history is the pre-registration proof, or it
  is the default this gate has always scored.
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
     versions, the arms look inverted, the arms are not the ones the
     registration named, the registered metric is on no row at all, or it is
     null across the whole control arm (the proposal added its own instrument)

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
EXPERIMENT=""
EXPERIMENTS_DIR=".skills/experiments"
# Set when --min-pairs was typed, so a registration's floor can override the
# DEFAULT without silently overriding a number the caller actually asked for.
MIN_PAIRS_SET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --cohort-file) COHORT_FILE="${2:?--cohort-file needs a path}"; shift 2 ;;
    --treatment) TREATMENT="${2:?--treatment needs a wave}"; shift 2 ;;
    --control) CONTROL="${2:?--control needs a wave}"; shift 2 ;;
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch needs a name}"; shift 2 ;;
    --min-pairs) MIN_PAIRS="${2:?--min-pairs needs a number}"
                 MIN_PAIRS_SET=1; shift 2 ;;
    --experiment) EXPERIMENT="${2:?--experiment needs a number}"; shift 2 ;;
    --experiments-dir) EXPERIMENTS_DIR="${2:?--experiments-dir needs a path}"
                       shift 2 ;;
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

# --- the pre-registration ---------------------------------------------------
# Resolved and validated BEFORE a single ledger is fetched. A registration that
# names a rejected metric or an illegal arm predicate is a usage error, and
# making the caller wait out twelve gh round-trips to be told so trains them to
# skip the flag.
#
# Its own python3 pass rather than a branch inside the scorer, so there is one
# parser and it runs first. The file is deliberately FLAT `key: value` — a
# pre-registration nobody can read is not evidence of anything, and a flat file
# is parseable in twenty lines here rather than requiring PyYAML, which the
# cohort repos this script runs in are not guaranteed to have.
: >"$TMP/experiment.json"
if [ -n "$EXPERIMENT" ]; then
  python3 - "$EXPERIMENTS_DIR" "$EXPERIMENT" \
      "$_libdir/../references/rejected-changes.md" \
      >"$TMP/experiment.json" <<'PY' || exit 1
import json
import re
import sys
from pathlib import Path

directory, number, rejected_path = sys.argv[1:4]


def die(*lines):
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(1)


if not number.isdigit():
    die(f"ERROR --experiment must be a number, not {number!r}")

d = Path(directory)
if not d.is_dir():
    die(f"ERROR no experiments directory at {directory}",
        "      A registration is a COMMITTED file — its git history is what "
        "proves the",
        "      metric was chosen before the rows were read. Create "
        f"{directory}/NN-<slug>.yml.")

# Matched on the numeric VALUE of the prefix, so `--experiment 2` and
# `--experiment 02` resolve the same file. A registration is cited by number in
# issues and commit messages, where nobody preserves the zero padding.
found = sorted(p for p in d.glob("*.yml")
               if re.match(r"^\d+-", p.name)
               and int(p.name.split("-", 1)[0]) == int(number))
if not found:
    die(f"ERROR no registration numbered {number} in {directory}",
        f"      Expected {directory}/{int(number):02d}-<slug>.yml, committed "
        "before the",
        "      treatment arm adopted. Without it there is no pre-registered "
        "metric to score.")
if len(found) > 1:
    die(f"ERROR {len(found)} files claim experiment {number} in {directory}:",
        *(f"        {p.name}" for p in found),
        "      Which one was registered is exactly the question the number "
        "answers.")

path = found[0]

REQUIRED = ("experiment", "proposal", "registered", "treatment_version",
            "control_version", "arm_predicate", "primary_metric", "direction",
            "min_pairs")
OPTIONAL = ("notes",)

fields = {}
for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    # Full-line comments only. An inline `#` is left in the value on purpose:
    # `proposal:` carries a URL, and stripping from the first `#` would silently
    # truncate a fragment into a different link.
    if not line or line.startswith("#"):
        continue
    if ":" not in line:
        die(f"ERROR {path.name}:{n}: not a `key: value` line: {raw!r}",
            "      A registration is flat by design — no nesting, no lists.")
    key, _, value = line.partition(":")
    key, value = key.strip(), value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if key in fields:
        # The second one silently winning is how an edited copy of another
        # registration keeps claiming to be the original.
        die(f"ERROR {path.name}:{n}: `{key}` is set twice")
    if key not in REQUIRED + OPTIONAL:
        die(f"ERROR {path.name}:{n}: unknown key `{key}`",
            f"      Known keys: {', '.join(REQUIRED + OPTIONAL)}.",
            "      Refused rather than ignored: a misspelled key reads as a "
            "declaration that",
            "      was never honoured, which is worse than one that was never "
            "made.")
    fields[key] = value

missing = [k for k in REQUIRED if k not in fields]
if missing:
    die(f"ERROR {path.name} omits required key(s): {', '.join(missing)}")

stem = int(path.name.split("-", 1)[0])
if not fields["experiment"].isdigit() or int(fields["experiment"]) != stem:
    die(f"ERROR {path.name} says `experiment: {fields['experiment']}` but is "
        f"filed as {stem:02d}",
        "      The file it is scored as and the file it says it is have to be "
        "the same file,",
        "      or the history proving pre-registration belongs to a different "
        "experiment.")

# The arm predicate. #118/#168 settled that the arm a run belongs to is the
# skill_version stamped on its OWN ROW — observed, never assigned — so there is
# exactly one legal value and the schema names it rather than leaving it
# implied. `wave` is refused BY NAME because it is the specific wrong answer: a
# generic "not a legal value" would read as a typo to the next author.
if fields["arm_predicate"] == "wave":
    die(f"ERROR {path.name}: `arm_predicate: wave` — wave:/pair: are rollout "
        "order, not an",
        "      arm assignment (#118/#168). A pin could hold a version in CI, "
        "but it cannot",
        "      label a SCORED run: the weekly cadence writes "
        "`baseline:scheduled`, and this",
        "      script skips every baseline* row when it looks for the run to "
        "score. The rows",
        "      a pin versions deterministically are exactly the rows the gate "
        "refuses to",
        "      score. Use `arm_predicate: skill_version`.")
if fields["arm_predicate"] != "skill_version":
    die(f"ERROR {path.name}: `arm_predicate: {fields['arm_predicate']}` — the "
        "only legal value",
        "      is `skill_version`, the version stamped on the scored row "
        "(#118/#168).")

if fields["direction"] not in ("higher", "lower"):
    die(f"ERROR {path.name}: `direction: {fields['direction']}` — must be "
        "`higher` or `lower`.",
        "      Which way is better is half of what registering a metric means; "
        "leaving it",
        "      implicit restores exactly the freedom the file exists to "
        "remove.")

if not fields["min_pairs"].isdigit() or int(fields["min_pairs"]) < 1:
    die(f"ERROR {path.name}: `min_pairs: {fields['min_pairs']}` — must be a "
        "positive integer.")

# A proposed primary metric is checked against rejected-changes.md before it is
# registered. `tokens_live` was proposed as a candidate in #118 despite already
# carrying an entry there — the exact failure that file exists to prevent,
# happening in the issue proposing the next round of metrics.
#
# READ from the file, never a list kept here. Adding an entry is what retires a
# metric, in one place; a copy of the list in this script is a second place to
# forget.
rejected = {}
try:
    for line in Path(rejected_path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("## "):
            continue
        for ident in re.findall(r"`([a-z_][a-z0-9_]*)`", line):
            rejected.setdefault(ident, line[3:].strip())
except OSError:
    # Not fatal, but not silent either: the check is the point of the step.
    print(f"WARN could not read {rejected_path}; the registered metric was NOT "
          "checked against the recorded rejections", file=sys.stderr)

metric = fields["primary_metric"]
if metric in rejected:
    die(f"ERROR {path.name}: `{metric}` is a recorded rejection and cannot be "
        "registered.",
        f"      references/rejected-changes.md: {rejected[metric]}",
        "      A metric already refuted cannot be the metric a later proposal "
        "is judged by.")

fields["experiment"] = f"{stem:02d}"
fields["min_pairs"] = int(fields["min_pairs"])
fields["file"] = str(path)
print(json.dumps(fields, sort_keys=True))
PY
fi

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
python3 - "$TMP/all.jsonl" "$TREATMENT" "$CONTROL" "$MIN_PAIRS" "$FORMAT" \
         "$TMP/experiment.json" "$MIN_PAIRS_SET" <<'PY' || RC=$?
import json
import sys

src, treatment, control, min_pairs, fmt, exp_src, min_pairs_set = sys.argv[1:8]
min_pairs = int(min_pairs)

# The registration, already resolved and validated above. Absent, the gate scores
# budget-gap closure with higher-is-better — which is not an unregistered metric
# but the one pre-registered in references/validation-gate.md's `## The metric`,
# committed long before any of these rows existed.
with open(exp_src, encoding="utf-8") as fh:
    _raw = fh.read().strip()
experiment = json.loads(_raw) if _raw else None
metric = experiment["primary_metric"] if experiment else "closure"
direction = experiment["direction"] if experiment else "higher"
if experiment:
    # A flag may TIGHTEN the registered floor and may not loosen it. Loosening
    # once the pair count is known is the same move as choosing the metric after
    # seeing the rows, and it is the move --min-pairs 2 nearly made in
    # experiment 1.
    min_pairs = (max(min_pairs, experiment["min_pairs"]) if min_pairs_set
                 else experiment["min_pairs"])

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
        # The registered metric's raw value off the scored row, when the metric
        # is a ledger FIELD rather than the derived closure. Null here means the
        # row did not record it — which is the whole content of the
        # added-its-own-instrument outcome below, so it must not be conflated
        # with a zero.
        "metric_raw": None,
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
    if metric != "closure":
        rec["metric_raw"] = scored.get(metric)

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

    # Everything below is CLOSURE's prerequisite, not the ledger's. A before-
    # state, a consistent measurement method and a token count are what the gap
    # arithmetic needs; a metric read straight off the scored row needs none of
    # them, and refusing such a row for a missing `tokens` would drop pairs from
    # an experiment the numbers have nothing to do with.
    if metric != "closure":
        # Still reported, just not required: the before/after token columns are
        # context for reading any experiment, and a blank one reads as a ledger
        # with nothing in it rather than as a metric that does not need it.
        if prev is not None and isinstance(prev.get("tokens"), int):
            rec["before"] = prev["tokens"]
        if not isinstance(rec["metric_raw"], (int, float)) \
                or isinstance(rec["metric_raw"], bool):
            # Scored, but with nothing to compare — the same shape as a repo
            # already under budget. The pair reports why rather than the repo
            # being called unscorable, which would suggest its ledger is at
            # fault when the field simply is not there.
            rec["metric_raw"] = None
            rec["why"] = f"no {metric} recorded on the scored run"
        rec["status"] = "scored"
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
             "informative": False, "winner": None, "margin": None,
             "saturated": False, "why": None}
    if len(t) != 1 or len(c) != 1:
        entry["why"] = (f"pair {pid} has {len(t)} treatment and {len(c)} control "
                        "repos; a pair needs exactly one of each")
        pairs.append(entry)
        continue
    tr, cr = t[0], c[0]
    # One accessor for both metric shapes, so every rule below — saturation,
    # ties, the winner, the margin — is written once and cannot drift between
    # them.
    key = "closure" if metric == "closure" else "metric_raw"
    tv, cv = tr[key], cr[key]
    if tr["status"] != "scored" or cr["status"] != "scored":
        bad = tr if tr["status"] != "scored" else cr
        entry["why"] = f"{bad['repo']}: {bad['status']} — {bad['why']}"
    elif tv is None or cv is None:
        side = tr if tv is None else cr
        entry["why"] = (f"{side['repo']} had no budget gap to close"
                        if metric == "closure"
                        else f"{side['repo']}: {side['why']}")
    elif metric == "closure" and tv >= 1.0 and cv >= 1.0:
        entry["saturated"] = True
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
        # Signed so a positive margin always means "the treatment did better",
        # whichever way the registered direction runs. Reading a lower-is-better
        # metric off an unsigned difference is how a winning change reads as a
        # losing one in a table nobody re-derives.
        entry["margin"] = (tv - cv) if direction == "higher" else (cv - tv)
        if tv == cv:
            # A TIE, not an uninformative pair, and deliberately so: "no
            # measurable difference" is a rejection under the adoption rule.
            # Saturation is the one exception, above, because there the metric
            # ran out of room rather than finding the arms equal.
            entry["winner"] = "tie"
        elif entry["margin"] > 0:
            entry["winner"] = "treatment"
        else:
            entry["winner"] = "control"
    pairs.append(entry)

informative = [p for p in pairs if p["informative"]]
wins = [p for p in informative if p["winner"] == "treatment"]
# Proposal 3 (#117). Four uninformative pairs out of six in experiment 1 because
# closure hit its cap is a finding about the BUDGET no longer binding for most of
# the cohort, and it read as "nothing happened". Counted and printed; it never
# moves the verdict.
saturated = [p for p in pairs if p["saturated"]]

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
# the ROSTER is newer than every version attributed to an arm, the comparison is
# historical and the notice names both.
#
# Roster-wide, not arm-wide, and the notice says "these ledgers" to match: a repo
# carrying no wave: annotation still evidences that the cohort has moved on, and
# narrowing this to the arms would let an unwaved member run six versions ahead
# with the table claiming to be current.
ledger_versions = {r.get("skill_version") for info in repos.values()
                   for r in info["rows"] if r.get("skill_version")}
# sorted() first: max() returns the FIRST maximal element, and set iteration order
# is not stable across runs. Two spellings of one release (1.2 / v1.2 / 1.2.0 —
# the collisions version_canon exists to absorb) key equal, so without this the
# reported spelling varies run to run for a value callers diff.
newest_in_ledgers = max(sorted(ledger_versions), key=version_key, default=None)
scored_versions = t_versions + c_versions
arms_are_historical = bool(
    newest_in_ledgers and scored_versions
    and version_key(newest_in_ledgers) > max(map(version_key, scored_versions)))


# In experiment 1 wave A adopted first and held the OLDER version, so that run
# needs `--treatment b --control a` — and running the script bare inverts it,
# turning a winning change into a losing one. Which wave holds which version is
# now an observation rather than an assignment (#118/#168), so the direction is
# detected from the rows rather than assumed from the flags.
inverted = bool(t_versions and c_versions
                and max(map(version_key, t_versions))
                < min(map(version_key, c_versions)))


def attributed(wave):
    """Records with a scored run — the only rows that could carry the metric.

    A repo with no attributed curation has not failed to record the field; it
    has not been curated. Counting it as a null would let one un-run repo
    declare the whole arm blind.
    """
    return [r for r in records if r["wave"] == wave and r["skill_version"]]


# Null across the WHOLE control arm, and present somewhere in the treatment arm.
# Both halves are load-bearing: null on both sides is not a proposal that added an
# instrument, it is a metric this gate cannot read at all — the branch below.
instrument_only = bool(
    experiment and metric != "closure"
    and attributed(control)
    and all(r["metric_raw"] is None for r in attributed(control))
    and any(r["metric_raw"] is not None for r in attributed(treatment)))

# Recorded on NO scored row anywhere. The registered metric is not a field the
# ledger carries — a derived rate (`truthfulness` is a share of scheduled rows,
# and this gate skips every scheduled row), a typo, or a measurement nobody has
# added yet. Without this branch all three land on "no informative pairs —
# nothing was measured", which is true, sends the reader to look at pair scoring,
# and never mentions that the metric was unreadable. That is the silent success
# this gate exists to stop producing.
unreadable_metric = bool(
    experiment and metric != "closure" and not instrument_only
    and (attributed(treatment) or attributed(control))
    and all(r["metric_raw"] is None
            for r in attributed(treatment) + attributed(control)))

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
elif experiment and (t_canon != {version_canon(experiment["treatment_version"])}
                     or c_canon != {version_canon(experiment["control_version"])}):
    # The last "is this even an experiment?" test, and it belongs with them: a
    # registration for 1.4-over-1.3 scored against 1.3-over-1.2 is not a weak
    # verdict but a verdict about a different comparison — and the reason a
    # registration is worth having is that this is now checkable at all.
    # Ahead of the REJECT branch, because writing the wrong change into
    # rejected-changes.md is the worst output this script can produce.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(
        f"registration {experiment['experiment']} "
        f"({experiment['file']}) is for treatment "
        f"{experiment['treatment_version']} over control "
        f"{experiment['control_version']}, but these arms carry "
        f"{', '.join(t_versions)} over {', '.join(c_versions)} — the rows in "
        "front of this run are not the experiment that was registered, so "
        "nothing here bears on it")
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
elif unreadable_metric:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(
        f"the registered primary metric `{metric}` is recorded on no scored row "
        "in either arm — this gate reads a metric as a FIELD off the run it "
        "scores, and that is not one")
    reasons.append(
        "a derived rate is not registerable as it stands: `truthfulness` is a "
        "share of SCHEDULED rows, and every `baseline*` row is skipped when "
        "looking for the run to score. Register a field the row carries — see "
        "the row schema in references/telemetry.md — or add the measurement "
        "before the experiment that needs it")
elif instrument_only:
    # Proposal 2 (#117), as a NAMED OUTCOME rather than as asymmetric scoring.
    # A field null on every control-arm row is a field the control version did
    # not record, so the proposal added its own instrument — and a gate that can
    # only score fields both arms share can never credit that.
    #
    # The alternative was to score across the asymmetry: control surfaces
    # re-measured with the new instrument against treatment surfaces produced
    # with it. Refused. It is an n=1 shape (`observo` re-run at v1.3 over its own
    # v1.2 surface), the two sides measure different things — detection on an
    # unswept surface against resolution during a run — and the script has no way
    # to check the comparison is being made honestly. Naming the outcome is
    # cheap, true, and not reachable for cases it does not fit.
    #
    # Below the safety branches on purpose: content lost under the proposed
    # version is lost whether or not the metric could see anything.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(
        f"the registered primary metric `{metric}` is null on every "
        f"control-arm row (wave {control}) — this proposal added its own "
        "instrument and cannot be judged by it")
    reasons.append(
        "a proposal aimed at a defect class the row cannot see yet should add "
        "its measurement first, as v1.3 did with `seams` — and doing so buys "
        "measurability for LATER rounds, not for its own experiment. Register "
        f"`{metric}` for the next proposal, once both arms record it")
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
    f"inverted: the arm carrying the proposal is the treatment, so re-run with "
    f"--treatment {control} --control {treatment}. As scored here, a winning "
    f"change reads as a losing one."
) if inversion_is_the_verdict else None

if fmt == "json":
    print(json.dumps({
        "treatment_wave": treatment, "control_wave": control,
        "treatment_versions": t_versions, "control_versions": c_versions,
        "repos": records, "pairs": pairs,
        "informative_pairs": len(informative), "treatment_wins": len(wins),
        # Null when no registration was named — the default is closure with
        # higher-is-better, and `primary_metric` says so either way rather than
        # leaving a reader to infer it from the absence of a file.
        "experiment": experiment,
        "primary_metric": metric, "metric_direction": direction,
        "saturated_pairs": len(saturated),
        "added_its_own_instrument": instrument_only,
        "metric_unreadable": unreadable_metric,
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


def metric_cell(r):
    """The scored column, whichever metric is registered."""
    if metric == "closure":
        return pct(r["closure"])
    v = r["metric_raw"]
    return "-" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


w = max([len(r["repo"]) for r in records] + [4])
print(f"treatment wave {treatment}: {', '.join(t_versions) or 'no attributed runs'}")
print(f"control   wave {control}: {', '.join(c_versions) or 'no attributed runs'}")
# Named before the table rather than after it. Which metric produced these
# numbers is the first thing a reader needs, and a registration cited by path is
# a registration whose history they can go and check.
if experiment:
    print(f"registration:    {experiment['file']} — primary metric "
          f"`{metric}`, {direction} is better, min-pairs "
          f"{experiment['min_pairs']}")
else:
    print(f"metric:          `{metric}` ({direction} is better), the default "
          "pre-registered in\n"
          "                 references/validation-gate.md. No --experiment "
          "was named.")
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
      f"{'budget':>7} {metric[:8]:>8}  no_loss")
print("-" * (w + 48))
for p in pairs:
    for tag, r in (("T", p["treatment"]), ("C", p["control"])):
        if r is None:
            print(f"{p['pair']:>4}  {tag:<3} (missing)")
            continue
        print(f"{p['pair']:>4}  {tag:<3} {r['repo']:<{w}} {num(r['before']):>8} "
              f"{num(r['after']):>8} {num(r['budget']):>7} {metric_cell(r):>8}"
              f"  {no_loss_cell(r)}")
    if p["informative"]:
        # Percentage points for closure, which is a fraction; the raw signed
        # difference for a ledger field, where "pp" would be a unit it does not
        # have.
        m = (f"{p['margin'] * 100:+.1f}pp" if metric == "closure"
             else f"{p['margin']:+g}")
        print(f"{'':>4}  -> {p['winner']} ({m})")
    else:
        print(f"{'':>4}  -> uninformative: {p['why']}")
print()

# Proposal 3 (#117): saturation counted rather than left to be inferred from a
# column of 100.0% cells.
if saturated:
    print(f"saturated pairs: {len(saturated)} of {len(pairs)} — both arms "
          "closed the gap completely, so")
    print("                 closure had no room left to express a difference.")
    if len(saturated) * 2 > len(pairs):
        print()
        print("FINDING most pairs saturated. The budget is no longer the "
              "binding constraint")
        print("        for most of the cohort, which is a finding about the "
              "budget rather than")
        print("        a tie between the arms.")
        print("        It is NOT a reason to tighten the budget now. A budget "
              "changed after")
        print("        seeing where the cohort landed is a retroactive "
              "parameter — the same")
        print("        integrity failure as choosing the metric late, and "
              "references/rejected-changes.md")
        print("        already carries that precedent. If the budget moves it "
              "moves as a")
        print("        pre-registered parameter of a FUTURE experiment, never "
              "applied backwards")
        print("        to score a past one. The durable answer to saturation "
              "is a metric that")
        print("        measures the axis the proposal changed (#118), not a "
              "rescued closure.")
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
