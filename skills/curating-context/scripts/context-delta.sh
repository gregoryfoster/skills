#!/usr/bin/env bash
# context-delta.sh — report the context-budget impact of the current diff.
#
# Designed to be called from a reviewing-* skill's gather-context.sh so the token
# cost of a branch is visible at review time, when the tradeoff is still cheap to
# negotiate. Prints nothing when the diff touches no context-surface file, so it
# never adds noise to an ordinary code review.
#
# Informational only. Exits 0 on every path — a context budget is not a review
# gate, and a review that failed on one would be a gate wearing a report's
# clothes. The gate belongs in enforcing-architecture.
set -euo pipefail

usage() {
  cat <<'USAGE'
context-delta.sh — context-budget impact of the current diff

Usage:
  context-delta.sh [options]

Options:
  --base REF     Compare against REF instead of HEAD.
  --budget N     Policy-file budget. Default: CONTEXT_BUDGET, then
                 .skills/context-budget, then 6000.
  --doc-budget N Per-reference-doc budget. Default: CONTEXT_DOC_BUDGET, then
                 .skills/context-doc-budget, then 10000.
  --quiet        Print only when something is over budget or growing.
  -h, --help     Show this help and exit 0.

Scope — the agent-context surface:
  - AGENTS.md / CLAUDE.md at the repo root (cost paid on every invocation). A
    symlinked CLAUDE.md is followed to its target and reported once.
  - <docs-dir>/**/*.md, excluding archival subtrees (plans, specs, research,
    audits, archive) at any depth. The root is CONTEXT_DOCS_DIR, then
    .skills/context-docs-dir, then docs.

Why this differs from the write-guard hook: the hook sees one edit at a time and
cannot tell a 400-token addition that replaced 600 tokens elsewhere from a
straight 400-token gain. This sees the whole branch.

Tokens are estimated offline at ~2.7 bytes/token (see the note by
BYTES_PER_TOKEN_X100), the same estimate the write guard uses. Enough to decide
whether a section belongs in docs/; run measure-context.sh --exact for an
authoritative count, which also recalibrates the ratio for this repo.

Exit codes:
  0  always (informational)
USAGE
}

BASE="HEAD"
BUDGET_OVERRIDE=""
DOC_BUDGET_OVERRIDE=""
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a ref}"; shift 2 ;;
    --budget) BUDGET_OVERRIDE="${2:?--budget needs a number}"; shift 2 ;;
    --doc-budget) DOC_BUDGET_OVERRIDE="${2:?--doc-budget needs a number}"; shift 2 ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "context-delta: ignoring unknown argument: $1" >&2; shift ;;
  esac
done

# Informational contract: never fail a review because this could not run. TMP is
# created immediately so a single trap covers cleanup and the exit-0 guarantee —
# installing 'exit 0' here and replacing it with the combined handler after
# mktemp would leave a window in which a failure exits non-zero, and this script
# is called from four gather-context.sh files that must not fail.
TMP="$(mktemp -d 2>/dev/null)" || { trap 'exit 0' EXIT; exit 0; }
trap 'rm -rf "$TMP"; exit 0' EXIT

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
ROOT="$(cd "$ROOT" 2>/dev/null && pwd -P)" || exit 0
cd "$ROOT" 2>/dev/null || exit 0

# --- shared library -------------------------------------------------------
# Resolve through a symlink chain: this script may be reached through a symlinked
# vendor tree, and ${BASH_SOURCE[0]}'s dirname would then hold no library.
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
  echo "context-delta: _context-lib.sh not found next to $_self; skipping" >&2
  exit 0
fi
# shellcheck source=_context-lib.sh
. "$_libdir/_context-lib.sh"

BUDGET="$(ctx_read_num_knob "$BUDGET_OVERRIDE" "${CONTEXT_BUDGET-}" "$ROOT/.skills/context-budget" 6000)"
DOC_BUDGET="$(ctx_read_num_knob "$DOC_BUDGET_OVERRIDE" "${CONTEXT_DOC_BUDGET-}" "$ROOT/.skills/context-doc-budget" 10000)"

