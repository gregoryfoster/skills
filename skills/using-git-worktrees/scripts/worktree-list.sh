#!/usr/bin/env bash
# worktree-list.sh
# Lists all worktrees for the current repo. Thin wrapper around `git worktree list`
# that ensures consistent invocation regardless of caller's working directory.
#
# Usage: bash <SKILL_SCRIPTS>/worktree-list.sh [--porcelain] [--help]
set -euo pipefail

# Scan all args for --help first so any combination (e.g. `--porcelain --help`)
# still prints help rather than running the command.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    echo "Usage: bash \"$0\" [--porcelain]"
    echo ""
    echo "Lists all worktrees for the current repo. First row is always the main checkout."
    echo ""
    echo "Options:"
    echo "  --porcelain   Machine-readable output (one key per line, blank-line-separated records)"
    echo ""
    echo "Exit codes:"
    echo "  0  Success"
    echo "  2  Not inside a git repository, or an unrecognised argument"
    exit 0
  fi
done

# Reject what we do not understand rather than ignoring it. The previous scan
# set PORCELAIN if it saw --porcelain and dropped every other argument in
# silence, so `worktree-list.sh --porcelian` (typo) printed human-readable
# output and exited 0 — a caller parsing porcelain keys got none and could not
# tell why. That is the same silent-drop class as #262, and it is the third of
# the four conventions this directory used to carry.
#
# This script takes no positional arguments at all, so a bare word is reported
# as an unexpected argument rather than as an "unknown flag" it plainly is not.
PORCELAIN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --porcelain)
      PORCELAIN=1
      shift
      ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      echo "Usage: bash \"$0\" [--porcelain]   (run with --help for the full description)" >&2
      exit 2
      ;;
    *)
      echo "ERROR: unexpected argument '$1' (this script takes no positional arguments)" >&2
      echo "Usage: bash \"$0\" [--porcelain]   (run with --help for the full description)" >&2
      exit 2
      ;;
  esac
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
