#!/usr/bin/env bash
# audit-worktree-zombies.sh — list processes referencing destroyed worktrees.
# Exits non-zero if zombies are found, so it can be wired into pre-flight checks.
#
# Limitation: assumes worktrees live under <project-root>/.worktrees/. Projects
# using a custom WORKTREE_ROOT or .skills/worktree_root path won't be audited
# by this script as written. (Future enhancement: source resolve-worktree-root.sh
# and match against the resolved root.)
set -euo pipefail

usage() {
  echo "Usage: bash scripts/audit-worktree-zombies.sh [--quiet]"
  echo ""
  echo "Lists processes whose cmdline references a .worktrees/<name>/ path that"
  echo "no longer exists on disk. Detection-only — does not kill anything."
  echo ""
  echo "Exit codes:"
  echo "  0  No zombies found"
  echo "  1  Zombies found (printed to stdout)"
  echo "  2  Tooling/infra failure (not a git repo)"
}

QUIET=0
[[ "${1:-}" == "--help" ]] && { usage; exit 0; }
[[ "${1:-}" == "--quiet" ]] && QUIET=1

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}

ZOMBIES=()
while IFS= read -r line; do
  PID=$(awk '{print $1}' <<<"$line")
  CMD=$(awk '{$1=""; print substr($0,2)}' <<<"$line")
  WT_PATH=$(grep -oE '\.worktrees/[^/ ]+' <<<"$CMD" | head -1 || true)
  [[ -z "$WT_PATH" ]] && continue
  [[ -d "$PROJECT_ROOT/$WT_PATH" ]] && continue
  ZOMBIES+=("$PID $CMD")
done < <(pgrep -af '\.worktrees/' || true)

if (( ${#ZOMBIES[@]} > 0 )); then
  if (( QUIET == 0 )); then
    printf 'Worktree zombie processes detected (%d):\n' "${#ZOMBIES[@]}"
    printf '  %s\n' "${ZOMBIES[@]}"
    echo ""
    echo "Kill all: bash scripts/audit-worktree-zombies.sh | awk '/^  [0-9]/ {print \$1}' | xargs -r kill"
  fi
  exit 1
fi

(( QUIET == 1 )) || echo "No worktree zombies."
