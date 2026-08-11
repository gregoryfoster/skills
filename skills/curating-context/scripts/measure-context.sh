#!/usr/bin/env bash
# measure-context.sh — baseline metrics for a repo's agent-context surface.
#
# Emits one JSON object on stdout describing the policy file (AGENTS.md), its
# per-section token census, the reference-doc tree, and the link graph between
# them. Diagnostics go to stderr. Exit 2 on infrastructure failure so a caller
# can never mistake a broken measurement for a clean one.
set -euo pipefail

usage() {
  cat <<'USAGE'
measure-context.sh — measure a repo's agent-context surface

Usage:
  measure-context.sh [options]

Options:
  --file PATH        Policy file to measure. Default: AGENTS.md, else CLAUDE.md.
  --docs-dir DIR     Reference-doc root. Default: CONTEXT_DOCS_DIR, then
                     .skills/context-docs-dir, then docs. The write guard and
                     context-delta.sh read the same knob, so setting it once
                     keeps all three looking at the same tree.
  --budget N         Token budget for the policy file. Overrides CONTEXT_BUDGET
                     and .skills/context-budget; default 6000. The knob file is
                     what install-guard.sh --budget writes, and what the write
                     guard and the review delta read, so all three agree.
  --doc-budget N     Token budget per reference doc. Same chain via
                     CONTEXT_DOC_BUDGET and .skills/context-doc-budget;
                     default 10000.
  --archival NAMES   Space-separated <docs-dir> subdirectory names treated as an
                     archive rather than live context: excluded from the doc
                     inventory, and not traversed for links. Default:
                     "plans specs research audits archive". Pass "" to measure
                     everything. Plans and audits are dated snapshots — a stale
                     path inside one is a correct historical record, so counting
                     them as orphans or dead links buries the live signal.
  --exact            Count tokens via the Anthropic count_tokens endpoint
                     instead of the calibrated offline estimate. The endpoint is FREE — it
                     is rate-limited per usage tier but consumes no tokens and
                     is billed nothing, with limits independent of message
                     creation. Requires python3 plus a credential, tried in
                     order: ANTHROPIC_API_KEY in the environment, then
                     ANTHROPIC_API_KEY parsed out of a repo-root secrets file
                     (see --env-file / --no-env-file), then an `ant auth login`
                     profile — last, because count_tokens rejects JWT auth
                     today. Falls back to the estimate with a WARN on any
                     failure.
  --check-credential Preflight only: resolve a credential through the same three
                     sources, say which one answered (never the value), and exit
                     without measuring anything. 0 = a usable credential exists;
                     3 = none does, or only the JWT profile does. Run this
                     BEFORE starting a curation: the credential is otherwise
                     first checked mid-Phase-1, which interactively is a stall
                     at the worst moment and autonomously is eight phases of
                     work toward a ledger row that exit-4s at the end.
  --model ID         Model for --exact token counting. Default: claude-opus-5
  --no-env-file      Never read a credential from a repo-root secrets file. Use
                     when the key must come only from the environment.
  --env-file NAMES   Space-separated secrets-file names to search, relative to
                     the repo root. Default: ".env env" (bare `env` is the name
                     this cohort used before 2026-08-05). Only
                     ANTHROPIC_API_KEY is read, by parsing — never by sourcing.
  --no-write         Touch nothing. Suppresses the one side effect an --exact run
                     otherwise has: writing the observed bytes-per-token ratio to
                     .skills/context-token-ratio. Required when measuring a repo
                     you are only surveying — cohort remediation is filed as
                     issues, never written across repos.
  -h, --help         Show this help and exit 0.

Output (stdout, JSON):
  policy    { path, lines, bytes, tokens, tokens_exact, bytes_per_token,
              budget, over_budget }
  skill     { name, version, commit }  which skill version measured this, so a
              ledger row can be attributed to a skill change
  sections  [ { title, lines, bytes, tokens, share } ]  `##`, descending by size
              A section's bytes INCLUDE its subsections, so share is
              share-of-file and the rows sum to the policy total.
  subsections [ { title, parent, lines, bytes, tokens, share } ]  `###`, ditto
              The unit most demotions actually act on: a large `##` section is
              usually kept-plus-demoted rather than moved whole.
  docs      [ { path, lines, bytes, tokens, linked, over_budget } ]  live only
  links     { refs, dead, orphans }
  totals    { tokens_policy, tokens_docs, tokens_live, files_docs, archival_skipped }

  tokens_live is the number that matters: the policy file plus every live
  reference doc reachable from it. That is the ceiling on what one session can
  pull into context from this repo's own guidance.

Exit codes:
  0  measurement completed (with or without budget violations), or
     --check-credential found a usable credential
  1  usage error, or no policy file found
  2  infrastructure failure (unreadable file, awk/find failure)
  3  --check-credential only: no credential that count_tokens will accept
USAGE
}

