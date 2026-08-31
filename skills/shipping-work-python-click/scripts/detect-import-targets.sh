#!/usr/bin/env bash
# detect-import-targets.sh
# Resolves Python package names for the import check. Emits one name per
# line to stdout. Resolution order:
#   1. .skills/import-targets at the repo root (committed override; one
#      package per line, blank lines and `#`-comments ignored)
#   2. tomllib-parsed [project] name from pyproject.toml, with hyphens
#      normalized to underscores
#
# Detection errors are reported on stderr (uv warnings included — accept
# the noise so a broken pyproject.toml or an unusual layout doesn't fail
# silently). The script exits 0 with no stdout when nothing is found.
#
# Shared between gather-context.sh (reviewing-code-python-click) and
# pre-ship.sh (shipping-work-python-click) — review and ship must agree
# on the import target, so the resolution logic lives in one place.
#
# Exit codes:
#   0  resolved (possibly to nothing — an empty answer is a valid one)
#   2  the resolver could not run. Never reported as "no import target":
#      pre-ship.sh skips the import check on an empty list, so a silent
#      tooling failure here ships a commit nothing was imported for (#255).
#
# Usage: bash <SKILL_SCRIPTS>/detect-import-targets.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Emits one Python package name per line to stdout."
  echo "Resolution: .skills/import-targets > pyproject.toml [project] name."
  echo "Detection errors go to stderr; exits 0 with empty stdout when nothing detected."
  echo ""
  echo "Exit codes:"
  echo "  0  resolved (an empty list is a valid answer)"
  echo "  2  the resolver could not run (uv failed, mktemp failed) — a"
  echo "     tooling failure must not read as 'this project has no package'"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

if [[ -f .skills/import-targets ]]; then
  # `|| [[ -n "$pkg" ]]` keeps the final line when the file has no trailing
  # newline — otherwise a one-line list written by an editor that omits it
  # resolves to nothing, and the import check silently targets the
  # pyproject.toml name the override existed to replace. doc-check.sh reads
  # .skills/doc-sensitive-paths with the same guard.
  while IFS= read -r pkg || [[ -n "$pkg" ]]; do
    [[ -z "$pkg" || "$pkg" =~ ^[[:space:]]*# ]] && continue
    # Pure-bash trim of leading/trailing whitespace (no fork+pipe per line).
    pkg="${pkg#"${pkg%%[![:space:]]*}"}"
    pkg="${pkg%"${pkg##*[![:space:]]}"}"
    [[ -z "$pkg" ]] && continue
    echo "$pkg"
  done < .skills/import-targets
elif [[ -f pyproject.toml ]] && command -v uv >/dev/null 2>&1; then
  # Scalar RC capture rather than `… || true`: this name drives a gate, and
  # `|| true` discards the one signal separating "this project has no [project]
  # name" from "uv could not run at all" (docs/STYLE.md, "Gate-script
  # discipline"; the sibling spelling AGENTS.md gates as an unchecked write).
  # pre-ship.sh skips the import check entirely on an empty answer, so the
  # discarded failure shipped as a passed gate — and its own careful exit-code
  # capture around this script could not see it (#255).
  #
  # The python snippet catches its own parse errors and still exits 0, so a
  # non-zero code here is uv itself failing. `import tomllib` sits INSIDE that
  # try for the same reason: on a project pinned to Python 3.10 it is a
  # detection limit, not a broken toolchain.
  TARGET_OUT=$(mktemp) || { echo "detect-import-targets: mktemp failed" >&2; exit 2; }
  trap 'rm -f "$TARGET_OUT"' EXIT
  UV_RC=0
  uv run python -c "
import sys
try:
    import tomllib
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.load(f)
    name = data.get('project', {}).get('name', '')
    if name:
        print(name.replace('-', '_'))
except Exception as e:
    print(f'detect-import-targets: {e}', file=sys.stderr)
" >"$TARGET_OUT" || UV_RC=$?
  if [[ $UV_RC -ne 0 ]]; then
    echo "detect-import-targets: uv run python failed (exit $UV_RC) reading [project] name" >&2
    exit 2
  fi
  cat "$TARGET_OUT"
fi
