#!/usr/bin/env bash
# structural-tests.sh
# The `structural-tests` pre-commit hook's entry (#156).
#
# Guarantees a usable `.venv` at the repo root, then runs the structural suite.
# A linked worktree — `git worktree add`, or the Claude Code Agent tool's
# `isolation: "worktree"` — starts with no `.venv`, so the hook's previous
# inline `source .venv/bin/activate` died with bash's raw
# `.venv/bin/activate: No such file or directory` after the work was done and
# the suite was green. This script links the main checkout's venv instead, and
# when it cannot, says what to type.
#
# Linking rather than creating is deliberate. A symlink is by construction the
# *same* interpreter and the same installed packages as the main checkout; a
# freshly resolved venv is a different environment that can collect fewer
# tests and still report green, which is the harder-to-catch half of #156.
#
# Usage: bash scripts/structural-tests.sh [--check] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--check]"
  echo ""
  echo "Ensures a usable .venv at the repo root, then runs tests/structural/."
  echo ""
  echo "Resolution order:"
  echo "  1. .venv/bin/activate already resolves      -> use it"
  echo "  2. linked worktree, main checkout has .venv -> symlink it in"
  echo "  3. neither                                  -> diagnose and exit 1"
  echo ""
  echo "Options:"
  echo "  --check  Do the venv resolution and stop; do not run pytest."
  echo ""
  echo "Exit codes:"
  echo "  0  venv resolved (and, without --check, the suite passed)"
  echo "  1  no venv could be resolved"
  echo "  2  not inside a git repository, or a bad argument"
  echo "  *  otherwise the suite's OWN exit code, passed through unchanged:"
  echo "     pytest exits 1 on failures, 5 on nothing collected, and the shell"
  echo "     reports 127 if pytest is missing from a venv that did resolve."
}

# Every argument, not just the first: a script on the commit path that rejects
# `--bogus` but silently swallows `--check --bogus` is worse than one that
# rejects neither, because the strictness is what makes a caller stop checking.
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    --check) CHECK_ONLY=1 ;;
    "") ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$REPO_ROOT"

# The main checkout's root. `--git-common-dir` is the shared .git for every
# worktree, so its parent is the main checkout — and it equals `--git-dir` when
# there is only one. It may be printed relative to the cwd, so absolutize it by
# hand rather than with `--path-format=absolute`, which needs git >= 2.31.
GIT_COMMON=$(git rev-parse --git-common-dir)
GIT_COMMON=$(cd "$GIT_COMMON" && pwd -P)
MAIN_ROOT=$(dirname "$GIT_COMMON")

if [[ ! -e ".venv/bin/activate" ]]; then
  if [[ ! -e ".venv" && ! -L ".venv" && "$MAIN_ROOT" != "$REPO_ROOT" && -e "$MAIN_ROOT/.venv/bin/activate" ]]; then
    # Resolve through any symlink the main checkout's own .venv may be, so we
    # never build a chain of links to a link.
    VENV_TARGET=$(cd "$MAIN_ROOT/.venv" && pwd -P)
    ln -s "$VENV_TARGET" "$REPO_ROOT/.venv"
    echo "NOTE: linked .venv -> $VENV_TARGET (this worktree had none)" >&2
  else
    echo "ERROR: no usable .venv at $REPO_ROOT — the structural suite cannot run." >&2
    if [[ "$MAIN_ROOT" != "$REPO_ROOT" ]]; then
      echo "  This is a linked worktree of $MAIN_ROOT, which has no .venv either." >&2
      echo "  Create one there, then:  ln -s $MAIN_ROOT/.venv .venv" >&2
    elif [[ -e ".venv" || -L ".venv" ]]; then
      echo "  .venv exists but has no bin/activate (a broken symlink, or an" >&2
      echo "  unfinished venv). Remove it, then:  python3 -m venv .venv" >&2
      echo "  In a linked worktree the fix is instead:  ln -s <main-checkout>/.venv .venv" >&2
    else
      echo "  Create it:  python3 -m venv .venv && source .venv/bin/activate" >&2
      echo "              pip install -r requirements-test.txt" >&2
      echo "  In a linked worktree the fix is instead:  ln -s <main-checkout>/.venv .venv" >&2
    fi
    exit 1
  fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  exit 0
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# --- Reuse a pass recorded for this exact tree (#537) -------------------------
# The hook runs the suite on what is being committed, and pre-ship runs it on
# HEAD; both come through here, so a pass recorded by one is reused by the
# other when the tree, the OS, the outcome-changing env, the host tools and the
# installed packages all match. The env list is every variable the suite reads
# that can turn a skip into a run or a pass into a failure: the *_REQUIRED
# switches, SKILL_BUDGET_EXACT, the SocratiCode and CTX overrides, PYTHONPATH
# (what pytest itself imports), and PATH, which decides whether node, zsh and
# friends exist at all. PATH names a binary, not its version, and a stamp never
# expires — so the versions of the host tools the suite branches on are keyed
# too, or an unchanged tree gated after a `brew upgrade` reuses a pass the new
# tool never ran (CR 1388). A helper that is absent or fails costs the reuse,
# never the run: the suite still runs, and says why.
STAMP="skills/shipping-work/scripts/gate-stamp.sh"
WORKERS="skills/shipping-work/scripts/gate-workers.sh"

