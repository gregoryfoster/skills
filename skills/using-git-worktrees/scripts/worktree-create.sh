#!/usr/bin/env bash
# worktree-create.sh
# Creates a git worktree for <branch> under the resolved worktree root.
# Refuses if <branch> is already checked out in another worktree (Iron Law).
#
# Usage: bash <SKILL_SCRIPTS>/worktree-create.sh [--new] <branch> [--help]
# Flags are position-independent: `--new <branch>` and `<branch> --new` are equivalent.
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--new] <branch>"
  echo ""
  echo "Creates a worktree at <root>/<branch-slug>, where <branch-slug> is"
  echo "<branch> with '/' replaced by '-' (e.g., feature/foo -> feature-foo)."
  echo "The root is resolved via resolve-worktree-root.sh (env var → .skills/worktree_root → <repo>/.worktrees/)."
  echo ""
  echo "The main checkout's .venv is symlinked into the new worktree when one"
  echo "exists. Write 'none' into .skills/worktree_venv (read from the PRIMARY"
  echo "checkout; 'link' is the default) to skip that — the right setting when"
  echo "the main checkout is also a running service's WorkingDirectory=, where"
  echo "the service's own 'uv run' / 'uv sync' rewrite the shared venv under a"
  echo "worktree's test run."
  echo ""
  echo "Options:"
  echo "  --new   Create the branch (passes -b to git worktree add). Default: branch must already exist."
  echo ""
  echo "Flags may appear before or after <branch>; both orders are equivalent."
  echo ""
  echo "Iron Law: refuses if <branch> is already checked out in another worktree."
  echo ""
  echo "Exit codes:"
  echo "  0  Worktree created; absolute path printed on stdout"
  echo "  1  Iron Law violation (branch already checked out elsewhere)"
  echo "  2  Tooling/infra failure (not a git repo, missing arg, git worktree add failed)"
}

# One line, not the whole block. An argument error used to print the full usage
# dump to stderr underneath the ERROR line — 23 lines here, 69 in the destroy
# script — so the one line carrying the actual diagnosis scrolled off the top,
# and a `| tail` on the output showed nothing but boilerplate (#262). `--help`
# still prints everything; a mistake gets a pointer to it.
usage_hint() {
  echo "Usage: bash \"$0\" [--new] <branch>   (run with --help for the full description)"
}

# Scan every argument for --help before anything runs, then parse flags in any
# position. Both properties are the convention worktree-list.sh already states
# in its own preamble; create and destroy were the two scripts in this
# directory that had drifted from it, in OPPOSITE directions (#262).
#
# The drift was not cosmetic. `--new` was recognised only as $1, so trailing it
# was dropped in silence and the failure surfaced as git's `fatal: invalid
# reference: <branch>` — the script blaming git for its own omission. And
# `--help` trailing an EXISTING branch fell through to provisioning: a request
# for documentation that created a worktree and printed its path.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    usage
    exit 0
  fi
done

NEW_BRANCH=0
BRANCH=""
BRANCH_SET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --new)
      NEW_BRANCH=1
      shift
      ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      usage_hint >&2
      exit 2
      ;;
    *)
      # First non-flag argument is <branch>. A second one is an ERROR, not a
      # silent drop: `create foo bar` previously ignored 'bar' entirely, which
      # is the same failure mode as the dropped trailing flag.
      if [[ $BRANCH_SET -eq 1 ]]; then
        echo "ERROR: unexpected argument '$1' (<branch> is already '$BRANCH')" >&2
        usage_hint >&2
        exit 2
      fi
      BRANCH="$1"
      BRANCH_SET=1
      shift
      ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  echo "ERROR: <branch> argument required" >&2
  usage_hint >&2
  exit 2
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}

SLUG="${BRANCH//\//-}"
WORKTREE_PATH="$ROOT/$SLUG"

# Iron Law check: refuse if the branch is already checked out elsewhere.
# `git worktree list --porcelain` emits a `branch refs/heads/<name>` line per worktree.
EXISTING=$(git worktree list --porcelain | awk -v b="refs/heads/$BRANCH" '$1=="branch" && $2==b {print "match"; exit}')
if [[ "$EXISTING" == "match" ]]; then
  echo "ERROR: branch '$BRANCH' is already checked out in another worktree (Iron Law: no double checkout)" >&2
  echo "Run 'bash \"$SCRIPT_DIR/worktree-list.sh\"' to see existing worktrees." >&2
  exit 1
