#!/usr/bin/env bash
# worktree-destroy.sh
# Destroys the worktree for <branch>. Refuses if the branch is NOT merged
# into the base ref AND --descoped <reason> was not supplied (Iron Law).
#
# Usage: bash scripts/worktree-destroy.sh <branch> [--descoped <reason>] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash scripts/worktree-destroy.sh <branch> [--descoped <reason>]"
  echo ""
  echo "Destroys the worktree for <branch> (resolved via the same path scheme"
  echo "as worktree-create.sh). Iron Law: refuses if the branch has NOT been"
  echo "merged into the base ref unless --descoped <reason> is supplied."
  echo ""
  echo "Side effects:"
  echo "  - If <worktree>/.port exists, kills any process bound to that port"
  echo "    via 'lsof -ti tcp:<port>' (portable to macOS + Linux)."
  echo "  - Removes the worktree directory (git worktree remove)."
  echo "  - Runs git worktree prune to clean stale metadata."
  echo ""
  echo "Merge verification:"
  echo "  Refuses if the branch is not an ancestor of the base ref. Base ref"
  echo "  is resolved as: .skills/default_branch -> origin's HEAD -> 'main'."
  echo "  Prefers origin/<base> over local <base> (authoritative remote state)."
  echo ""
  echo "Does NOT delete the branch ref. Use 'git branch -d <branch>' afterward"
  echo "if you also want to drop the local ref."
  echo ""
  echo "Exit codes:"
  echo "  0  Worktree removed"
  echo "  1  Iron Law violation (unmerged work without --descoped)"
  echo "  2  Tooling/infra failure (not a git repo, missing arg, worktree not found, git remove failed)"
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
  echo "ERROR: <branch> argument required" >&2
  usage >&2
  exit 2
fi
shift

DESCOPED=0
DESCOPE_REASON=""
if [[ "${1:-}" == "--descoped" ]]; then
  DESCOPED=1
  DESCOPE_REASON="${2:-}"
  if [[ -z "$DESCOPE_REASON" ]]; then
    echo "ERROR: --descoped requires a <reason> argument" >&2
    exit 2
  fi
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

if [[ ! -d "$WORKTREE_PATH" ]]; then
  echo "ERROR: no worktree at '$WORKTREE_PATH'" >&2
  exit 2
fi

# Iron Law: verify the branch has been merged into the project's base branch.
# "Verified merge" = the branch tip is an ancestor of the base branch. Pushing
# alone is NOT enough — a pushed-but-unmerged branch would still lose work on
# destroy. Base branch resolution order:
#   1. .skills/default_branch (single-line file)
#   2. git symbolic-ref refs/remotes/origin/HEAD (whatever origin's HEAD points to)
#   3. "main" fallback
if [[ $DESCOPED -eq 0 ]]; then
  BASE=""
  if [[ -f "$PROJECT_ROOT/.skills/default_branch" ]]; then
    BASE=$(head -n1 "$PROJECT_ROOT/.skills/default_branch" | tr -d '[:space:]')
  fi
  if [[ -z "$BASE" ]]; then
    BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)
  fi
  if [[ -z "$BASE" ]]; then
    BASE="main"
  fi

  # Resolve the base ref. Prefer origin/<base> (authoritative — what the team
  # has merged), fall back to local <base> if no remote tracking exists.
  BASE_REF=""
  if git rev-parse --verify --quiet "origin/$BASE" >/dev/null; then
    BASE_REF="origin/$BASE"
  elif git rev-parse --verify --quiet "$BASE" >/dev/null; then
    BASE_REF="$BASE"
  fi

  if [[ -z "$BASE_REF" ]]; then
    echo "ERROR: could not resolve base branch '$BASE' (neither origin/$BASE nor local $BASE exists)" >&2
    echo "Set .skills/default_branch to your project's base branch name, or pass --descoped <reason>." >&2
    exit 2
  fi

  if ! git rev-parse --verify --quiet "$BRANCH" >/dev/null; then
    echo "ERROR: branch '$BRANCH' does not exist locally — cannot verify merge status" >&2
    exit 2
  fi

  if ! git merge-base --is-ancestor "$BRANCH" "$BASE_REF"; then
    UNMERGED=$(git rev-list --count "$BASE_REF..$BRANCH" 2>/dev/null || echo "?")
    echo "ERROR: branch '$BRANCH' is not merged into '$BASE_REF' ($UNMERGED commit(s) ahead)" >&2
    echo "Merge it first, or pass --descoped <reason> to acknowledge the descope." >&2
    exit 1
  fi
else
  echo "Descoped: $DESCOPE_REASON"
fi

# Free the port if the worktree recorded one. Use lsof (portable: macOS + Linux)
# rather than fuser (Linux-only). Silently no-op if lsof isn't installed and
# warn explicitly so the operator knows the port wasn't actually freed.
PORT_FILE="$WORKTREE_PATH/.port"
if [[ -f "$PORT_FILE" ]]; then
  PORT=$(head -n1 "$PORT_FILE" | tr -d '[:space:]')
  if [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "Freeing port $PORT..."
    if command -v lsof >/dev/null 2>&1; then
      PIDS=$(lsof -ti "tcp:$PORT" 2>/dev/null || true)
      if [[ -n "$PIDS" ]]; then
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
      fi
    else
      echo "WARN: lsof not installed; could not free port $PORT" >&2
    fi
  else
    echo "WARN: $PORT_FILE did not contain a numeric port; skipping port cleanup" >&2
  fi
fi

git worktree remove "$WORKTREE_PATH" || exit 2
git worktree prune || exit 2

echo "Worktree removed: $WORKTREE_PATH"
