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
  echo "  2  Tooling/infra failure (not a git repo, unknown flag)"
}

QUIET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help) usage; exit 0 ;;
    --quiet) QUIET=1; shift ;;
    *) echo "ERROR: unknown flag '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}

# Scope all matching to THIS project's worktree root. Without this, processes
# referencing other projects' .worktrees/ paths on the same machine would be
# flagged as zombies of this project — a false positive that could lead an
# operator to kill a live process belonging to a different repo.
# Escape regex metacharacters in PROJECT_ROOT for the grep/pgrep patterns.
ESC_ROOT=$(printf '%s\n' "$PROJECT_ROOT" | sed 's/[][\\.*^$/()+?{|}]/\\&/g')

ZOMBIES=()
while IFS= read -r line; do
  PID=$(awk '{print $1}' <<<"$line")
  CMD=$(awk '{$1=""; print substr($0,2)}' <<<"$line")
  WT_PATH=$(grep -oE "$ESC_ROOT/\.worktrees/[^/ ]+" <<<"$CMD" | head -1 || true)
  [[ -z "$WT_PATH" ]] && continue
  [[ -d "$WT_PATH" ]] && continue
  ZOMBIES+=("$PID $CMD")
done < <(pgrep -af "$ESC_ROOT/\.worktrees/" 2>/dev/null || true)

if (( ${#ZOMBIES[@]} > 0 )); then
  if (( QUIET == 0 )); then
    printf 'Worktree zombie processes detected (%d):\n' "${#ZOMBIES[@]}"
    printf '  %s\n' "${ZOMBIES[@]}"
    echo ""
    echo "Kill all: bash scripts/audit-worktree-zombies.sh | awk '/^  [0-9]/ {print \$1}' | xargs kill"
  fi
  exit 1
fi

(( QUIET == 1 )) || echo "No worktree zombies."
