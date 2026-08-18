#!/usr/bin/env bash
# resolve-worktree-root.sh
# Prints the resolved worktree root for the current repo on stdout.
# Resolution order: WORKTREE_ROOT env var → .skills/worktree_root file → <repo>/.worktrees/
#
# Usage: bash <SKILL_SCRIPTS>/resolve-worktree-root.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints the resolved worktree root for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. WORKTREE_ROOT env var"
  echo "  2. .skills/worktree_root file under the repo root (single-line path)"
  echo "  3. <repo-root>/.worktrees/ (fallback)"
  echo ""
  echo "<repo-root> is the PRIMARY checkout, not whichever worktree you are"
  echo "standing in — so worktrees created from inside a worktree are siblings."
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

# Everything below needs the PROJECT root, so it runs only once the env var has
# had its say — an explicit WORKTREE_ROOT answers without two extra git calls.
#
# --show-toplevel answers with the CURRENT checkout, so run from inside a
# linked worktree it returns the worktree — and the fallback root below became
# <worktree>/.worktrees, one level deeper per generation. It also relocates the
# .skills/worktree_root lookup to a checkout where that untracked knob does not
# exist, so a configured root was silently ignored rather than merely nested.
#
# --git-common-dir is the SHARED .git from either vantage point, and its parent
# is the primary checkout. A script that must talk about "the project" cannot
# ask the current checkout.
#
# Two traps, both load-bearing:
#   * The path is relative to $PWD in the primary checkout ('.git', '../../.git'
#     from a subdirectory) and absolute in a linked worktree. Absolutize before
#     taking the parent, and absolutize both sides before comparing them.
#   * Inside a submodule the common dir is <super>/.git/modules/<name>, whose
#     parent is not a work tree at all — taking it would put worktrees inside
#     .git. The submodule's own --show-toplevel is already right, so the
#     candidate is accepted only if it is a checkout sharing this common dir.
COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null || true)
if [[ -n "$COMMON_DIR" ]] && COMMON_DIR=$(cd "$COMMON_DIR" 2>/dev/null && pwd -P); then
  CANDIDATE=$(dirname "$COMMON_DIR")
  # `git -C "$CANDIDATE"` answers relative to CANDIDATE, not to our $PWD.
  CANDIDATE_COMMON=$(git -C "$CANDIDATE" rev-parse --git-common-dir 2>/dev/null || true)
  if [[ -n "$CANDIDATE_COMMON" ]] &&
     CANDIDATE_COMMON=$(cd "$CANDIDATE" && cd "$CANDIDATE_COMMON" 2>/dev/null && pwd -P) &&
     [[ "$CANDIDATE_COMMON" == "$COMMON_DIR" ]]; then
    PROJECT_ROOT="$CANDIDATE"
  fi
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
