#!/usr/bin/env bash
# run-deploy-command.sh
# Runs the project's deploy command, named in .skills/deploy_command, once,
# with the SHA that was pushed as its last argument (#345).
#
# A project whose production runs immutable releases deploys through its own
# script: "migrate, then systemctl restart" restarts the old release there,
# and a hand migration runs outside the deploy's order. The knob names that
# script, and Step 8 offers to run it through this file.
#
# WHY THIS NAME, and not deploy.sh: Step 1 lets a project-local
# scripts/<name> win for that script alone (#301), and the projects this
# serves ship a scripts/deploy.sh. A skill script called deploy.sh would
# resolve to the project's own script and skip the knob.
#
# THE KNOB is read from the primary checkout (the first `git worktree list`
# entry), like worktree_root, and the command runs from that checkout's root.
# Grammar: exactly one command line of whitespace-separated words; blank lines
# and whole-line `#` comments are ignored. No shell evaluation: a pipe or a
# redirect belongs in the project's script. The pushed SHA is appended as the
# last argument (operator's decision, 2026-10-30), so `setsid -w
# scripts/deploy.sh` runs as `setsid -w scripts/deploy.sh <sha>`. The command
# handles detaching itself; a plain `setsid` returns once the deploy has
# started, so its 0 means "started", not "deployed".
#
# ONLY PUSHED CODE IS DEPLOYED: HEAD must equal its upstream (@{u}), or
# nothing runs.
#
# The command's stdin is /dev/null (agents run non-interactively, so a prompt
# would hang), and its stdout and stderr reach the caller unfiltered: the
# project documents its own exit codes, and the report quotes them verbatim.

set -euo pipefail

usage() {
  cat <<EOF
Usage: bash "$0" [--check]

Runs the command named in the primary checkout's .skills/deploy_command once,
from that checkout's root, with the pushed SHA (HEAD, which must equal its
upstream) as its last argument. stdin is /dev/null; output is unfiltered.

Options:
  --check   Validate the knob and print the command line that would run, with
            the SHA. Runs nothing.
  --help    Show this help.

Exit codes:
  0  The command exited 0 (with --check: the knob is usable; line printed)
  1  The command exited non-zero; its own code is printed. Report it and its
     output verbatim, and close no issue
  2  Nothing ran: the knob is present but unusable (no command line, more than
     one, a command not found or not executable, not a readable file), HEAD
     is not what was pushed, git failed, or a bad argument
  3  No .skills/deploy_command: nothing to deploy; Step 8 is the next-steps
     table, as before the knob existed
EOF
}

die() {
  echo "run-deploy-command: $*" >&2
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

WT_LIST=$(git worktree list --porcelain) || die "git worktree list failed: not in a git checkout?"
PRIMARY=${WT_LIST%%$'\n'*}
PRIMARY=${PRIMARY#worktree }
[ -d "$PRIMARY" ] || die "could not resolve the primary checkout (got '$PRIMARY')"

KNOB="$PRIMARY/.skills/deploy_command"
if [ ! -e "$KNOB" ] && [ ! -L "$KNOB" ]; then
  echo "no .skills/deploy_command in $PRIMARY: nothing to deploy"
  exit 3
fi
{ [ -f "$KNOB" ] && [ -r "$KNOB" ]; } || die "$KNOB is present but not a readable file"

WORDS=()
LINES=0
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%$'\r'}
  read -r -a words <<<"$line"
  [ "${#words[@]}" -gt 0 ] || continue
  case ${words[0]} in \#*) continue ;; esac
  LINES=$((LINES + 1))
  WORDS=("${words[@]}")
done <"$KNOB"
[ "$LINES" -gt 0 ] || die "$KNOB has no command line"
[ "$LINES" -eq 1 ] || die "$KNOB names $LINES commands; it takes one line"

CMD=${WORDS[0]}
case $CMD in
  */*)
    case $CMD in /*) PATH_OF=$CMD ;; *) PATH_OF="$PRIMARY/$CMD" ;; esac
    { [ -f "$PATH_OF" ] && [ -x "$PATH_OF" ]; } ||
      die "$CMD is not an executable file (a relative path resolves from $PRIMARY)"
    ;;
  *)
    command -v -- "$CMD" >/dev/null || die "$CMD is not on PATH"
    ;;
esac

SHA=$(git rev-parse --verify HEAD) || die "git rev-parse HEAD failed"
UPSTREAM=$(git rev-parse --verify '@{u}') ||
  die "HEAD has no upstream to compare with: push it first (Step 4)"
[ "$SHA" = "$UPSTREAM" ] ||
  die "HEAD ($SHA) is not what was pushed (upstream is $UPSTREAM): push first (Step 4). Only pushed code is deployed"

if [ "$CHECK" -eq 1 ]; then
  echo "${WORDS[*]} $SHA"
  exit 0
fi

echo "run-deploy-command: in $PRIMARY: ${WORDS[*]} $SHA" >&2
cd "$PRIMARY"
RC=0
"${WORDS[@]}" "$SHA" </dev/null || RC=$?
if [ "$RC" -eq 0 ]; then
  echo "deploy_command exited 0"
  exit 0
fi
echo "deploy_command exited $RC"
echo "run-deploy-command: the deploy failed (exit $RC). Report it and its output verbatim, and close no issue" >&2
exit 1
