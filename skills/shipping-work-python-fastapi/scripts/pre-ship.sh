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
  echo "Runs 'uv run ruff check .' and 'uv run pytest -x -m \"not integration\"'"
  echo "(with --no-cov auto-applied when pytest-cov is installed)."
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

# Defensive fallback inherited from sibling scripts. If pre-ship is invoked
# outside a repo, downstream git checks (status, rev-parse HEAD) will still
# fail loudly — this `|| pwd` only delays that to a clearer error site.
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

# Single trap covers every tempfile created below (git status capture,
# git rev-parse stderr). Scalars (not an array) for bash 3.2 + `set -u` —
# an empty array expansion errors under set -u on stock-macOS bash.
STATUS_OUT=""; STATUS_ERR=""; REV_ERR=""
trap 'rm -f "$STATUS_OUT" "$STATUS_ERR" "$REV_ERR"' EXIT

echo "=== Lint (ruff) ==="
uv run ruff check .

echo ""
echo "=== Tests (Python) ==="

# SHA resolution: degrade gracefully. If git can't compute HEAD (no commits
# yet, broken index), run pytest unconditionally rather than poisoning a
# shared `/tmp/<project>-tests-clean-unknown` stamp slot across runs.
# Stream git's own stderr in the WARN so operators can triage expected
# ("no HEAD yet") vs. genuine infra rot.
REV_ERR=$(mktemp) || { echo "ERROR: mktemp failed (REV_ERR)" >&2; exit 2; }
CURRENT_SHA=""
if ! CURRENT_SHA=$(git rev-parse HEAD 2>"$REV_ERR"); then
  echo "WARN: could not resolve HEAD SHA; running pytest unconditionally (no stamp):" >&2
  cat "$REV_ERR" >&2
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
# grep -v exits 1 when its inverse filter matches no lines — the clean-tree
# case (empty $STATUS_OUT) or the all-untracked case. The `|| true` keeps
# that benign exit-1 from tripping `set -e` (pipefail propagates it here).
WORKING_TREE_DIRTY=$(grep -v '^??' "$STATUS_OUT" | grep -v '^[ M]M.*vendor/' || true)

if [[ -n "$CURRENT_SHA" ]]; then
  STAMP_PREFIX="$(basename "$PROJECT_ROOT")-tests-clean"
  STAMP_FILE="/tmp/${STAMP_PREFIX}-${CURRENT_SHA}"
else
  STAMP_FILE=""
fi

# Auto-detect pytest-cov. When present, pass --no-cov to skip coverage on the
# pre-ship run (faster, and the coverage threshold belongs in CI, not the
# pre-push gate). When absent, omit the flag — passing --no-cov to a pytest
# install without the plugin is a hard usage error.
PYTEST_COV_FLAG=""
if uv run python -c "import pytest_cov" >/dev/null 2>&1; then
  PYTEST_COV_FLAG="--no-cov"
fi

if [[ -n "$STAMP_FILE" && -f "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
  echo "Test suite already passed for commit ${CURRENT_SHA:0:7} with a clean working tree — skipping."
else
  # Exit code 5 = no tests collected (acceptable on an empty suite).
  # $PYTEST_COV_FLAG is intentionally unquoted: empty expansion → no arg.
  uv run pytest $PYTEST_COV_FLAG -x -m "not integration" || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
  if [[ -n "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
    touch "$STAMP_FILE"
  fi
fi

# --- Optional JS toolchain (auto-detected) -----------------------------------
# Projects with a frontend (e.g., power-map) ship a package.json. Pure-backend
# projects skip this block entirely without per-project override.

if [[ -f "package.json" ]]; then
  # Probing package.json requires node. Fail loudly if it's absent rather than
  # silently treating every script as missing (gate-script discipline: the
  # output of `has_script` decides whether each JS gate runs, so its stderr
  # must not be swallowed).
  if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node is required to probe package.json scripts (no JS gates would run)" >&2
    exit 2
  fi

  # Validate package.json parses cleanly up front. Without this, `has_script`
  # would return non-zero on a JSON parse error and the JS gates would silently
  # skip — conflating "script missing" with "package.json broken." Gate-script
  # discipline: a broken package.json is an ERROR (exit 2), not a skip.
  # require("./package.json") uses node's built-in JSON loader; a parse error
  # throws and node exits non-zero with the parse error on stderr.
  if ! node -e 'require("./package.json")' >/dev/null; then
    echo "ERROR: package.json failed to parse" >&2
    exit 2
  fi

  # has_script <name>: exits 0 if package.json has the named npm script, else 1.
  # Script name is passed via env so colons (`lint:js`) or any future special
  # character can't break out of the node -e JS literal. With package.json
  # pre-validated above, non-zero from has_script means only "script not present".
  has_script() {
    SCRIPT="$1" node -e 'const s=require("./package.json").scripts; process.exit(s&&s[process.env.SCRIPT]?0:1)'
  }

  if has_script lint:js; then
    echo ""
    echo "=== Lint (ESLint) ==="
    npm run lint:js
  fi

  if has_script format:js:check; then
    echo ""
    echo "=== Format check (Prettier) ==="
    npm run format:js:check
  fi

  if has_script test:js; then
    echo ""
    echo "=== Tests (JS) ==="
    npm run test:js
  fi
fi

echo ""
echo "Pre-ship checks passed."
