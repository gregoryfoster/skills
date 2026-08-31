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
  --baseline[=KIND]
                   Record a measurement-only row for the surface AS FOUND.
                   Tagged `baseline:KIND`, which every reader already knows to
                   skip past when looking for a curation.

                   KIND defaults to `pre-curation` — the state this run's edits
                   will be measured against. The scheduled cadence passes
                   `--baseline=scheduled`: a reading of a surface nobody
                   touched. The two mean different things to a longitudinal
                   comparison, and the distinction belongs on the tag rather
                   than in --note freetext.

                   This is what makes a FIRST curation scorable. The validation
                   gate takes a run's before-state from the previous row for the
                   same file, and a first curation is the run that creates the
                   ledger — so without a baseline row the scored run is exactly
                   the run that can never be scored, and the docs_orphaned gate
                   has nothing to compare against and silently cannot trip
                   (#116). Phase 1 records this row; Phase 7 records the
                   curation, and both ship in the same commit.

                   Refuses --actions (a baseline row is measurement-only, and
                   its tag is fixed) and --no-loss (nothing was relocated yet).
                   --note, --seams and --seams-acked are allowed: they measure
                   the surface as found, which is a before-state too.
  --actions LIST   Comma-separated action tags applied this run, e.g.
                   "demote:Project Layout,prune:Conventions,fix:dead-link".
                   Recorded verbatim so a later run can correlate a token
                   delta with what produced it.
  --note TEXT      Free-text note for this row (one line).
  --no-loss V      Record prove-no-loss.sh's verdict for this run: ok, failed,
                   or skipped. Omitted means "not run", recorded as null.
                   This is a SAFETY field, not a score: a validation gate reads
                   it to reject a skill change that reduced tokens by dropping
                   content, which no token count can distinguish from a good
                   run. A null is treated as unscorable, never as ok.
                   `skipped` records the decision explicitly and reads better in
                   a ledger, but the gate treats it exactly like a null: only
                   `ok` clears the check, and only `failed` is evidence that
                   anything actually went wrong.
  --no-loss-warrants N
                   Record how many of prove-no-loss.sh's unaccounted lines
                   carried a judged entry in .skills/context-loss-ok — its
                   `loss_warranted:` line. Requires --no-loss ok or failed: a
                   count with no verdict, or against `skipped`, would claim
                   lines were judged by a check that did not run. Omitted is
                   null, which is never the same as 0 — 0 says the run read the
                   report and warranted nothing, and null says it did not say.
                   Without this the ledger cannot tell a clean run from one
                   that waved eight lines through, and the cohort already holds
                   both recorded as `ok` (#111).
  --claims-dropped N
  --claims-warranted N
                   Record prove-no-loss.sh --claims' two trailer lines:
                   `claims_dropped:` (atoms present at base and nowhere now,
                   unwarranted) and `claims_warranted:` (dropped atoms carrying
                   a judged entry). Both require --no-loss ok or failed, for
                   the reason --no-loss-warrants does. Omitted is null, and
                   null is not 0: without them a run that passed --claims and
                   cleared it writes the same row as one that never ran the
                   check, so the ledger cannot tell a VERIFIED class-C
                   tightening from an unverified one (#253). `no_loss_warrants`
                   cannot answer it — it aggregates all six warrant kinds, so a
                   `tighten` is indistinguishable from a `retarget` in the
                   count.
                   A non-zero --claims-dropped requires --no-loss failed:
                   prove-no-loss.sh exits 3 on an unwarranted dropped atom, so
                   `ok` beside one is a verdict the run did not reach.
  --seams N        Record check-seams.sh's final count for this run: the number
                   of UNACKNOWLEDGED cross-reference seams after Phase 6.5's
                   hits were judged — the wrong ones fixed, the legitimate ones
                   added to .skills/context-seams-ok. Omitted means "not swept",
                   recorded as null — which, like no_loss, is never the same
                   as 0. Run the sweep last and record the number it prints.
  --seams-acked N  Record the sweep's acknowledged count — hits judged
                   legitimate and carried in .skills/context-seams-ok. Recorded
                   alongside --seams so a repo whose acknowledged set balloons
                   is visible in the roll-up: 0 new / 0 acked and 0 new /
                   50 acked are different states. Null when not swept.
  --repo NAME      Override the row's repo identity. Needed only when neither
                   the origin remote nor the checkout directory names the
                   repository the cohort roster knows this repo as.
  --repo-commit REV
                   BACKFILL MODE. Set `repo_commit` on the row this run already
                   recorded to REV, and do nothing else: no measurement is read
                   from stdin and no row is appended. The row it targets is the
                   NEWEST in the ledger — the one the append just wrote.

                   Phase 7 measures, records, and only then commits the ledger
                   alongside the edits — so the hash the append could see is the
                   PARENT of the tree the row describes. The field carries two
                   meanings, which state of this tree the row describes and
                   where the next scheduled seam sweep starts, and a commit that
                   does not exist yet can satisfy neither at append time (#206).
                   After the commit that ships the curation:

                       record-telemetry.sh --repo-commit HEAD

                   Then commit the ledger again — that second commit touches
                   only this line, so the row still describes the commit it
                   names.

                   A rewrite WITHIN a run is what references/telemetry.md
                   sanctions; a second row for an intermediate state nobody can
                   check out is what it forbids. So this rewrites in place and
                   never appends, is a no-op when the row already names REV, and
                   leaves any malformed line exactly where it found it.

                   Refuses a revision this repo does not have: `null` already
                   means "cannot name an interval", and a fabricated one would
                   send the next sweep to a tree nobody measured. Refuses a
                   `baseline` row, which records a state that has already passed
                   and cannot be changed by a later commit. Refuses the flags
                   that only make sense on an append, rather than discarding
                   them silently.
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
  repo              the roll-up's join key — from --repo, else the origin
                    remote's basename, else the checkout directory name
  file              policy file path
  tokens            policy-file tokens (exact when tokens_exact is true)
  tokens_exact      whether the count came from the count_tokens endpoint
  skill_version     declared version of the skill that produced this row — what a
                    cohort A/B groups by. Null for rows predating the field.
  skill_commit      short commit of the skill repo, so an unbumped version is
                    still attributable after the fact
  repo_commit       short commit of THIS repo holding the state of the tree the
                    rest of the row describes. The append can only see the
                    commit current when it ran, which on a Phase 7 run is the
                    parent of the one that ships the curation; `--repo-commit`
                    backfills it afterwards (#206). Distinct from skill_commit,
                    which names the skill's repo and can never stand in for it.
                    The scheduled seam sweep reads this back out of the previous
                    row (`check-seams.sh --base-ledger`) to span the interval
                    since the last measurement, so a row without it sends the
                    next sweep back to an empty interval.
                    Null when the measurement was not taken inside a git repo
                    with a commit, and null on rows predating the field
  lines, bytes      policy-file size
  budget            budget in force for this run
  over_budget       tokens > budget
  tokens_live       policy + reachable live reference docs
  docs_total        live reference docs measured
  docs_orphaned     live docs not reachable from the policy file
  links_dead        broken relative links in the curated surface
  links_dead_anchors  links whose file resolves but whose #fragment names no
                    heading; null on a payload predating the field, which is
                    never the same as 0
  no_loss           prove-no-loss.sh's verdict, from --no-loss; null if not run
  no_loss_warrants  how many of that verdict's unaccounted lines carried a
                    judged entry in .skills/context-loss-ok, from
                    --no-loss-warrants. Null when the run did not report it,
                    which is never the same as 0: `ok` alone cannot tell
                    "nothing was unaccounted for" from "eight lines were judged
                    and waved through", and two cohort adoptions recorded that
                    same state in opposite ways (#111)
  claims_dropped    atoms prove-no-loss.sh --claims found at base and nowhere
  claims_warranted  now, and how many of those carried a judged entry, from
                    --claims-dropped / --claims-warranted. Null when the run
                    did not report them — which is never the same as 0, and is
                    the only thing distinguishing a tightening whose claim
                    check ran and passed from one that was never checked (#253)
  seams             check-seams.sh's unacknowledged count, from --seams; null
                    if not swept
  seams_acked       the sweep's acknowledged count, from --seams-acked; null
                    if not swept
  top_section       largest section title, and its share of the file
  delta_tokens      change vs the previous row for this file. Null on the first
                    row, and null when the measurement method changed since the
                    previous row — see delta_unavailable
  delta_days        days since the previous row (null if first)
  delta_unavailable present only when delta_tokens was suppressed; says why
  actions           action tags from --actions, or ["baseline:KIND"] with
                    --baseline
  note              --note text

Exit codes:
  0  row appended or backfilled (or printed, with --dry-run)
  1  usage error (including --baseline with --actions, --no-loss,
     --no-loss-warrants or --claims-*; --no-loss-warrants or --claims-*
     without a verdict; --claims-dropped N>0 against `ok`; or --repo-commit
     with an append-only flag, an unknown revision, an empty ledger or a
     baseline row), or stdin was not measure-context.sh JSON
  2  infrastructure failure (unwritable ledger, python3 missing)
  4  refused: measurement method differs from the previous row for this file
     (pass --allow-method-change to record it anyway)
USAGE
}

LEDGER=".skills/context-metrics.jsonl"
ACTIONS=""
NOTE=""
NO_LOSS=""
NO_LOSS_WARRANTS=""
CLAIMS_DROPPED=""
CLAIMS_WARRANTED=""
SEAMS=""
SEAMS_ACKED=""
REPO_OVERRIDE=""
DRY=0
TREND=0
ALLOW_METHOD_CHANGE=0
BASELINE=0
BASELINE_KIND=""
ACTIONS_SET=0
NOTE_SET=0
BACKFILL=0
BACKFILL_REV=""

# --actions and --note accept an empty value deliberately, so they cannot use
# ${2:?...} for arity — and a bare `shift 2` at the end of argv fails under
# `set -e` with no message at all.
need_arg() {
  [ "$1" -ge 2 ] || { echo "ERROR $2 needs a value" >&2; exit 1; }
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ledger) LEDGER="${2:?--ledger needs a path}"; shift 2 ;;
    --baseline) BASELINE=1; BASELINE_KIND="pre-curation"; shift ;;
    --baseline=*) BASELINE=1; BASELINE_KIND="${1#*=}"; shift ;;
    --actions) need_arg "$#" --actions; ACTIONS="$2"; ACTIONS_SET=1; shift 2 ;;
    --note) need_arg "$#" --note; NOTE="$2"; NOTE_SET=1; shift 2 ;;
    --no-loss) NO_LOSS="${2:?--no-loss needs ok, failed, or skipped}"; shift 2 ;;
    --no-loss-warrants)
      NO_LOSS_WARRANTS="${2:?--no-loss-warrants needs a count}"; shift 2 ;;
    --claims-dropped)
      CLAIMS_DROPPED="${2:?--claims-dropped needs a count}"; shift 2 ;;
    --claims-warranted)
      CLAIMS_WARRANTED="${2:?--claims-warranted needs a count}"; shift 2 ;;
    --seams) SEAMS="${2:?--seams needs a count}"; shift 2 ;;
    --seams-acked) SEAMS_ACKED="${2:?--seams-acked needs a count}"; shift 2 ;;
    --repo) REPO_OVERRIDE="${2:?--repo needs a name}"; shift 2 ;;
    --repo-commit)
      BACKFILL=1; BACKFILL_REV="${2:?--repo-commit needs a revision}"; shift 2 ;;
    --allow-method-change) ALLOW_METHOD_CHANGE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --print-trend) TREND=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Backfill mode reads no measurement and writes no new row, so every flag that
