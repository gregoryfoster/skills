#!/usr/bin/env bash
# cloud-session-start.sh
# The repo's SessionStart hook (#479): provisions a Claude Code cloud session.
#
# A cloud session's clone *is* the main checkout and has no `.venv`, so
# `structural-tests.sh` has nothing to resolve or link and every commit's
# pre-commit chain would fail. This creates the venv, installs
# requirements-test.txt into it, and runs `pre-commit install`.
#
# It does nothing outside a cloud session: the hook is committed to
# .claude/settings.json, so it runs on every local session too, and exits 0
# there before touching anything unless CLAUDE_CODE_REMOTE is `true` — the
# variable the cloud VM sets and a local machine never does.
#
# It runs on `startup` and `resume` alike. A reclaimed VM comes back as a fresh
# one, so a resume can need the whole install again; a stamp of
# requirements-test.txt's blob hash, kept inside .venv, makes a resume on a
# live VM cost one comparison.
#
# System tools (shellcheck, zsh) are the environment's setup script's job, not
# this hook's: the setup script runs as root and is cached. This hook only
# reports which are missing, on stdout, which reaches the session's context.
#
# Usage: bash scripts/cloud-session-start.sh [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--help]"
  echo ""
  echo "SessionStart hook for Claude Code cloud sessions (#479)."
  echo "Exits 0 at once unless CLAUDE_CODE_REMOTE is 'true'. In a cloud"
  echo "session it creates .venv, installs requirements-test.txt into it,"
  echo "runs 'pre-commit install', and reports missing system tools."
  echo ""
  echo "Exit codes:"
  echo "  0  not a cloud session, or the session is provisioned"
  echo "  2  a bad argument, or not inside a git repository"
  echo "  *  otherwise the failing tool's own exit code (uv, pip, pre-commit),"
  echo "     with its stderr shown unchanged"
}

for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

STAMP=.venv/.requirements-test.blob
WANT=$(git hash-object requirements-test.txt)

if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ]; then
  echo "cloud session: .venv already provisioned for requirements-test.txt $WANT"
else
  # uv first: it is preinstalled in the cloud image, and `python3 -m venv`
  # needs Ubuntu's separate python3-venv package.
  if command -v uv >/dev/null; then
    [ -x .venv/bin/python ] || uv venv --quiet .venv
    uv pip install --quiet --python .venv/bin/python -r requirements-test.txt
  else
    [ -x .venv/bin/python ] || python3 -m venv .venv
    .venv/bin/python -m pip install --quiet -r requirements-test.txt
  fi
  printf '%s\n' "$WANT" > "$STAMP"
  echo "cloud session: .venv provisioned from requirements-test.txt $WANT"
fi

.venv/bin/pre-commit install >/dev/null
echo "cloud session: pre-commit hook installed"

missing=()
for tool in shellcheck zsh; do
  command -v "$tool" >/dev/null || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "cloud session: MISSING ${missing[*]} — the environment's setup script should apt-get install them; *_REQUIRED=1 tests will fail"
fi
