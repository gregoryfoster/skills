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
# entry's work tree), and the command runs from that checkout's root. A
# primary made with --separate-git-dir names no work tree to its linked
# worktrees, so only the primary itself can read it (#605).
# Grammar: exactly one command line of whitespace-separated words; blank lines
# and whole-line `#` comments are ignored. No shell evaluation: a pipe or a
# redirect belongs in the project's script. _command-knob.sh holds the
# reader, shared with .skills/pre_restart (#557). The pushed SHA is appended as the
# last argument (operator's decision, 2026-10-30), so `setsid -w
# scripts/deploy.sh` runs as `setsid -w scripts/deploy.sh <sha>`. The command
# handles detaching itself; a plain `setsid` returns once the deploy has
# started, so its 0 means "started", not "deployed".
#
# ONLY PUSHED CODE IS DEPLOYED: HEAD must equal its upstream (@{u}), or
# nothing runs.
#
# IN `pr` MODE, ONLY THE DEFAULT BRANCH IS DEPLOYED (#342, CR 1545). With
# .skills/merge_mode set to `pr`, a feature branch is pushed and a PR opened,
# so it passes the upstream check and would deploy unreviewed. The post-merge
# pass deploys the default branch at the merge commit instead, and HEAD must
# be on that branch. The default branch resolves as worktree-destroy.sh
# resolves it: .skills/default_branch (here from the primary checkout), then
# origin's HEAD, then `main`. Absent or `direct`: the branch is not checked,
# since Step 3 has already put the agent on the default branch.
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

With .skills/merge_mode set to 'pr', HEAD must also be on the default branch
(.skills/default_branch, else origin's HEAD, else main): the post-merge pass
deploys the merge commit, never a feature branch's tip.

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
     is not what was pushed, in pr mode HEAD is not the default branch,
     .skills/merge_mode is unusable, git failed, or a bad argument. From a
     linked worktree of a --separate-git-dir primary: run from the primary
     checkout
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
# -P (CR 1872): through a directory link, $_self can spell `<link>/../..`, and
# a logical cd reduces that by spelling, not by what the link points at.
SCRIPT_DIR=$(cd -P "$(dirname "$_self")" && pwd -P) || die "could not resolve this script's directory (from $_self)"
[ -f "$SCRIPT_DIR/_command-knob.sh" ] || die "_command-knob.sh not found next to this script in $SCRIPT_DIR"
# The knob's grammar and reader, shared with run-pre-restart.sh (#557).
# shellcheck source=_command-knob.sh
. "$SCRIPT_DIR/_command-knob.sh"

primary_checkout
KNOB="$PRIMARY/.skills/deploy_command"
if [ ! -e "$KNOB" ] && [ ! -L "$KNOB" ]; then
  echo "no .skills/deploy_command in $PRIMARY: nothing to deploy"
  exit 3
fi
read_command_knob "$KNOB"

SHA=$(git rev-parse --verify HEAD) || die "git rev-parse HEAD failed"

# DEFAULT := the default branch: .skills/default_branch (from the primary
# checkout), then origin's HEAD, then main, as worktree-destroy.sh resolves it.
resolve_default() {
  DEFAULT=""
  DB_KNOB="$PRIMARY/.skills/default_branch"
  if [ -e "$DB_KNOB" ] || [ -L "$DB_KNOB" ]; then
    { [ -f "$DB_KNOB" ] && [ -r "$DB_KNOB" ]; } || die "$DB_KNOB is present but not a readable file"
    DEFAULT=$(head -n1 "$DB_KNOB" | tr -d '[:space:]')
  fi
  if [ -z "$DEFAULT" ]; then
    # --quiet: exit 1 with no message when origin/HEAD is absent, an answer;
    # anything else is git failing.
    SR_RC=0
    DEFAULT=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD) || SR_RC=$?
    case $SR_RC in
      0) DEFAULT=${DEFAULT#origin/} ;;
      1) DEFAULT="" ;;
      *) die "git symbolic-ref refs/remotes/origin/HEAD failed (exit $SR_RC)" ;;
    esac
  fi
  [ -n "$DEFAULT" ] || DEFAULT=main
}

MODE=$(bash "$SCRIPT_DIR/merge-mode.sh") || die "could not read .skills/merge_mode (merge-mode.sh's reason is above); nothing ran"
if [ "$MODE" = pr ]; then
  resolve_default
  REMEDY="in the main checkout, git switch $DEFAULT && git pull --ff-only, then re-run"
  CURRENT=$(git symbolic-ref --quiet --short HEAD) ||
    die "HEAD is detached; merge_mode is pr, so only the default branch ($DEFAULT) is deployed, at the merge: $REMEDY"
  [ "$CURRENT" = "$DEFAULT" ] ||
    die "HEAD is on $CURRENT; merge_mode is pr, so only the default branch ($DEFAULT) is deployed, at the merge, never a branch's tip: $REMEDY"
fi

# No upstream on the default branch is a tracking gap, not unpushed code
# (CR 2009, #587): `git clone --bare` sets no upstream and no fetch refspec,
# so a bare layout's default branch has no @{u} even after the post-merge
# pull. Off the default branch it is a branch nobody pushed.
if ! UPSTREAM=$(git rev-parse --verify '@{u}'); then
  CURRENT=$(git symbolic-ref --quiet --short HEAD) || CURRENT=""
  resolve_default
  if [ -n "$CURRENT" ] && [ "$CURRENT" = "$DEFAULT" ]; then
    die "HEAD ($DEFAULT, the default branch) has no upstream, which a bare clone never sets: git fetch origin && git branch --set-upstream-to=origin/$DEFAULT, then re-run (with no remote.origin.fetch, first: git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*')"
  fi
  die "HEAD has no upstream to compare with: push it first (Step 4)"
fi
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