fi

if [[ -e "$WORKTREE_PATH" ]]; then
  echo "ERROR: path '$WORKTREE_PATH' already exists" >&2
  exit 2
fi

# Pre-flight zombie audit: warn (do not fail) if processes from previously-
# destroyed worktrees are still around. Fresh worktree creation is a good
# moment to surface stale state — non-zero from the audit becomes a WARN,
# never a gate. The audit script is detection-only and lives in the same
# scripts/ directory.
# Runs AFTER the Iron Law + existing-path checks so we don't pay the audit
# cost when we're about to abort anyway.
#
# `>/dev/null` as well as `--quiet`: this script's stdout contract is exactly
# the worktree path, and routing it through a child's flag makes the contract
# depend on that flag still working. Neutering QUIET in the audit script failed
# nine tests in test_worktree_venv_knob.py — a file about the venv knob, which
# is where the breakage would have been diagnosed. The redirect makes the
# coupling structural instead of behavioural; --quiet stays so the audit is not
# doing work whose output is thrown away.
if [[ -x "$SCRIPT_DIR/audit-worktree-zombies.sh" ]]; then
  if ! "$SCRIPT_DIR/audit-worktree-zombies.sh" --quiet >/dev/null; then
    echo "WARN: worktree zombies detected — run 'bash $SCRIPT_DIR/audit-worktree-zombies.sh' for details" >&2
  fi
fi

mkdir -p "$ROOT"

# `git worktree add` splits its own chatter across both streams: "Preparing
# worktree ..." goes to stderr, but the checkout notice "HEAD is now at <sha>
# <subject>" goes to STDOUT, where it lands ahead of the path this script
# promises. Redirect, do not silence: `-q` empties stdout too, but it also
# drops the stderr line, leaving no record of what was checked out.
if [[ $NEW_BRANCH -eq 1 ]]; then
  git worktree add -b "$BRANCH" "$WORKTREE_PATH" >&2 || exit 2
else
  git worktree add "$WORKTREE_PATH" "$BRANCH" >&2 || exit 2
fi

# The link below is right by default and wrong for exactly one shape: a main
# checkout that is ALSO a running service's `WorkingDirectory=`. There the link
# hands every worktree one shared *mutable* environment while isolating it in
# every other respect, and the service's own tooling rewrites that environment
# underneath a worktree's test run (#201). Two mechanisms, both confirmed on uv
# 0.10.4:
#   * `uv run` reinstalls the current project, restamping
#     `importlib.metadata.version(...)` to the MAIN checkout's version mid-run.
#     A worktree suite on a bumped version then fails in a full run and passes
#     in isolation — a flake whose direction depends on which checkout ran uv
#     last.
#   * `uv sync` prunes every dependency group it was not asked for. An opt-in
#     group whose test modules `pytest.importorskip` at module scope does not
#     error when it vanishes; it turns a few hundred passes into skips against
#     a suite that still reports green.
#
# `.skills/worktree_venv` is the opt-out: `none`, or `link` (the default, so
# nothing changes for existing users).
#
# Read from the PRIMARY checkout, not from `git rev-parse --show-toplevel`.
# `.skills/` knobs are machine-local and untracked, and an untracked file does
# not exist in a linked worktree at all — so a knob read from the current
# checkout would be invisible whenever this script runs from inside a worktree,
# silently restoring the link in the one deployment the knob exists to protect.
# This is the derivation `resolve-worktree-root.sh` uses for the same reason,
# including its submodule guard: the parent of `<super>/.git/modules/<name>` is
# not a work tree, so the candidate is accepted only if it is a checkout
# sharing this common dir. The #203 gap is inherited with it — in a linked
# worktree OF a submodule the candidate is rejected and the knob is read from
# the current checkout, where an untracked file is absent.
worktree_venv_mode() {
  local common_dir candidate candidate_common knob_root knob configured
  knob_root="$PROJECT_ROOT"
  common_dir=$(git rev-parse --git-common-dir 2>/dev/null || true)
  if [[ -n "$common_dir" ]] && common_dir=$(cd "$common_dir" 2>/dev/null && pwd -P); then
    candidate=$(dirname "$common_dir")
    # `git -C "$candidate"` answers relative to candidate, not to our $PWD.
    candidate_common=$(git -C "$candidate" rev-parse --git-common-dir 2>/dev/null || true)
    if [[ -n "$candidate_common" ]] &&
       candidate_common=$(cd "$candidate" && cd "$candidate_common" 2>/dev/null && pwd -P) &&
       [[ "$candidate_common" == "$common_dir" ]]; then
      knob_root="$candidate"
    fi
  fi

  knob="$knob_root/.skills/worktree_venv"
  [[ -f "$knob" ]] || { echo link; return 0; }

  # First non-blank, non-comment line, trimmed — the same read
  # `resolve-worktree-root.sh` gives `.skills/worktree_root`, so one knob
  # syntax covers the directory. `|| true` keeps pipefail from aborting on a
  # file that is empty or all comments: that must default, not crash.
  configured=$(grep -v '^[[:space:]]*#' "$knob" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  case "$configured" in
    none) echo none ;;
    link | "") echo link ;;
    # A malformed knob file degrades to the default AND says so. Silence is
    # what lets a typo ('off', 'false', 'no') read as a working opt-out, and
    # the symptom it would leave — a venv that keeps being rewritten — is the
    # one this whole block exists to make legible.
    *)
      echo "WARN: $knob: unrecognised value '$configured' (expected 'link' or 'none') — linking as usual" >&2
      echo link
      ;;
  esac
}

