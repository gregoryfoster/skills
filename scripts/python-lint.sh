#!/usr/bin/env bash
# python-lint.sh
# The `python-lint` pre-commit hook's entry (#246).
#
# Runs the repo's Python gate — `ruff check` then `ruff format --check` over
# the whole tree, configured by `[tool.ruff]` in pyproject.toml.
#
# It exists as a hook of its own, ahead of the structural suite, for the same
# reason the context-budget gate does: a formatting breach should fail in
# ~1s rather than after the ~4 min suite. The suite still carries the gate
# (`tests/structural/test_python_lint.py`) so that a run outside pre-commit —
# CI, a bare `pytest` — is gated too; this script is the fast, surface-level
# spelling of the same check, not a second source of truth.
#
# Venv resolution is delegated to `structural-tests.sh --check` rather than
# reimplemented. That script already links a linked worktree's missing `.venv`
# to the main checkout's, and duplicating the logic here is how #156 would
# come back: a hook that dies with bash's raw "No such file or directory"
# after the work is done.
#
# The ruff version is pinned exactly in requirements-test.txt, and checked
# below, because `ruff format`'s output is defined by the build that produced
# it — a mismatched build reports a committed-clean tree as dirty. The same
# pin is asserted from the other side by `TestThePinIsSingleSourced`.
#
# Usage: bash scripts/python-lint.sh [--fix] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--fix]"
  echo ""
  echo "Runs ruff check and ruff format --check over the repo."
  echo ""
  echo "Options:"
  echo "  --fix    Apply fixes instead of reporting: ruff check --fix, ruff format."
  echo ""
  echo "Exit codes:"
  echo "  0  clean — with --fix, every finding was fixed and the tree formatted"
  echo "  1  findings remain (with --fix: the ones ruff could not fix; the"
  echo "     format pass still ran), or no usable .venv, or no ruff in it"
  echo "  2  not inside a git repository, or a bad argument"
  echo "  3  the venv's ruff is not the version requirements-test.txt pins,"
  echo "     or could not be asked"
}

# Every argument, not just the first — the same reason structural-tests.sh
# checks them all: a gate that rejects `--bogus` but swallows `--fix --bogus`
# teaches callers to stop reading its output.
FIX=0
for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    --fix) FIX=1 ;;
    "") ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

# BEFORE the cd below, not after. $BASH_SOURCE is the path as invoked, so
# `cd tests && bash ../scripts/python-lint.sh` leaves it relative — and
# resolving it after cd'ing to the repo root sends `../scripts` one level ABOVE
# the repo, where the script exits with bash's raw "cd: ../scripts: No such
# file or directory". That raw-error-after-the-work shape is #156 itself, which
# this script's own header cites; the ordering is the whole fix.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

# Resolve (or link) the venv, and let that script own the diagnosis when it
# cannot: it names the remedy for both the worktree and the fresh-clone case.
bash "${SCRIPT_DIR}/structural-tests.sh" --check

RUFF="${REPO_ROOT}/.venv/bin/ruff"
if [[ ! -x "$RUFF" ]]; then
  echo "ERROR: no ruff in ${REPO_ROOT}/.venv — the Python gate cannot run." >&2
  echo "  Install it:  source .venv/bin/activate && pip install -r requirements-test.txt" >&2
  exit 1
fi

# The pin, read from the one file that installs it, so this script cannot
# drift from the venv it is about to invoke.
# Three components required, matching _REQUIREMENTS_PIN_RE in
# tests/structural/test_python_lint.py exactly. A looser pattern here would
# accept a `ruff==0.16` the suite rejects, which splits the single source of
# truth the two halves exist to keep. `q` stops at the FIRST ruff== line, so a
# malformed one is reported rather than skipped over in favour of a later one,
# and PIN can never become the multi-line concatenation of two matches.
PIN=$(sed -n '/^ruff==/{s/^ruff==\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)[[:space:]]*$/\1/p;q;}' \
  "${REPO_ROOT}/requirements-test.txt")
if [[ -z "$PIN" ]]; then
  echo "ERROR: requirements-test.txt has no exact 'ruff==X.Y.Z' line." >&2
  echo "  The gate needs one specific build; see tests/structural/test_python_lint.py." >&2
  exit 3
fi
# Not a bare assignment: under `set -euo pipefail` a ruff that cannot run —
# corrupt install, wrong architecture — would abort the script here with no
# message at all, on the commit path, which is the one place a gate must
# explain itself.
FOUND=$("$RUFF" --version | awk '{print $2}') || {
  echo "ERROR: ${RUFF} could not report its version (exit $?)." >&2
  echo "  Reinstall:  source .venv/bin/activate && pip install -r requirements-test.txt" >&2
  exit 3
}
if [[ "$FOUND" != "$PIN" ]]; then
  echo "ERROR: .venv has ruff ${FOUND}, but requirements-test.txt pins ${PIN}." >&2
  echo "  'ruff format' output is version-defined, so a mismatched build reports" >&2
  echo "  a committed-clean tree as needing reformatting." >&2
  echo "  Fix:  source .venv/bin/activate && pip install -r requirements-test.txt" >&2
  exit 3
fi

# Both passes run in both modes, and neither short-circuits the other.
#
# Reporting: naming only the first failure hides the second, and the two have
# different remedies (`--fix` vs `ruff format .`).
#
# Fixing: `check --fix` exits non-zero on anything it could NOT fix — E741, say
# — and under `set -e` that would skip the format pass entirely, so `--fix`
# would leave the tree unformatted in exactly the case a caller most needs both
# passes to have run. The unfixable findings are still real, so the status is
# carried to the exit rather than swallowed.
status=0
if [[ $FIX -eq 1 ]]; then
  "$RUFF" check --fix . || status=1
  "$RUFF" format . || status=1
else
  "$RUFF" check . || status=1
  "$RUFF" format --check . || status=1
fi
exit "$status"
