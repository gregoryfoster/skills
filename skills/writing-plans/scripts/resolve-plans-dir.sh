#!/usr/bin/env bash
# resolve-plans-dir.sh
# Prints the resolved plans directory for the current repo on stdout.
# Resolution order: PLANS_DIR env var → .skills/plans_dir file → <repo>/docs/plans/
#
# Usage: bash scripts/resolve-plans-dir.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/resolve-plans-dir.sh"
  echo ""
  echo "Prints the resolved plans directory for the current repo on stdout."
  echo ""
  echo "Resolution order (first match wins):"
  echo "  1. PLANS_DIR env var"
  echo "  2. .skills/plans_dir file under the repo root (single-line path)"
  echo "  3. <repo-root>/docs/plans/ (fallback)"
  echo ""
  echo "Exit codes:"
  echo "  0  Resolution succeeded"
  echo "  2  Not inside a git repository"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}

if [[ -n "${PLANS_DIR:-}" ]]; then
  echo "$PLANS_DIR"
  exit 0
fi

CONFIG_FILE="$PROJECT_ROOT/.skills/plans_dir"
if [[ -f "$CONFIG_FILE" ]]; then
  # Read first non-blank, non-comment line. Trim leading/trailing whitespace.
  # `|| true` keeps pipefail from aborting when the file is empty or all
  # comments — that case must fall through to the default, not crash.
  CONFIGURED=$(grep -v '^[[:space:]]*#' "$CONFIG_FILE" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  if [[ -n "$CONFIGURED" ]]; then
    echo "$CONFIGURED"
    exit 0
  fi
fi

echo "$PROJECT_ROOT/docs/plans"
