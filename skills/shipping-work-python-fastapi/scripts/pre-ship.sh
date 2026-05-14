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
  echo ""
  echo "Skips pytest when HEAD hasn't changed AND working tree is clean (per-SHA stamp)."
  exit 0
fi

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

echo "=== Lint (ruff) ==="
uv run ruff check .

echo ""
echo "=== Tests (Python) ==="
CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
STAMP_PREFIX="$(basename "$PROJECT_ROOT")-tests-clean"
STAMP_FILE="/tmp/${STAMP_PREFIX}-${CURRENT_SHA}"
WORKING_TREE_DIRTY=$(git status --porcelain 2>/dev/null \
  | grep -v '^??' \
  | grep -v '^[ M]M.*vendor/' \
  || true)

if [[ -f "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
  echo "Test suite already passed for commit ${CURRENT_SHA:0:7} with a clean working tree — skipping."
else
  # Exit code 5 = no tests collected (acceptable on an empty suite).
  # --no-cov skips coverage (faster); requires pytest-cov to be installed
  # (drop the flag if your project doesn't depend on it).
  uv run pytest --no-cov -x -m "not integration" || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
  if [[ -z "$WORKING_TREE_DIRTY" ]]; then
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