POLICY=""
DOCS_DIR=""
# Resolved AFTER the library loads, through the same override -> env -> knob
# file -> default chain the write guard and the review delta use. These hold
# only the flag.
BUDGET_OVERRIDE=""
DOC_BUDGET_OVERRIDE=""
ARCHIVAL="plans specs research audits archive"
EXACT=0
CHECK_CRED=0
NO_WRITE=0
NO_ENV_FILE=0
ENV_FILES=".env env"
MODEL="claude-opus-5"

# An option that legitimately accepts an EMPTY value cannot use ${2:?...} to
# check arity, and a bare `shift 2` at the end of the argv fails under `set -e`
# with no message at all. Check the count explicitly.
need_arg() {
  [ "$1" -ge 2 ] || { echo "ERROR $2 needs a value${3:+ ($3)}" >&2; exit 1; }
}

while [ $# -gt 0 ]; do
  case "$1" in
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --budget) BUDGET_OVERRIDE="${2:?--budget needs a number}"; shift 2 ;;
    --doc-budget) DOC_BUDGET_OVERRIDE="${2:?--doc-budget needs a number}"; shift 2 ;;
    --archival) need_arg "$#" --archival 'pass "" to measure everything'
                ARCHIVAL="$2"; shift 2 ;;
    --exact) EXACT=1; shift ;;
    --check-credential) CHECK_CRED=1; shift ;;
    --no-write) NO_WRITE=1; shift ;;
    --no-env-file) NO_ENV_FILE=1; shift ;;
    --env-file) need_arg "$#" --env-file 'space-separated names, relative to the repo root'
                ENV_FILES="$2"; shift 2 ;;
    --model) MODEL="${2:?--model needs an id}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# --- shared library -------------------------------------------------------
# Resolve through a symlink chain first: this script may be reached through a
# symlinked vendor tree, and ${BASH_SOURCE[0]}'s dirname would then hold no
# library. Unlike the hook, a missing library here is fatal — a measurement that
# silently fell back to different constants is worse than no measurement.
#
# BEFORE the cd to the repo root, deliberately: a relative invocation from a
# subdirectory (bash ../skills/.../measure-context.sh) leaves ${BASH_SOURCE[0]}
# relative to the ORIGINAL cwd, and resolving it after the cd looked for the
# library in the wrong tree and blamed the library for it.
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

# Repo root, so the measurement is stable regardless of cwd. The silent
# fallback to cwd covers running outside a git repo at all.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

# The budgets, through the SAME chain as context-budget-guard.sh and
# context-delta.sh: flag, then CONTEXT_BUDGET, then .skills/context-budget, then
# the default. This script used to hardcode 6000 and read the flag only, so the
# two continuous surfaces honoured a repo's configured budget and the WEEKLY
# MEASUREMENT did not — and it is this script that puts `budget` and
# `over_budget` on the ledger row, which score-cohort.sh divides by and #118
# proposes as the adherence metric. install-guard.sh --budget writes that knob,
# so the supported way to configure a budget was the one that produced the
# disagreement (#126).
BUDGET="$(ctx_read_num_knob "$BUDGET_OVERRIDE" "${CONTEXT_BUDGET-}" \
  "$ROOT/.skills/context-budget" 6000)"
DOC_BUDGET="$(ctx_read_num_knob "$DOC_BUDGET_OVERRIDE" "${CONTEXT_DOC_BUDGET-}" \
  "$ROOT/.skills/context-doc-budget" 10000)"

