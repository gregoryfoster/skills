#!/usr/bin/env bash
# resolve-worktree-root.sh
# Prints the resolved worktree root for the current repo on stdout.
# Resolution order: WORKTREE_ROOT env var → .skills/worktree_root file → <repo>/.worktrees/
#
# Usage: bash "<resolve-worktree-root.sh>" [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints the resolved worktree root for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. WORKTREE_ROOT env var"
  echo "  2. .skills/worktree_root file under the repo root (single-line path;"
  echo "     a relative one resolves against <repo-root>)"
  echo "  3. <repo-root>/.worktrees/ (fallback)"
  echo ""
  echo "<repo-root> is the PRIMARY checkout, not whichever worktree you are"
  echo "standing in — so worktrees created from inside a worktree are siblings."
  echo ""
  echo "A relative WORKTREE_ROOT is printed as given: it resolves against the"
  echo "directory of whoever reads it (worktree-create.sh and"
  echo "worktree-destroy.sh read it from the current checkout's top level)."
  echo ""
  echo "A primary git refuses (\"dubious ownership\") is exit 2, never this"
  echo "checkout. A bare primary has no checkout, so there this one is the"
  echo "repo root. A primary whose .git is a file (git init --separate-git-dir)"
  echo "is known only from inside it (git >= 2.31): from its linked worktrees,"
  echo "exit 2, and below 2.31 from the primary too."
  echo ""
  echo "Exit codes:"
  echo "  0  Resolution succeeded"
  echo "  2  Not inside a git repository, git failed, or the primary checkout"
  echo "     could not be resolved (the reason is on stderr)"
  exit 0
fi

# here_git <args> — git without an inherited GIT_DIR or GIT_WORK_TREE (#605,
# set R's CR 1895). Git exports GIT_DIR to every hook, and it beats both cwd
# and -C: `git -C "$CANDIDATE"` below answered for this checkout instead, and
# in a submodule that put the root inside .git. Every call here answers for
# the checkout this runs in (docs/STYLE.md, #189).
here_git() {
  env -u GIT_DIR -u GIT_WORK_TREE git "$@"
}