# Offline by design, same estimate the write guard uses — enough to decide
# whether a section belongs in docs/. measure-context.sh --exact is the
# authoritative count, and also recalibrates the ratio for this repo.
CTX_BPT_X100="$(ctx_bytes_per_token_x100 "$ROOT")"
DOCS_DIR="$(ctx_docs_dir "$ROOT")"

# Changed files vs BASE, staged and unstaged, plus untracked. Deleted paths are
# included on purpose: removing a doc changes the surface too. Untracked files
# matter as much as modified ones here — a brand-new docs/API.md is the single
# most common way a branch adds to the surface, and `git diff` never lists it.
{ git diff --name-only "$BASE" 2>/dev/null || true
  git diff --name-only --staged "$BASE" 2>/dev/null || true
  git ls-files --others --exclude-standard 2>/dev/null || true
} | sort -u >"$TMP/changed"

# Classify and follow symlinks first, then dedupe: a branch touching both
# AGENTS.md and a CLAUDE.md that points at it must produce one row, not two.
: >"$TMP/surface"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  kind=""
  case "$f" in
    AGENTS.md|CLAUDE.md) kind="policy" ;;
    "$DOCS_DIR"/*.md) ctx_is_archival "$f" || kind="doc" ;;
  esac
  [ -n "$kind" ] || continue
  if [ -L "$f" ]; then
    t="$(ctx_resolve_rel "$ROOT" "$f")"
    [ -n "$t" ] || continue
    f="$t"
  fi
  printf '%s\t%s\n' "$kind" "$f" >>"$TMP/surface"
done <"$TMP/changed"
sort -u "$TMP/surface" >"$TMP/surface.u"

: >"$TMP/rows"
while IFS="$(printf '\t')" read -r kind f; do
  [ -n "$f" ] || continue
  now=0
  [ -f "$f" ] && now=$(ctx_est_from_bytes "$(LC_ALL=C wc -c <"$f" 2>/dev/null || echo 0)")
  prev=0
  pb="$(ctx_prev_bytes "$BASE" "$f")" || pb=""
  case "$pb" in
    ''|*[!0-9]*) prev=0 ;;
    *) prev=$(ctx_est_from_bytes "$pb") ;;
  esac

  if [ "$kind" = "policy" ]; then b="$BUDGET"; else b="$DOC_BUDGET"; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$kind" "$f" "$now" "$prev" "$b" >>"$TMP/rows"
done <"$TMP/surface.u"

[ -s "$TMP/rows" ] || exit 0

# In --quiet mode, say nothing unless something is over budget or growing.
if [ "$QUIET" -eq 1 ]; then
  worth_saying=0
  while IFS="$(printf '\t')" read -r kind f now prev b; do
    if [ "$now" -gt "$b" ] || [ "$now" -gt "$prev" ]; then worth_saying=1; break; fi
  done <"$TMP/rows"
  [ "$worth_saying" -eq 1 ] || exit 0
fi

echo ""
echo "=== Context budget (informational — not a gate) ==="
printf '%-34s %9s %9s %9s  %s\n' "file" "tokens" "delta" "budget" "status"

flagged=0
while IFS="$(printf '\t')" read -r kind f now prev b; do
  delta=$(( now - prev ))
  if [ "$now" -eq 0 ]; then
    status="deleted (freed $prev)"
  elif [ "$now" -gt "$b" ]; then
    status="OVER by $(( now - b ))"
    flagged=1
  else
    status="ok ($(( b - now )) headroom)"
  fi
  # printf %+d needs a signed integer; 0 renders as +0, which reads fine.
  printf '%-34s %9s %+9d %9s  %s\n' "$f" "$now" "$delta" "$b" "$status"
done <"$TMP/rows"

if [ "$flagged" -eq 1 ]; then
  cat <<'NOTE'

An over-budget policy file is paid on every invocation. If this branch added to
it, consider whether the addition belongs in a docs/ reference doc linked from
the Detail Docs index — the curating-context skill does that classification.
NOTE
fi

echo ""
echo "(offline estimate. For an authoritative count and a full section census,"
echo " run curating-context's measure-context.sh --exact.)"
