#!/usr/bin/env bash
# structural-tests.sh
# The `structural-tests` pre-commit hook's entry (#156).
#
# Guarantees a usable `.venv` at the repo root, then runs the structural suite.
# A linked worktree — `git worktree add`, or the Claude Code Agent tool's
# `isolation: "worktree"` — starts with no `.venv`, so the hook's previous
# inline `source .venv/bin/activate` died with bash's raw
# `.venv/bin/activate: No such file or directory` after the work was done and
# the suite was green. This script links the main checkout's venv instead, and
# when it cannot, says what to type.
#
# Linking rather than creating is deliberate. A symlink is by construction the
# *same* interpreter and the same installed packages as the main checkout; a
# freshly resolved venv is a different environment that can collect fewer
# tests and still report green, which is the harder-to-catch half of #156.
#
# Usage: bash scripts/structural-tests.sh [--check] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--check]"
  echo ""
  echo "Ensures a usable .venv at the repo root, then runs tests/structural/."
  echo ""
  echo "Resolution order:"
  echo "  1. .venv/bin/activate already resolves      -> use it"
  echo "  2. linked worktree, main checkout has .venv -> symlink it in"
  echo "  3. neither                                  -> diagnose and exit 1"
  echo ""
  echo "Options:"
  echo "  --check  Do the venv resolution and stop; do not run pytest."
  echo ""
  echo "Exit codes:"
  echo "  0  venv resolved (and, without --check, the suite passed)"
  echo "  1  no venv could be resolved"
  echo "  2  not inside a git repository, or a bad argument"
  echo "  *  otherwise the suite's OWN exit code, passed through unchanged:"
  echo "     pytest exits 1 on failures, 5 on nothing collected, and the shell"
  echo "     reports 127 if pytest is missing from a venv that did resolve."
}

# Every argument, not just the first: a script on the commit path that rejects
# `--bogus` but silently swallows `--check --bogus` is worse than one that
# rejects neither, because the strictness is what makes a caller stop checking.
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    --check) CHECK_ONLY=1 ;;
    "") ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

# The main checkout's root. `--git-common-dir` is the shared .git for every
# worktree, so its parent is the main checkout — and it equals `--git-dir` when
# there is only one. It may be printed relative to the cwd, so absolutize it by
# hand rather than with `--path-format=absolute`, which needs git >= 2.31.
GIT_COMMON=$(git rev-parse --git-common-dir)
GIT_COMMON=$(cd "$GIT_COMMON" && pwd -P)
MAIN_ROOT=$(dirname "$GIT_COMMON")

if [[ ! -e ".venv/bin/activate" ]]; then
  if [[ ! -e ".venv" && ! -L ".venv" && "$MAIN_ROOT" != "$REPO_ROOT" && -e "$MAIN_ROOT/.venv/bin/activate" ]]; then
    # Resolve through any symlink the main checkout's own .venv may be, so we
    # never build a chain of links to a link.
    VENV_TARGET=$(cd "$MAIN_ROOT/.venv" && pwd -P)
    ln -s "$VENV_TARGET" "$REPO_ROOT/.venv"
    echo "NOTE: linked .venv -> $VENV_TARGET (this worktree had none)" >&2
  else
    echo "ERROR: no usable .venv at $REPO_ROOT — the structural suite cannot run." >&2
    if [[ "$MAIN_ROOT" != "$REPO_ROOT" ]]; then
      echo "  This is a linked worktree of $MAIN_ROOT, which has no .venv either." >&2
      echo "  Create one there, then:  ln -s $MAIN_ROOT/.venv .venv" >&2
    elif [[ -e ".venv" || -L ".venv" ]]; then
      echo "  .venv exists but has no bin/activate (a broken symlink, or an" >&2
      echo "  unfinished venv). Remove it, then:  python3 -m venv .venv" >&2
      echo "  In a linked worktree the fix is instead:  ln -s <main-checkout>/.venv .venv" >&2
    else
      echo "  Create it:  python3 -m venv .venv && source .venv/bin/activate" >&2
      echo "              pip install -r requirements-test.txt" >&2
      echo "  In a linked worktree the fix is instead:  ln -s <main-checkout>/.venv .venv" >&2
    fi
    exit 1
  fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  exit 0
fi

# shellcheck source=/dev/null
source .venv/bin/activate
# `exec` replaces this shell, so pytest's exit code IS this script's — see the
# usage block, which documents the pass-through rather than claiming a 1.
exec pytest tests/structural/ -v