PROJECT_ROOT=$(here_git rev-parse --show-toplevel) || {
  echo "ERROR: not inside a git repository, or git refused it (git's reason is above)" >&2
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
#
# One shape that guard does NOT rescue, left unhandled deliberately (#203): in
# a linked worktree of a submodule the common dir is that same
# <super>/.git/modules/<name>, so the candidate is rejected and the fallback to
# --show-toplevel names the LINKED worktree — the root nests, exactly as it did
# before this fix. Recovering the submodule's primary work tree means walking
# <super>/.git/modules/<name>/worktrees/<id>/gitdir back to the registering
# checkout: real parsing for a combination nobody in the cohort runs. The
# nesting is pinned by tests/structural/test_worktree_root_contract.py
# (TestSubmoduleWorktreeBoundary), so changing the guard is a decision.
#
# A rejected candidate falls back to --show-toplevel only in the layouts where
# that is the answer (#585, #605). Anything else is exit 2, never a fallback:
# git refusing the primary ("dubious ownership") had read as "not a checkout",
# and the primary's knob went unread from every linked worktree.
#   1. This checkout is the main worktree (its git dir is the common dir): a
#      submodule's own checkout, or a primary whose .git is a pointer file
#      (`git init --separate-git-dir`), whose common dir's parent is no
#      checkout. Set R's test (CR 1892), which needs git 2.31: below that a
#      submodule's checkout still lands in 3, and that primary is exit 2
#      saying git is too old (CR 1990).
#   2. A bare primary (a `bare` line in the first `git worktree list` block)
#      has no checkout, so the current one is the project (set T, CR 1839).
#   3. The candidate is inside a git dir: a submodule's linked worktree, #203.
# Anything else is exit 2. Where the candidate's .git, or its gitfile's
# target, is the common dir, the primary is there and git refused it: that
# is asked before 2, since a `.bare` store is bare too, and git is asked
# again for its reason. Anywhere else this is a linked worktree of a primary
# git knows no path to, so the message says to run from the primary.
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
  # The candidate's .git: a directory, or a gitfile's `gitdir:` read against
  # the candidate, as `<dir>/.git` naming `./.bare` is (CR 1988).
  CANDIDATE_GIT="$CANDIDATE/.git"
  if [[ -f "$CANDIDATE_GIT" ]]; then
    GITFILE=""
    { IFS= read -r GITFILE <"$CANDIDATE_GIT"; } 2>/dev/null || true
    GITFILE=${GITFILE#gitdir: }
    case $GITFILE in
      /*) CANDIDATE_GIT=$GITFILE ;;
      ?*) CANDIDATE_GIT="$CANDIDATE/$GITFILE" ;;
    esac
  fi
  if [[ -n "$DIRS" && "${DIRS%%$'\n'*}" == "${DIRS#*$'\n'}" ]]; then
    : # 1. the main worktree
  elif [[ "$CANDIDATE_GIT" -ef "$COMMON_DIR" ]]; then
    # The primary is right there, and git would not answer for it. Asked
    # before the bare case (CR 1988): a `.bare` store with a `<dir>/.git`
    # gitfile is bare too, and its knob is <dir>'s.
    WHY="git's reason is above"
    if here_git -C "$CANDIDATE" rev-parse --git-common-dir >/dev/null; then
      WHY="git names another common dir there"
    fi
    echo "ERROR: could not resolve the primary checkout '$CANDIDATE' ($WHY)" >&2
    exit 2
  elif [[ $'\n'"$PRIMARY_BLOCK"$'\n' == *$'\n'bare$'\n'* ]]; then
    : # 2. a bare primary
  elif [[ "$(here_git -C "$CANDIDATE" rev-parse --is-inside-git-dir 2>/dev/null)" == true ]]; then
    : # 3. a submodule's linked worktree (#203)
  elif [[ "${DIRS%%$'\n'*}" == --path-format=absolute ]]; then
    # Below 2.31 rev-parse echoes the option back at exit 0 (CR 1990), so
    # case 1 cannot be told: run from the primary it is no answer either.
    GIT_VERSION=$(here_git --version 2>/dev/null) || GIT_VERSION="git version (unknown)"
    echo "ERROR: could not resolve the primary checkout: git ${GIT_VERSION#git version } predates 2.31, which this layout needs to tell its primary from a linked worktree: upgrade git, or set WORKTREE_ROOT" >&2
    exit 2
  else
    echo "ERROR: could not resolve the primary checkout: this repository's common dir '$COMMON_DIR' is no checkout's .git, as a primary whose .git is a file makes it (git init --separate-git-dir), and only that primary knows its work tree, so run this from the primary checkout" >&2
    exit 2
  fi
fi

CONFIG_FILE="$PROJECT_ROOT/.skills/worktree_root"
if [[ -f "$CONFIG_FILE" ]]; then
  # Read first non-blank, non-comment line. Trim leading/trailing whitespace.
  # `|| true` keeps pipefail from aborting when the file is empty or all
  # comments — that case must fall through to the default, not crash.
  CONFIGURED=$(grep -v '^[[:space:]]*#' "$CONFIG_FILE" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  if [[ -n "$CONFIGURED" ]]; then
    # A relative path is the PRIMARY checkout's (#562, #567). Echoed as given,
    # it resolved against the caller's directory: from a subdirectory it named
    # a path under that subdirectory, and worktree-create.sh, which reads it
    # from the current checkout's top level, nested every worktree created
    # from a linked worktree inside that worktree. The knob lives in the
    # primary checkout, so that is the only directory it can mean.
    case $CONFIGURED in
      /*) ;;
      *) CONFIGURED="$PROJECT_ROOT/${CONFIGURED#./}" ;;
    esac
    echo "$CONFIGURED"
    exit 0
  fi
fi

echo "$PROJECT_ROOT/.worktrees"
