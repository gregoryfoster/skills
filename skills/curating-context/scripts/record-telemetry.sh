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
  lines, bytes      policy-file size
  budget            budget in force for this run
  over_budget       tokens > budget
  tokens_live       policy + reachable live reference docs
  docs_total        live reference docs measured
  docs_orphaned     live docs not reachable from the policy file
  links_dead        broken relative links in the curated surface
  no_loss           prove-no-loss.sh's verdict, from --no-loss; null if not run
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
NO_LOSS=""
SEAMS=""
SEAMS_ACKED=""
REPO_OVERRIDE=""
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
    --no-loss) NO_LOSS="${2:?--no-loss needs ok, failed, or skipped}"; shift 2 ;;
    --seams) SEAMS="${2:?--seams needs a count}"; shift 2 ;;
    --seams-acked) SEAMS_ACKED="${2:?--seams-acked needs a count}"; shift 2 ;;
    --repo) REPO_OVERRIDE="${2:?--repo needs a name}"; shift 2 ;;
    --allow-method-change) ALLOW_METHOD_CHANGE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --print-trend) TREND=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Reject an unrecognised verdict rather than storing it. A gate that reads this
# field treats anything other than "ok" as not-ok, so a typo would silently be a
# permanent failure recorded against the run — and a typo the other way ("OK"
# normalised in by a lenient reader) would be a permanent false pass.
case "$NO_LOSS" in
  ''|ok|failed|skipped) ;;
  *) echo "ERROR --no-loss must be ok, failed, or skipped (got '$NO_LOSS')" >&2; exit 1 ;;
esac
# Digits only — the value comes from check-seams.sh's `seams: N` line, and
# anything else here is a transcription error, not a count.
for _pair in "--seams=$SEAMS" "--seams-acked=$SEAMS_ACKED"; do
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

cat >"$TMP/in.json"
[ -s "$TMP/in.json" ] || { echo "ERROR no measurement on stdin — pipe measure-context.sh into this script" >&2; exit 1; }

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

mkdir -p "$(dirname "$LEDGER")" || { echo "ERROR cannot create $(dirname "$LEDGER")" >&2; exit 2; }
[ -f "$LEDGER" ] || : >"$LEDGER" || { echo "ERROR cannot create $LEDGER" >&2; exit 2; }

RC=0
python3 - "$TMP/in.json" "$LEDGER" "$TODAY" "$REPO_NAME" "$ACTIONS" "$NOTE" "$DRY" "$TREND" "$ALLOW_METHOD_CHANGE" "$NO_LOSS" "$SEAMS" "$SEAMS_ACKED" <<'PY' || RC=$?
import datetime as dt
import json
import sys

(src, ledger, today, repo, actions, note, dry, trend, allow_method,
 no_loss, seams, seams_acked) = sys.argv[1:13]

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
    "lines": policy["lines"],
    "bytes": policy["bytes"],
    "budget": policy["budget"],
    "over_budget": policy["over_budget"],
    "tokens_live": totals["tokens_live"],
    "docs_total": totals["files_docs"],
    "docs_orphaned": len(links["orphans"]),
    "links_dead": len(links["dead"]),
    "no_loss": no_loss or None,
    "seams": int(seams) if seams else None,
    "seams_acked": int(seams_acked) if seams_acked else None,
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
    print(f"recorded {row['file']}: {row['tokens']} tokens", file=sys.stderr)

if trend == "1":
    series = history + [row]
    print(f"\ntrend for {row['file']} ({len(series)} runs):", file=sys.stderr)
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
