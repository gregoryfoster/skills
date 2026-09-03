#!/usr/bin/env bash
# context-budget-guard.sh — Claude Code PostToolUse hook that flags an edit which
# grows the agent-context surface past its token budget.
#
# Regrowth is the failure mode weekly curation cannot fix: a run reduces
# AGENTS.md, the next fortnight of edits puts it back, and the telemetry trend
# sawtooths forever. This catches the growth at the moment it happens, which is
# the only moment it is cheap to fix.
#
# Contract (PostToolUse): the tool has already run, so nothing here can block.
# Always exits 0 and emits the advisory as JSON on stdout — `additionalContext`
# so the agent can act on it in the same turn, `systemMessage` so the human sees
# it. Exit 1/2 would surface as a "hook error" notice, which is wrong for an
# advisory: this is information, not a failure.
set -euo pipefail

# The exit-0 contract, enforced rather than hand-maintained. `set -e` aborts on
# the first unexpected failure and this trap converts that abort into a clean
# exit 0 — strictly safer than dropping `-e`, which would let a failed step fall
# through and report a number computed from nothing. Installed before anything
# can fail. Every deliberate early return below is already an explicit `exit 0`.
trap 'exit 0' EXIT

usage() {
  cat <<'USAGE'
context-budget-guard.sh — PostToolUse hook: warn when an edit grows the
agent-context surface past its token budget.

Usage:
  context-budget-guard.sh            # reads PostToolUse JSON on stdin
  context-budget-guard.sh --help

Install with:
  bash install-guard.sh

Budget resolution (first match wins, matching the repo's other knobs):
  1. CONTEXT_BUDGET env var
  2. .skills/context-budget  (single line, token count)
  3. 6000

Watched files:
  - the policy file: AGENTS.md or CLAUDE.md at the repo root. A symlinked
    CLAUDE.md is followed to its target, which is the cohort norm.
  - live reference docs: <docs-dir>/**/*.md, excluding archival subtrees
    (plans, specs, research, audits, archive) at any depth

The reference-doc root is CONTEXT_DOCS_DIR, then .skills/context-docs-dir, then
docs — the same knob measure-context.sh takes as its --docs-dir default.

Reference docs are measured against a 10k budget (CONTEXT_DOC_BUDGET, or
.skills/context-doc-budget), since their cost is paid on load rather than on
every invocation.

When it stays quiet:
  - the edited file is not part of the context surface
  - the file is under budget
  - the edit REDUCED the token count — someone curating is never nagged

Tokens are estimated offline at ~2.7 bytes/token, refined per repo by
.skills/context-token-ratio and then per FILE by .skills/context-token-counts,
both written by measure-context.sh --exact. A hook must be fast and offline, so
it never calls count_tokens; the estimate only decides whether to speak.

The per-file figures matter because one repo-wide ratio is derived from one file
— the policy file — and then divides every other. Measured across this repo's
own surface the per-file ratio runs 2.04 to 3.03 against a 2.65 global, so a
single divisor is wrong by -23% to +14% depending on the file, in both
directions at once. Over-flagging trains the reader to ignore the guard;
under-flagging is silence on a file that is genuinely over budget.

Which figure produced a number is recorded in the log as est=file or est=repo.

Logs every decision to <git-dir>/context-budget.log (truncated at 64 KiB), where
<git-dir> is `git rev-parse --absolute-git-dir` — the per-worktree git dir, so a
linked worktree keeps its own trail rather than losing every line to a .git that
is a file there.

Exit codes:
  0  always — including every internal failure. A hook must never be the reason
     a session misbehaves.
USAGE
}

case "${1-}" in
  -h|--help) usage; exit 0 ;;
esac

# From here on, every failure path must still reach exit 0.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || ROOT=""
# The wired command is anchored on $CLAUDE_PROJECT_DIR so the SCRIPT resolves from
# any cwd (#110); this is the other half — the repo it measures resolves from any
# cwd too. Without it a hook invoked from elsewhere finds the script, finds no
# repo, and exits 0 silently, which looks identical to "installed and quiet".
if [ -z "$ROOT" ] && [ -n "${CLAUDE_PROJECT_DIR-}" ]; then
  ROOT="$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null)" || ROOT=""
fi
[ -n "$ROOT" ] || exit 0
# `pwd -P` resolves symlinks in the root. Without it, a checkout reached through
# a symlinked parent (/tmp -> /private/tmp on macOS, or any symlinked home) gives
# a root that no incoming absolute file_path is ever a prefix of, and the guard
# silently ignores every edit.
ROOT="$(cd "$ROOT" 2>/dev/null && pwd -P)" || exit 0
cd "$ROOT" 2>/dev/null || exit 0

