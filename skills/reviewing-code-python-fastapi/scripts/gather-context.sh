#!/usr/bin/env bash
# gather-context.sh (Python/FastAPI variant)
# Prints a structured summary of current repo state for use during code review.
# Runs ruff informationally — lint failures become Phase 3 findings, not
# gather-context errors. Does NOT run pytest; full-suite runs belong in
# pre-ship.sh, not in review-time context gathering.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, changed files,"
  echo "then runs 'uv run ruff check .' informationally. Does not run pytest."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Branch ==="
git branch --show-current 2>/dev/null || true

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

# --- Informational lint ------------------------------------------------------
# Failures here are NOT gather-context errors — they become Phase 3 findings.
# The `|| true` is deliberate: we want the output, not a script abort.

echo ""
echo "=== ruff check (informational) ==="
if command -v uv >/dev/null 2>&1; then
  uv run ruff check . 2>&1 || true
else
  echo "uv not installed; skipping ruff. (uv is required by this variant.)"
fi

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