# describes a run has nothing to land on. Refused rather than silently
# discarded: `--repo-commit HEAD --actions demote:X` looks like it records the
# tags and would record nothing, which is the failure mode #111 found in the
# cohort's data with a different field.
if [ "$BACKFILL" -eq 1 ]; then
  APPEND_ONLY=""
  [ "$ACTIONS_SET" -eq 0 ] || APPEND_ONLY="$APPEND_ONLY --actions"
  [ "$NOTE_SET" -eq 0 ] || APPEND_ONLY="$APPEND_ONLY --note"
  [ "$BASELINE" -eq 0 ] || APPEND_ONLY="$APPEND_ONLY --baseline"
  [ -z "$NO_LOSS" ] || APPEND_ONLY="$APPEND_ONLY --no-loss"
  [ -z "$NO_LOSS_WARRANTS" ] || APPEND_ONLY="$APPEND_ONLY --no-loss-warrants"
  [ -z "$CLAIMS_DROPPED" ] || APPEND_ONLY="$APPEND_ONLY --claims-dropped"
  [ -z "$CLAIMS_WARRANTED" ] || APPEND_ONLY="$APPEND_ONLY --claims-warranted"
  [ -z "$SEAMS" ] || APPEND_ONLY="$APPEND_ONLY --seams"
  [ -z "$SEAMS_ACKED" ] || APPEND_ONLY="$APPEND_ONLY --seams-acked"
  [ -z "$REPO_OVERRIDE" ] || APPEND_ONLY="$APPEND_ONLY --repo"
  [ "$ALLOW_METHOD_CHANGE" -eq 0 ] || APPEND_ONLY="$APPEND_ONLY --allow-method-change"
  [ "$TREND" -eq 0 ] || APPEND_ONLY="$APPEND_ONLY --print-trend"
  [ -z "$APPEND_ONLY" ] || {
    echo "ERROR --repo-commit backfills the row this run already recorded, so" >&2
    echo "      it reads no measurement and cannot record:$APPEND_ONLY." >&2
    echo "      Pass those on the Phase 7 append, before the commit." >&2
    exit 1; }