# A worktree inherits no virtualenv, so the first `.venv/bin/python -m pytest`
# in it dies before any test runs (#156). Link the parent's when there is one:
# a symlink is by construction the same interpreter and the same installed
# packages, where a freshly resolved venv is a different environment that can
# collect fewer tests and still report green.
#
# Opportunistic, never a gate — this script is vendored into repos that have no
# venv at all, and a worktree without one is not a failed worktree. Notes go to
# stderr; stdout stays the worktree path, which is this script's contract.
#
# Does NOT reach harness-provisioned worktrees (the Agent tool's
# `isolation: "worktree"`), which call `git worktree add` directly and never
# run this script. Those rely on the consuming repo's own hook, plus the
# by-hand `ln -s` in SKILL.md Phase 3.
#
# Every failure path here is swallowed. The worktree already exists by this
# point, so a `set -e` abort would return non-zero for a creation that
# succeeded — and leave the caller without the path on stdout.
# `! -e && ! -L`, matching scripts/structural-tests.sh: a BROKEN symlink at
# .venv is `-e` false and `-L` true, so testing -e alone would fall through to
# an `ln -s` that fails on the existing name. It lands in the WARN branch either
# way, but the two linkers must read identically or a later edit fixes one.
if [[ -e "$PROJECT_ROOT/.venv/bin/activate" && ! -e "$WORKTREE_PATH/.venv" && ! -L "$WORKTREE_PATH/.venv" ]]; then
  # Resolved here rather than up front so a repo with no venv pays none of it,
  # and so a malformed knob warns only where it would have changed something.
  if [[ "$(worktree_venv_mode)" == "none" ]]; then
    # Announced, never silent. An absent .venv is also the signature of the
    # #156 bug this linker fixes, so the operator standing in a fresh worktree
    # has to be told which of the two they are looking at.
    echo "NOTE: .skills/worktree_venv=none — no .venv linked into $WORKTREE_PATH; provision one there" >&2
  else
    # `pwd -P` resolves through a .venv that is itself a symlink (a worktree
    # provisioning a worktree), so we never build a link to a link.
    VENV_TARGET=$(cd "$PROJECT_ROOT/.venv" 2>/dev/null && pwd -P) || VENV_TARGET=""
    if [[ -z "$VENV_TARGET" ]]; then
      echo "WARN: could not resolve $PROJECT_ROOT/.venv — no venv linked into $WORKTREE_PATH" >&2
    elif ln -s "$VENV_TARGET" "$WORKTREE_PATH/.venv" 2>/dev/null; then
      echo "NOTE: linked .venv -> $VENV_TARGET" >&2
    else
      echo "WARN: could not link .venv into $WORKTREE_PATH — run 'ln -s $VENV_TARGET .venv' there" >&2
    fi
  fi
fi

echo "$WORKTREE_PATH"
