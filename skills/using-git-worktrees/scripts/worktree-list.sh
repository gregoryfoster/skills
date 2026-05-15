#!/usr/bin/env bash
# worktree-list.sh
# Lists all worktrees for the current repo. Thin wrapper around `git worktree list`
# that ensures consistent invocation regardless of caller's working directory.
#
# Usage: bash scripts/worktree-list.sh [--porcelain] [--help]
set -euo pipefail

# Scan all args for --help first so any combination (e.g. `--porcelain --help`)
# still prints help rather than running the command.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    echo "Usage: bash scripts/worktree-list.sh [--porcelain]"
    echo ""
    echo "Lists all worktrees for the current repo. First row is always the main checkout."
    echo ""
    echo "Options:"
    echo "  --porcelain   Machine-readable output (one key per line, blank-line-separated records)"
    echo ""
    echo "Exit codes:"
    echo "  0  Success"
    echo "  2  Not inside a git repository"
    exit 0
  fi
done

PORCELAIN=0
for arg in "$@"; do
  if [[ "$arg" == "--porcelain" ]]; then
    PORCELAIN=1
  fi
done

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

if [[ $PORCELAIN -eq 1 ]]; then
  git worktree list --porcelain
else
  git worktree list
fi
