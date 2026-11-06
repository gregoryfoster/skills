#!/usr/bin/env bash
# run-pre-restart.sh
# Runs the project's reachability check, named in .skills/pre_restart, before
# Step 8 offers any row that restarts the service (#557).
#
# Without .skills/deploy_command the main checkout is the deployment, and
# Step 8's migrate and restart rows ran with nothing checked first. A unit
# that applies its schema in ExecStartPre doesn't fail on an unreachable DB:
# CannObserv/power-map#748 looped in start-pre for about 16 h (873 attempts,
# each a 60 s connect timeout, so StartLimitBurst never tripped), and applied
# the pending schema with nobody watching when the DB came back. The deploy
# turned a degraded API into a down one.
#
# THE KNOB has deploy_command's grammar and reader (_command-knob.sh): one
# command line read from the primary checkout (the first `git worktree list`
# entry), no shell evaluation, a repo script given by its path. It runs from
# that checkout's root with stdin from /dev/null, and its stdout and stderr
# reach the caller unfiltered. Unlike deploy_command, nothing is appended: the
# check is about the host, not the commit.
#
# With .skills/deploy_command set, Step 8 doesn't run this: the deploy command
# owns the restart, so it runs its own check.

set -euo pipefail

usage() {
  cat <<EOF
Usage: bash "$0" [--check]

Runs the command named in the primary checkout's .skills/pre_restart once,
from that checkout's root, with stdin from /dev/null and its output
unfiltered. Step 8 runs it before offering any row that restarts the service.

Options:
  --check   Validate the knob and print the command line that would run. Runs
            nothing.
  --help    Show this help.

Exit codes:
  0  The check exited 0 (with --check: the knob is usable; line printed).
     Offer the restart rows as before the knob
  1  The check refused: it exited non-zero, and its own code is printed. Offer
     no restart row, quote its code and output verbatim, and close no issue
     whose "Done when" is about production
  2  Nothing ran: the knob is present but unusable (no command line, more than
     one, a command not found or not executable, not a readable file), git
     failed, or a bad argument. Fix it; it never reads as absent
  3  No .skills/pre_restart: Step 8's table, as before the knob existed
EOF
}

die() {
  echo "run-pre-restart: $*" >&2
  exit 2
}

CHECK=0
case "${1:-}" in
  --help | -h)
    usage
    exit 0
    ;;
  --check)
    CHECK=1
    shift
    ;;
  "") ;;
  *) die "unknown argument: $1 (see --help)" ;;
esac
[ "$#" -eq 0 ] || die "unexpected argument: $1 (see --help)"

# Through the symlink chain first (CR 1841): a consumer's per-script symlink
# (managing-skills' local-overrides.md) puts this file's link in a directory
# with no _command-knob.sh or merge-mode.sh beside it, while the target has
# both. Resolved as curating-context's check-counts.sh does.
_self="${BASH_SOURCE[0]}"
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 10 ]; do
  _t=$(readlink "$_self") || break
  case "$_t" in
    /*) _self="$_t" ;;
    *) _self="$(dirname "$_self")/$_t" ;;
  esac
  _n=$((_n + 1))
done
SCRIPT_DIR=$(cd "$(dirname "$_self")" && pwd -P) || die "could not resolve this script's directory (from $_self)"
[ -f "$SCRIPT_DIR/_command-knob.sh" ] || die "_command-knob.sh not found next to this script in $SCRIPT_DIR"
# shellcheck source=_command-knob.sh
. "$SCRIPT_DIR/_command-knob.sh"

primary_checkout
KNOB="$PRIMARY/.skills/pre_restart"
if [ ! -e "$KNOB" ] && [ ! -L "$KNOB" ]; then
  echo "no .skills/pre_restart in $PRIMARY: no check; offer the restart rows as before"
  exit 3
fi
read_command_knob "$KNOB"

if [ "$CHECK" -eq 1 ]; then
  echo "${WORDS[*]}"
  exit 0
fi

echo "run-pre-restart: in $PRIMARY: ${WORDS[*]}" >&2
cd "$PRIMARY"
RC=0
"${WORDS[@]}" </dev/null || RC=$?
if [ "$RC" -eq 0 ]; then
  echo "pre_restart exited 0"
  exit 0
fi
echo "pre_restart exited $RC"
echo "run-pre-restart: the check refused (exit $RC). Offer no restart row, quote its code and output verbatim, and close no issue whose \"Done when\" is about production" >&2
exit 1
