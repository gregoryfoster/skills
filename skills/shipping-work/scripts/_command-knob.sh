#!/usr/bin/env bash
# _command-knob.sh — the one reader of a .skills/ knob that names a command
# line: .skills/deploy_command (#345) and .skills/pre_restart (#557). Sourced
# by run-deploy-command.sh and run-pre-restart.sh; running it does nothing.
# One grammar, one parser: a fix here is a fix for both knobs.
#
# The caller defines die() (print, exit 2) before sourcing this.
#
# Grammar: exactly one command line of whitespace-separated words; blank lines
# and whole-line `#` comments are ignored; a trailing CR is dropped. No shell
# evaluation, so a pipe or a redirect belongs in the project's script. A
# first word with a `/` must be an executable file, relative to the primary
# checkout; one without is looked up on PATH.
# PRIMARY and WORDS are read by the scripts that source this, which shellcheck
# can't see.
# shellcheck disable=SC2034
set -euo pipefail

command_knob_usage() {
  cat <<'USAGE'
Usage: . _command-knob.sh    (sourced by run-deploy-command.sh and
                             run-pre-restart.sh; running it does nothing)

  primary_checkout        PRIMARY := the first `git worktree list` entry's
                          working tree (bare: the current checkout's)
  read_command_knob KNOB  WORDS := the knob's one command line, its first
                          word checked; die() on anything unusable
USAGE
}

case "${0##*/}" in
  _command-knob.sh) case "${1-}" in -h | --help) command_knob_usage; exit 0 ;; esac ;;
esac

# The first entry is a git dir, not a working tree, in two layouts (CR 1839b):
# a bare primary (`repo.git`) and a submodule (`<super>/.git/modules/<name>`).
# Neither holds a .skills/, so a knob there read as absent. --show-toplevel
# names the submodule's working tree; a bare primary has none, so the current
# checkout's top level stands in, as using-git-worktrees resolves it.
primary_checkout() {
  local wt_list
  wt_list=$(git worktree list --porcelain) || die "git worktree list failed: not in a git checkout?"
  PRIMARY=${wt_list%%$'\n'*}
  PRIMARY=${PRIMARY#worktree }
  [ -d "$PRIMARY" ] || die "could not resolve the primary checkout (got '$PRIMARY')"
  # A bare primary's "must be run in a work tree" is the expected answer here,
  # not a failure, and the fallback's own error is shown.
  PRIMARY=$(git -C "$PRIMARY" rev-parse --show-toplevel 2>/dev/null) ||
    PRIMARY=$(git rev-parse --show-toplevel) ||
    die "could not resolve a working tree for the primary checkout"
}

read_command_knob() {
  local knob=$1 line cmd path_of lines=0
  local -a words
  { [ -f "$knob" ] && [ -r "$knob" ]; } || die "$knob is present but not a readable file"
  WORDS=()
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line"
    [ "${#words[@]}" -gt 0 ] || continue
    case ${words[0]} in \#*) continue ;; esac
    lines=$((lines + 1))
    WORDS=("${words[@]}")
  done <"$knob"
  [ "$lines" -gt 0 ] || die "$knob has no command line"
  [ "$lines" -eq 1 ] || die "$knob names $lines commands; it takes one line"

  cmd=${WORDS[0]}
  case $cmd in
    */*)
      case $cmd in /*) path_of=$cmd ;; *) path_of="$PRIMARY/$cmd" ;; esac
      { [ -f "$path_of" ] && [ -x "$path_of" ]; } ||
        die "$cmd is not an executable file (a relative path resolves from $PRIMARY)"
      ;;
    *)
      command -v -- "$cmd" >/dev/null || die "$cmd is not on PATH"
      ;;
  esac
}
