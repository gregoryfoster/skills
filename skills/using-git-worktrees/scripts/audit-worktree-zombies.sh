#!/usr/bin/env bash
# audit-worktree-zombies.sh — list processes referencing destroyed worktrees.
# Exits non-zero if zombies are found, so it can be wired into pre-flight checks.
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--quiet]"
  echo ""
  echo "Lists processes whose cmdline references a path under the resolved"
  echo "worktree root that no longer exists on disk. Detection-only — does"
  echo "not kill anything."
  echo ""
  echo "Searches for zombies under the resolved worktree root (env WORKTREE_ROOT"
  echo "→ .skills/worktree_root → <repo>/.worktrees/, in that order)."
  echo ""
  echo "Exit codes:"
  echo "  0  No zombies found"
  echo "  1  Zombies found (printed to stdout)"
  echo "  2  Tooling/infra failure (not a git repo, unknown flag)"
}

# Argument errors print one line, not the whole usage block — the rule the rest
# of this directory adopted in #262, so a diagnosis is not buried under
# boilerplate that a `| tail` would show instead.
usage_hint() {
  echo "Usage: bash \"$0\" [--quiet]   (run with --help for the full description)"
}

# Scan every argument for --help before the loop runs. Handling it inside the
# loop covered `--quiet --help` but not `stray --help`, where the bare word hit
# the error arm first — so a help request could still be answered with an
# error. This is the convention worktree-list.sh states in its own preamble
# and the one create/destroy adopted in #262.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    usage
    exit 0
  fi
done

# This script takes no positional arguments, so a bare word is an unexpected
# argument, not an "unknown flag" — the same misdiagnosis #262 removed from
# worktree-destroy.sh, where the branch name was reported as a flag.
QUIET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet) QUIET=1; shift ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      usage_hint >&2
      exit 2
      ;;
    *)
      echo "ERROR: unexpected argument '$1' (this script takes no positional arguments)" >&2
      usage_hint >&2
      exit 2
      ;;
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
    # $0, not a hardcoded path: under vendoring the script lives at
    # skills-vendor/<owner>-<repo>/skills/using-git-worktrees/scripts/, where a
    # hardcoded prefix names a file that does not exist. $0 is whatever the
    # caller actually invoked, so the recipe is copy-pasteable as printed.
    echo "Kill all: bash \"$0\" | awk '/^  [0-9]/ {print \$1}' | xargs kill"
  fi
  exit 1
fi

(( QUIET == 1 )) || echo "No worktree zombies."
