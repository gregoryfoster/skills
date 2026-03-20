#!/usr/bin/env bash
# pre-ship.sh
# Stub: runs the project's test suite before shipping.
#
# This script must be overridden by the consuming project's local skill override.
# The global shipping-work-claude skill cannot know the project's test runner.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs the project test suite. Must be overridden in the consuming project."
  echo "The global skill provides this stub only — replace with your test runner."
  exit 0
fi

echo "ERROR: pre-ship.sh is a stub. The consuming project must override this script." >&2
echo "       Copy shipping-work-claude/ into your project's skills/ directory and" >&2
echo "       replace this file with your test runner (e.g., uv run pytest)." >&2
exit 1
