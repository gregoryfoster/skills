#!/usr/bin/env bash
# pre-ship.sh (Python/FastAPI variant)
# Runs lint and tests. Exits non-zero on any failure.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Stamp prefix auto-derived from $(basename "$(git rev-parse --show-toplevel)"),
# so a single canonical pre-ship.sh works across every consumer without per-
# project substitution. (Eliminates the historical copy-paste bug class where
# a stamp like `/tmp/watcher-tests-clean-<sha>` leaked into a sibling repo.)
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs 'uv run ruff check .' and 'uv run pytest --no-cov -x -m \"not integration\"'."
  echo "If package.json is present, also runs npm lint/format/test scripts."
  echo "Exits non-zero on any failure. Must pass before committing or pushing."
  echo ""
  echo "Exit codes:"
  echo "  0  All checks passed"
  echo "  1  Lint or test failure"
  echo "  2  Tooling/infra failure (uv missing, git status failed, mktemp failed)"
  echo ""
  echo "Skips pytest when HEAD hasn't changed AND working tree is clean (per-SHA stamp)."
  exit 0
fi

# Intentional `|| pwd` fallback: this script may be invoked outside a git repo
# (e.g., in a scratch directory during local development). The pwd fallback
# lets downstream checks run against the cwd rather than aborting.
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

# --- Project-local env loading (optional override point) ---------------------
# Some deployments need to source /etc/<project>/.env before running tests
# (e.g., when test fixtures read live secrets). Override this block in a
# project-local fork of pre-ship.sh if your project requires it. Example:
#
#   export $(cat /etc/<project>/.env "$PROJECT_ROOT/.env" 2>/dev/null | xargs)
#
# Upstream ships without env loading — most projects don't need it, and the
# ones that do (e.g., archiver, notifier, watcher) keep a thin local fork.

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not installed. This variant is for uv-managed Python projects." >&2
  exit 2
fi

# Single trap covers every tempfile created below (git status capture).
# Scalars (not an array) for bash 3.2 + `set -u` — an empty array expansion
# errors under set -u on stock-macOS bash.
STATUS_OUT=""; STATUS_ERR=""
trap 'rm -f "$STATUS_OUT" "$STATUS_ERR"' EXIT

echo "=== Lint (ruff) ==="
uv run ruff check .

echo ""
echo "=== Tests (Python) ==="

# SHA resolution: degrade gracefully. If git can't compute HEAD (no commits
# yet, broken index), run pytest unconditionally rather than poisoning a
# shared `/tmp/<project>-tests-clean-unknown` stamp slot across runs.
CURRENT_SHA=""
if ! CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null); then
  echo "WARN: could not resolve HEAD SHA; running pytest unconditionally (no stamp)" >&2
fi

# git status: ERROR + exit 2 on failure. A masked failure here is a real
# gate-defeating path — `WORKING_TREE_DIRTY=""` would cause the script to
# touch the stamp file, recording a "passed" run that may not actually be
# clean.
STATUS_OUT=$(mktemp) || { echo "ERROR: mktemp failed (STATUS_OUT)" >&2; exit 2; }
STATUS_ERR=$(mktemp) || { echo "ERROR: mktemp failed (STATUS_ERR)" >&2; exit 2; }
STATUS_RC=0
git status --porcelain >"$STATUS_OUT" 2>"$STATUS_ERR" || STATUS_RC=$?
if [[ $STATUS_RC -ne 0 ]]; then
  echo "ERROR: git status --porcelain failed (exit $STATUS_RC):" >&2
  cat "$STATUS_ERR" >&2
  exit 2
fi
# Strip untracked and vendor-only modifications before deciding cleanliness.
WORKING_TREE_DIRTY=$(grep -v '^??' "$STATUS_OUT" | grep -v '^[ M]M.*vendor/' || true)

if [[ -n "$CURRENT_SHA" ]]; then
  STAMP_PREFIX="$(basename "$PROJECT_ROOT")-tests-clean"
  STAMP_FILE="/tmp/${STAMP_PREFIX}-${CURRENT_SHA}"
else
  STAMP_FILE=""
fi

if [[ -n "$STAMP_FILE" && -f "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
  echo "Test suite already passed for commit ${CURRENT_SHA:0:7} with a clean working tree — skipping."
else
  # Exit code 5 = no tests collected (acceptable on an empty suite).
  # --no-cov skips coverage (faster); requires pytest-cov to be installed
  # (drop the flag if your project doesn't depend on it).
  uv run pytest --no-cov -x -m "not integration" || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
  if [[ -n "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
    touch "$STAMP_FILE"
  fi
fi

# --- Optional JS toolchain (auto-detected) -----------------------------------
# Projects with a frontend (e.g., power-map) ship a package.json. Pure-backend
# projects skip this block entirely without per-project override.

if [[ -f "package.json" ]]; then
  echo ""
  echo "=== Lint (ESLint) ==="
  npm run lint:js

  echo ""
  echo "=== Format check (Prettier) ==="
  npm run format:js:check

  echo ""
  echo "=== Tests (JS) ==="
  npm run test:js
fi

echo ""
echo "Pre-ship checks passed."
