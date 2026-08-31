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
# Python/FastAPI defaults below. Projects tailor them by committing
# `.skills/doc-sensitive-paths` at the repo root — no fork required. Exits 0
# if no sensitive paths changed, 1 if any did, or 2 on an infra/tooling
# failure that prevented the check from running.
#
# Usage: bash <SKILL_SCRIPTS>/doc-check.sh [--help] [--base <ref>]
set -euo pipefail

# --- Project-configurable section ---------------------------------------------
# Add paths (one per line) — exact filenames, or directory prefixes ending in /.
# Entries match path SEGMENTS, not just the start of the path: `src/` matches
# `src/x.py` and `packages/co-core/src/x.py`, and `pyproject.toml` matches the
# root file and `packages/*/pyproject.toml`. Nested-package layouts (uv and
# hatch workspaces, Bedrock plugin trees) are the ordinary shape of the stacks
# these skills target, and root-anchored matching missed every file in them
# while still printing a clean green (#252). The cost of segment matching is
# that vendored and generated trees match too; for a spot-check that exits 1
# and asks a human to look, over-matching is the cheap failure and
# under-matching is the expensive one. Do not re-anchor these patterns.
#
# Projects tailor the list without forking this script by committing
# `.skills/doc-sensitive-paths` at the repo root — one path per line, blank
# lines and `#`-comments ignored, same grammar as `.skills/import-targets`.
# That file REPLACES the defaults below rather than extending them.
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
# Sections in AGENTS.md / README.md to spot-check when drift is detected.
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory, route table"
  "README.md: orientation + curated links into canonical docs; only the README-owned bits (e.g. top-level CLI list, two-line quick start) should change here"
)
# ------------------------------------------------------------------------------

usage() {
  echo "Usage: bash \"$0\" [--help] [--base <ref>]"
  echo ""
  echo "Lists files changed on the current branch vs the upstream default branch"
  echo "and flags any that match the project's sensitive-path list."
  echo ""
  echo "  --base <ref>   Compare against <ref> instead of the auto-detected default."
  echo ""
  echo "Path list: .skills/doc-sensitive-paths at the repo root when present (one"
  echo "path per line), otherwise the built-in defaults. Entries match path"
  echo "segments, so src/ also matches packages/<pkg>/src/."
  echo ""
  echo "Exit codes:"
  echo "  0  no sensitive paths changed (or no changes at all)"
  echo "  1  one or more sensitive paths changed"
  echo "  2  infra/tooling failure — the gate did not run. Covers: an unknown or"
  echo "     incomplete argument, a base ref auto-detection failure, a git diff"
  echo "     failure, an empty .skills/doc-sensitive-paths, or a path list where"
  echo "     no entry matches any tracked file (a list that cannot hit anything"
  echo "     is not a pass). Other unexpected failures (e.g., running outside a"
  echo "     git repo) may surface git's own exit code instead; check stderr in"
  echo "     either case."
}

BASE_REF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --base)
      BASE_REF="${2:-}"
      if [[ -z "$BASE_REF" ]]; then
        echo "ERROR: --base requires a ref argument" >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      # Silently ignoring an unrecognized argument would compare against the
      # auto-detected base and report a confident result for the wrong diff.
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

# Project override: .skills/doc-sensitive-paths replaces the defaults wholesale.
LIST_SOURCE="built-in defaults"
if [[ -f .skills/doc-sensitive-paths ]]; then
  OVERRIDE=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    # Pure-bash trim of leading/trailing whitespace (no fork+pipe per line).
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    OVERRIDE+=("$line")
  done < .skills/doc-sensitive-paths
  if [[ ${#OVERRIDE[@]} -eq 0 ]]; then
    echo "ERROR: .skills/doc-sensitive-paths exists but lists no paths." >&2
    echo "Remove the file to fall back to the built-in defaults." >&2
    exit 2
  fi
  SENSITIVE_PATHS=("${OVERRIDE[@]}")
  LIST_SOURCE=".skills/doc-sensitive-paths"
fi

# Segment match. A directory entry (trailing /) matches at any depth; a
# filename entry matches a whole final component. The two cases differ
# deliberately — a trailing * on a filename entry would also match
# pyproject.toml.bak and pyproject.tomlish.
path_matches() {
  local file="$1" entry="$2"
  if [[ "$entry" == */ ]]; then
    case "$file" in "$entry"*|*"/$entry"*) return 0 ;; esac
  else
    case "$file" in "$entry"|*"/$entry") return 0 ;; esac
  fi
  return 1
}

# Resolve base ref: explicit > origin/HEAD > origin/main > main
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
  for entry in "${SENSITIVE_PATHS[@]}"; do
    if path_matches "$file" "$entry"; then
      HITS+=("$file")
      break
    fi
  done
done <<< "$CHANGED"

if [[ ${#HITS[@]} -eq 0 ]]; then
  # A list that matches nothing in the tree prints exactly what a genuinely
  # doc-neutral branch prints, so its miss is indistinguishable from its pass.
  # Probe the tree here and only here, where that ambiguity lives: on the
  # exit-1 path the list has demonstrably hit, and a dead-entry census would
  # be noise. The probe reuses path_matches so it cannot disagree with the
  # matcher it is vouching for.
  LIVE=()
  for i in "${!SENSITIVE_PATHS[@]}"; do
    LIVE[i]=0
  done
  while IFS= read -r file; do
    for i in "${!SENSITIVE_PATHS[@]}"; do
      if [[ ${LIVE[i]} -eq 0 ]] && path_matches "$file" "${SENSITIVE_PATHS[i]}"; then
        LIVE[i]=1
      fi
    done
  done < <(git ls-files)

  DEAD=()
  for i in "${!SENSITIVE_PATHS[@]}"; do
    if [[ ${LIVE[i]} -eq 0 ]]; then
      DEAD+=("${SENSITIVE_PATHS[i]}")
    fi
  done

  if [[ ${#DEAD[@]} -eq ${#SENSITIVE_PATHS[@]} ]]; then
    echo "ERROR: no entry in the sensitive-path list ($LIST_SOURCE) matches any" >&2
    echo "tracked file, so this check could not have found anything. The list is" >&2
    echo "misconfigured for this repo — that is a gate that did not run, not a pass:" >&2
    printf '  - %s\n' "${SENSITIVE_PATHS[@]}" >&2
    echo "Tailor it in .skills/doc-sensitive-paths (one path per line)." >&2
    exit 2
  fi

  # Name the list on every verdict. A green that does not say what it consulted
  # cannot be audited by the reader who most needs to — the one wondering
  # whether this repo ever tailored the list at all.
  echo "No sensitive paths changed vs $BASE_REF (list: $LIST_SOURCE)."
  if [[ ${#DEAD[@]} -gt 0 ]]; then
    echo ""
    echo "Note: these entries ($LIST_SOURCE) match no tracked file, so they could"
    echo "not have contributed to that result:"
    printf '  - %s\n' "${DEAD[@]}"
  fi
  exit 0
fi

echo "Sensitive paths changed vs $BASE_REF (list: $LIST_SOURCE):"
printf '  - %s\n' "${HITS[@]}"
echo ""
echo "Spot-check these doc sections before shipping:"
printf '  - %s\n' "${DOC_SECTIONS[@]}"
exit 1