# --check-credential: answer "will --exact succeed?" BEFORE a run commits to
# eight phases of work. Same three sources as the real resolution below, same
# order, and the same honesty about the JWT profile: a credential that resolves
# but will 401 on count_tokens is reported and still exits 3, because the
# question is whether the LEDGER ROW will be exact, not whether something
# authenticated. Prints the source that answered, never the value.
if [ "$CHECK_CRED" -eq 1 ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "no: python3 is missing, so --exact cannot call the endpoint at all" >&2
    exit 3
  fi
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ok: ANTHROPIC_API_KEY is in the environment"
    exit 0
  fi
  if [ "$NO_ENV_FILE" -eq 0 ]; then
    # Unquoted $ENV_FILES is deliberate: it is a space-separated list of names.
    # shellcheck disable=SC2086
    _k="$(ctx_api_key_from_env_file "$ROOT" $ENV_FILES)" || _k=""
    if [ -n "$_k" ]; then
      echo "ok: ANTHROPIC_API_KEY is in a repo-root secrets file ($ENV_FILES)"
      exit 0
    fi
  fi
  if command -v ant >/dev/null 2>&1 \
    && [ -n "$(ant auth print-credentials --access-token 2>/dev/null)" ]; then
    echo "no: only an \`ant auth\` profile resolves, and count_tokens rejects JWT" >&2
    echo "    auth today — the run would degrade to an estimate row. Set" >&2
    echo "    ANTHROPIC_API_KEY or put it in a repo-root .env first." >&2
    exit 3
  fi
  echo "no: no credential found. Set ANTHROPIC_API_KEY, or put it in a repo-root" >&2
  echo "    .env — resolve this BEFORE starting the run; in autonomous mode, abort." >&2
  exit 3
fi

# Which version of the skill is producing this measurement — carried into the
# ledger row so a later A/B can group by it.
SKILL_META="$(ctx_skill_version "$_libdir")" || SKILL_META=""
SKILL_VERSION="${SKILL_META%%"$CTX_TAB"*}"
SKILL_COMMIT="${SKILL_META#*"$CTX_TAB"}"

# Reference-doc root: --docs-dir, then CONTEXT_DOCS_DIR, then the .skills knob,
# then docs. The write guard and context-delta.sh read the same knob, so setting
# it once points all three at one tree.
DOCS_DIR="$(ctx_docs_dir "$ROOT" "$DOCS_DIR")"
# --archival feeds the library's matcher, which both continuous surfaces use too.
CTX_ARCHIVAL="$ARCHIVAL"

if [ -z "$POLICY" ]; then
  for cand in AGENTS.md CLAUDE.md; do
    [ -f "$cand" ] && { POLICY="$cand"; break; }
  done
fi
if [ -z "$POLICY" ] || [ ! -f "$POLICY" ]; then
  echo "ERROR no policy file found (looked for AGENTS.md, CLAUDE.md under $ROOT)" >&2
  exit 1
fi

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT
TAB="$(printf '\t')"

# --- token counting -------------------------------------------------------
# Default is the calibrated offline estimate, not a measurement. --exact calls
# messages/count_tokens, the only accurate tokenizer for Claude models (tiktoken
# is OpenAI's and undercounts Claude text by 15-20%, more on code).
# Counting is free, so --exact costs nothing but a credential. An unset API key
# does NOT mean there are no credentials.
#
# Order matters, and it is not the obvious one. An API key is first. A repo-root
# secrets file is SECOND, ahead of `ant auth`, because the OAuth path is
# currently non-functional against this endpoint: it authenticates fine and then
# count_tokens answers
#   HTTP 401 "jwt auth is not yet supported on count_tokens"
# so trying it first meant that on a machine with the `ant` CLI installed the
# broken credential won and a perfectly good key in .env was never reached. It is
# kept, last, because the endpoint may support JWT later — and it announces the
# known limitation rather than looking like a working choice.
EXACT_OK=0
if [ "$EXACT" -eq 1 ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARN --exact requires python3; using offline estimate" >&2
  elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    EXACT_OK=1
  elif [ "$NO_ENV_FILE" -eq 0 ] \
    && ANTHROPIC_API_KEY="$(ctx_api_key_from_env_file "$ROOT" $ENV_FILES)" \
    && [ -n "$ANTHROPIC_API_KEY" ]; then
    # The source that makes an interactive run match a scheduled one: a Claude
    # Code session exports no key and usually has no `ant` CLI, so without this
    # the interactive path writes an estimate row into a ledger of exact rows and
    # every delta afterwards is null.
    export ANTHROPIC_API_KEY
    EXACT_OK=1
    echo "INFO --exact read ANTHROPIC_API_KEY from a repo-root secrets file ($ENV_FILES); pass --no-env-file to refuse" >&2
  elif command -v ant >/dev/null 2>&1 \
    && ANTHROPIC_OAUTH_TOKEN="$(ant auth print-credentials --access-token 2>/dev/null)" \
    && [ -n "$ANTHROPIC_OAUTH_TOKEN" ]; then
    # OAuth tokens go on `Authorization: Bearer`, not `x-api-key`, and need the
    # oauth beta header — converting from a key is a header change, not a swap.
    export ANTHROPIC_OAUTH_TOKEN
    EXACT_OK=1
    echo "WARN --exact falling back to the \`ant auth\` profile; count_tokens does not" >&2
    echo "     yet accept JWT auth, so this will very likely 401 and degrade to the" >&2
    echo "     offline estimate. Set ANTHROPIC_API_KEY or put it in .env instead." >&2
  else
    echo "WARN --exact needs ANTHROPIC_API_KEY, the key in a repo-root .env, or an \`ant auth login\` profile; using offline estimate" >&2
    echo "WARN the resulting row records tokens_exact=false, which suppresses every delta against an exact row" >&2
  fi
fi

if [ "$EXACT_OK" -eq 1 ]; then
  cat >"$TMP/count.py" <<'PY'
import json, os, sys, urllib.error, urllib.request

path, model = sys.argv[1], sys.argv[2]
body = json.dumps({
    "model": model,
    "messages": [
        {"role": "user", "content": open(path, encoding="utf-8", errors="replace").read()}
    ],
}).encode()
headers = {
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}
if os.environ.get("ANTHROPIC_API_KEY"):
    headers["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
else:
    # An OAuth profile token authenticates on Authorization: Bearer and needs the
    # oauth beta header; /v1/messages* rejects it without one.
    headers["authorization"] = "Bearer " + os.environ["ANTHROPIC_OAUTH_TOKEN"]
    headers["anthropic-beta"] = "oauth-2025-04-20"

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages/count_tokens",
    data=body,
    headers=headers,
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(json.load(resp)["input_tokens"])
except urllib.error.HTTPError as exc:
    # The response body carries the actionable reason (bad model id, expired
    # key, exhausted credit); the status line alone does not.
    detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ")
    print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
    sys.exit(1)
except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
    print(f"count_tokens failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
fi

# Offline token estimate, used unless --exact supplies a real count. The ratio
# and its calibration live in the library so the guard and context-delta.sh
# cannot disagree with this script about it.
CTX_BPT_X100="$(ctx_bytes_per_token_x100 "$ROOT")"

est_from_bytes() { ctx_est_from_bytes "$1"; }

est_tokens() { est_from_bytes "$(LC_ALL=C wc -c <"$1" | tr -d ' ')"; }

count_tokens() {
  # count_tokens <file> -> token count on stdout. Falls back to the estimate on any
  # per-file failure, so one bad response degrades a number rather than the run.
  local f="$1" est out rc=0
  est="$(est_tokens "$f")"
  if [ "$EXACT_OK" -ne 1 ]; then printf '%s' "$est"; return 0; fi
  out="$(python3 "$TMP/count.py" "$f" "$MODEL" 2>"$TMP/ct.err")" || rc=$?
  if [ "$rc" -ne 0 ] || ! printf '%s' "$out" | grep -qE '^[0-9]+$'; then
    echo "WARN exact count failed for $f ($(tr -d '\n' <"$TMP/ct.err")); using estimate" >&2
    # Record the fallback for the caller. A marker FILE, not a variable: this
    # function is invoked in a command substitution, so its subshell cannot set
    # anything in the parent. Holding a credential is not the same as having
    # counted — without this, an accepted-but-rejected credential (see the `ant`
    # note above) reported tokens_exact=true over numbers that were entirely
    # estimates, which is the one lie the whole comparability chain cannot survive.
    : >"$TMP/count_fell_back"
    printf '%s' "$est"
  else
    printf '%s' "$out"
  fi
}

jesc() {
  # Minimal JSON string escaping for the values this script emits (repo-relative
  # paths and markdown headings): backslash, double quote, tab.
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e "s/$TAB/\\\\t/g"
}

# --- policy file ----------------------------------------------------------
P_LINES=$(LC_ALL=C wc -l <"$POLICY" | tr -d ' ')
P_BYTES=$(LC_ALL=C wc -c <"$POLICY" | tr -d ' ')
P_TOKENS=$(count_tokens "$POLICY")
# An empty policy file yields zero tokens, which the bytes-per-token ratio below
# divides by. Refuse it here, before a single byte of JSON is emitted: falling
# through printed a bare "{" to stdout and exited 1, so a caller piping into
# record-telemetry.sh saw "stdin is not measure-context.sh JSON" and never the
# real cause. Exit 2 — this is an infrastructure failure, not a usage error.
# Checked before the clamp below so the message reports the true byte count.
if [ "$P_TOKENS" -le 0 ]; then
  echo "ERROR $POLICY has no measurable content ($P_BYTES bytes, $P_TOKENS tokens)" >&2
  exit 2
fi
[ "$P_BYTES" -gt 0 ] || P_BYTES=1

# --- section census -------------------------------------------------------
# Two levels, because the section is not reliably the unit of demotion. Measured
# on this repo's first real run, three of four demotions were A+B splits: the `##`
# section stayed and its `###` subsections moved. A `##`-only census hides the
# unit the decision is actually made on, and leaves the run estimating the split
# by eye.
#
# `##` rows keep their full byte total INCLUDING their subsections, so `share`
# still means share-of-file and the rows still sum to wc -c. `###` rows are
# reported separately, each naming its parent.
#
# `/^### /` cannot match `#### x` (### then #, not a space), so deeper headings
# fall through to the body of their enclosing `###` — which is correct: they are
# not independently demotable.
#
# LC_ALL=C makes awk's length() byte-based rather than character-based, so the
# per-section bytes sum to wc -c.
AWK_RC=0
LC_ALL=C awk -v tab="$TAB" '
  function flush2() { if (h2 != "") printf "2%s%d%s%d%s%s%s\n", tab, l2, tab, b2, tab, h2, tab }
  function flush3() { if (h3 != "") printf "3%s%d%s%d%s%s%s%s\n", tab, l3, tab, b3, tab, h3, tab, h2 }
  /^## / {
    flush3(); flush2()
    h2 = substr($0, 4); l2 = 1; b2 = length($0) + 1
    h3 = ""; l3 = 0; b3 = 0
    next
  }
  /^### / {
    flush3()
    # Same lazy (preamble) init as the body rule, and it must run BEFORE the
    # increment below. A `### ` heading preceding both the first `## ` and the
    # first body line otherwise added its bytes to an unnamed h2, which the body
    # rule then reset to 0 — losing them, and breaking the sum-to-wc-c invariant
    # this census advertises (measured: 71 bytes of file, 49 in the rows).
    if (h2 == "") { h2 = "(preamble)"; l2 = 0; b2 = 0 }
    h3 = substr($0, 5); l3 = 1; b3 = length($0) + 1
    l2++; b2 += length($0) + 1
    next
  }
  {
    if (h2 == "") { h2 = "(preamble)"; l2 = 0; b2 = 0 }
    l2++; b2 += length($0) + 1
    if (h3 != "") { l3++; b3 += length($0) + 1 }
  }
  END { flush3(); flush2() }
' "$POLICY" >"$TMP/census.tsv" || AWK_RC=$?
if [ "$AWK_RC" -ne 0 ]; then
  echo "ERROR section census failed (awk exit $AWK_RC)" >&2
  exit 2
fi
awk -F"$TAB" -v OFS="$TAB" '$1 == 2 { print $2, $3, $4 }' "$TMP/census.tsv" >"$TMP/sections.tsv"
awk -F"$TAB" -v OFS="$TAB" '$1 == 3 { print $2, $3, $4, $5 }' "$TMP/census.tsv" >"$TMP/subsections.tsv"

# --- link graph -----------------------------------------------------------
# Reachability from the policy file over relative markdown links, computed
# transitively: the cohort convention is AGENTS.md -> docs/SKILLS.md -> deeper
# docs, so a direct-links-only check reports every second-hop doc as an orphan.
norm() {
  # norm <dir> <target> -> repo-relative path with . and .. resolved.
  local dir="$1" tgt="$2" combined out part oldifs
  case "$tgt" in
    /*) combined="${tgt#/}" ;;
    *) combined="${dir:+$dir/}$tgt" ;;
  esac
  out=""
  oldifs="$IFS"
  IFS='/'
  for part in $combined; do
    case "$part" in
      ""|.) ;;
      ..) case "$out" in */*) out="${out%/*}" ;; *) out="" ;; esac ;;
      *) out="${out:+$out/}$part" ;;
    esac
  done
  IFS="$oldifs"
  printf '%s' "$out"
}