fi

# A baseline row records the surface AS FOUND, so the flags that assert
# something about a curation are refused rather than quietly ignored. --no-loss
# in particular would put a relocation verdict on a row where nothing was
# relocated, and the gate reads that field as evidence.
#
# --seams/--seams-acked are deliberately NOT refused: a sweep of the surface as
# found measures the state before the run, which is a before-state like any
# other and the one #117 argues the next experiment turns on.
if [ "$BASELINE" -eq 1 ]; then
  [ "$ACTIONS_SET" -eq 0 ] || {
    echo "ERROR --baseline and --actions are mutually exclusive: a baseline row" >&2
    echo "      is measurement-only and carries the fixed tag \`baseline\`." >&2
    echo "      Record the edits on the Phase 7 row instead." >&2
    exit 1; }
  if [ -n "$NO_LOSS" ] || [ -n "$NO_LOSS_WARRANTS" ] \
    || [ -n "$CLAIMS_DROPPED" ] || [ -n "$CLAIMS_WARRANTED" ]; then
    echo "ERROR --baseline and --no-loss/--no-loss-warrants/--claims-* are" >&2
    echo "      mutually exclusive: nothing has been relocated or rewritten" >&2
    echo "      yet, so there is no verdict to record, nothing to have" >&2
    echo "      warranted and no atom that could have been dropped." >&2
    exit 1
  fi
  # The KIND is on the TAG, not in --note. Two kinds of baseline row mean
  # different things to the longitudinal analysis — the state a curation was
  # measured against, versus a scheduled reading of a surface nobody touched —
  # and recovering that distinction from freetext is the asymmetry #116 called
  # out. `verb:target` is the house tag shape, and every reader already matches
  # on the `baseline` prefix, so a qualified tag is still a state.
  case "$BASELINE_KIND" in
    ''|*[!a-z0-9-]*)
      echo "ERROR --baseline=KIND must be lowercase letters, digits or dashes" >&2
      echo "      (got '$BASELINE_KIND'). Known kinds: pre-curation, scheduled." >&2
      exit 1 ;;
  esac
  ACTIONS="baseline:$BASELINE_KIND"
