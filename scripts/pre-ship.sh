#!/usr/bin/env bash
# pre-ship.sh
# This repo's ship gate — the `shipping-work` Step 1 entry point (#318).
#
# The skill's own pre-ship.sh is a stub that exits 1, because the global skill
# cannot know a project's test runner. This file is the answer for THIS repo,
# and it lives at the repo root rather than in a forked `skills/shipping-work/`
# because Step 1 resolves each script separately (#301): a repo-root
# `scripts/pre-ship.sh` wins for this gate alone, and doc-check, check-status,
# push, comment-issue and close-issue all keep resolving to the skill through
# `.claude/skills` -> `../skills`. Forking the skill into a sibling override of
# itself would leave no upstream to track, which is the drift `overrides:` and
# `synced-from:` exist to prevent.
#
# WHAT IT RUNS, and why in this order
#
# The three pre-commit hooks, in the order .pre-commit-config.yaml runs them:
# the context-budget gate, ruff, then the structural suite. A ship gate that
# ran a different set than the commit path would be a second source of truth;
# it runs the same three because `pre-commit install` is a manual step
# (AGENTS.md, "Dev setup") and a commit can be made with --no-verify. This is
# the belt to pre-commit's braces, not a replacement for it.
#
# Ahead of all three is a venv preflight, and it is load-bearing rather than
# tidy: `structural-tests.sh` exits 1 for BOTH "no usable .venv" and "pytest
# reported failures", so the same code means "fix your environment" and "fix
# your code". Resolving the venv first, through that script's own --check mode,
# makes a later 1 unambiguously a test failure. Delegating the resolution also
# keeps #156's worktree-symlink fix in one place; python-lint.sh already does
# the same.
#
# WHAT IT DOES NOT RUN
#
# - `tests/integration/` — billed, needs .env, and AGENTS.md states it is never
#   wired to pre-push. A ship gate that quietly acquired it would spend money
#   on every ship. Run it by hand: scripts/run-integration-tests.sh.
# - The skill stub's `package.json` / npm block. This is a skills library; it
#   has no frontend and will not grow one, so an auto-detect that can never
#   fire is dead weight that still has to be read and maintained.
#
# The stub's other inherited piece, the worktree-zombie audit, IS kept: this
# repo works in linked worktrees constantly, and the audit warns without
# failing, which is the right weight for drift the destroy script cannot see.
#
# FAIL-FAST
#
# The first failing gate ends the run; later gates do not report. That matches
# .pre-commit-config.yaml, which marks the budget and lint hooks fail_fast for
# a measured reason — a 0.1s breach should not cost a ~4min suite run before
# anyone hears about it. The trade is real and is the same one documented
# there: a lint failure hides suite failures until the next run. It is accepted
# for the same reason, and the cheap gates run first so the hidden window is
# small.
#
# EXIT CODES: normalized, because the delegates disagree
#
# Left alone, the three delegates return overlapping codes with different
# meanings (structural-tests 1 = no venv OR failures; python-lint 3 = ruff
# version mismatch; measure-context 4 = over budget). Propagating that union
# would make the --help block below a lie. So this script collapses them to the
# gate-script convention used across skills/: 1 = a gate found something, 2 =
# the gate could not run. Every delegate's own stderr is passed through
# untouched, so the specific diagnosis is never lost — only the code is
# normalized.
#
# Usage: bash "<pre-ship.sh>" [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--help]"
  echo ""
  echo "This repo's ship gate. Runs, in .pre-commit-config.yaml's order:"
  echo "  preflight  scripts/structural-tests.sh --check   (resolve/link .venv)"
  echo "  warn-only  worktree-zombie audit, if the script is present"
  echo "  gate 1/3   measure-context.sh --gate   (AGENTS.md vs .skills/context-budget)"
  echo "  gate 2/3   scripts/python-lint.sh      (ruff check + ruff format --check)"
  echo "  gate 3/3   scripts/structural-tests.sh (pytest tests/structural/)"
  echo ""
  echo "The first failing gate ends the run; later gates do not report."
  echo "tests/integration/ is deliberately NOT run: it is billed and needs .env."
  echo "Run it by hand with scripts/run-integration-tests.sh."
  echo ""
  echo "Options:"
  echo "  --help   Show this text and exit 0."
  echo ""
  echo "Exit codes:"
  echo "  0  every gate passed"
  echo "  1  a gate found something: AGENTS.md over budget, ruff findings, or"
  echo "     structural-test failures. Fix the code, then re-run."
  echo "  2  a gate could not run, so nothing was verified: no usable .venv, a"
  echo "     missing delegate script, not inside a git repository, a bad"
  echo "     argument, a ruff whose version does not match the pin, or pytest"
  echo "     collecting NO tests. Read the delegate's own stderr above; it is"
  echo "     passed through unchanged. Never treat a 2 as a pass."
  echo ""
  echo "Delegate codes are normalized, not propagated: the three disagree (1"
  echo "means 'no venv' to one and 'findings' to another), so a raw union could"
  echo "not be documented honestly. The preflight is what makes a later 1 from"
  echo "structural-tests.sh unambiguously a test failure."
}

