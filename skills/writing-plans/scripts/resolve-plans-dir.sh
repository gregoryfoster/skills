#!/usr/bin/env bash
# resolve-plans-dir.sh
# Prints the resolved plans directory for the current repo on stdout.
# Resolution order: PLANS_DIR env var → .skills/plans_dir file → <repo>/docs/plans/
#
# Usage: bash "<resolve-plans-dir.sh>" [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints the resolved plans directory for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. PLANS_DIR env var"
  echo "  2. .skills/plans_dir file under the repo root (single-line path;"
  echo "     a relative one resolves against <repo-root>; \`~\` is not expanded)"
  echo "  3. <repo-root>/docs/plans/ (fallback)"
  echo ""
  echo "<repo-root> is the PRIMARY checkout, not whichever worktree you are"
  echo "standing in — so a project's configured plans directory is found from"
  echo "a linked worktree too, where that untracked knob does not exist."
  echo ""
  echo "A relative PLANS_DIR is printed as given: it resolves against the"
  echo "directory of whoever reads it."
  echo ""
  echo "A primary git refuses (\"dubious ownership\") is exit 2, never this"
  echo "checkout. A bare primary has no checkout, so there this one is the"
  echo "repo root. A primary whose .git is a file (git init --separate-git-dir)"
  echo "is known only from inside it: from its linked worktrees, exit 2."
  echo ""
  echo "Exit codes:"
  echo "  0  Resolution succeeded"
  echo "  2  Not inside a git repository, git failed, or the primary checkout"
  echo "     could not be resolved (the reason is on stderr)"
  exit 0
fi

# here_git <args> — git without an inherited GIT_DIR or GIT_WORK_TREE (#605).
# Git exports GIT_DIR to every hook, and it beats both cwd and -C: in a
# submodule `git -C "$CANDIDATE"` answered for this checkout and put the plans
# directory inside .git. Why, beside the twin in resolve-worktree-root.sh.
here_git() {
  env -u GIT_DIR -u GIT_WORK_TREE git "$@"
}

PROJECT_ROOT=$(here_git rev-parse --show-toplevel) || {
  echo "ERROR: not inside a git repository, or git refused it (git's reason is above)" >&2
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
#
# A rejected candidate falls back to --show-toplevel only in three layouts:
# the main worktree, a bare primary, and #203's submodule worktree. Anything
# else is exit 2, never a fallback (#585, #605): git refusing the primary had
# read as "not a checkout", and the primary's knob went unread. Which layouts,
# and why, is written once beside the twin, as above; this block is a copy of
# it, held to the same answers by test_plans_dir_contract.py's parity test.
if ! COMMON_DIR=$(here_git rev-parse --git-common-dir) ||
  ! COMMON_DIR=$(cd "$COMMON_DIR" && pwd -P); then
  echo "ERROR: could not resolve this checkout's git common dir (the reason is above)" >&2
  exit 2
fi
CANDIDATE=$(dirname "$COMMON_DIR")
# `git -C "$CANDIDATE"` answers relative to CANDIDATE, not to our $PWD. Asked
# in silence: in layouts 1–3 the candidate is no checkout, and git saying so
# is not a failure. Where it is one, git is asked again for its reason.
if ! CANDIDATE_COMMON=$(here_git -C "$CANDIDATE" rev-parse --git-common-dir 2>/dev/null) ||
  ! CANDIDATE_COMMON=$(cd "$CANDIDATE" && cd "$CANDIDATE_COMMON" 2>/dev/null && pwd -P); then
  CANDIDATE_COMMON=""
fi
if [[ "$CANDIDATE_COMMON" == "$COMMON_DIR" ]]; then
  PROJECT_ROOT="$CANDIDATE"
else
  DIRS=$(here_git rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || DIRS=""
  WT_LIST=$(here_git worktree list --porcelain) || {
    echo "ERROR: failed to enumerate worktrees (git worktree list --porcelain)" >&2
    exit 2
  }
  PRIMARY_BLOCK=${WT_LIST%%$'\n\n'*}
  if [[ -n "$DIRS" && "${DIRS%%$'\n'*}" == "${DIRS#*$'\n'}" ]]; then
    : # 1. the main worktree
  elif [[ $'\n'"$PRIMARY_BLOCK"$'\n' == *$'\n'bare$'\n'* ]]; then
    : # 2. a bare primary
  elif [[ "$(here_git -C "$CANDIDATE" rev-parse --is-inside-git-dir 2>/dev/null)" == true ]]; then
    : # 3. a submodule's linked worktree (#203)
  elif [[ "$CANDIDATE/.git" -ef "$COMMON_DIR" ]]; then
    # The primary is right there, and git would not answer for it.
    WHY="git's reason is above"
    if here_git -C "$CANDIDATE" rev-parse --git-common-dir >/dev/null; then
      WHY="git names another common dir there"
    fi
    echo "ERROR: could not resolve the primary checkout '$CANDIDATE' ($WHY)" >&2
    exit 2
  else
    echo "ERROR: could not resolve the primary checkout: this repository's common dir '$COMMON_DIR' is no checkout's .git, as a primary whose .git is a file makes it (git init --separate-git-dir), and only that primary knows its work tree, so run this from the primary checkout" >&2
    exit 2
  fi
fi

CONFIG_FILE="$PROJECT_ROOT/.skills/plans_dir"
if [[ -f "$CONFIG_FILE" ]]; then
  # Read first non-blank, non-comment line. Trim leading/trailing whitespace.
  # `|| true` keeps pipefail from aborting when the file is empty or all
  # comments — that case must fall through to the default, not crash.
  CONFIGURED=$(grep -v '^[[:space:]]*#' "$CONFIG_FILE" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  if [[ -n "$CONFIGURED" ]]; then
    # A relative path is the PRIMARY checkout's (#590), by the rule
    # resolve-worktree-root.sh applies to .skills/worktree_root (#562, #567).
    # Echoed as given, it resolved against the caller's directory: from a
    # subdirectory it named a directory under that subdirectory, and from a
    # linked worktree one inside that worktree. The knob lives in the primary
    # checkout, so that is the only directory it can mean. As there, `~` is
    # not expanded and `..` is not folded: the file is not shell input.
    case $CONFIGURED in
      /*) ;;
      *) CONFIGURED="$PROJECT_ROOT/${CONFIGURED#./}" ;;
    esac
    echo "$CONFIGURED"
    exit 0
  fi
fi

echo "$PROJECT_ROOT/docs/plans"