fi

# Reject an unrecognised verdict rather than storing it. A gate that reads this
# field treats anything other than "ok" as not-ok, so a typo would silently be a
# permanent failure recorded against the run — and a typo the other way ("OK"
# normalised in by a lenient reader) would be a permanent false pass.
case "$NO_LOSS" in
  ''|ok|failed|skipped) ;;
  *) echo "ERROR --no-loss must be ok, failed, or skipped (got '$NO_LOSS')" >&2; exit 1 ;;
esac
# Warrants are the COMPOSITION of a verdict, never a verdict of their own.
# Recorded against `skipped` or against nothing they would assert that lines
# were judged by a check nobody ran — the over-statement #111 found already in
# the cohort's data. Against `failed` they are informative: five warranted of
# eight unaccounted says how much of the failure was understood.
if [ -n "$NO_LOSS_WARRANTS" ]; then
  case "$NO_LOSS" in
    ok|failed) ;;
    *) echo "ERROR --no-loss-warrants needs --no-loss ok or --no-loss failed" >&2
       echo "      (got '${NO_LOSS:-nothing}'). A count with no verdict claims" >&2
       echo "      lines were judged by a check that did not run." >&2
       exit 1 ;;
  esac
fi
# The claim check is a MODE of the same run, not a second run, so its counts
# answer to the same verdict (#253). Recorded against `skipped` or nothing they
# would say atoms were compared by a check nobody ran — `no_loss_warrants`'
# failure mode exactly, one field over.
for _claim in "--claims-dropped=$CLAIMS_DROPPED" \
              "--claims-warranted=$CLAIMS_WARRANTED"; do
  _flag="${_claim%%=*}"; _val="${_claim#*=}"
  [ -n "$_val" ] || continue
  case "$NO_LOSS" in
    ok|failed) ;;
    *) echo "ERROR $_flag needs --no-loss ok or --no-loss failed (got" >&2
       echo "      '${NO_LOSS:-nothing}'). A claim count with no verdict says" >&2
       echo "      atoms were compared by a check that did not run." >&2
       exit 1 ;;
  esac
