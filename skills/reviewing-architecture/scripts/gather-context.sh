#!/usr/bin/env bash
# gather-context.sh
# Prints a structured architectural snapshot of the repo.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Every list that is truncated discloses how many entries were omitted — a
# whole-system review must never silently see a partial system.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints, for the enclosing git repo:"
  echo "  - directory tree, source file sizes, dependency manifests, recent commits"
  echo "  - internal import fan-in (which modules everything depends on)"
  echo "  - churn hotspots and temporal coupling mined from git history"
  echo "Every truncated list discloses the omitted count. Resolves the git root"
  echo "regardless of invocation directory."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

# Print at most $2 lines of stdin, then disclose how many were omitted.
# Usage: some_command | capped "<label>" <limit>
capped() {
  local label="$1" limit="$2" buf total
  buf=$(cat)
  [ -n "$buf" ] || return 0          # empty section: emit nothing, not a blank line
  total=$(printf '%s\n' "$buf" | grep -c . || true)
  # Here-string, not `printf | head`: a pipe lets head close the read end after
  # $limit lines while the writer is mid-stream, and the resulting SIGPIPE under
  # `set -o pipefail` would abort the whole script on any repo larger than the
  # pipe buffer — silently truncating the very snapshot this is meant to disclose.
  head -n "$limit" <<<"$buf"
  if [ "$total" -gt "$limit" ]; then
    echo "... ($((total - limit)) more $label omitted; $total total)"
  fi
}

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Directory tree (depth 3) ==="
find . -not -path '*/.git/*' -not -path '*/__pycache__/*' \
       -not -path '*/.venv/*' -not -path '*/node_modules/*' \
       -not -path '*/.mypy_cache/*' -not -path '*/.ruff_cache/*' \
       -not -path '*/.pytest_cache/*' \
  | sort | capped "entries" 250

echo ""
echo "=== File sizes (lines) ==="
# Strip the trailing `total` line wc emits for multi-file runs (it otherwise
# sorts to the top as the largest number and masquerades as the biggest file).
find . \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
          -o -name '*.jsx' -o -name '*.go' -o -name '*.rb' \) \
  -not -path '*/.git/*' -not -path '*/.venv/*' -not -path '*/node_modules/*' \
  -not -path '*/__pycache__/*' -print0 \
  | xargs -0 wc -l 2>/dev/null | grep -vE '[[:space:]]total$' | sort -rn \
  | capped "files" 60

echo ""
echo "=== Internal import fan-in (Python) ==="
# Cheap dependency-direction signal without a full graph: for each first-party
# top-level package, how many source files import it. High fan-in = a module the
# whole system leans on (a boundary/god-module candidate). When SocratiCode is
# indexed, prefer codebase_graph_circular / codebase_impact for real edges.
local_pkgs=$(find . -maxdepth 2 -name '__init__.py' \
               -not -path '*/.venv/*' -not -path '*/node_modules/*' 2>/dev/null \
             | sed -E 's#^\./##; s#/__init__\.py$##; s#/.*##' | sort -u || true)
top_py=$(find . -maxdepth 1 -name '*.py' 2>/dev/null | sed -E 's#^\./##; s#\.py$##' || true)
local_set=$(printf '%s\n%s\n' "$local_pkgs" "$top_py" | grep -c . || true)
if [ "${local_set:-0}" -eq 0 ]; then
  echo "(no Python packages detected — for other stacks, inspect imports manually"
  echo " or use the SocratiCode graph tools)"
else
  # Build a regex alternation of first-party top-level names, then count how
  # often each is the import target across all .py files. `-Ex '<ident>'` keeps
  # only valid Python identifiers, so a stray non-module filename can't inject a
  # regex metacharacter into the alternation below (also drops blank lines).
  names=$(printf '%s\n%s\n' "$local_pkgs" "$top_py" \
    | grep -Ex '[A-Za-z_][A-Za-z0-9_]*' | sort -u | paste -sd'|' - || true)
  if [ -z "$names" ]; then
    echo "(no first-party imports found)"
  else
    grep -rhoE "^[[:space:]]*(from|import)[[:space:]]+($names)\b" \
      --include='*.py' \
      --exclude-dir=.venv --exclude-dir=node_modules \
      --exclude-dir=.git --exclude-dir=__pycache__ . 2>/dev/null \
      | sed -E "s/^[[:space:]]*(from|import)[[:space:]]+//; s/[[:space:]].*//; s/\..*//" \
      | sort | uniq -c | sort -rn | capped "modules" 25 \
      || echo "(no first-party imports found)"
  fi
fi

echo ""
echo "=== Churn hotspots (last 300 commits) ==="
# Files changed most often. Cross-reference with File sizes: high churn × high
# line-count = a decaying hotspot worth splitting.
git log --format= --name-only -n 300 -- \
    '*.py' '*.ts' '*.tsx' '*.js' '*.jsx' '*.go' '*.rb' 2>/dev/null \
  | grep -v '^$' | sort | uniq -c | sort -rn | capped "files" 20 \
  || echo "(no history)"

echo ""
echo "=== Temporal coupling (files that change together) ==="
# Pairs of files co-edited in the same commit across the last 300 commits.
# Commits touching >15 files are skipped (bulk renames/formatting drown signal).
# A high-count pair in different modules is hidden coupling the import graph misses.
# `format:@` (not a bare `@`, which git rejects as an invalid pretty format)
# prints a lone `@` line per commit as the record separator awk splits on.
git log --format=format:@ --name-only -n 300 -- \
    '*.py' '*.ts' '*.tsx' '*.js' '*.jsx' '*.go' '*.rb' 2>/dev/null \
  | awk '
      /^@$/ { emit(); n = 0; next }
      NF    { files[n++] = $0 }
      END   { emit() }
      function emit(   i, j, a, b, key) {
        if (n < 2 || n > 15) return
        for (i = 0; i < n; i++)
          for (j = i + 1; j < n; j++) {
            a = files[i]; b = files[j]
            key = (a < b) ? a "\t" b : b "\t" a
            pair[key]++
          }
      }
      END {
        for (k in pair) if (pair[k] >= 3) print pair[k] "\t" k
      }
    ' 2>/dev/null | sort -rn | capped "pairs" 15 \
  || echo "(no history)"

echo ""
echo "=== Dependency manifest ==="
found=0
for f in pyproject.toml package.json go.mod Gemfile requirements.txt; do
  if [ -f "$f" ]; then
    echo "--- $f ---"
    cat "$f"
    echo ""
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "(none found)"

echo ""
echo "=== Recent commits ==="
git log --oneline -15 2>/dev/null || true

echo ""
echo "=== Architecture-graph tools ==="
echo "If SocratiCode is indexed for this project, use it for evidence the static"
echo "snapshot above cannot give — real dependency edges, cycles, and blast radius:"
echo "  codebase_graph_circular  — import cycles"
echo "  codebase_graph_query     — fan-in/fan-out for a module"
echo "  codebase_impact          — blast radius of changing a file"
echo "  codebase_graph_visualize — layering / direction overview"
