#!/usr/bin/env bash
# check-status.sh
# Reports working tree state. Exits 0 if clean, 1 if there are uncommitted
# changes, 2 if git could not tell us which (#257).
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash <SKILL_SCRIPTS>/check-status.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Reports branch, working tree status, and recent commits."
  echo "Automatically resolves the git project root regardless of invocation directory."
  echo ""
  echo "Exit codes:"
  echo "  0  the working tree is clean"
  echo "  1  uncommitted changes are present"
  echo "  2  the tree state could not be determined (git status failed) — not"
  echo "     the same as clean, and the ship must not proceed on it"
  exit 0
fi

# Intentional silent fallback: outside a git checkout there is no toplevel, so
# run against the current directory — every git command below then fails on its
# own terms rather than this line inventing a project root.
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Branch ==="
git branch --show-current

echo ""
echo "=== Status ==="
git status --short

echo ""
echo "=== Recent commits ==="
git log --oneline -5

# Scalar capture with the exit code, not `[ -n "$(git status --porcelain)" ]`:
# a failing git substitutes the empty string, which is exactly what a CLEAN
# tree substitutes to, so the two states were indistinguishable and the script
# picked the reassuring one (#257). The asymmetry that hid it: `set -e` aborts
# on the three reporting commands above — a failing simple command is not in a
# condition context — but is exempt inside `if [ -n "$(...)" ]`, so the only
# line whose answer is a ship/skip decision was the only one failing silently.
#
# git's stderr is deliberately NOT redirected: this is the `DIFF_RC` form
# doc-check.sh uses (docs/STYLE.md, "Gate-script discipline"), and the operator
# needs to read what git said.
STATUS_RC=0
PORCELAIN=$(git status --porcelain) || STATUS_RC=$?
if [ "$STATUS_RC" -ne 0 ]; then
  echo "" >&2
  echo "ERROR: git status --porcelain failed (exit $STATUS_RC) — the working" >&2
  echo "       tree state is UNKNOWN, which is not the same as clean. See" >&2
  echo "       git's message above; do not proceed with the ship." >&2
  exit 2
fi

if [ -n "$PORCELAIN" ]; then
  echo ""
  echo "UNCOMMITTED CHANGES DETECTED"
  exit 1
fi

echo ""
echo "Working tree is clean."