# PATH enters the key without git's exec-path. git runs every hook with that
# directory prepended, so a raw PATH made the hook's stamp unreachable from the
# shell pre-ship runs in — the first real commit + pre-ship pair re-ran the
# whole suite. The directory holds git's own subcommands and nothing a test's
# outcome turns on.
key_path() {
  local exec_path entry out=""
  exec_path=$(git --exec-path) || return 1
  local IFS=:
  for entry in $PATH; do
    if [[ "$entry" != "$exec_path" ]]; then
      out=${out:+$out:}$entry
    fi
  done
  echo "$out"
}

# git's version gates tests outright, shellcheck's is pinned by TestShellcheck,
# and every script under test runs on PATH's bash. `sed -n 1p`, not `head -1`:
# head exits early, and under pipefail the writer's SIGPIPE fails the pipe.
tool_versions() {
  local g b s=absent
  g=$(git --version) || return 1
  b=$(bash --version | sed -n 1p) || return 1
  if command -v shellcheck >/dev/null 2>&1; then
    s=$(shellcheck --version | sed -n 's/^version: //p') || return 1
  fi
  echo "tools git=[$g] shellcheck=[$s] bash=[$b]"
}

stamp_key() {
  local dists kpath tools args=()
  dists=$(python -c 'import importlib.metadata as m, sys; print(sys.version.split()[0], *sorted({f"{d.name}=={d.version}" for d in m.distributions()}))') || return 2
  kpath=$(key_path) || return 2
  tools=$(tool_versions) || return 2
  if [[ "${PRE_COMMIT:-}" == "1" ]]; then
    args+=(--index)
  fi
  # GATE_STAMP_EXPLAIN=1 prints what went into the key, to diagnose a reuse
  # that should have happened and did not.
  if [[ "${GATE_STAMP_EXPLAIN:-}" == "1" ]]; then
    args+=(--explain)
  fi
  bash "$STAMP" key "${args[@]+"${args[@]}"}" \
    --env '*_REQUIRED' --env SKILL_BUDGET_EXACT --env 'SOCRATICODE_*' \
    --env 'CTX_*' --env PYTHONPATH --extra "PATH=$kpath" --extra "$tools" \
    --extra "$dists"
}

KEY=""
if [[ -f "$STAMP" ]]; then
  RC=0
  KEY=$(stamp_key) || RC=$?
  case "$RC" in
    0) ;;
    3) KEY="" ;;  # not stampable; gate-stamp.sh said why on stderr
    *) echo "NOTE: no stamp key (exit $RC) — running without reuse" >&2; KEY="" ;;
  esac
  if [[ -n "$KEY" ]]; then
    RC=0
    RECORD=$(bash "$STAMP" check "$KEY") || RC=$?
    case "$RC" in
      0)
        echo "structural suite: this exact tree already passed — not re-running."
        echo "  recorded: $RECORD"
        echo "  (GATE_STAMP=off forces a run)"
        exit 0
        ;;
      1) ;;
      *) echo "NOTE: stamp check failed (exit $RC) — running" >&2 ;;
    esac
  fi
fi

# --- Workers (#537, decision D2) ---------------------------------------------
# gate-workers.sh resolves PYTEST_XDIST_AUTO_NUM_WORKERS, then
# .skills/test-workers, then a core count shared across the gates running now.
# A malformed setting is a 2 here: a gate that guessed past a broken knob
# would be running a configuration nobody chose.
N=0
if [[ -f "$WORKERS" ]]; then
  N=$(bash "$WORKERS" --explain) || exit 2
fi
PYTEST_ARGS=(tests/structural/ -q)
if [[ -f tests/utils/gate_durations.py ]]; then
  PYTEST_ARGS+=(-p tests.utils.gate_durations)
fi
SLOT=""
if [[ "$N" -ge 2 ]]; then
  if python -c 'import xdist' >/dev/null 2>&1; then
    PYTEST_ARGS+=(-n "$N" --dist loadfile)
    SLOTS=$(bash "$WORKERS" --slot-dir) && SLOT="$SLOTS/$$" && : >"$SLOT"
  else
    echo "NOTE: $N workers allowed, but pytest-xdist is not in .venv — running serially." >&2
    echo "      Fix: pip install -r requirements-test.txt" >&2
  fi
fi
trap '[[ -z "$SLOT" ]] || rm -f "$SLOT"' EXIT

# Not `exec`: the slot has to be released and the pass recorded afterwards.
# pytest's exit code is still this script's — the usage block documents the
# pass-through, and pre-ship.sh relies on 5 meaning "collected nothing".
START=$SECONDS
RC=0
pytest "${PYTEST_ARGS[@]}" || RC=$?

# Record the pass only if the files did not move under the run: the key is
# recomputed and must still match, so an edit made mid-suite costs the stamp
# rather than certifying a tree the suite never saw.
if [[ "$RC" -eq 0 && -n "$KEY" ]]; then
  AFTER=""
  AFTER=$(stamp_key) || true
  if [[ "$AFTER" == "$KEY" ]]; then
    bash "$STAMP" write "$KEY" --label "structural suite, $N workers" \
      --seconds "$((SECONDS - START))" \
      || echo "NOTE: the pass was not recorded; the next gate will re-run" >&2
  else
    echo "NOTE: files changed during the run — the pass is not recorded" >&2
  fi
fi
exit "$RC"
