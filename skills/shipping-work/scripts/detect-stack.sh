#!/usr/bin/env bash
# detect-stack.sh
# Says what a repo has, so one ship gate serves every repo instead of one
# variant per stack (#537, plan Step 5 rows 1 and 1b).
#
# Two kinds of answer, kept apart on purpose:
#
#   toolchain   decides which CHECKS pre-ship.sh runs. Every one found runs.
#     uv        pyproject.toml plus a uv.lock or a [tool.uv] table. A Poetry
#               or pip project is not one: the gate would `uv run` against a
#               project uv does not manage, so it gets the remedy instead.
#     composer  composer.json at the root, or one level under themes/ or
#               plugins/ (the layout the PHP gate validates).
#     npm       package.json.
#
#   framework   decides only which DOCS apply: doc-check.sh's default watch
#               list and which references/stack-*.md to load. Never a check.
#     fastapi   fastapi is a declared dependency.
#     click     click or typer is, and fastapi is not: a service that pulls
#               in click for a management command is still a service.
#     php       any composer toolchain.
#
# The dependency match is a quoted requirement whose name is exactly the
# framework's, case-insensitive — "fastapi>=0.110", "FastAPI[standard]" — so
# "clickhouse-driver" is not click. It reads pyproject.toml as text rather
# than parsing TOML: this runs before any interpreter is known to exist, and a
# miss only costs a doc default, never a check.
#
# Output: one `kind<TAB>name` line per finding. Nothing found is exit 0 with
# no output.
#
# Usage: bash "<detect-stack.sh>" [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--help]"
  echo ""
  echo "Prints what this repo has, one tab-separated line per finding:"
  echo "  toolchain uv|composer|npm      which checks the ship gate runs"
  echo "  framework fastapi|click|php    which docs apply (never a check)"
  echo ""
  echo "Exit codes:"
  echo "  0  done (no output means nothing was detected)"
  echo "  2  not inside a git repository, or a bad argument"
}

for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$ROOT"

# A quoted requirement named exactly $1: the name, then a version operator,
# an extras bracket, a marker, a space or the closing quote.
declares() {
  grep -qiE "[\"'][[:space:]]*$1[[:space:]]*([][<>=!~;,[:space:]\"']|\$)" pyproject.toml
}

if [[ -f pyproject.toml ]]; then
  if [[ -f uv.lock ]] || grep -qE '^[[:space:]]*\[tool\.uv[].]' pyproject.toml; then
    printf 'toolchain\tuv\n'
  fi
  if declares fastapi; then
    printf 'framework\tfastapi\n'
  elif declares click || declares typer; then
    printf 'framework\tclick\n'
  fi
fi

composer=0
if [[ -f composer.json ]]; then
  composer=1
else
  for f in themes/*/composer.json plugins/*/composer.json; do
    if [[ -f "$f" ]]; then
      composer=1
      break
    fi
  done
fi
if [[ "$composer" -eq 1 ]]; then
  printf 'toolchain\tcomposer\n'
  printf 'framework\tphp\n'
fi

if [[ -f package.json ]]; then
  printf 'toolchain\tnpm\n'
fi
