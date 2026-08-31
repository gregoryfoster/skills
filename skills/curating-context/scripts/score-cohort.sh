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
  score-cohort.sh [--cohort-file PATH] --treatment VERSION --control VERSION

Options:
  --cohort-file PATH  Roster carrying `pair:` annotations (and `wave:`, which
                      is rollout order and scores nothing).
                      Default: .skills/cohort
  --treatment VERSION The PROPOSED version. Required.
  --control VERSION   The CURRENT version. Required.

                      These name VERSIONS, not waves (#194). The arm a repo is
                      in is the skill_version stamped on its own scored row —
                      observed, never assigned (#118/#168) — so a repo whose
                      scored run carries neither of these two versions is in
                      NO arm, and is reported rather than scored as though it
                      carried the version its roster line implies. wave:/pair:
                      are rollout order: which half a change reached first, and
                      which two repos were size-matched. pair: still comes from
                      the roster, because size-matching is a property of the
                      repos rather than of any run.

                      There is no default, deliberately. Naming the comparison
                      is what makes it one, and inferring the two versions from
                      the ledgers would be choosing the experiment after seeing
                      the rows. --experiment NN supplies them from the
                      registration's treatment_version/control_version, which
                      is where they were pre-registered; a flag may still name
                      them, and disagreeing with the registration is refused.

                      Note the direction. Naming the OLDER version as the
                      treatment turns a winning change into a losing one, so it
                      is detected from the flags and returns INCONCLUSIVE
                      rather than a rejection.
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

                      It may also name the metric's `bound` — the value the
                      metric cannot move past at its GOOD end, a ceiling under
                      `direction: higher` and a floor under `lower`. A pair
                      tied THERE is reported uninformative — saturated, the
                      treatment having had no way to win it. Optional, because
                      a tie on an unbounded metric is real evidence of no
                      effect and stays a loss.
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

  claims_dropped / claims_warranted get the same treatment for the same reason
  (#253): surfaced, never gated. They ride the same column as `/c`, `/c2w`,
  `/c3d` — the marker says the run ran prove-no-loss.sh --claims at all, which
  is the whole distinction a `tighten` needs and which no_loss_warrants cannot
  make (it aggregates all six warrant kinds). A dropped-but-judged atom is a
  judgement, not a safety violation; an unwarranted one already fails the run
  through no_loss, which IS a gate.

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
  1  usage error, the roster carries no pair assignment, or the two versions
     named are one release
  2  infrastructure failure (python3 or gh missing, library missing)
  3  REJECT — a recorded safety gate tripped, or the treatment did not sweep
     over at least the rejection floor of informative pairs
  5  INCONCLUSIVE — nothing was decided: too few informative pairs, a failed
     sweep below the rejection floor, safety unverified, every repo in both arms
     unscorable for one reason, an arm with no attributed run, the versions are
     named in the wrong order, they are not the ones the registration named, the
     registered metric is on no row at all, or it is null across the whole
     control arm (the proposal added its own instrument)

  An arm can no longer be "split across versions" and both arms can no longer
  be "on one version": since #194 the arm IS the version, so both states are
  ruled out by construction rather than diagnosed after the fact. A repo whose
  row carries some third version falls out of both arms and is reported there.

Every question of the form "is this even an experiment?" is answered BEFORE any
verdict that would reject, because a REJECT tells the reader to write the change
into rejected-changes.md — a permanent record. Naming a change as refuted when
the comparison was mislabelled, or when no proposal existed, is the worst single
output this script can produce. Treatment-arm safety failures are printed
whatever the verdict, so the reordering masks nothing.
USAGE
}

COHORT_FILE=".skills/cohort"
# No defaults. `a`/`b` were wave names, and there is no version that plays the
# same role: the two versions being compared are the experiment, so a default
# would be this script choosing one. Filled from the registration when
# --experiment names one, otherwise required (#194).
TREATMENT=""
CONTROL=""
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
    --treatment) TREATMENT="${2:?--treatment needs a version}"; shift 2 ;;
    --control) CONTROL="${2:?--control needs a version}"; shift 2 ;;
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
# The literal half of the same-release check, here so the obvious typo costs
# nothing. Spellings of ONE release — 1.2 against v1.2.0 — are caught in the
# scorer, which is where version_canon() lives; a second copy of it in bash
# would be a second opinion about what one release is.
if [ -n "$TREATMENT" ] && [ "$TREATMENT" = "$CONTROL" ]; then
  echo "ERROR --treatment and --control name the same version ('$TREATMENT')" >&2
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
      "$_libdir/../references/rejected-changes.md" "$TMP/reg-arms" \
      >"$TMP/experiment.json" <<'PY' || exit 1
import json
import re
import sys
from pathlib import Path

directory, number, rejected_path, arms_path = sys.argv[1:5]


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
OPTIONAL = ("bound", "notes")

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

