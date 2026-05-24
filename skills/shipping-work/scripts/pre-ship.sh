#!/usr/bin/env bash
# pre-ship.sh
# Stub: runs the project's test suite before shipping.
#
# This script must be overridden by the consuming project's local skill override.
# The global shipping-work skill cannot know the project's test runner.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs the project test suite. Must be overridden in the consuming project."
  echo "The global skill provides this stub only — replace with your test runner."
  echo "If package.json is present, also runs npm lint/format/test scripts (these"
  echo "gates run even in the stub so a downstream override that only swaps the"
  echo "test-runner block inherits the hardened JS toolchain pattern verbatim)."
  exit 0
fi

# --- Optional JS toolchain (auto-detected) -----------------------------------
# The stub itself does not run a test runner — overrides supply that. The JS
# toolchain block is kept here so a downstream project that only swaps the
# `exit 1` stub for a real Python/Node test invocation inherits the hardened
# four-element pattern (node pre-flight, JSON pre-validation, `has_script`
# helper, per-script gates) verbatim — matching the FastAPI/Click/PHP siblings.

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

echo "ERROR: pre-ship.sh is a stub. The consuming project must override this script." >&2
echo "       Copy shipping-work/ into your project's skills/ directory and" >&2
echo "       replace this file with your test runner (e.g., uv run pytest)." >&2
exit 1
