#!/usr/bin/env bash
# push.sh
# Pushes the current branch to origin.
# Detects the git project root automatically; safe to invoke from any directory.
#
# With .skills/attest-local-gate committed as `on` (#688) it also attests the
# local gate, through _attest-gate.sh: it asks the gate about HEAD's tree
# first and pushes only what passes, then posts the commit status gate/local
# = success on the pushed SHA and reads it back. A refused write is said
# aloud and doesn't fail the push, which has landed by then. Without the
# knob, or with it `off`, this is the script it was before the knob: the
# same push and the same output. references/attestation.md.
#
# Usage: bash "<push.sh>" [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Pushes the current git branch to origin."
  echo "Automatically resolves the git project root regardless of invocation directory."
  echo ""
  echo "With .skills/attest-local-gate committed as 'on', it first runs the gate"
  echo "(scripts/pre-ship.sh, else the skill's; a pass recorded for this exact"
  echo "tree is reused) on a clean tree, pushes only if it passes, then posts the"
  echo "commit status gate/local = success on the pushed SHA with gh and reads it"
  echo "back. 'off', or no file, changes nothing."
  echo ""
  echo "Exit codes:"
  echo "  0  pushed. With the knob on, see the 'Attestation:' line: a refused"
  echo "     status write is reported under ATTESTATION NOT POSTED and is still 0"
  echo "  1  with the knob on, before the push: uncommitted changes, the gate"
  echo "     failed on this tree, or the tree changed under the gate. It says"
  echo "     'Nothing was pushed'"
  echo "  2  with the knob on, before the push: the knob is unusable,"
  echo "     _attest-gate.sh or pre-ship.sh was not found, the gate could not"
  echo "     run, or git failed. It says 'Nothing was pushed'"
  echo "  *  after 'Pushing <branch> to origin...': git push's own exit code, as"
  echo "     without the knob (a rejected push is git's 1)"
  exit 0
fi

# How this script was run, kept before the cd below: with the knob on, the
# attestation looks beside this path, then beside its target.
SELF=${BASH_SOURCE[0]}
case $SELF in /*) ;; *) SELF=$PWD/$SELF ;; esac

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

BRANCH=$(git branch --show-current)

# --- Local-gate attestation (#688): only where the knob is ------------------
# A file here or in the commit is all that is asked without the knob: no gh,
# no gate, no library. The library then reads the knob from the commit, and a
# file that is only in the work tree is refused there, by name.
# The committed knob's one word is `off`, by _attest-gate.sh's grammar: a
# regular file with no NUL byte in it (CR 2677). Asked only when that library
# is missing; with it, the library reads the knob.
attest_knob_says_off() {
  local entry text size kept line count=0 word=""
  local -a words
  entry=$(git ls-tree HEAD -- .skills/attest-local-gate 2>/dev/null) || return 1
  case ${entry%% *} in 100644 | 100755) ;; *) return 1 ;; esac
  size=$(git cat-file -s HEAD:.skills/attest-local-gate 2>/dev/null) || return 1
  kept=$(git cat-file blob HEAD:.skills/attest-local-gate 2>/dev/null | LC_ALL=C tr -d '\000' | wc -c) || return 1
  [[ $((size)) -eq $((kept)) ]] || return 1
  text=$(git cat-file blob HEAD:.skills/attest-local-gate 2>/dev/null) || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line"
    [[ ${#words[@]} -gt 0 ]] || continue
    case ${words[0]} in \#*) continue ;; esac
    count=$((count + ${#words[@]}))
    word=${words[0]}
  done <<<"$text"
  [[ $count -eq 1 && "$word" == off ]]
}

ATTEST=0
if [[ -e .skills/attest-local-gate || -L .skills/attest-local-gate ]] ||
  git cat-file -e HEAD:.skills/attest-local-gate 2>/dev/null; then
  # This script's own directory through the symlink chain, as pre-ship.sh
  # resolves its helpers (CR 1865): a per-file link's directory may hold
  # nothing else, while the target's holds the library.
  _self=$SELF
  _n=0
  while [[ -L $_self && $_n -lt 10 ]]; do
    _t=$(readlink "$_self") || break
    case $_t in
      /*) _self=$_t ;;
      *) _self=$(dirname "$_self")/$_t ;;
    esac
    _n=$((_n + 1))
  done
  ATTEST_LINK_DIR=$(dirname "$SELF")
  ATTEST_SCRIPT_DIR=$(cd -P "$(dirname "$_self")" && pwd -P) || {
    echo "ERROR: could not resolve this script's directory (from $_self)." >&2
    echo "       Nothing was pushed." >&2
    exit 2
  }
  ATTEST_LIB=""
  for _d in "$ATTEST_LINK_DIR" "$ATTEST_SCRIPT_DIR"; do
    if [[ -f "$_d/_attest-gate.sh" ]]; then
      ATTEST_LIB="$_d/_attest-gate.sh"
      break
    fi
  done
  # `off` is the same as no file, so it must not need the library either
  # (CR 2667): a copied push.sh with no library beside it pushed before the
  # knob, and still does when the committed knob's one word is `off`.
  if [[ -z "$ATTEST_LIB" ]] && attest_knob_says_off; then
    ATTEST_LIB=off
  elif [[ -z "$ATTEST_LIB" ]]; then
    echo "ERROR: .skills/attest-local-gate is present, but _attest-gate.sh is not" >&2
    echo "       beside push.sh ($ATTEST_LINK_DIR) or its target" >&2
    echo "       ($ATTEST_SCRIPT_DIR). Link or restore it, or remove the knob." >&2
    echo "       Nothing was pushed." >&2
    exit 2
  fi
  ATTEST_RC=3
  if [[ "$ATTEST_LIB" != off ]]; then
    # shellcheck source=_attest-gate.sh
    . "$ATTEST_LIB"
    ATTEST_RC=0
    attest_verify || ATTEST_RC=$?
  fi
  case $ATTEST_RC in
    0) ATTEST=1 ;;
    3) ;; # the knob says off: the plain push below
    1 | 2) exit "$ATTEST_RC" ;; # it said why; nothing was pushed
    *) exit 2 ;;
  esac
fi

echo "Pushing $BRANCH to origin..."
# -u sets upstream tracking on first push; no-op when tracking is already configured.
git push -u origin "$BRANCH"
echo "Push succeeded."

if [[ $ATTEST -eq 1 ]]; then
  # A refused write is said on both streams and doesn't fail the push.
  attest_post || true
fi
