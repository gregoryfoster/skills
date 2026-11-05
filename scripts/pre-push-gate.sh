#!/usr/bin/env bash
# pre-push-gate.sh
# The `pre-push-gate` pre-commit hook's entry (#537 Step 10).
#
# Under the pre-commit hook, structural-tests.sh may run only the tests a
# commit's staged paths reach. This is the backstop that makes that safe: a
# push is refused unless the pushed commit's tree has passed the full suite,
# either recorded by an earlier full run (pre-ship, a full hook run) or run
# here and now.
#
# Usage: bash scripts/pre-push-gate.sh [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\""
  echo ""
  echo "Refuses a push whose tree has not passed the full structural suite."
  echo ""
  echo "Reads the pushed commit from PRE_COMMIT_TO_REF (pre-commit sets it for"
  echo "pre-push hooks), else PRE_COMMIT_LOCAL_BRANCH, else HEAD. When that"
  echo "commit's tree is checked out here and the checkout is clean,"
  echo "scripts/structural-tests.sh runs in place, with the hook's test"
  echo "selection off, and reuses a pass recorded for the tree. Otherwise the"
  echo "commit is checked out into a temporary worktree and gated there. A"
  echo "branch deletion pushes no tree and runs nothing."
  echo ""
  echo "Exit codes:"
  echo "  0  the pushed tree passed the full suite (recorded, or just now)"
  echo "  1  it did not, or the suite could not run (no venv): push refused"
  echo "  2  not inside a git repository, or a bad argument"
}

for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

# A push that includes the root commit (the remote has none of this history)
# runs pre-commit in all-files mode, which sets no TO_REF; LOCAL_BRANCH still
# names what is pushed (the SHA itself, for a push by SHA). HEAD is the last
# resort, for a run outside pre-commit.
TO=${PRE_COMMIT_TO_REF:-${PRE_COMMIT_LOCAL_BRANCH:-HEAD}}
if [[ "$TO" =~ ^0+$ ]]; then
  exit 0
fi
TO_TREE=$(git rev-parse "$TO^{tree}") || {
  echo "ERROR: cannot resolve the pushed commit '$TO' — push refused" >&2
  exit 1
}

# The pushed tree is what is on disk only when HEAD carries it and nothing
# tracked or untracked (and not ignored) differs; otherwise a pass here would
# certify files the push does not contain.
STATUS_RC=0
DIRTY=$(git status --porcelain) || STATUS_RC=$?
HEAD_TREE=$(git rev-parse 'HEAD^{tree}' 2>/dev/null) || HEAD_TREE=""
WT=""
cleanup() {
  if [[ -n "$WT" ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$WT" >/dev/null 2>&1 \
      || echo "NOTE: could not remove the temporary worktree $WT" >&2
    rm -rf "$(dirname "$WT")"
  fi
}
trap cleanup EXIT

RUN_IN="$REPO_ROOT"
if [[ $STATUS_RC -ne 0 || -n "$DIRTY" || "$HEAD_TREE" != "$TO_TREE" ]]; then
  BASE=$(mktemp -d) || { echo "ERROR: mktemp failed — push refused" >&2; exit 1; }
  WT="$BASE/pushed"
  git worktree add -q --detach "$WT" "$TO" || {
    echo "ERROR: could not check out $TO to gate it — push refused" >&2
    rm -rf "$BASE"
    WT=""
    exit 1
  }
  RUN_IN="$WT"
  echo "pre-push gate: $TO is not what is checked out here; gating it in $WT"
fi

# git exports GIT_DIR to a hook run from a linked worktree. Left set, every
# git command in the suite (the stamp key, the tests that read history) would
# resolve the pushing worktree's HEAD and index, not the commit gated here
# (#189). Unset, git finds the repo from RUN_IN, which is the same repo when
# the run is in place.
RC=0
(cd "$RUN_IN" && env -u PRE_COMMIT -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE \
  -u GIT_COMMON_DIR -u GIT_OBJECT_DIRECTORY bash scripts/structural-tests.sh) || RC=$?
if [[ $RC -ne 0 ]]; then
  echo "pre-push gate: the full structural suite did not pass on $TO (exit $RC) — push refused" >&2
  exit 1
fi