# Every argument, not just the first: a gate that rejects `--bogus` but accepts
# `--help --bogus` teaches its callers to stop checking.
for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    "") ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository — the ship gate did not run." >&2
  exit 2
}
cd "$REPO_ROOT"

SUITE="scripts/structural-tests.sh"
LINT="scripts/python-lint.sh"
MEASURE="skills/curating-context/scripts/measure-context.sh"
AUDIT="skills/using-git-worktrees/scripts/audit-worktree-zombies.sh"

# A delegate that is absent is infra, never a pass. Without this the shell
# reports bash's generic "No such file or directory" at exit 127, which reads
# as noise next to a real failure.
for delegate in "$SUITE" "$LINT" "$MEASURE"; do
  if [[ ! -f "$delegate" ]]; then
    echo "ERROR: missing delegate: $delegate — the ship gate did not run." >&2
    exit 2
  fi
done

# --- Preflight: virtualenv ---------------------------------------------------
# Delegated to structural-tests.sh --check so #156's worktree-symlink fix lives
# in one place. Its stderr names the remedy; do not swallow it.
echo "=== Preflight: virtualenv ==="
RC=0
bash "$SUITE" --check || RC=$?
if [[ "$RC" -ne 0 ]]; then
  echo "" >&2
  echo "ERROR: no usable .venv (exit $RC) — no gate below was run." >&2
  exit 2
fi
echo "ok"

# --- Preflight: worktree zombies (warn only) ---------------------------------
# Drift the destroy script cannot see: raw `git worktree remove`, post-destroy
# spawn races. A warning, not a gate — a stale process is not a reason to
# refuse a ship, but it is worth one line before one is made. Absent script is
# a silent skip: it is vendored at a non-canonical path in some consumers.
if [[ -x "$AUDIT" ]]; then
  if ! bash "$AUDIT" --quiet; then
    echo "WARN: worktree zombies detected — see 'bash $AUDIT'" >&2
  fi
fi

# --- Gate 1/3: context budget ------------------------------------------------
# stdout is the JSON report and is discarded; the GATE lines on stderr are the
# signal, exactly as the pre-commit hook invokes it.
echo ""
echo "=== Gate 1/3: context budget (AGENTS.md) ==="
RC=0
bash "$MEASURE" --gate >/dev/null || RC=$?
case "$RC" in
  0) echo "ok" ;;
  4)
    echo "" >&2
    echo "FAIL: AGENTS.md is over .skills/context-budget." >&2
    echo "      Trim it, or move detail into a docs/ reference and link it." >&2
    exit 1
    ;;
  *)
    echo "" >&2
    echo "ERROR: the context-budget gate did not run (exit $RC)." >&2
    exit 2
    ;;
esac

# --- Gate 2/3: ruff ----------------------------------------------------------
# Exit 1 from this delegate means findings OR a .venv with no ruff in it; the
# preflight above rules out a missing venv but not an incomplete one. Its own
# stderr says which ("no ruff in …/.venv — the Python gate cannot run"), and
# both stop the ship, so the normalized code is 1 either way. Named here
# because an undocumented conflation is how a gate starts being trusted for
# something it does not check.
echo ""
echo "=== Gate 2/3: ruff (check + format --check) ==="
RC=0
bash "$LINT" || RC=$?
case "$RC" in
  0) echo "ok" ;;
  1)
    echo "" >&2
    echo "FAIL: ruff reported findings (or the venv has no ruff — see above)." >&2
    echo "      Fix: bash $LINT --fix" >&2
    exit 1
    ;;
  3)
    echo "" >&2
    echo "ERROR: the venv's ruff does not match the pin in requirements-test.txt." >&2
    echo "       The gate did not run. Fix: pip install -r requirements-test.txt" >&2
    exit 2
    ;;
  *)
    echo "" >&2
    echo "ERROR: the lint gate did not run (exit $RC)." >&2
    exit 2
    ;;
esac

# --- Gate 3/3: structural suite ----------------------------------------------
# pytest's 5 is the one worth spelling out. "Collected no tests" is not a pass:
# it is the shape where a broken conftest, a bad rootdir or a renamed directory
# reports green while verifying nothing. structural-tests.sh passes 5 through
# unchanged for exactly this reason, so the wrapper must not flatten it into
# success — it becomes a 2, loudly.
echo ""
echo "=== Gate 3/3: structural suite ==="
RC=0
bash "$SUITE" || RC=$?
case "$RC" in
  0) ;;
  1)
    echo "" >&2
    echo "FAIL: the structural suite has failures (see pytest output above)." >&2
    exit 1
    ;;
  5)
    echo "" >&2
    echo "ERROR: pytest collected NO tests — nothing was verified." >&2
    echo "       This is not a pass. Check rootdir, conftest and the path" >&2
    echo "       tests/structural/ before shipping anything." >&2
    exit 2
    ;;
  127)
    echo "" >&2
    echo "ERROR: pytest is missing from the venv that resolved." >&2
    echo "       Fix: pip install -r requirements-test.txt" >&2
    exit 2
    ;;
  *)
    echo "" >&2
    echo "ERROR: the structural suite did not run (exit $RC)." >&2
    exit 2
    ;;
esac

echo ""
echo "=== pre-ship: all gates passed ==="
