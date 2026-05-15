#!/usr/bin/env bash
# resolve-worktree-root.sh
# Prints the resolved worktree root for the current repo on stdout.
# Resolution order: WORKTREE_ROOT env var → .skills/worktree_root file → <repo>/.worktrees/
#
# Usage: bash scripts/resolve-worktree-root.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/resolve-worktree-root.sh"
  echo ""
  echo "Prints the resolved worktree root for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. WORKTREE_ROOT env var"
  echo "  2. .skills/worktree_root file under the repo root (single-line path)"
  echo "  3. <repo-root>/.worktrees/ (fallback)"
  echo ""
  echo "Exit codes:"
  echo "  0  Resolution succeeded"
  echo "  2  Not inside a git repository"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}

if [[ -n "${WORKTREE_ROOT:-}" ]]; then
  echo "$WORKTREE_ROOT"
  exit 0
fi

CONFIG_FILE="$PROJECT_ROOT/.skills/worktree_root"
if [[ -f "$CONFIG_FILE" ]]; then
  # Read first non-blank, non-comment line. Trim leading/trailing whitespace.
  # `|| true` keeps pipefail from aborting when the file is empty or all
  # comments — that case must fall through to the default, not crash.
  CONFIGURED=$(grep -v '^[[:space:]]*#' "$CONFIG_FILE" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  if [[ -n "$CONFIGURED" ]]; then
    echo "$CONFIGURED"
    exit 0
  fi
fi

echo "$PROJECT_ROOT/.worktrees"