# The git DIRECTORY, not "$ROOT/.git". In a linked worktree that path is a FILE
# containing `gitdir: …`, so every append failed and was swallowed by the
# `|| true` below — no audit trail in precisely the trees several cohort repos
# mandate all development happens in (#109).
#
# Per-worktree (`--absolute-git-dir`) rather than a single shared log
# (`--git-common-dir`), for three reasons: it matches skills-submodule-update.sh,
# which already logs to `git rev-parse --git-dir`; the log answers "did the guard
# fire on the edit I just made here", which is a per-tree question; and the
# truncation below rewrites the file whole, so several worktrees appending to one
# shared log would race and lose lines.
GITDIR="$(git rev-parse --absolute-git-dir 2>/dev/null)" || GITDIR=""
LOG="$GITDIR/context-budget.log"
log() {
  [ -n "$GITDIR" ] && [ -d "$GITDIR" ] || return 0
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >>"$LOG" 2>/dev/null || true
  # Truncate to the last 200 lines once the log crosses 64 KiB.
  if [ -f "$LOG" ] && [ "$(LC_ALL=C wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 65536 ]; then
    # Truncation is best-effort: `|| true` is the C branch on purpose, so a
    # failed tail and a failed mv both leave the log as-is and the hook silent.
    # unchecked-write-ok: the log is a diagnostic, not state anything reads
    # back, and this is a PostToolUse hook that must never block an edit. The
    # marker is required because `|| true` on a temp-file write is #187's shape
    # by default — this is the one place it is a decision (#181).
    # shellcheck disable=SC2015
    tail -n 200 "$LOG" >"$LOG.tmp" 2>/dev/null && mv -f "$LOG.tmp" "$LOG" 2>/dev/null || true
  fi
}

# --- shared library -------------------------------------------------------
# This script is installed as a SYMLINK at .claude/hooks/, so ${BASH_SOURCE[0]}
# is the link path and its dirname holds no library — resolve the chain to the
# real file first. Sourced after log() so a missing library is recorded rather
# than silent; a hook that cannot measure stays quiet and exits 0.
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
if [ -z "$_libdir" ] || [ ! -f "$_libdir/_context-lib.sh" ]; then
  log "skip: _context-lib.sh not found next to $_self — reinstall with install-guard.sh"
  exit 0
fi
# shellcheck source=_context-lib.sh
. "$_libdir/_context-lib.sh"

PAYLOAD="$(cat 2>/dev/null)" || exit 0
[ -n "$PAYLOAD" ] || exit 0

# Extract tool_input.file_path. python3 first (the skill already requires it),
# jq second. Without either, stay silent rather than parse JSON with a regex.
FILE=""
if command -v python3 >/dev/null 2>&1; then
  FILE="$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except (ValueError, OSError):
    sys.exit(0)
ti = d.get("tool_input") or {}
p = ti.get("file_path") or ti.get("notebook_path") or ""
print(p if isinstance(p, str) else "")
' 2>/dev/null)" || FILE=""
elif command -v jq >/dev/null 2>&1; then
  FILE="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""' 2>/dev/null)" || FILE=""
else
  log "skip: neither python3 nor jq available to parse the hook payload"
  exit 0
fi
[ -n "$FILE" ] && [ "$FILE" != "null" ] || exit 0

# Normalize to a repo-relative path, resolving symlinks on both sides so the
# prefix test is comparing like with like. An edit outside this repo is not ours.
FDIR="$(cd "$(dirname "$FILE")" 2>/dev/null && pwd -P)" || exit 0
ABS="$FDIR/$(basename "$FILE")"
case "$ABS" in
  "$ROOT"/*) REL="${ABS#"$ROOT"/}" ;;
  *) exit 0 ;;
esac
[ -f "$REL" ] || exit 0

# Follow a symlinked policy file to its real path before measuring — see
# ctx_resolve_rel for why comparing a symlink against git fabricates growth.
if [ -L "$REL" ]; then
  TARGET="$(ctx_resolve_rel "$ROOT" "$REL")"
  if [ -z "$TARGET" ]; then
    log "skip: $REL is a symlink resolving outside the repo"
    exit 0
  fi
  log "note: $REL is a symlink; measuring $TARGET"
  REL="$TARGET"
  [ -f "$REL" ] || exit 0
fi

# --- is this file part of the context surface? ----------------------------
DOCS_DIR="$(ctx_docs_dir "$ROOT")"

KIND=""
case "$REL" in
  AGENTS.md|CLAUDE.md) KIND="policy" ;;
  # `*` in a case pattern matches `/`, unlike filename globbing — so this one
  # pattern already covers <docs>/a/b/deep.md at any depth.
  "$DOCS_DIR"/*.md) ctx_is_archival "$REL" || KIND="doc" ;;
esac
[ -n "$KIND" ] || exit 0

# --- budget ---------------------------------------------------------------
if [ "$KIND" = "policy" ]; then
  BUDGET="$(ctx_read_num_knob "" "${CONTEXT_BUDGET-}" "$ROOT/.skills/context-budget" 6000)"
else
  BUDGET="$(ctx_read_num_knob "" "${CONTEXT_DOC_BUDGET-}" "$ROOT/.skills/context-doc-budget" 10000)"
fi

# --- measure --------------------------------------------------------------
# Offline by design: a hook must be fast, so it never calls count_tokens. The
# estimate only decides whether to speak; the authoritative count is
# measure-context.sh --exact, which — run over the whole surface, or scoped
# with --calibrate (#263) — also recalibrates the ratio for this repo.
# Read by ctx_est_from_bytes in _context-lib.sh (and by the repo-ratio fallback
# in ctx_est_tokens_for), which shellcheck cannot see across `source` — dropping
# this assignment silently discards the repo's measured calibration and prices
# every estimate at CTX_BPT_DEFAULT_X100 instead.
# shellcheck disable=SC2034
CTX_BPT_X100="$(ctx_bytes_per_token_x100 "$ROOT")"
# Report a broken calibration artifact once, here, rather than once per
# file priced (CR finding 26). Advisory: never changes the exit code.
ctx_validate_counts "$ROOT"
NOW_BYTES="$(LC_ALL=C wc -c <"$REL" 2>/dev/null || echo 0)"

# The committed version is the comparison point, so the advisory reads as "your
# uncommitted changes add N tokens" rather than "this file is big" — which is
# what makes it actionable rather than ambient. A file with no committed version
# compares against 0, so a brand-new over-budget doc is flagged once.
# One call returning both halves: the byte count, and the reason there isn't one.
# Without the reason, "prev=0" on a file that plainly has history is the kind of
# number someone reasonably distrusts.
PREV_OUT="$(ctx_prev_bytes HEAD "$REL")" || PREV_OUT=""
# The delimiter comes from the library that emits it, as $CTX_TAB, rather than
# being typed literally into the expansions below. A literal tab there is
# invisible in review and in most editors, and any tab-to-space conversion would
# silently turn the split into a no-op — PREV_BYTES would take the whole string,
# fail the digit test, and leave PREV at 0, so every edit would look like growth
# from nothing. That is the exact symptom of the symlink bug these lines exist to
# prevent, which is a poor thing to reintroduce by way of whitespace.
PREV_BYTES="${PREV_OUT%%"$CTX_TAB"*}"
PREV_NOTE="${PREV_OUT#*"$CTX_TAB"}"
[ -z "$PREV_NOTE" ] || log "note: $PREV_NOTE"
# Per file, not per repo. One ratio describes well only the file it was derived
# from — which is the policy file — and on this repo the per-file ratio spans
# 2.04 to 3.03 against a 2.65 global, so the same divisor is wrong by -23% to
# +14% depending on which file it is pointed at. Both signs cost something: over
# the budget it flags files that are under it, which trains the reader to ignore
# the guard; under it, the guard is silent on a file that is genuinely over,
# which is the decay it exists to catch (#145).
#
# Both sides in one call, priced by one method — see ctx_est_pair for why a
# calibrated `now` differenced against a global `prev` reports the gap between
# two methods as growth someone wrote.
EST="$(ctx_est_pair "$ROOT" "$REL" "$NOW_BYTES" "$PREV_BYTES")"
NOW="${EST%%"$CTX_TAB"*}"
EST="${EST#*"$CTX_TAB"}"
PREV="${EST%%"$CTX_TAB"*}"
EST_SRC="${EST#*"$CTX_TAB"}"
[ "$NOW" -gt 0 ] || exit 0

# --- decide ---------------------------------------------------------------
# Two conditions must both hold. Over-budget alone would fire on every edit to a
# file that is already over, which trains the reader to ignore the hook; and an
# increase alone would fire on healthy growth inside budget. Notably an edit that
# REDUCES the count is never flagged, so curating is never nagged.
if [ "$NOW" -le "$BUDGET" ] || [ "$NOW" -le "$PREV" ]; then
  log "ok: $REL now=${NOW} prev=${PREV} budget=${BUDGET} ($KIND, est=${EST_SRC})"
  exit 0
fi

DELTA=$(( NOW - PREV ))
OVER=$(( NOW - BUDGET ))
log "WARN: $REL now=${NOW} prev=${PREV} (+${DELTA}) budget=${BUDGET} over=${OVER} ($KIND, est=${EST_SRC})"

if [ "$KIND" = "policy" ]; then
  ADVICE="This file is loaded on every invocation, so the cost is paid on every task. Move the addition to a docs/ reference doc and link it from the Detail Docs index, or run the curating-context skill to rebalance."
else
  ADVICE="A reference doc past its budget costs more to load than it saves. Split it on its top-level headings, or run the curating-context skill."
fi

# "since HEAD", not "this edit": the comparison point is the committed version, so
# the number covers every uncommitted change to the file. Saying "this edit" would
# overstate a single edit's contribution once several have accumulated.
MSG="context budget: $REL is now ~${NOW} tokens, ${OVER} over the ${BUDGET} budget (+${DELTA} since HEAD)."

# Emit the advisory. additionalContext reaches the agent so it can act in this
# same turn; systemMessage reaches the human. Exit 0 keeps it an advisory.
if command -v python3 >/dev/null 2>&1; then
  python3 -c '
import json, sys
msg, advice = sys.argv[1], sys.argv[2]
print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": msg + " " + advice,
    },
}))
' "$MSG" "$ADVICE" 2>/dev/null || true
elif command -v jq >/dev/null 2>&1; then
  jq -nc --arg m "$MSG" --arg a "$ADVICE" '{
    systemMessage: $m,
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: ($m + " " + $a)
    }
  }' 2>/dev/null || true
fi

exit 0