# The bound, and it is OPTIONAL on purpose (#195). A metric that names one gets
# the saturated-not-tied treatment; one that does not keeps today's behaviour,
# where a tie is a loss. There is deliberately no blanket "ties are
# uninformative" rule: for an UNBOUNDED metric a tie is real evidence of no
# effect, and discarding it would make the adoption rule easier to satisfy by
# deleting the pairs that disagree — which is the failure rejected-changes.md
# exists to record.
#
# ONE number, not a pair, and `direction` already says which end it is: a
# ceiling under `higher`, a floor under `lower`. The bound at the metric's BAD
# end is never needed, because a pair tied at the worst attainable value is a
# pair the treatment COULD have won and did not. That is a real loss and stays
# one. Only the good end can make winning impossible, and impossibility is the
# whole content of the carve-out.
if "bound" in fields:
    try:
        b = float(fields["bound"])
    except ValueError:
        b = float("nan")
    # Rejects nan directly and inf via the second test, so `bound: inf` cannot
    # register a bound nothing can reach as though it were a real one.
    if b != b or b in (float("inf"), float("-inf")):
        die(f"ERROR {path.name}: `bound: {fields['bound']}` — must be a finite "
            "number.",
            "      It is the value the metric cannot move past at its GOOD end: "
            "a ceiling when",
            "      `direction: higher`, a floor when `direction: lower`. Two "
            "arms tied there are",
            "      both at the best attainable score, not merely equal.")
    # Both the number and the TEXT. Every rule reads the float; the one message
    # that sends an operator to edit this file quotes the text, because `:g`
    # renders a registered `bound: 1.0` as `1` and a grep for that value fails
    # on the very path where they are already unsure which number is wrong.
    fields["bound_text"] = fields["bound"]
    fields["bound"] = b

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

# The two versions the arms are made of, written out for the shell so that
# --experiment alone is a complete invocation. This file is where the
# registration and the flags meet: the registration NAMES the comparison, and
# before #194 the flags named waves, so the two could not be checked against
# each other at all. A flag still wins — and disagreeing with the registration
# is caught downstream, which is the check worth having.
Path(arms_path).write_text(
    f"{fields['treatment_version']}\n{fields['control_version']}\n",
    encoding="utf-8")
print(json.dumps(fields, sort_keys=True))
PY
fi

if [ -f "$TMP/reg-arms" ]; then
  { IFS= read -r REG_TREATMENT || true
    IFS= read -r REG_CONTROL || true
  } <"$TMP/reg-arms"
  [ -n "$TREATMENT" ] || TREATMENT="$REG_TREATMENT"
  [ -n "$CONTROL" ] || CONTROL="$REG_CONTROL"
fi

if [ -z "$TREATMENT" ] || [ -z "$CONTROL" ]; then
  cat >&2 <<'EOF'
ERROR --treatment and --control name the two VERSIONS being compared, and both
      are required. They stopped naming waves in #194: the arm a repo is in is
      the skill_version on its own scored row, so the flags name the versions
      that define the arms.

      There is no default. Inferring the two versions from the ledgers would
      choose the experiment after seeing the rows, which is the same move as
      choosing the metric late.

        score-cohort.sh --treatment 1.3 --control 1.2

      Or cite the pre-registration, which already records both:

        score-cohort.sh --experiment NN
EOF
  exit 1
fi