done
# An unwarranted dropped atom exits prove-no-loss.sh 3, so `ok` beside one is a
# verdict that run never reached. Refused rather than stored: this pair is the
# only evidence the ledger will ever hold that a class-C tightening was
# verified, and a row saying "checked, clean" over a check that failed is worse
# than the null it replaces.
case "$CLAIMS_DROPPED" in
  ''|0) ;;
  *) if [ "$NO_LOSS" = "ok" ]; then
       echo "ERROR --claims-dropped $CLAIMS_DROPPED with --no-loss ok:" >&2
       echo "      prove-no-loss.sh exits 3 on an unwarranted dropped atom, so" >&2
       echo "      that run did not pass. Record --no-loss failed, or warrant" >&2
       echo "      the atoms in .skills/context-loss-ok and re-run the check." >&2
       exit 1
     fi ;;
esac
# Digits only — the value comes from check-seams.sh's `seams: N` line, and
# anything else here is a transcription error, not a count.
for _pair in "--seams=$SEAMS" "--seams-acked=$SEAMS_ACKED" \
             "--no-loss-warrants=$NO_LOSS_WARRANTS" \
             "--claims-dropped=$CLAIMS_DROPPED" \
             "--claims-warranted=$CLAIMS_WARRANTED"; do
  _flag="${_pair%%=*}"; _val="${_pair#*=}"
  case "$_val" in
    ''|*[!0-9]*)
      [ -z "$_val" ] || {
        echo "ERROR $_flag must be a non-negative integer (got '$_val')" >&2; exit 1; } ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

# Backfill mode must NOT touch stdin. A caller running this by hand after the
# commit has a terminal on fd 0, and reading it to exhaustion would hang the
# script with no output at all rather than doing the one thing it was asked to.
if [ "$BACKFILL" -eq 0 ]; then
  cat >"$TMP/in.json"
  [ -s "$TMP/in.json" ] || { echo "ERROR no measurement on stdin — pipe measure-context.sh into this script" >&2; exit 1; }
fi

# TZ is pinned to UTC so rows from different machines sort and diff consistently.
TODAY="$(TZ=UTC date +%Y-%m-%d)"

# The row's repo identity — the join key the cohort roll-up and the validation
# gate match against the roster, so it is not cosmetic. basename(ROOT) alone was
# wrong in exactly the repos most likely to run this: in a git worktree
# --show-toplevel is the worktree path, so a run from
# .worktrees/feat-161-curating-context/ recorded THAT as the repo, and the row
# never joined its roster entry (#102). Several cohort members mandate
# worktree-based feature work, so this was not an edge case.
#
# Precedence: --repo, then the origin remote's basename (the identity the
# roster's owner/repo entries actually use), then the directory name for a repo
# with no origin at all.
if [ -n "$REPO_OVERRIDE" ]; then
  REPO_NAME="$REPO_OVERRIDE"
