#!/usr/bin/env bash
# gather-context.sh (Python/FastAPI variant)
# Prints a structured summary of current repo state for use during code review.
# Runs ruff informationally — lint failures become Phase 3 findings, not
# gather-context errors. Does NOT run pytest; full-suite runs belong in
# pre-ship.sh, not in review-time context gathering.
#
# Usage: bash scripts/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/gather-context.sh"
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
