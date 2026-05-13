#!/usr/bin/env bash
# gather-context.sh
# Prints a structured summary of current repo state for use during code review.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash scripts/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/gather-context.sh"
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
