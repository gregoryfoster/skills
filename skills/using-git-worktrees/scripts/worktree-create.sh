#!/usr/bin/env bash
# worktree-create.sh
# Creates a git worktree for <branch> under the resolved worktree root.
# Refuses if <branch> is already checked out in another worktree (Iron Law).
#
# Usage: bash scripts/worktree-create.sh [--new] <branch> [--help]
set -euo pipefail

usage() {
  echo "Usage: bash scripts/worktree-create.sh [--new] <branch>"
  echo ""
  echo "Creates a worktree at <root>/<branch-slug>, where <branch-slug> is"
  echo "<branch> with '/' replaced by '-' (e.g., feature/foo -> feature-foo)."
  echo "The root is resolved via resolve-worktree-root.sh (env var → .skills/worktree_root → <repo>/.worktrees/)."
  echo ""
  echo "Options:"
  echo "  --new   Create the branch (passes -b to git worktree add). Default: branch must already exist."
  echo ""
  echo "Iron Law: refuses if <branch> is already checked out in another worktree."
  echo ""
  echo "Exit codes:"
  echo "  0  Worktree created; absolute path printed on stdout"
  echo "  1  Iron Law violation (branch already checked out elsewhere)"
  echo "  2  Tooling/infra failure (not a git repo, missing arg, git worktree add failed)"
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

NEW_BRANCH=0
if [[ "${1:-}" == "--new" ]]; then
  NEW_BRANCH=1
  shift
fi

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
  echo "ERROR: <branch> argument required" >&2
  usage >&2
  exit 2
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}

SLUG="${BRANCH//\//-}"
WORKTREE_PATH="$ROOT/$SLUG"

# Iron Law check: refuse if the branch is already checked out elsewhere.
# `git worktree list --porcelain` emits a `branch refs/heads/<name>` line per worktree.
EXISTING=$(git worktree list --porcelain | awk -v b="refs/heads/$BRANCH" '$1=="branch" && $2==b {print "match"; exit}')
if [[ "$EXISTING" == "match" ]]; then
  echo "ERROR: branch '$BRANCH' is already checked out in another worktree (Iron Law: no double checkout)" >&2
  echo "Run 'bash scripts/worktree-list.sh' to see existing worktrees." >&2
  exit 1
fi

if [[ -e "$WORKTREE_PATH" ]]; then
  echo "ERROR: path '$WORKTREE_PATH' already exists" >&2
  exit 2
fi

# Pre-flight zombie audit: warn (do not fail) if processes from previously-
# destroyed worktrees are still around. Fresh worktree creation is a good
# moment to surface stale state — non-zero from the audit becomes a WARN,
# never a gate. The audit script is detection-only and lives in the same
# scripts/ directory.
# Runs AFTER the Iron Law + existing-path checks so we don't pay the audit
# cost when we're about to abort anyway.
if [[ -x "$SCRIPT_DIR/audit-worktree-zombies.sh" ]]; then
  if ! "$SCRIPT_DIR/audit-worktree-zombies.sh" --quiet; then
    echo "WARN: worktree zombies detected — run 'bash $SCRIPT_DIR/audit-worktree-zombies.sh' for details" >&2
  fi
fi

mkdir -p "$ROOT"

if [[ $NEW_BRANCH -eq 1 ]]; then
  git worktree add -b "$BRANCH" "$WORKTREE_PATH" || exit 2
else
  git worktree add "$WORKTREE_PATH" "$BRANCH" || exit 2
fi

echo "$WORKTREE_PATH"
