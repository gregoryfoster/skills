#!/usr/bin/env bash
# doc-check.sh (PHP variant)
# Spot-check that documentation inventories haven't drifted from code.
#
# Lists files changed on the current branch vs the upstream default branch,
# and flags any that match SENSITIVE_PATHS — files whose existence, names,
# or structure is referenced from project docs (e.g., AGENTS.md, README.md).
# When sensitive paths change, the matching documentation sections likely
# need updates too.
#
# WP/Bedrock/Sage 11 defaults below. Projects can override SENSITIVE_PATHS
# in a thin local fork. Exits 0 if no sensitive paths changed, 1 if any did,
# or 2 on an infra/tooling failure that prevented the check from running.
#
# Usage: bash scripts/doc-check.sh [--help] [--base <ref>]
set -euo pipefail

# --- Project-configurable section ---------------------------------------------
SENSITIVE_PATHS=(
  "AGENTS.md"
  "README.md"
  "composer.json"
  "composer.lock"
  "package.json"
  "web/app/themes/"
  "web/app/plugins/"
  "web/app/acf-json/"
  ".env.example"
)
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory, CPT/Skills tables"
  "README.md: feature list, install/run instructions"
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
  echo "Exit codes:"
  echo "  0  no sensitive paths changed (or no changes at all)"
  echo "  1  one or more sensitive paths changed"
  echo "  2  infra/tooling failure — the gate did not run. Covers: missing"
  echo "     --base argument, base ref auto-detection exhausted, or git diff"
  echo "     failed. Other unexpected failures (e.g., not in a git repo) may"
  echo "     surface git's own exit code instead; check stderr in either case."
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

CHANGED=""
DIFF_RC=0
CHANGED=$(git diff --name-only "${BASE_REF}...HEAD") || DIFF_RC=$?
if [[ $DIFF_RC -ne 0 ]]; then
  echo "ERROR: git diff --name-only ${BASE_REF}...HEAD failed (exit $DIFF_RC)" >&2
  exit 2
fi

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
