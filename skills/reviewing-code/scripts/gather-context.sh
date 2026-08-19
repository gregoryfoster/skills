#!/usr/bin/env bash
# gather-context.sh
# Prints a structured summary of current repo state for use during code review.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, and changed files."
  echo "Automatically resolves the git project root regardless of invocation directory."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Git status ==="
git status --short

echo ""
echo "=== Staged diff ==="
git diff --staged --stat 2>/dev/null || true

echo ""
echo "=== Unstaged diff ==="
git diff --stat 2>/dev/null || true

echo ""
echo "=== Recent commits ==="
git log --oneline -10 2>/dev/null || true

echo ""
echo "=== Changed files (working tree vs HEAD) ==="
git diff --name-only HEAD 2>/dev/null || true
git diff --name-only --staged HEAD 2>/dev/null || true

# --- Context-budget delta (informational) ------------------------------------
# Delegates to curating-context so the measurement logic lives in one place.
# Silent when that skill isn't vendored here, and never fails this script: a
# context budget is a review signal, not a review gate.
#
# --base is a MERGE BASE, not the default HEAD. A review whose changes are
# already committed — a batch branch, a PR branch, anything but a dirty tree —
# diffs empty against HEAD, so the budget block never printed on exactly the
# reviews that most need it: one batch branch added ~150 tokens to AGENTS.md
# across two agents and this stayed silent through three review rounds. Third
# sighting of the `--base HEAD` default reading as "nothing changed" (#169 was
# the cadence's).
#
# Falls back to HEAD when there is no upstream and no main/master — a detached
# checkout, a repo whose default branch is named something else — which is the
# old behaviour and still correct for reviewing a dirty tree.
_cd_base=""
for _ref in "@{upstream}" main master; do
  _cd_base=$(git merge-base HEAD "$_ref" 2>/dev/null) && [ -n "$_cd_base" ] && break
  _cd_base=""
done
[ -n "$_cd_base" ] || _cd_base=HEAD
for _cc in "skills/curating-context/scripts" \
           ".claude/skills/curating-context/scripts" \
           "$HOME/.claude/skills/curating-context/scripts"; do
  if [ -f "$_cc/context-delta.sh" ]; then
    bash "$_cc/context-delta.sh" --base "$_cd_base" || true
    break
  fi
done