else
  ORIGIN="$(git remote get-url origin 2>/dev/null)" || ORIGIN=""
  if [ -n "$ORIGIN" ]; then
    REPO_NAME="${ORIGIN%/}"
    REPO_NAME="${REPO_NAME##*[/:]}"
    REPO_NAME="${REPO_NAME%.git}"
  else
    REPO_NAME="$(basename "$ROOT")"
  fi
fi
[ -n "$REPO_NAME" ] || REPO_NAME="$(basename "$ROOT")"

# WHICH STATE of this repo the row describes. `skill_commit` is the skill's
# commit and was never a candidate — the two repos are different repos.
#
# The scheduled seam sweep reads this back out of the previous row to bound the
# week it measures (#169). Empty here becomes null on the row rather than a
# guess: a fabricated revision would send the next sweep to a tree nobody
# measured, and null already means "cannot name an interval" to the reader.
REPO_COMMIT="$(git rev-parse --short HEAD 2>/dev/null)" || REPO_COMMIT=""

MODE=append
if [ "$BACKFILL" -eq 1 ]; then
  MODE=backfill
  # Resolve REV here rather than in python, so the row can only ever carry a
  # revision this repo can check out — and normalise it to the short form the
  # append writes and `check-seams.sh --base-ledger` reads back. Recorded long
  # and read short is the way this pair would silently join nothing.
  REPO_COMMIT="$(git rev-parse --short --verify "${BACKFILL_REV}^{commit}" 2>/dev/null)" || {
    echo "ERROR --repo-commit '$BACKFILL_REV' is not a commit in this repo." >&2
    echo "      \`null\` already means \"cannot name an interval\"; a revision" >&2
    echo "      nobody can check out would send the next seam sweep to a tree" >&2
    echo "      that was never measured. Run this from the curated repo, after" >&2
    echo "      the commit that ships the curation." >&2
    exit 1; }
  # -s, so a missing ledger and an empty one give the same answer. Creating one
  # here would be answering a request to rewrite a row by inventing a file with
  # no rows in it.
  [ -s "$LEDGER" ] || {
    echo "ERROR $LEDGER has no rows, so there is nothing to backfill." >&2
    echo "      --repo-commit rewrites the row this run already recorded;" >&2
    echo "      record it first, then commit, then backfill." >&2
    exit 1; }
else
  mkdir -p "$(dirname "$LEDGER")" || { echo "ERROR cannot create $(dirname "$LEDGER")" >&2; exit 2; }
  [ -f "$LEDGER" ] || : >"$LEDGER" || { echo "ERROR cannot create $LEDGER" >&2; exit 2; }
fi

RC=0
python3 - "$TMP/in.json" "$LEDGER" "$TODAY" "$REPO_NAME" "$ACTIONS" "$NOTE" "$DRY" "$TREND" "$ALLOW_METHOD_CHANGE" "$NO_LOSS" "$SEAMS" "$SEAMS_ACKED" "$NO_LOSS_WARRANTS" "$REPO_COMMIT" "$MODE" "$CLAIMS_DROPPED" "$CLAIMS_WARRANTED" <<'PY' || RC=$?
import datetime as dt
import json
import os
import sys
import tempfile

(src, ledger, today, repo, actions, note, dry, trend, allow_method,
 no_loss, seams, seams_acked, no_loss_warrants, repo_commit,
 mode, claims_dropped, claims_warranted) = sys.argv[1:18]


