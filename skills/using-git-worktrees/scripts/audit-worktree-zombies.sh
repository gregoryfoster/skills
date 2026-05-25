#!/usr/bin/env bash
# audit-worktree-zombies.sh — list processes referencing destroyed worktrees.
# Exits non-zero if zombies are found, so it can be wired into pre-flight checks.
set -euo pipefail

usage() {
  echo "Usage: bash skills/using-git-worktrees/scripts/audit-worktree-zombies.sh [--quiet]"
  echo ""
  echo "Lists processes whose cmdline references a path under the resolved"
  echo "worktree root that no longer exists on disk. Detection-only — does"
  echo "not kill anything."
  echo ""
  echo "Searches for zombies under the resolved worktree root (env WORKTREE_ROOT"
  echo "→ .skills/worktree_root → <repo>/.worktrees/, in that order)."
  echo ""
  echo "Adjust the path prefix when the skill is vendored under a different"
  echo "layout (e.g. skills-vendor/<owner>-<repo>/skills/using-git-worktrees/...)."
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE_ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}
# resolve-worktree-root.sh already verifies we're inside a git repo (exits 2
# otherwise), so no separate `git rev-parse --show-toplevel` sentinel is needed.

# Trim any trailing slash so the pgrep/grep patterns don't produce `//` when
# WORKTREE_ROOT is set via env with a conventional trailing slash. Without
# this, `WORKTREE_ROOT=/custom/wt/` produces pattern `/custom/wt//` which
# won't match real cmdlines — silent false negatives.
WORKTREE_ROOT="${WORKTREE_ROOT%/}"

# Scope all matching to the project's RESOLVED worktree root, which may be the
# default <repo>/.worktrees/ or a custom location set via WORKTREE_ROOT env var
# or .skills/worktree_root file. Without this scoping, processes referencing
# other projects' worktree paths on the same machine would be falsely flagged
# as zombies of this project.
# Escape regex metacharacters for the grep/pgrep patterns.
ESC_WORKTREE_ROOT=$(printf '%s\n' "$WORKTREE_ROOT" | sed 's/[][\\.*^$/()+?{|}]/\\&/g')

ZOMBIES=()
while IFS= read -r line; do
  PID=$(awk '{print $1}' <<<"$line")
  CMD=$(awk '{$1=""; print substr($0,2)}' <<<"$line")
  # The pgrep filter guarantees $CMD contains at least one match for
  # "$ESC_WORKTREE_ROOT/<name>", so this extraction is the SECOND-pass
  # step: it isolates which specific worktree this process belongs to,
  # so we can check whether that worktree's directory still exists.
  WT_PATH=$(grep -oE "$ESC_WORKTREE_ROOT/[^/ ]+" <<<"$CMD" | head -1 || true)
  [[ -z "$WT_PATH" ]] && continue
  [[ -d "$WT_PATH" ]] && continue
  ZOMBIES+=("$PID $CMD")
done < <(pgrep -af "$ESC_WORKTREE_ROOT/" 2>/dev/null || true)

if (( ${#ZOMBIES[@]} > 0 )); then
  if (( QUIET == 0 )); then
    printf 'Worktree zombie processes detected (%d):\n' "${#ZOMBIES[@]}"
    printf '  %s\n' "${ZOMBIES[@]}"
    echo ""
    echo "Kill all: bash skills/using-git-worktrees/scripts/audit-worktree-zombies.sh | awk '/^  [0-9]/ {print \$1}' | xargs kill"
  fi
  exit 1
fi

(( QUIET == 1 )) || echo "No worktree zombies."
