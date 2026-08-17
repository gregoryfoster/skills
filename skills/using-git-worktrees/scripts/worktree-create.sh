#!/usr/bin/env bash
# worktree-create.sh
# Creates a git worktree for <branch> under the resolved worktree root.
# Refuses if <branch> is already checked out in another worktree (Iron Law).
#
# Usage: bash <SKILL_SCRIPTS>/worktree-create.sh [--new] <branch> [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--new] <branch>"
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
  echo "Run 'bash \"$SCRIPT_DIR/worktree-list.sh\"' to see existing worktrees." >&2
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

# A worktree inherits no virtualenv, so the first `.venv/bin/python -m pytest`
# in it dies before any test runs (#156). Link the parent's when there is one:
# a symlink is by construction the same interpreter and the same installed
# packages, where a freshly resolved venv is a different environment that can
# collect fewer tests and still report green.
#
# Opportunistic, never a gate — this script is vendored into repos that have no
# venv at all, and a worktree without one is not a failed worktree. Notes go to
# stderr; stdout stays the worktree path, which is this script's contract.
#
# Does NOT reach harness-provisioned worktrees (the Agent tool's
# `isolation: "worktree"`), which call `git worktree add` directly and never
# run this script. Those rely on the consuming repo's own hook, plus the
# by-hand `ln -s` in SKILL.md Phase 3.
#
# Every failure path here is swallowed. The worktree already exists by this
# point, so a `set -e` abort would return non-zero for a creation that
# succeeded — and leave the caller without the path on stdout.
# `! -e && ! -L`, matching scripts/structural-tests.sh: a BROKEN symlink at
# .venv is `-e` false and `-L` true, so testing -e alone would fall through to
# an `ln -s` that fails on the existing name. It lands in the WARN branch either
# way, but the two linkers must read identically or a later edit fixes one.
if [[ -e "$PROJECT_ROOT/.venv/bin/activate" && ! -e "$WORKTREE_PATH/.venv" && ! -L "$WORKTREE_PATH/.venv" ]]; then
  # `pwd -P` resolves through a .venv that is itself a symlink (a worktree
  # provisioning a worktree), so we never build a link to a link.
  VENV_TARGET=$(cd "$PROJECT_ROOT/.venv" 2>/dev/null && pwd -P) || VENV_TARGET=""
  if [[ -z "$VENV_TARGET" ]]; then
    echo "WARN: could not resolve $PROJECT_ROOT/.venv — no venv linked into $WORKTREE_PATH" >&2
  elif ln -s "$VENV_TARGET" "$WORKTREE_PATH/.venv" 2>/dev/null; then
    echo "NOTE: linked .venv -> $VENV_TARGET" >&2
  else
    echo "WARN: could not link .venv into $WORKTREE_PATH — run 'ln -s $VENV_TARGET .venv' there" >&2
  fi
fi

echo "$WORKTREE_PATH"
