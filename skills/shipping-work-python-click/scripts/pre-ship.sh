#!/usr/bin/env bash
# pre-ship.sh (Python/Click variant)
# Runs lint, import check, and tests. Exits non-zero on any failure.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Import target resolution is delegated to detect-import-targets.sh
# (shared with gather-context.sh). Test-location resolution prefers a
# top-level tests/ directory, falling back to pyproject.toml
# [tool.pytest.ini_options].testpaths.
#
# Stamp prefix auto-derived from $(basename "$(git rev-parse --show-toplevel)"),
# so a single canonical pre-ship.sh works across every consumer without per-
# project substitution.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

# Capture the script's own directory *before* any cd, so helper lookups
# resolve correctly regardless of invocation cwd.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs 'uv run ruff check .', an import check (auto-detected from"
  echo "pyproject.toml or .skills/import-targets via detect-import-targets.sh),"
  echo "and 'uv run pytest' (auto-discovers tests/ or pyproject.toml"
  echo "[tool.pytest.ini_options].testpaths). Exits non-zero on any failure."
  echo "Must pass before committing or pushing."
  echo ""
  echo "Exit codes:"
  echo "  0  All checks passed"
  echo "  1  Lint, import, or test failure"
  echo "  2  Tooling/infra failure (uv missing, helper script failed,"
  echo "     git status failed, mktemp failed)"
  echo ""
  echo "Skips pytest when HEAD hasn't changed AND working tree is clean (per-SHA stamp)."
  exit 0
fi

# Defensive fallback inherited from sibling scripts. If pre-ship is invoked
# outside a repo, downstream git checks (status, rev-parse HEAD) will still
# fail loudly — this `|| pwd` only delays that to a clearer error site.
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

# Pre-flight: warn (do not fail) if zombie processes from previously-destroyed
# worktrees are still around. Helps surface drift the destroy script can't see
# (operators using raw `git worktree remove`, post-destroy spawn races, etc.).
# Silent skip when vendored at a non-canonical path (warning, not a gate).
AUDIT_SCRIPT="skills/using-git-worktrees/scripts/audit-worktree-zombies.sh"
if [[ -x "$AUDIT_SCRIPT" ]]; then
  if ! "$AUDIT_SCRIPT" --quiet; then
    echo "WARN: worktree zombies detected — see 'bash $AUDIT_SCRIPT'" >&2
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not installed. This variant is for uv-managed Python projects." >&2
  exit 2
fi

# Single trap covers every tempfile created below (helper-script captures,
# git status, git rev-parse stderr). Scalars (not an array) for bash 3.2 +
# `set -u` — an empty array expansion errors under set -u on stock-macOS bash.
IMPORT_OUT=""; TESTDIRS_OUT=""; STATUS_OUT=""; STATUS_ERR=""; REV_ERR=""
trap 'rm -f "$IMPORT_OUT" "$TESTDIRS_OUT" "$STATUS_OUT" "$STATUS_ERR" "$REV_ERR"' EXIT

echo "=== Lint (ruff) ==="
uv run ruff check .

# --- Import check ------------------------------------------------------------
# Resolution handled by detect-import-targets.sh (shared with gather-context.sh).

echo ""
echo "=== Import check ==="

# Run the helper to a tempfile so its exit code is observable — process
# substitution hides the producer's status, which would let a missing
# helper script or a broken pyproject.toml silently skip the import gate.
IMPORT_OUT=$(mktemp) || { echo "ERROR: mktemp failed (IMPORT_OUT)" >&2; exit 2; }
IMPORT_RC=0
bash "$SCRIPT_DIR/detect-import-targets.sh" >"$IMPORT_OUT" || IMPORT_RC=$?
if [[ $IMPORT_RC -ne 0 ]]; then
  echo "ERROR: detect-import-targets.sh failed (exit $IMPORT_RC)" >&2
  exit 2
fi

IMPORT_TARGETS=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] && IMPORT_TARGETS+=("$pkg")
done < "$IMPORT_OUT"

if [[ ${#IMPORT_TARGETS[@]} -eq 0 ]]; then
  echo "No import target detected (no .skills/import-targets and no [project] name in pyproject.toml). Skipping."
else
  for pkg in "${IMPORT_TARGETS[@]}"; do
    echo "--- import $pkg ---"
    uv run python -c "import $pkg"
  done
fi

# --- Tests -------------------------------------------------------------------
# Per-SHA stamp: skip pytest if HEAD hasn't changed AND working tree is clean.
# A missing test suite is acceptable — shared libraries may not have one;
# ruff + import-check still gate the ship.
#
# Test directory resolution is delegated to detect-test-dirs.sh (shared
# with gather-context.sh). The helper prefers tests/ then falls back to
# every entry in pyproject.toml [tool.pytest.ini_options].testpaths.

echo ""
echo "=== Tests (Python) ==="

# Same tempfile pattern as the import check above — a missing helper or a
# broken pyproject.toml must not silently degrade to "no tests, skip pytest".
TESTDIRS_OUT=$(mktemp) || { echo "ERROR: mktemp failed (TESTDIRS_OUT)" >&2; exit 2; }
TESTDIRS_RC=0
bash "$SCRIPT_DIR/detect-test-dirs.sh" >"$TESTDIRS_OUT" || TESTDIRS_RC=$?
if [[ $TESTDIRS_RC -ne 0 ]]; then
  echo "ERROR: detect-test-dirs.sh failed (exit $TESTDIRS_RC)" >&2
  exit 2
fi

TEST_DIRS=()
while IFS= read -r dir; do
  # Normalize: strip any trailing slash, then append exactly one. Avoids
  # double-slash noise when testpaths entries already include one.
  [[ -n "$dir" ]] && TEST_DIRS+=("${dir%/}/")
done < "$TESTDIRS_OUT"

if [[ ${#TEST_DIRS[@]} -eq 0 ]]; then
  echo "No tests directory found (checked tests/ and pyproject.toml [tool.pytest.ini_options].testpaths). Skipping pytest. (This is acceptable for shared libraries without a suite.)"
else
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
  # grep -v exits 1 when the inverse filter matches no lines — i.e., the
  # clean-tree case (empty $STATUS_OUT) or the all-untracked case. The
  # `|| true` keeps that benign exit-1 from tripping `set -e`.
  WORKING_TREE_DIRTY=$(grep -v '^??' "$STATUS_OUT" || true)

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
    uv run pytest "${TEST_DIRS[@]}" -v || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
    if [[ -n "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
      touch "$STAMP_FILE"
    fi
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