extract_links() {
  # Relative markdown link targets, with anchors and absolute URLs stripped.
  # Targets containing <>, *, or a comma-space are prose that happens to sit in
  # bracket-paren form — `[label](references/<name>.md)` documenting a naming
  # convention, or a parenthesised list. Reporting them as dead links trains the
  # reader to ignore the dead-link list, so they are dropped here.
  grep -oE '\]\([^)]+\)' "$1" 2>/dev/null \
    | sed -e 's/^](//' -e 's/)$//' -e 's/#.*$//' \
    | grep -vE '^(https?:|mailto:|//|$)' \
    | grep -vE '[<>*]|, ' || true
}

in_scope() {
  # The curated surface: the policy file, plus live reference docs under
  # DOCS_DIR. Only these are traversed and only their links are reported as
  # dead. A root CHANGELOG.md or README.md is reachable but not curated — its
  # links to since-moved source files are a historical record, and reporting
  # them buries the rot that actually needs fixing.
  local p="$1"
  [ "$p" = "$POLICY" ] && return 0
  case "$p" in
    "$DOCS_DIR"/*) ctx_is_archival "$p" && return 1; return 0 ;;
  esac
  return 1
}

: >"$TMP/reachable"
: >"$TMP/refs"
: >"$TMP/dead"
QUEUE=("$POLICY")
qi=0
while [ "$qi" -lt "${#QUEUE[@]}" ]; do
  cur="${QUEUE[$qi]}"
  qi=$(( qi + 1 ))
  grep -Fxq "$cur" "$TMP/reachable" && continue
  printf '%s\n' "$cur" >>"$TMP/reachable"
  curdir="$(dirname "$cur")"
  [ "$curdir" = "." ] && curdir=""
  extract_links "$cur" >"$TMP/links.raw"
  while IFS= read -r raw; do
    [ -n "$raw" ] || continue
    tgt="$(norm "$curdir" "$raw")"
    [ -n "$tgt" ] || continue
    if [ "$cur" = "$POLICY" ]; then printf '%s\n' "$tgt" >>"$TMP/refs"; fi
    if [ ! -e "$tgt" ]; then
      printf '%s -> %s\n' "$cur" "$tgt" >>"$TMP/dead"
      continue
    fi
    # Out-of-scope targets (archival docs, root-level history files) are recorded
    # as reachable — so they never count as orphans — but are not traversed.
    if in_scope "$tgt"; then
      case "$tgt" in
        *.md) if [ -f "$tgt" ]; then QUEUE+=("$tgt"); fi ;;
      esac
    else
      printf '%s\n' "$tgt" >>"$TMP/reachable"
    fi
  done <"$TMP/links.raw"
done

# --- reference docs -------------------------------------------------------
: >"$TMP/docs.tsv"
if [ -d "$DOCS_DIR" ]; then
  FIND_RC=0
  find "$DOCS_DIR" -type f -name '*.md' >"$TMP/docfiles" 2>"$TMP/find.err" || FIND_RC=$?
  if [ "$FIND_RC" -ne 0 ]; then
    echo "ERROR find over $DOCS_DIR failed (exit $FIND_RC): $(cat "$TMP/find.err")" >&2
    exit 2
  fi
  [ -s "$TMP/find.err" ] && echo "WARN find over $DOCS_DIR: $(cat "$TMP/find.err")" >&2
  ARCHIVAL_SKIPPED=0
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    if ctx_is_archival "$d"; then
      ARCHIVAL_SKIPPED=$(( ARCHIVAL_SKIPPED + 1 ))
      continue
    fi
    dl=$(LC_ALL=C wc -l <"$d" | tr -d ' ')
    db=$(LC_ALL=C wc -c <"$d" | tr -d ' ')
    dt=$(count_tokens "$d")
    linked=false
    grep -Fxq "$d" "$TMP/reachable" && linked=true
    printf '%s%s%s%s%s%s%s%s%s\n' "$dl" "$TAB" "$db" "$TAB" "$dt" "$TAB" "$linked" "$TAB" "$d" >>"$TMP/docs.tsv"
  done <"$TMP/docfiles"
else
  ARCHIVAL_SKIPPED=0
  echo "WARN no $DOCS_DIR directory — reference-doc metrics will be empty" >&2
fi
if [ "$ARCHIVAL_SKIPPED" -gt 0 ]; then
  echo "INFO skipped $ARCHIVAL_SKIPPED archival doc(s) under: $ARCHIVAL" >&2
fi

# --- emit -----------------------------------------------------------------
json_list() {
  # json_list <file> — one value per line -> JSON array of strings.
  local f="$1" line n=0
  printf '['
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    [ "$n" -eq 0 ] || printf ', '
    n=1
    printf '"%s"' "$(jesc "$line")"
  done <"$f"
  printf ']'
}

over_policy=false
[ "$P_TOKENS" -gt "$BUDGET" ] && over_policy=true
# tokens_exact reports whether the numbers ARE exact, not whether a credential was
# found. If any count_tokens call fell back, the file's total is a blend at best
# and an estimate at worst, and a blend must not be compared against a true exact
# row — so the whole run is reported as an estimate.
exact_flag=false
COUNT_FELL_BACK=0
[ -f "$TMP/count_fell_back" ] && COUNT_FELL_BACK=1
if [ "$EXACT_OK" -eq 1 ] && [ "$COUNT_FELL_BACK" -eq 0 ]; then
  exact_flag=true
elif [ "$EXACT_OK" -eq 1 ]; then
  echo "WARN a credential was accepted but at least one count_tokens call failed;" >&2
  echo "     reporting tokens_exact=false, because a partially-estimated total is" >&2
  echo "     not comparable with an exact one. See the WARN lines above for the cause." >&2
fi

sort -t"$TAB" -k2,2nr "$TMP/sections.tsv" >"$TMP/sections.sorted"
sort -t"$TAB" -k2,2nr "$TMP/subsections.tsv" >"$TMP/subsections.sorted"
sort -t"$TAB" -k3,3nr "$TMP/docs.tsv" >"$TMP/docs.sorted"
awk -F"$TAB" '$4 == "false" { print $5 }' "$TMP/docs.tsv" | sort >"$TMP/orphans"
sort -u "$TMP/refs" >"$TMP/refs.sorted"
sort -u "$TMP/dead" >"$TMP/dead.sorted"

printf '{\n'
# Observed bytes-per-token, and — on a genuinely exact run — persist it so the
# offline estimators (the write guard, context-delta.sh) stop guessing for this
# repo. Gated on exact_flag rather than on EXACT_OK: deriving a calibration from
# an estimate re-derives the divisor it was computed with, so a credential that
# authenticated and then failed every count produced exactly 2.70 — a
# self-confirming fake measurement, comfortably inside the plausibility band,
# which would then be trusted by every later offline estimate in the repo.
RATIO_X100=$(( P_BYTES * 100 / P_TOKENS ))
# Persist only a plausible ratio. Real markdown measures 2.0-4.0 bytes/token; a
# value outside 1.5-6.0 means the file is degenerate or unrepresentative (a
# generated table, a wall of single-character lines), and freezing it would skew
# every later offline estimate. The reader has a matching floor, but writing
# nonsense and relying on the reader to reject it is worse than not writing it.
if [ "$RATIO_X100" -lt 150 ] || [ "$RATIO_X100" -gt 600 ]; then
  if [ "$exact_flag" = true ]; then
    echo "WARN observed ratio $(( RATIO_X100 / 100 )).$(printf '%02d' $(( RATIO_X100 % 100 ))) bytes/token is outside the plausible 1.50-6.00 band; not persisting it" >&2
  fi
  RATIO_PERSISTABLE=0
else
  RATIO_PERSISTABLE=1
fi

if [ "$exact_flag" = true ] && [ "$P_TOKENS" -gt 0 ] && [ "$NO_WRITE" -eq 0 ] && [ "$RATIO_PERSISTABLE" -eq 1 ]; then
  mkdir -p "$ROOT/.skills" 2>/dev/null || true
  printf '%d.%02d\n' $(( RATIO_X100 / 100 )) $(( RATIO_X100 % 100 )) \
    >"$ROOT/.skills/context-token-ratio" 2>/dev/null \
    || echo "WARN could not write .skills/context-token-ratio" >&2
elif [ "$exact_flag" = true ] && [ "$NO_WRITE" -eq 1 ] && [ "$RATIO_PERSISTABLE" -eq 1 ]; then
  echo "INFO --no-write: not persisting the observed ratio ($(( RATIO_X100 / 100 )).$(printf '%02d' $(( RATIO_X100 % 100 ))))" >&2
fi

printf '  "policy": {"path": "%s", "lines": %s, "bytes": %s, "tokens": %s, "tokens_exact": %s, "bytes_per_token": %d.%02d, "budget": %s, "over_budget": %s},\n' \
  "$(jesc "$POLICY")" "$P_LINES" "$P_BYTES" "$P_TOKENS" "$exact_flag" \
  $(( RATIO_X100 / 100 )) $(( RATIO_X100 % 100 )) "$BUDGET" "$over_policy"

printf '  "skill": {"name": "curating-context", "version": "%s", "commit": "%s"},\n' \
  "$(jesc "$SKILL_VERSION")" "$(jesc "$SKILL_COMMIT")"

printf '  "sections": [\n'
first=1
while IFS="$TAB" read -r sl sb st; do
  [ -n "${sl:-}" ] || continue
  [ "$first" -eq 1 ] || printf ',\n'
  first=0
  # Section tokens are derived from THIS run's observed ratio, so they sum to the
  # policy total above. Using bytes/4 here made the parts contradict the whole by
  # ~60% on an exact run; using the persisted ratio would use the previous run's.
  printf '    {"title": "%s", "lines": %s, "bytes": %s, "tokens": %s, "share": %s}' \
    "$(jesc "$st")" "$sl" "$sb" "$(( sb * 100 / RATIO_X100 ))" "$(( sb * 100 / P_BYTES ))"
done <"$TMP/sections.sorted"
[ "$first" -eq 1 ] || printf '\n'
printf '  ],\n'

printf '  "subsections": [\n'
first=1
while IFS="$TAB" read -r sl sb st sp; do
  [ -n "${sl:-}" ] || continue
  [ "$first" -eq 1 ] || printf ',\n'
  first=0
  # `share` is of the whole file, same denominator as sections, so a subsection
  # and its parent are directly comparable — which is the comparison a demotion
  # decision actually needs.
  printf '    {"title": "%s", "parent": "%s", "lines": %s, "bytes": %s, "tokens": %s, "share": %s}' \
    "$(jesc "$st")" "$(jesc "$sp")" "$sl" "$sb" "$(( sb * 100 / RATIO_X100 ))" "$(( sb * 100 / P_BYTES ))"
done <"$TMP/subsections.sorted"
[ "$first" -eq 1 ] || printf '\n'
printf '  ],\n'

printf '  "docs": [\n'
first=1
docs_tokens=0
while IFS="$TAB" read -r dl db dt dlinked dpath; do
  [ -n "${dl:-}" ] || continue
  docs_tokens=$(( docs_tokens + dt ))
  dover=false
  [ "$dt" -gt "$DOC_BUDGET" ] && dover=true
  [ "$first" -eq 1 ] || printf ',\n'
  first=0
  printf '    {"path": "%s", "lines": %s, "bytes": %s, "tokens": %s, "linked": %s, "over_budget": %s}' \
    "$(jesc "$dpath")" "$dl" "$db" "$dt" "$dlinked" "$dover"
done <"$TMP/docs.sorted"
[ "$first" -eq 1 ] || printf '\n'
printf '  ],\n'

printf '  "links": {"refs": '
json_list "$TMP/refs.sorted"
printf ', "dead": '
json_list "$TMP/dead.sorted"
printf ', "orphans": '
json_list "$TMP/orphans"
printf '},\n'

# tokens_live = policy + every live (non-archival) doc reachable from it. This
# is the ceiling on what one session can pull in from the repo's own guidance.
live_tokens="$P_TOKENS"
while IFS="$TAB" read -r dl db dt dlinked dpath; do
  [ -n "${dl:-}" ] || continue
  [ "$dlinked" = "true" ] && live_tokens=$(( live_tokens + dt ))
done <"$TMP/docs.tsv"

printf '  "totals": {"tokens_policy": %s, "tokens_docs": %s, "tokens_live": %s, "files_docs": %s, "archival_skipped": %s}\n' \
  "$P_TOKENS" "$docs_tokens" "$live_tokens" "$(LC_ALL=C wc -l <"$TMP/docs.tsv" | tr -d ' ')" "$ARCHIVAL_SKIPPED"
printf '}\n'
