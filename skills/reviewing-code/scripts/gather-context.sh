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
for _cc in "skills/curating-context/scripts" \
           ".claude/skills/curating-context/scripts" \
           "$HOME/.claude/skills/curating-context/scripts"; do
  if [ -f "$_cc/context-delta.sh" ]; then
    bash "$_cc/context-delta.sh" || true
    break
  fi
done
