#!/usr/bin/env bash
# pre-ship.sh (PHP variant)
# Pre-ship gate for PHP/WordPress/Bedrock/Sage 11 monorepos:
#   1. composer validate --no-check-publish at root + every discovered
#      composer dir under themes/ and plugins/
#   2. php -l on ALL tracked PHP files (comprehensive — pre-ship cardinality
#      differs from gather-context, which lints only changed files).
#      Parallelized via xargs -P; override worker count with PRE_SHIP_PHP_LINT_JOBS
#      (default: 4).
#   3. Test runner if the root composer.json defines a "test" script
#
# Exits non-zero if any check fails.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs composer validate at each composer.json, php -l on every tracked"
  echo "PHP file (parallel; PRE_SHIP_PHP_LINT_JOBS=N to tune, default 4), and"
  echo "'composer test' if defined. Fails fast on any error."
  echo ""
  echo "Exit codes:"
  echo "  0 = pass"
  echo "  1 = check failure (composer validate, php -l, or composer test)"
  echo "  2 = tooling/infra failure (composer missing, find failed,"
  echo "      git ls-files failed, mktemp failed)"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

if ! command -v composer >/dev/null; then
  echo "ERROR: composer not installed. This variant is for Composer-managed repos." >&2
  exit 2
fi

FAIL=0
JOBS_DEFAULT=4

# Single trap covers every tempfile created below (find + git ls-files).
# Scalars (not an array) for bash 3.2 + `set -u` compatibility — expanding
# an empty array under set -u errors on stock-macOS bash.
FIND_OUT=""; FIND_ERR=""; LS_OUT=""; LS_ERR=""
trap 'rm -f "$FIND_OUT" "$FIND_ERR" "$LS_OUT" "$LS_ERR"' EXIT

# --- composer validate --------------------------------------------------------

COMPOSER_DIRS=()
[[ -f composer.json ]] && COMPOSER_DIRS+=(".")

# Build find paths dynamically: passing a missing dir to `find` is itself an
# error (non-zero exit + stderr), which would falsely trip the ERROR handler
# below on repos that have only themes/ or only plugins/.
FIND_PATHS=()
[[ -d themes ]] && FIND_PATHS+=(themes)
[[ -d plugins ]] && FIND_PATHS+=(plugins)
if [[ ${#FIND_PATHS[@]} -gt 0 ]]; then
  FIND_OUT=$(mktemp) || { echo "ERROR: mktemp failed (FIND_OUT)" >&2; exit 2; }
  FIND_ERR=$(mktemp) || { echo "ERROR: mktemp failed (FIND_ERR)" >&2; exit 2; }
  FIND_RC=0
  find "${FIND_PATHS[@]}" -mindepth 2 -maxdepth 2 -name composer.json \
    >"$FIND_OUT" 2>"$FIND_ERR" || FIND_RC=$?
  if [[ $FIND_RC -ne 0 ]]; then
    echo "ERROR: find for composer.json failed (exit $FIND_RC):" >&2
    cat "$FIND_ERR" >&2
    exit 2
  fi
  # `find` can exit 0 yet still write to stderr (e.g. permission-denied on a
  # subdir). Surface those without aborting — discovered dirs are still valid.
  if [[ -s "$FIND_ERR" ]]; then
    echo "WARN: find for composer.json wrote diagnostics:" >&2
    cat "$FIND_ERR" >&2
  fi
  while IFS= read -r f; do
    [[ -n "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done < "$FIND_OUT"
fi

echo "=== composer validate ==="
if [[ ${#COMPOSER_DIRS[@]} -eq 0 ]]; then
  echo "No composer.json found. Skipping."
else
  for dir in "${COMPOSER_DIRS[@]}"; do
    echo "--- $dir ---"
    if ! (cd "$dir" && composer validate --no-check-publish); then
      echo "FAIL: composer validate in $dir" >&2
      FAIL=1
    fi
  done
fi

# --- php -l on all tracked PHP files ------------------------------------------

# Run git to a tempfile so its exit code is observable — process substitution
# hides the producer's status. Tempfile also preserves NUL separators.
TRACKED_PHP=()
LS_OUT=$(mktemp) || { echo "ERROR: mktemp failed (LS_OUT)" >&2; exit 2; }
LS_ERR=$(mktemp) || { echo "ERROR: mktemp failed (LS_ERR)" >&2; exit 2; }

LS_RC=0
git ls-files -z '*.php' >"$LS_OUT" 2>"$LS_ERR" || LS_RC=$?
if [[ $LS_RC -ne 0 ]]; then
  echo "ERROR: git ls-files failed (exit $LS_RC):" >&2
  cat "$LS_ERR" >&2
  exit 2
fi

while IFS= read -r -d '' f; do TRACKED_PHP+=("$f"); done < "$LS_OUT"

echo ""
if [[ ${#TRACKED_PHP[@]} -eq 0 ]]; then
  echo "=== php -l (all tracked PHP files) ==="
  echo "No tracked PHP files."
else
  JOBS="${PRE_SHIP_PHP_LINT_JOBS:-$JOBS_DEFAULT}"
  if ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WARN: PRE_SHIP_PHP_LINT_JOBS='$JOBS' invalid (expected positive integer); using $JOBS_DEFAULT." >&2
    JOBS=$JOBS_DEFAULT
  fi
  echo "=== php -l (all tracked PHP files, ${JOBS} parallel workers) ==="
  # xargs returns 123 if any worker exits 1-125; we map that to FAIL=1 and let
  # php -l's stderr (multi-line syntax errors) flow through to the user.
  # shellcheck disable=SC2016  # $1 is expanded by the inner bash -c, intentional
  if ! printf '%s\0' "${TRACKED_PHP[@]}" | xargs -0 -P "$JOBS" -I {} \
      bash -c '[[ -f "$1" ]] || exit 0; php -l "$1" >/dev/null || { echo "FAIL: php -l $1" >&2; exit 1; }' _ {}; then
    FAIL=1
  else
    echo "Lint OK."
  fi
fi

# --- test runner (optional) ---------------------------------------------------

echo ""
echo "=== composer test ==="
if [[ -f composer.json ]] && composer run-script --list 2>/dev/null | grep -qE '^[[:space:]]*test[[:space:]]'; then
  if ! composer test; then
    echo "FAIL: composer test" >&2
    FAIL=1
  fi
else
  echo "No 'test' script defined in composer.json. Skipping."
fi

# --- Optional JS toolchain (auto-detected) -----------------------------------
# Projects with a frontend (e.g., Sage 11 themes built via Bud) ship a
# package.json. Pure-backend repos skip this block entirely without per-
# project override.

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

if [[ $FAIL -ne 0 ]]; then
  echo ""
  echo "Pre-ship checks failed." >&2
  exit 1
fi

echo ""
echo "Pre-ship checks passed."