# One definition of what a version IS, written out for both passes below to
# import. The literal `--treatment X --control X` check lives in the shell,
# where it costs nothing; this is the SPELLINGS half — 1.2 against v1.2.0 — and
# it used to sit in the scorer, which runs after twelve gh round-trips. Same
# objection the registration parser above answers: a usage error that takes a
# minute to arrive trains the caller to skip the check. Hoisting it needed
# version_canon here, and a bash reimplementation would be a second opinion
# about what one release is — so the function moves to a file both import
# instead of being copied.
cat >"$TMP/versionlib.py" <<'PY'
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
    decide whether the versions were named in the wrong order, never who wins: a
    non-numeric component reads as 0, which is fine for refusing to score and
    not fine for scoring.

    Derived from the canonical form so the two cannot disagree. They did: v1.2
    keyed to (0, 2) against 1.2's (1, 2), and the gate reported the arms as
    inverted for one release spelled two ways — a confidently wrong diagnosis
    pointing at the flags, which were not the problem. Deriving it also settles
    1.2.0 vs 1.2, which keyed unequal and could trip the same test.
    """
    return tuple(int(p) if p.isdigit() else 0
                 for p in version_canon(v).split("."))
PY

python3 - "$TMP" "$TREATMENT" "$CONTROL" <<'PY' || exit 1
import sys

tmp, treatment, control = sys.argv[1:4]
sys.path.insert(0, tmp)
from versionlib import version_canon        # noqa: E402

canon = version_canon(treatment)
if canon != version_canon(control):
    sys.exit(0)
# A usage error rather than a verdict, and that is the change #194 made: before
# it, the arms were the roster's and the versions were whatever turned up, so
# "both arms ran the same version" was an observation about the rows. Now the
# versions ARE the arms, and no ledger can make one release into an experiment.
print(f"ERROR --treatment {treatment} and --control {control} canonicalise to "
      f"the same release ({canon}).", file=sys.stderr)
print("      1.2, v1.2 and 1.2.0 are one version. A release compared against "
      "itself is a", file=sys.stderr)
print("      baseline, not an experiment — name the two versions the proposal "
      "sits between.", file=sys.stderr)
sys.exit(1)
PY

[ -f "$COHORT_FILE" ] || {
  echo "ERROR no cohort file at $COHORT_FILE" >&2; exit 1; }

ctx_read_roster "$COHORT_FILE" >"$TMP/roster"

# An unannotated roster cannot answer the question this script asks. Say what is
# missing and what it looks like, rather than reporting an empty comparison as
# though the experiment had run and found nothing.
#
# `pair:` is what is checked, not `wave:` (#194). The arms come off each row's
# skill_version now, so a roster carrying every wave and no pair describes no
# comparison at all, while one carrying every pair and no wave describes a
# perfectly good one. Field 4, not field 3.
#
# The flag, rather than `$4 != "" { exit 0 }`: awk's `exit` runs the END block on
# its way out, so an END that exits too has the last word and the early exit is
# discarded. Written the obvious way this reported every annotated roster as
# unannotated.
if ! awk -F"$CTX_US" '$4 != "" { found = 1; exit } END { exit !found }' "$TMP/roster"; then
  cat >&2 <<EOF
ERROR $COHORT_FILE carries no pair: assignment, so there is nothing to compare.
      Annotate each entry, e.g.:

        CannObserv/usa-wa                      wave:a pair:1
        CannObserv/cannabis.observer-wordpress wave:b pair:1

      Pairs are matched on starting state and stay roster-driven: size-matching
      is a property of the repos, not of any run. wave: is rollout order and is
      optional — the arm a repo is in is the skill_version on its own scored
      row. See references/validation-gate.md.
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
  # EVERY entry is fetched (#194). Which arm a repo is in is the skill_version
  # on its own scored row, and that is not knowable until the ledger is read —
  # so this layer can no longer divert anything, and the shell no longer decides
  # arm membership at all. What falls out of both arms is decided in the scorer
  # and reported there.
  #
  # Two things this fixes beyond the arms. The `arms_are_historical` notice
  # claims to be roster-wide precisely so that a member outside the experiment
  # still evidences that the cohort has moved on — and it was arm-wide in fact,
  # because the entries it wanted to see were the ones diverted before their
  # ledger was ever read. And an entry with a typo'd or missing wave: is no
  # longer excluded from an experiment its rows may well belong to.
  #
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
import os
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

# One accessor for both metric shapes, so every rule below — the bound check,
# saturation, ties, the winner, the margin — is written once and cannot drift
# between them.
METRIC_KEY = "closure" if metric == "closure" else "metric_raw"

# The registered bound, if the registration named one (#195). Kept apart from
# `bound` below because only a REGISTERED bound is a claim anyone made, and only
# a claim can be wrong: the check that refuses a false bound cites this file.
reg_bound = experiment.get("bound") if experiment else None

# Closure's cap IS a bound and always was — hardcoded at 1.0 in the pair loop
# until #195. Read as the default here so there is ONE saturation rule rather
# than a general one beside a closure-shaped special case that can drift from
# it. A registration naming closure with some other bound does not override the
# arithmetic; it gets caught by the wrong-side check below, since closure cannot
# exceed 1.0.
bound = reg_bound
if metric == "closure" and bound is None:
    bound = 1.0


def at_bound(v):
    """Is this value at the metric's good end — the point it cannot move past?

    `>=`/`<=` rather than `==` so closure's cap keeps exactly the comparison it
    had before #195, and so float noise at the cap lands on the same side as the
    arithmetic that produced it. For a REGISTERED bound the two are the same
    test anyway: an ARM member strictly past the bound is refused below, and
    only arm members reach the pairing, so nothing that reaches here can be
    beyond it. An out-of-arm row may be — it draws a note rather than a
    refusal — and it is never passed to this function.
    """
    if bound is None:
        return False
    return v >= bound if direction == "higher" else v <= bound


if experiment:
    # A flag may TIGHTEN the registered floor and may not loosen it. Loosening
    # once the pair count is known is the same move as choosing the metric after
    # seeing the rows, and it is the move --min-pairs 2 nearly made in
    # experiment 1.
    min_pairs = (max(min_pairs, experiment["min_pairs"]) if min_pairs_set
                 else experiment["min_pairs"])


# The two arms, as the two versions that define them (#194). Canonical, so one
# release spelled two ways is one arm.
#
# version_canon/version_key are IMPORTED, not defined here. They used to live in
# this heredoc, which put the "is this one release spelled twice?" refusal after
# twelve gh round-trips; hoisting it above the fetch needed the same function in
# two places, and one definition in a file both import beats two copies that can
# drift. That refusal has already fired above, so T_CANON != C_CANON here.
sys.path.insert(0, os.path.dirname(src))
from versionlib import version_canon, version_key    # noqa: E402

T_CANON = version_canon(treatment)
C_CANON = version_canon(control)


def arm_of(rec):
    """Which arm a scored repo is in: the canonical `skill_version` on its OWN
    row, matched against the two versions named on the command line.

    None is a real answer and the point of #194 — a repo whose scored run
    carries neither version belongs to NO arm, rather than to the arm its
    roster line names. Before this the roster decided, so the third state could
    not be expressed: a repo six releases adrift was scored as though it
    carried the version its `wave:` implied, and could veto a proposal it never
    ran.

    Reads the RECORD, not the ledger row, so there is one answer per repo and it
    is the version of the run that was actually scored. A repo with no
    attributed run has no version and therefore no arm.
    """
    v = rec["skill_version"]
    if not v:
        return None
    canon = version_canon(v)
    if canon == T_CANON:
        return "treatment"
    if canon == C_CANON:
        return "control"
    return None


def why_no_arm(rec):
    """Why a record is in neither arm, in the words that help.

    The version when there is one — the repo ran something and which something
    is the whole answer. Otherwise the repo's own unscorable reason, which names
    the file and the fix; "no attributed run" alone reads as a repo nobody has
    curated when the ledger may simply be missing.
    """
    return (rec["skill_version"] or rec["why"] or "no attributed run")


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
        "claims_dropped": None, "claims_warranted": None,
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
            # The version is recorded even though the run is unscorable: this
            # row HAS a skill_version — that is how the scan reached it — so the
            # repo is in an arm, and since #194 the arm is read off exactly this
            # field. Left null, an untagged run would fall out of both arms and
            # the systematic-untagging defect could never be detected, which is
            # the one diagnosis that tells the reader to re-run Phase 7.
            rec["skill_version"] = r.get("skill_version")
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
    # Carried, not scored (#253). A consumer of this record's JSON can ask
    # whether a class-C tightening was verified; the gate never asks.
    rec["claims_dropped"] = scored.get("claims_dropped")
    rec["claims_warranted"] = scored.get("claims_warranted")
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

# Stamped once, so every rule below reads one answer rather than re-deriving it,
# and so the JSON says which arm each repo landed in. `wave` stays on the record
# beside it: rollout order is still true, it is simply not what an arm is.
for r in records:
    r["arm"] = arm_of(r)


def past_bound(r):
    """Does this record carry the metric strictly beyond the declared bound?"""
    v = r[METRIC_KEY]
    if not isinstance(v, (int, float)):
        return False
    return v > reg_bound if direction == "higher" else v < reg_bound


# A registered bound is a CLAIM about the metric's range, and a false one is not
# inert. It moves the saturation point, and every tie it swallows leaves the
# informative set — making the adoption rule easier to satisfy by deleting the
# pairs that disagree, which is exactly what #195 refused to do wholesale and
# must not do by accident here. So the claim is checked against what the rows
# actually carry: a value strictly PAST the declared bound proves the metric is
# not bounded there.
#
# Scoped to the ARMS, which is why this sits below arm_of() rather than beside
# the records that feed it. A repo running neither version is running neither
# version OF THE METRIC — six releases back a share may be computed from a
# different denominator — so its value is not evidence about what the two named
# versions can produce, and letting it refuse the run is the shape #194 removed
# from the safety gates: a repo adrift vetoing a proposal it never ran. Both
# remedies the error offers ("fix the registration or drop the key") are wrong
# when the bound is right for the arms and the stray repo is simply old.
#
# Out of arm it is still SAID, as a note, because a bound is a claim about the
# metric and a value past it anywhere is worth a look before the next round.
# Reported, not fatal: the distinction is between evidence that the registration
# is wrong and evidence that the cohort has moved on.
#
# Refused rather than warned in the arms. The same argument the schema makes
# about an unknown key applies with more force to a false one: a bound nobody
# honoured still reads, in the report and in the JSON, as a bound that was.
bound_notes = []
if reg_bound is not None:
    reg_bound_text = experiment["bound_text"]
    beyond = [(r["repo"], r[METRIC_KEY]) for r in records
              if r["arm"] and past_bound(r)]
    if beyond:
        print(f"ERROR {experiment['file']}: `bound: {reg_bound_text}` is not a "
              f"bound — `{metric}` is recorded past it:", file=sys.stderr)
        for repo, v in beyond:
            print(f"        {repo}: {v:g}", file=sys.stderr)
        print("      A bound is the value the metric cannot move past at its "
              "good end, and it\n"
              "      decides which ties stop counting as losses. Declared in "
              "the wrong place it\n"
              "      removes pairs the treatment did not win, which is how a "
              "sweep gets easier to\n"
              "      satisfy the more of the cohort saturates. Fix the "
              "registration or drop the key.",
              file=sys.stderr)
        sys.exit(1)
    adrift = [(r["repo"], r[METRIC_KEY]) for r in records
              if not r["arm"] and past_bound(r)]
    if adrift:
        bound_notes.append(
            f"note: `{metric}` is recorded past the registered bound "
            f"{reg_bound_text} OUTSIDE the arms: "
            + ", ".join(f"{repo} ({v:g})" for repo, v in adrift)
            + ".\n      Not a refusal — those repos ran neither version, so "
              "neither did the metric.\n      Worth a look before the next "
              "round: if the bound is wrong there it is wrong here.")

# The pairing needs BOTH groupings and they answer different questions. `pair:`
# stays roster-driven — it encodes size-matching against the 2026-08-05 baseline,
# which is a property of the repos and not of any run — while which side of the
# pair a repo sits on is the version on its own row.
by_arm = {"treatment": {}, "control": {}}
by_pair = {}
for r in records:
    if not r["pair"]:
        continue
    by_pair.setdefault(r["pair"], []).append(r)
    if r["arm"]:
        by_arm[r["arm"]].setdefault(r["pair"], []).append(r)

pairs = []
# Iterated over every pair the ROSTER declares, not over the pairs that happened
# to land members in an arm. A pair whose members both fell out of the arms would
# otherwise vanish from the report entirely — the sample shrinking silently,
# which is the failure out-of-arm reporting exists to prevent, reached through
# the new rule instead of through a typo.
for pid in sorted(by_pair, key=lambda p: (len(p), p)):
    t = by_arm["treatment"].get(pid, [])
    c = by_arm["control"].get(pid, [])
    entry = {"pair": pid, "treatment": t[0] if len(t) == 1 else None,
             "control": c[0] if len(c) == 1 else None,
             "informative": False, "winner": None, "margin": None,
             "saturated": False, "why": None}
    if len(t) != 1 or len(c) != 1:
        entry["why"] = (f"pair {pid} has {len(t)} treatment and {len(c)} control "
                        "repos; a pair needs exactly one of each")
        # Named here because the roster looks correct in this case and the
        # reason is on the other repo's row. "0 treatment and 1 control" sent
        # the reader to the roster, which is where the answer used to be.
        adrift = [r for r in by_pair[pid] if r["arm"] is None]
        if adrift:
            entry["why"] += "; " + ", ".join(
                f"{r['repo']} is in neither arm — {why_no_arm(r)}"
                for r in adrift)
        pairs.append(entry)
        continue
    tr, cr = t[0], c[0]
    tv, cv = tr[METRIC_KEY], cr[METRIC_KEY]
    if tr["status"] != "scored" or cr["status"] != "scored":
        bad = tr if tr["status"] != "scored" else cr
        entry["why"] = f"{bad['repo']}: {bad['status']} — {bad['why']}"
    elif tv is None or cv is None:
        side = tr if tv is None else cr
        entry["why"] = (f"{side['repo']} had no budget gap to close"
                        if metric == "closure"
                        else f"{side['repo']}: {side['why']}")
    elif tv == cv and at_bound(tv):
        entry["saturated"] = True
        # A TIE AT THE BOUND, which is the one tie that is not evidence about
        # the arms. Closure is capped at 1.0 — a run that cuts far past the
        # budget scores the same as one that lands on it, deliberately, so
        # over-cutting earns nothing — and when both arms reach budget the
        # metric has no room left to express a difference. Generalised in #195
        # to any metric whose registration NAMES its bound, because the
        # argument was never about closure: at the good end the control is
        # already perfect, so no treatment result could have won that pair, and
        # requiring one makes the sweep rule unsatisfiable. "The metric cannot
        # separate them" is a different claim from "they are equal".
        #
        # Scoped to TIES, and both halves of that matter. A tie away from the
        # bound is a real tie and stays a loss. A pair where one arm sits at the
        # bound and the other does not is a real WIN or LOSS — the metric
        # separated them perfectly well — so it never reaches here. And a tie at
        # the metric's BAD end is a pair the treatment could have won and did
        # not, which is why `bound` names one end rather than two.
        entry["why"] = ("both arms closed the gap completely — closure saturates "
                        "and cannot separate them"
                        if metric == "closure" else
                        f"both arms scored {bound:g}, the registered bound for "
                        f"`{metric}` — the metric saturates and cannot separate "
                        "them")
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

# The repos actually in an arm. Not every record is one any more (#194): a repo
# whose scored run carries neither version is in neither arm, and a repo with no
# attributed run has no version to place it by.
#
# That second case narrows this check, deliberately. "Every repo in both arms is
# unscorable for one reason" can now only be inferred from repos that got far
# enough to record a version: no_before_state, untagged_run, method_changed and
# missing_counts. SYSTEMIC_HINTS covers the first three — #116's case included —
# and NOT missing_counts, which is a gap rather than a boundary: a cohort
# systematically missing token counts would be diagnosed with no hint attached.
# `.get` degrades to no hint rather than raising, so add one when it is earned.
# A cohort where nobody has curated at all no longer reaches here and does not
# need to: the empty-arm branches below say so in plainer words than a GATE
# DEFECT would.
arm_records = [r for r in records if r["arm"]]
no_arm = [r for r in records if r["arm"] is None]
# "No repo in either arm can satisfy this rule" is an inference from BREADTH, and
# at two repos it is not supported — the likelier reading is two non-compliant
# repos, which is a finding about the cohort and needs a different fix.
#
# Counted PER ARM, not over the roster. A roster total let 3 treatment repos and
# 1 control repo clear a floor of 4 and print the defect, which is the same thin
# evidence the floor exists to refuse — one arm carrying a single repo says
# nothing about whether the rule is satisfiable.
SYSTEMIC_MIN_PER_ARM = 2
t_arm_n = sum(1 for r in records if r["arm"] == "treatment")
c_arm_n = sum(1 for r in records if r["arm"] == "control")
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


def arm(which, status):
    """Every repo in the arm, INCLUDING ones in no pair — deliberately wider
    than the pairing.

    Safety is not a property of a comparison. Content lost under the proposed
    version is lost whether or not that repo had a partner, so an unpaired repo
    can veto adoption on its own while contributing nothing to any closure. It
    stays visible: it is listed under "not in any pair" and again in the
    treatment-arm failures block. Do not narrow this to paired repos.

    Wider than the pairing, and no wider (#194). A repo that ran neither version
    is in neither arm, so it cannot veto a proposal it never ran — which is what
    grouping by the roster made it do.
    """
    return [r for r in records if r["arm"] == which and r["status"] == status]


t_failures = arm("treatment", "failed")
t_unverified = arm("treatment", "unverified")
c_failures = arm("control", "failed")
c_unverified = arm("control", "unverified")


def versions_in(which):
    """How each arm's version is actually SPELLED on the rows, and by whom.

    The arm is one canonical version now, so this can no longer report two
    releases in one arm. What it can still report is 1.2 and v1.2.0 sitting in
    the same arm under two spellings, which is worth saying out loud, and which
    repo is where.
    """
    m = {}
    for r in records:
        if r["arm"] == which and r["skill_version"]:
            m.setdefault(r["skill_version"], []).append(r["repo"])
    return m


t_by_version, c_by_version = versions_in("treatment"), versions_in("control")
t_versions, c_versions = sorted(t_by_version), sorted(c_by_version)


# The scored run is each repo's FIRST attributed curation, and that never moves.
# Six releases on, this table still reports experiment 1's arms — 1.3 against
# 1.2 — off rows written in August, with nothing saying those versions are
# spent. That is the failure #168 raises against the roster's wave:/pair:
# annotations, a reader taking an annotation as describing reality, sitting in
# the script instead. wave:/pair: are rollout order now, not a version
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
# outside the two versions still evidences that the cohort has moved on, and
# narrowing this to the arms would let such a member run six versions ahead with
# the table claiming to be current. Roster-wide in FACT only since #194 — the
# shell used to divert an out-of-arm entry before its ledger was ever fetched,
# so the rows this wants to see were the ones it could not see.
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


# Name the OLDER version as the treatment and a winning change reads as a losing
# one. In experiment 1 wave A adopted first and held the older version, which is
# how the bare invocation used to invert the comparison; there is no bare
# invocation now, but a caller can still type the two versions in the wrong
# order.
#
# Read straight off the flags since #194. It used to be inferred from the rows —
# the only place the direction could be found while the flags named waves — and
# the two agree, because the arms now carry exactly the versions the flags name.
#
# Asked only when both versions HAVE a numeric leading component. version_key is
# lossy by design — every non-numeric component reads as 0 — so a release named
# vNext keys to (0,) and compares older than every numbered release. That is a
# false inversion whose message points at the flags, which are not the problem —
# the same shape version_key's own docstring records being fixed for v1.2 vs
# 1.2, arriving from the other side. No numeric lead means no opinion about
# order; the ordering exists to refuse, and it cannot refuse on a comparison it
# cannot make.
def has_numeric_lead(v):
    return version_canon(v).split(".")[0].isdigit()


comparable = has_numeric_lead(treatment) and has_numeric_lead(control)
inverted = comparable and version_key(treatment) < version_key(control)

# `--treatment b --control a` is what every doc and six months of history told a
# reader to type, and until #194 it was correct. It now names two versions that
# no row carries, so the arms come out empty and the run reports INCONCLUSIVE —
# which reads as "the experiment ran and found nothing" rather than as a
# mistyped invocation. The roster is what disambiguates: if the value is a wave
# name in this very cohort file, say so.
roster_waves = {r["wave"] for r in records if r["wave"]}
mistaken_waves = sorted({v for v in (treatment, control) if v in roster_waves})
wave_name_hint = [
    f"`{'` and `'.join(mistaken_waves)}` "
    f"{'name waves' if len(mistaken_waves) > 1 else 'names a wave'} in this "
    "roster, not versions. Since #194 --treatment/--control name the two "
    "VERSIONS being compared — the arm a repo is in is the skill_version on "
    "its own scored row. Re-run naming versions, or cite the registration "
    "with --experiment NN"
] if mistaken_waves else []


def attributed(which):
    """Records with a scored run — the only rows that could carry the metric.

    A repo with no attributed curation has not failed to record the field; it
    has not been curated. Counting it as a null would let one un-run repo
    declare the whole arm blind.

    Arm membership already implies a scored version, so the `skill_version`
    test that used to sit beside the wave test is now redundant rather than
    dropped: arm_of() returns None without one.
    """
    return [r for r in records if r["arm"] == which]


# Null across the WHOLE control arm, and present somewhere in the treatment arm.
# Both halves are load-bearing: null on both sides is not a proposal that added an
# instrument, it is a metric this gate cannot read at all — the branch below.
instrument_only = bool(
    experiment and metric != "closure"
    and attributed("control")
    and all(r["metric_raw"] is None for r in attributed("control"))
    and any(r["metric_raw"] is not None for r in attributed("treatment")))

# Recorded on NO scored row anywhere. The registered metric is not a field the
# ledger carries — a derived rate (`truthfulness` is a share of scheduled rows,
# and this gate skips every scheduled row), a typo, or a measurement nobody has
# added yet. Without this branch all three land on "no informative pairs —
# nothing was measured", which is true, sends the reader to look at pair scoring,
# and never mentions that the metric was unreadable. That is the silent success
# this gate exists to stop producing.
unreadable_metric = bool(
    experiment and metric != "closure" and not instrument_only
    and (attributed("treatment") or attributed("control"))
    and all(r["metric_raw"] is None
            for r in attributed("treatment") + attributed("control")))

# Order matters, and it is the opposite of the obvious one. Every question of
# the form "is this even an experiment?" is asked BEFORE any verdict that would
# reject, because a REJECT tells the reader to write the change into
# rejected-changes.md — a permanent record that shapes future proposals. Naming
# a change as refuted when the comparison was mislabelled, or when there was no
# proposal at all, is the worst single output this script can produce. Treatment
# safety failures are still printed in the body whatever the verdict, so nothing
# is masked by the reordering.
#
# Two of these questions moved to the FRONT with #194, because they stopped
# being questions about the rows. While the flags named waves, "are these the
# arms the registration named?" and "are they the right way round?" could only
# be answered by looking at what turned up in the arms — so an empty arm hid
# both. Now they are answerable from the invocation alone, and asking them first
# means a run mislabelled AND short of data reports the mislabelling, which is
# the fault the reader can act on.
verdict, code, reasons = None, 0, []
inversion_is_the_verdict = False
if (experiment
        and (T_CANON != version_canon(experiment["treatment_version"])
             or C_CANON != version_canon(experiment["control_version"]))):
    # A registration for 1.4-over-1.3 scored against 1.3-over-1.2 is not a weak
    # verdict but a verdict about a different comparison — and the reason a
    # registration is worth having is that this is checkable at all. It compares
    # the FLAGS to the registration now; before #194 the flags were waves and
    # there was nothing on this side of it to compare.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(
        f"registration {experiment['experiment']} "
        f"({experiment['file']}) is for treatment "
        f"{experiment['treatment_version']} over control "
        f"{experiment['control_version']}, but this run was asked for "
        f"{treatment} over {control} — that is not the experiment that was "
        "registered, so nothing here bears on it")
elif inverted:
    # Detection alone was not enough: the WARN printed at the top and the verdict
    # then rejected the winning change and told the reader to file it as refuted,
    # twenty lines below the warning saying not to trust the result.
    inversion_is_the_verdict = True
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"the versions are named in the wrong order — the treatment "
                   f"{treatment} is OLDER than the control {control}. Re-run "
                   f"with --treatment {control} --control {treatment}; as "
                   "scored here a winning change reads as a losing one")
elif not t_versions:
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"no scored run carries the treatment version {treatment} "
                   "yet — nothing has been measured to compare")
    reasons.extend(wave_name_hint)
elif not c_versions:
    # The symmetric case, and the EXPECTED intermediate state during the first
    # experiment: half the cohort adopts the proposal before the other half has
    # re-run. Without this branch it fell through to "no informative pairs",
    # which is true and sends the reader to look at pair scoring instead of at
    # adoption progress.
    verdict, code = "INCONCLUSIVE", 5
    reasons.append(f"no scored run carries the control version {control} yet — "
                   "the treatment has nothing to be compared against. Expected "
                   "while the cohort is still catching up")
    reasons.extend(wave_name_hint)
# Two branches used to sit here and are gone with #194, because the states they
# diagnosed are now unreachable rather than undetected. "An arm is split across
# versions" cannot happen when the arm IS a version — a repo on some third
# version leaves the arm instead, and is reported under "not in either arm".
# "Both arms ran the same version" cannot happen either: the two versions come
# off the command line and canonicalising them equal is refused up front, as a
# usage error rather than as a verdict about the rows.
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
        f"control-arm row (version {control}) — this proposal added its own "
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

# Only when inversion is what actually stopped the run — an empty arm is
# diagnosed first, and printing both banners would walk the reader through two
# diagnoses for one problem.
inversion_warning = (
    f"WARN --treatment {treatment} is OLDER than --control {control}. The arm "
    f"carrying the proposal is the treatment, so re-run with --treatment "
    f"{control} --control {treatment}. As scored here, a winning change reads "
    f"as a losing one."
) if inversion_is_the_verdict else None

if fmt == "json":
    print(json.dumps({
        # The two versions that DEFINE the arms, as asked for. Distinct from the
        # plural keys below, which are how those versions were actually spelled
        # on the rows — one canonical release, possibly several spellings.
        "treatment_version": treatment, "control_version": control,
        "treatment_versions": t_versions, "control_versions": c_versions,
        "repos": records, "pairs": pairs,
        "informative_pairs": len(informative), "treatment_wins": len(wins),
        # Null when no registration was named — the default is closure with
        # higher-is-better, and `primary_metric` says so either way rather than
        # leaving a reader to infer it from the absence of a file.
        "experiment": experiment,
        "primary_metric": metric, "metric_direction": direction,
        # The bound actually in force, which is closure's cap when nothing was
        # registered and null for any other unregistered-bound metric. Null is
        # the answer that means "a tie here is a loss", so it is worth reading
        # off the payload rather than inferring from the registration.
        "metric_bound": bound,
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
        # Records now, not roster lines: what puts a repo here is the version on
        # its own scored row matching neither arm — or its having no scored run
        # at all — rather than a `wave:` value the flags did not name.
        "out_of_arm": [{"entry": r["entry"], "repo": r["repo"],
                        "wave": r["wave"] or None,
                        "skill_version": r["skill_version"]} for r in no_arm],
        # Repos outside the arms carrying the metric past the registered bound.
        # Inside the arms this state is fatal and there is no payload to read;
        # here it is reported, so a consumer sees what the text report prints
        # rather than having to re-derive it from `out_of_arm`.
        "bound_exceeded_out_of_arm": [
            {"repo": r["repo"], "skill_version": r["skill_version"],
             metric: r[METRIC_KEY]}
            for r in no_arm if reg_bound is not None and past_bound(r)],
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
    cell = f"{base}+{n}w" if isinstance(n, int) and n > 0 else base
    return cell + claims_suffix(r)


def claims_suffix(r):
    """`/c`, `/c2w`, `/c3d` — whether the claim check ran, and what it found.

    The bare `/c` carries most of the value (#253): `tighten` is refused
    without --claims, so its absence on a row tagged `prune:` is the one thing
    saying the tightening's own check was never run. Same isinstance shape as
    above, and for the same reason — every row predating the field is null, and
    a null must not render as a check that ran and found nothing.
    """
    d, w = r.get("claims_dropped"), r.get("claims_warranted")
    if not isinstance(d, int) and not isinstance(w, int):
        return ""
    parts = []
    if isinstance(w, int) and w > 0:
        parts.append(f"{w}w")
    if isinstance(d, int) and d > 0:
        parts.append(f"{d}d")
    return "/c" + "+".join(parts)


def metric_cell(r):
    """The scored column, whichever metric is registered."""
    if metric == "closure":
        return pct(r["closure"])
    v = r["metric_raw"]
    return "-" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def arm_header(label, version, by_version):
    """One arm: the version that defines it, and who is in it.

    The membership is what changed and so it is what the header shows. Printing
    the versions alone made sense while the arm was a wave and its version was
    the observation; now the version is the arm, and `treatment 1.3: 1.3` would
    say nothing at all. A spelling note rides along when a row records the same
    release differently, which the arm absorbs but a reader diffing two runs
    should still see.
    """
    if not by_version:
        return f"{label} {version}: no attributed runs"
    members = ", ".join(sorted(r for v in by_version for r in by_version[v]))
    spellings = sorted(by_version)
    note = "" if spellings == [version] else f" (recorded as {', '.join(spellings)})"
    return f"{label} {version}{note}: {members}"


w = max([len(r["repo"]) for r in records] + [4])
print(arm_header("treatment", treatment, t_by_version))
print(arm_header("control  ", control, c_by_version))
# Named before the table rather than after it. Which metric produced these
# numbers is the first thing a reader needs, and a registration cited by path is
# a registration whose history they can go and check.
if experiment:
    # The bound is printed whenever one was registered, saturated pairs or not.
    # A bound nothing reached is INERT — it changes no score — and printing it
    # is what makes that visible rather than leaving a reader to wonder whether
    # the declaration was honoured.
    at = f", saturates at {reg_bound:g}" if reg_bound is not None else ""
    print(f"registration:    {experiment['file']} — primary metric "
          f"`{metric}`, {direction} is better{at}, min-pairs "
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
          f"     the experiment that ran, not the cohort as it is now. The arm "
          f"is the version on\n"
          f"     each scored row; wave:/pair: are rollout order (#168/#194).")
if inversion_warning:
    print()
    print(inversion_warning)
# The out-of-arm half of the bound check. In the arms a value past the bound is
# fatal; outside them it is this, because those repos ran neither version of the
# skill and so neither version of the metric.
for _note in bound_notes:
    print()
    print(_note)
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
if saturated and metric != "closure":
    # The registered-bound half (#195). Kept as its own block rather than
    # squeezed into the closure wording below: "the budget is no longer the
    # binding constraint" is a claim about budgets, and printing it for a metric
    # that has nothing to do with the budget would be a finding about the wrong
    # parameter.
    print(f"saturated pairs: {len(saturated)} of {len(pairs)} — both arms "
          f"reached {bound:g}, the registered")
    print(f"                 bound for `{metric}`, so it had no room left to "
          "express a difference.")
    if len(saturated) * 2 > len(pairs):
        print()
        print(f"FINDING most pairs saturated. `{metric}` is at its bound for "
              "most of the cohort,")
        print("        which is a finding about the metric having run out of "
              "range rather than")
        print("        a tie between the arms.")
        print("        It is NOT a licence to move the bound now. A bound is a "
              "pre-registered")
        print("        property of the metric, and one edited to rescue a round "
              "is a retroactive")
        print("        parameter — the same integrity failure as choosing the "
              "metric late, which")
        print("        references/rejected-changes.md already carries a "
              "precedent for. The durable")
        print("        answer is a metric with room left on the axis the "
              "proposal changed (#118).")
    print()
elif saturated:
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
          + ", ".join(f"{r['repo']} ({r['arm'] or 'in neither arm'})"
                      for r in unassigned))
if no_arm:
    # Reported, never dropped. The roll-up refuses to skip a repo silently on the
    # principle that missing telemetry is itself the finding, and a gate that
    # quietly shrinks its own sample is worse. What lands here changed with #194
    # — a run on some third version rather than a typo'd wave: — and the reason
    # is printed per repo, because "neither arm" is now a fact about the ledger.
    print(f"not in either arm (skill_version is neither {treatment} nor "
          f"{control}): "
          + ", ".join(f"{r['repo']} ({why_no_arm(r)})" for r in no_arm))
if unassigned or no_arm:
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
