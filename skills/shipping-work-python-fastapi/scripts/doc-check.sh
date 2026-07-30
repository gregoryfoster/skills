#!/usr/bin/env bash
# doc-check.sh (Python/FastAPI variant)
# Spot-check that documentation inventories haven't drifted from code.
#
# Lists files changed on the current branch vs the upstream default branch,
# and flags any that match SENSITIVE_PATHS — files whose existence, names,
# or structure is referenced from project docs (e.g., AGENTS.md, README.md).
# When sensitive paths change, the matching documentation sections likely
# need updates too.
#
# Python/FastAPI defaults below. Projects can override SENSITIVE_PATHS in a
# thin local fork. Exits 0 if no sensitive paths changed, 1 if any did, or
# 2 on an infra/tooling failure that prevented the check from running.
#
# Usage: bash <SKILL_SCRIPTS>/doc-check.sh [--help] [--base <ref>]
set -euo pipefail

# --- Project-configurable section ---------------------------------------------
# Add paths (one per line) — exact filenames or directory prefixes ending in /.
# Entries are matched literally, not as globs. Defaults are conservative;
# projects should tailor them.
SENSITIVE_PATHS=(
  "AGENTS.md"
  "README.md"
  "CHANGELOG.md"
  "pyproject.toml"
  "uv.lock"
  "schema.sql"
  "alembic/versions/"
  "deploy/"
  "src/api/"
  "src/models/"
  "src/core/"
  ".env.example"
)
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory, route table"
  "README.md: orientation + curated links into canonical docs; only the README-owned bits (e.g. top-level CLI list, two-line quick start) should change here"
)
# ------------------------------------------------------------------------------

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\" [--base <ref>]"
  echo ""
  echo "Lists files changed on the current branch vs the upstream default branch"
  echo "and flags any that match the project's SENSITIVE_PATHS list."
  echo ""
  echo "  --base <ref>   Compare against <ref> instead of the auto-detected default."
  echo ""
  echo "Exit codes:"
  echo "  0  no sensitive paths changed (or no changes at all)"
  echo "  1  one or more sensitive paths changed"
  echo "  2  infra/tooling failure — the gate did not run. Covers: a missing"
  echo "     --base argument, a base ref auto-detection failure, or a git diff"
  echo "     failure. Other unexpected failures (e.g., running outside a git"
  echo "     repo) may surface git's own exit code instead; check stderr in"
  echo "     either case."
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
  for prefix in "${SENSITIVE_PATHS[@]}"; do
    case "$file" in
      "$prefix"|"$prefix"*) HITS+=("$file"); break ;;
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
