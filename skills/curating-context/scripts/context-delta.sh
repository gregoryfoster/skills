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
                 .skills/context-budget, then 4000.
  --doc-budget N Per-reference-doc budget. Default: CONTEXT_DOC_BUDGET, then
                 .skills/context-doc-budget, then 10000.
  --quiet        Print only when something is over budget or growing.
  -h, --help     Show this help and exit 0.

Scope — the agent-context surface:
  - AGENTS.md / CLAUDE.md at the repo root (cost paid on every invocation)
  - docs/**/*.md, excluding archival subtrees (plans, specs, research, audits,
    archive) at any depth

Why this differs from the write-guard hook: the hook sees one edit at a time and
cannot tell a 400-token addition that replaced 600 tokens elsewhere from a
straight 400-token gain. This sees the whole branch.

Tokens are estimated as bytes/4 — the same estimate the guard uses, and enough to
decide whether a section belongs in docs/. Run measure-context.sh --exact for an
authoritative count.

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

# Informational contract: never fail a review because this could not run.
trap 'exit 0' EXIT

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
ROOT="$(cd "$ROOT" 2>/dev/null && pwd -P)" || exit 0
cd "$ROOT" 2>/dev/null || exit 0

read_knob() {
  local override="$1" envval="$2" file="$3" fallback="$4" v=""
  if [ -n "$override" ]; then v="$override"
  elif [ -n "$envval" ]; then v="$envval"
  elif [ -f "$file" ]; then v="$(head -1 "$file" 2>/dev/null | tr -dc '0-9')"; fi
  case "$v" in
    ''|*[!0-9]*) printf '%s' "$fallback" ;;
    *) printf '%s' "$v" ;;
  esac
}
BUDGET="$(read_knob "$BUDGET_OVERRIDE" "${CONTEXT_BUDGET-}" "$ROOT/.skills/context-budget" 4000)"
DOC_BUDGET="$(read_knob "$DOC_BUDGET_OVERRIDE" "${CONTEXT_DOC_BUDGET-}" "$ROOT/.skills/context-doc-budget" 10000)"

ARCHIVAL="plans specs research audits archive"
is_archival() {
  local name
  for name in $ARCHIVAL; do
    case "/$1/" in */"$name"/*) return 0 ;; esac
  done
  return 1
}

TMP="$(mktemp -d)" || exit 0
# Two traps would replace each other, so the cleanup and the exit-0 contract
# share one handler.
trap 'rm -rf "$TMP"; exit 0' EXIT

# Changed files vs BASE, staged and unstaged, plus untracked. Deleted paths are
# included on purpose: removing a doc changes the surface too. Untracked files
# matter as much as modified ones here — a brand-new docs/API.md is the single
# most common way a branch adds to the surface, and `git diff` never lists it.
{ git diff --name-only "$BASE" 2>/dev/null || true
  git diff --name-only --staged "$BASE" 2>/dev/null || true
  git ls-files --others --exclude-standard 2>/dev/null || true
} | sort -u >"$TMP/changed"

: >"$TMP/rows"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  kind=""
  case "$f" in
    AGENTS.md|CLAUDE.md) kind="policy" ;;
    docs/*.md) is_archival "$f" || kind="doc" ;;
  esac
  [ -n "$kind" ] || continue

  now=0
  [ -f "$f" ] && now=$(( $(LC_ALL=C wc -c <"$f" 2>/dev/null || echo 0) / 4 ))
  prev=0
  pb="$(git show "$BASE:$f" 2>/dev/null | LC_ALL=C wc -c 2>/dev/null | tr -d ' ')" || pb=""
  case "$pb" in
    ''|*[!0-9]*) prev=0 ;;
    *) prev=$(( pb / 4 )) ;;
  esac

  if [ "$kind" = "policy" ]; then b="$BUDGET"; else b="$DOC_BUDGET"; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$kind" "$f" "$now" "$prev" "$b" >>"$TMP/rows"
done <"$TMP/changed"

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
echo "(estimate: bytes/4. For an authoritative count and a full section census,"
echo " run curating-context's measure-context.sh --exact.)"
