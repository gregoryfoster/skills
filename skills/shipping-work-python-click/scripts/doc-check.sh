#!/usr/bin/env bash
# doc-check.sh (Python/Click variant)
# Spot-check that documentation inventories haven't drifted from code.
#
# Lists files changed on the current branch vs the upstream default branch,
# and flags any that match SENSITIVE_PATHS — files whose existence, names,
# or structure is referenced from project docs (e.g., AGENTS.md, README.md).
# When sensitive paths change, the matching documentation sections likely
# need updates too.
#
# Python/Click defaults below. Projects can override SENSITIVE_PATHS in a
# thin local fork. Exits 0 if no sensitive paths changed, 1 if any did.
#
# Usage: bash scripts/doc-check.sh [--help] [--base <ref>]
set -euo pipefail

# --- Project-configurable section ---------------------------------------------
SENSITIVE_PATHS=(
  "AGENTS.md"
  "README.md"
  "pyproject.toml"
  "uv.lock"
  "src/"
  ".env.example"
)
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory, command inventory"
  "README.md: feature list, install/run instructions, env var inventory, --help examples"
)
# ------------------------------------------------------------------------------

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/doc-check.sh [--base <ref>]"
  echo ""
  echo "Lists files changed on the current branch vs the upstream default branch"
  echo "and flags any that match the project's SENSITIVE_PATHS list."
  echo ""
  echo "  --base <ref>   Compare against <ref> instead of the auto-detected default."
  echo ""
  echo "Exits 0 if no sensitive paths changed, 1 otherwise."
  exit 0
fi

BASE_REF=""
if [[ "${1:-}" == "--base" ]]; then
  BASE_REF="${2:-}"
  if [[ -z "$BASE_REF" ]]; then
    echo "ERROR: --base requires a ref argument" >&2
    exit 2
  fi
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

if [[ -z "$BASE_REF" ]]; then
  if git rev-parse --verify --quiet origin/HEAD >/dev/null; then
    BASE_REF=$(git rev-parse --abbrev-ref origin/HEAD)
  elif git rev-parse --verify --quiet origin/main >/dev/null; then
    BASE_REF="origin/main"
  elif git rev-parse --verify --quiet main >/dev/null; then
    BASE_REF="main"
  else
    echo "ERROR: could not resolve a base ref. Pass --base <ref>." >&2
    exit 2
  fi
fi

CHANGED=$(git diff --name-only "${BASE_REF}...HEAD" 2>/dev/null || true)

if [[ -z "$CHANGED" ]]; then
  echo "No changes vs $BASE_REF."
  exit 0
fi

HITS=()
while IFS= read -r file; do
  for pattern in "${SENSITIVE_PATHS[@]}"; do
    case "$file" in
      $pattern|$pattern*) HITS+=("$file"); break ;;
    esac
  done
done <<< "$CHANGED"

if [[ ${#HITS[@]} -eq 0 ]]; then
  echo "No sensitive paths changed vs $BASE_REF."
  exit 0
fi

echo "Sensitive paths changed vs $BASE_REF:"
printf '  - %s\n' "${HITS[@]}"
echo ""
echo "Spot-check these doc sections before shipping:"
printf '  - %s\n' "${DOC_SECTIONS[@]}"
exit 1
