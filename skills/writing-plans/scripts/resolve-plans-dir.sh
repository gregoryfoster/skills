#!/usr/bin/env bash
# resolve-plans-dir.sh
# Prints the resolved plans directory for the current repo on stdout.
# Resolution order: PLANS_DIR env var → .skills/plans_dir file → <repo>/docs/plans/
#
# Usage: bash <SKILL_SCRIPTS>/resolve-plans-dir.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints the resolved plans directory for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. PLANS_DIR env var"
  echo "  2. .skills/plans_dir file under the repo root (single-line path)"
  echo "  3. <repo-root>/docs/plans/ (fallback)"
  echo ""
  echo "<repo-root> is the PRIMARY checkout, not whichever worktree you are"
  echo "standing in — so a project's configured plans directory is found from"
  echo "a linked worktree too, where that untracked knob does not exist."
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

if [[ -n "${PLANS_DIR:-}" ]]; then
  echo "$PLANS_DIR"
  exit 0
fi

# Everything below needs the PROJECT root, so it runs only once the env var has
# had its say — an explicit PLANS_DIR answers without two extra git calls.
#
# --show-toplevel answers with the CURRENT checkout, so run from inside a
# linked worktree it returns the worktree, and plans were filed under
# <worktree>/docs/plans instead of the project's. It also relocates the
# .skills/plans_dir lookup to a checkout where that untracked knob does not
# exist, so a configured directory was silently ignored rather than merely
# mis-rooted — a wrong path is visible, an ignored configuration is not.
#
# --git-common-dir is the SHARED .git from either vantage point, and its parent
# is the primary checkout. A script that must talk about "the project" cannot
# ask the current checkout. Third instance of the rule (#180, #188, #202).
#
# Two traps, both load-bearing:
#   * The path is relative to $PWD in the primary checkout ('.git', '../../.git'
#     from a subdirectory) and absolute in a linked worktree. Absolutize before
#     taking the parent, and absolutize both sides before comparing them.
#   * Inside a submodule the common dir is <super>/.git/modules/<name>, whose
#     parent is not a work tree at all — taking it would resolve the plans
#     directory inside .git. The submodule's own --show-toplevel is already
#     right, so the candidate is accepted only if it is a checkout sharing this
#     common dir. This repo vendors skills as submodules; the case is live.
#
# One shape that guard does NOT rescue, left unhandled deliberately (#203): in
# a linked worktree of a submodule the candidate is rejected and the fallback
# to --show-toplevel names the LINKED worktree, so the root nests.
#
# The argument for leaving it — what the fix would cost, and why nobody in the
# cohort hits it — is written once, beside the identical guard in
# skills/using-git-worktrees/scripts/resolve-worktree-root.sh. Deliberately not
# restated here: two copies of one decision drift into two accounts of it, and
# only the copy someone happens to edit gets corrected. Pinned by
# tests/structural/test_plans_dir_contract.py (TestSubmoduleWorktreeBoundary).
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

CONFIG_FILE="$PROJECT_ROOT/.skills/plans_dir"
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

echo "$PROJECT_ROOT/docs/plans"