def is_curation_row(r):
    """Whether a row records a RUN rather than a state.

    THIS RULE IS SHARED WITH cohort-report.sh's is_curation_row() and
    score-cohort.sh's classify_run(), and a test pins all three to one answer
    over a single mixed ledger. An untagged row (actions: []) counts as a run —
    something happened that nobody tagged, which is a tagging gap rather than a
    measurement. Only an explicit `baseline*` row is a state.

    Both modes below call THIS function rather than re-deciding: a backfill that
    disagreed with the append about what a curation row is would rewrite a row
    the append never wrote.
    """
    acts = r.get("actions") or []
    return not (acts and all(a.split(":", 1)[0] == "baseline" for a in acts))


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def read_ledger(path):
    """(every line verbatim, [(index, row)] for the ones that parse).

    A malformed line is skipped rather than fatal: the ledger is append-only and
    a half-written row from an interrupted run must not block every future
    measurement. It is also KEPT — the backfill rewrites the file, and a rewrite
    that dropped what an append merely stepped over would do the poisoning this
    tolerance exists to prevent, on a line no reader can get back.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        print(f"ERROR cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    parsed, malformed = [], 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            parsed.append((i, json.loads(line)))
        except ValueError:
            malformed += 1
    if malformed:
        print(f"WARN skipped {malformed} malformed ledger line(s)", file=sys.stderr)
    return lines, parsed


if mode == "backfill":
    # Phase 7 records the row and only then commits it alongside the edits, so
    # the append could not have named the commit that ships the tree it
    # measured. Rewrite that row IN PLACE — telemetry.md sanctions a rewrite
    # within a run and forbids a third row for an intermediate state.
    lines, parsed = read_ledger(ledger)
    if not parsed:
        print(f"ERROR no parseable row in {ledger} to backfill", file=sys.stderr)
        sys.exit(1)
    idx, target = parsed[-1]
    if not is_curation_row(target):
        print(
            "ERROR the newest row in "
            f"{ledger} is a `{(target.get('actions') or ['baseline'])[0]}` row, "
            "which records a state that has already passed — a later commit "
            "cannot change what it describes, and telemetry.md exempts it from "
            "the rewrite rule in both directions. Backfill the curation row.",
            file=sys.stderr,
        )
        sys.exit(1)
    was = target.get("repo_commit")
    if dry == "1":
        target["repo_commit"] = repo_commit
        print(json.dumps(target, sort_keys=True, ensure_ascii=False))
        sys.exit(0)
    if was == repo_commit:
        # Idempotent by answering, not by writing. A re-run is the normal way an
        # interrupted Phase 7 finishes, and it must not churn the file.
        print(f"repo_commit already {repo_commit}; nothing to backfill",
              file=sys.stderr)
        sys.exit(0)
    target["repo_commit"] = repo_commit
    lines[idx] = json.dumps(target, sort_keys=True, ensure_ascii=False)
    # Write-then-rename, so a crash mid-write leaves the ledger as it was rather
    # than truncated. The temp file is created in the ledger's own directory
    # because os.replace is only atomic within a filesystem.
    d = os.path.dirname(os.path.abspath(ledger)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".context-metrics-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(ln + "\n" for ln in lines))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ledger)
    except OSError as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        print(f"ERROR cannot rewrite {ledger}: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"backfilled repo_commit {was or 'null'} -> {repo_commit} on "
          f"{target.get('file')} ({target.get('ts')})", file=sys.stderr)
    sys.exit(0)

try:
    m = json.load(open(src, encoding="utf-8"))
    policy, totals, links = m["policy"], m["totals"], m["links"]
except (ValueError, KeyError) as exc:
    print(f"ERROR stdin is not measure-context.sh JSON: {exc}", file=sys.stderr)
    sys.exit(1)


# Which skill version produced this row. Absent from measurements taken before
# the field existed, and null rather than guessed in that case — a wrong
# attribution is worse than a missing one when the point is to A/B skill changes.
skill = m.get("skill") or {}

sections = m.get("sections") or []
top = sections[0] if sections else {}

row = {
    "ts": today,
    "repo": repo,
    "file": policy["path"],
    "tokens": policy["tokens"],
    "tokens_exact": policy["tokens_exact"],
    "skill_version": skill.get("version") or None,
    "skill_commit": skill.get("commit") or None,
    # The repo's own commit, not the skill's (#169). The next scheduled sweep
    # takes its `--base` from here, which is what makes `seams` span a week
    # instead of an empty diff. On a Phase 7 run this is the PARENT of the
    # commit that ships the curation, and `--repo-commit` backfills it once
    # that commit exists (#206).
    "repo_commit": repo_commit or None,
    "lines": policy["lines"],
    "bytes": policy["bytes"],
    "budget": policy["budget"],
    "over_budget": policy["over_budget"],
    "tokens_live": totals["tokens_live"],
    "docs_total": totals["files_docs"],
    "docs_orphaned": len(links["orphans"]),
    "links_dead": len(links["dead"]),
    # None, not 0, when the payload predates the field (#120/#124): a row that
    # never measured anchors has not proved there are none, and the ledger
    # already distinguishes null from zero for no_loss and seams. Recording 0
    # here would tell the gate a surface was checked when it wasn't.
    "links_dead_anchors": (
        len(links["dead_anchors"]) if "dead_anchors" in links else None
    ),
    "no_loss": no_loss or None,
    # Empty-string test, not truthiness: `--no-loss-warrants 0` is a positive
    # claim — the run read the report and had nothing to warrant — and the
    # `or None` shape used above would fold it back into "not measured". That
    # distinction is the whole point of the field (#111).
    "no_loss_warrants": int(no_loss_warrants) if no_loss_warrants != "" else None,
    # Same empty-string test, and the same reason: `claims_dropped: 0` from a
    # run that passed --claims is the positive claim the field exists to carry
    # (#253). Two fields rather than one because a dropped-but-judged atom and
    # an unwarranted one are different states — the first is a judgement, the
    # second is why the run exited 3.
    "claims_dropped": int(claims_dropped) if claims_dropped != "" else None,
    "claims_warranted": (
        int(claims_warranted) if claims_warranted != "" else None
    ),
    "seams": int(seams) if seams else None,
    "seams_acked": int(seams_acked) if seams_acked else None,
    "top_section": top.get("title"),
    "top_section_share": top.get("share"),
    "delta_tokens": None,
    "delta_days": None,
    "actions": [a.strip() for a in actions.split(",") if a.strip()],
    "note": note or None,
}

# Prior rows for the same file, oldest first — through the same reader the
# backfill uses, so the two modes cannot disagree about which lines are rows.
history = [prev for _, prev in read_ledger(ledger)[1]
           if prev.get("file") == row["file"]]

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
                "credential (ANTHROPIC_API_KEY, or the key in a repo-root .env).\n"
                "  Next time, catch this before doing any work: "
                "measure-context.sh --check-credential is the Phase 0 preflight "
                "for exactly this refusal.\n"
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
    # Name the kind of row, not just the number. A baseline row is the one a
    # reader is most likely to think did not land, because it records a state
    # rather than a change and its delta is null by construction.
    acts = row["actions"]
    kind = f" ({acts[0]} — a measurement, not a curation)" \
        if len(acts) == 1 and acts[0].split(":", 1)[0] == "baseline" else ""
    print(f"recorded {row['file']}: {row['tokens']} tokens{kind}",
          file=sys.stderr)

if trend == "1":
    series = history + [row]
    # Runs, not rows. A curation run writes two rows — the Phase 1 `baseline` and
    # the Phase 7 curation — so len(series) reported one curation as two runs.
    # Every row is still PRINTED below; the baselines are what the deltas are
    # measured against.
    n_runs = sum(1 for r in series if is_curation_row(r))
    print(f"\ntrend for {row['file']} "
          f"({plural(n_runs, 'run')} over {plural(len(series), 'row')}):",
          file=sys.stderr)
    # Action tags are the point of the ledger, so a real run carries several and a
    # single-line format stops being readable at about three. Wrap onto
    # continuation lines aligned under the first tag rather than truncating: the
    # tag that got cut is exactly the one someone is reading the trend to find.
    LABEL_W = 30
    for r in series[-8:]:
        d = r.get("delta_tokens")
        mark = "" if d is None else f"  ({d:+d})"
        head = f"  {r['ts']}  {r['tokens']:>7} tok{mark:<12}"
        acts = r.get("actions") or ["-"]
        line, rest = head, []
        for tag in acts:
            candidate = f"{line}{'' if line == head else ', '}{tag}"
            if len(candidate) > len(head) + LABEL_W and line != head:
                rest.append(line)
                line = f"{' ' * len(head)}{tag}"
            else:
                line = candidate
        rest.append(line)
        for out in rest:
            print(out, file=sys.stderr)
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
