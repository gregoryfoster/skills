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
                          working tree (bare: the current checkout's; a
                          --separate-git-dir primary: only from itself)
  read_command_knob KNOB  WORDS := the knob's one command line, its first
                          word checked; die() on anything unusable
USAGE
}

case "${0##*/}" in
  _command-knob.sh) case "${1-}" in -h | --help) command_knob_usage; exit 0 ;; esac ;;
esac

# >>> resolve_primary: one body in nine readers (#612), held byte-identical
# by tests/structural/test_primary_checkout_copies.py. Change every copy.
#
# resolve_primary <dir>: the primary checkout of the repository at <dir>,
# where its untracked .skills/ knobs live. Prints nothing.
#   0: RP_TREE is the primary's work tree. For a bare primary RP_BARE is 1
#      and RP_TREE is <dir>'s own top level, empty when <dir> has none.
#   1: RP_ERR says what failed, with git's reason, and what to run.
# Git is asked without an inherited GIT_DIR, GIT_WORK_TREE or GIT_COMMON_DIR:
# git exports GIT_DIR to every hook, and each of them beats -C (CR 1895).
#   1. From the primary itself (its git dir is the common dir), its own top
#      level, asked first: a --separate-git-dir store whose path ends in
#      /.git is listed as the directory above it, a work tree to git.
#   2. Else the first `git worktree list --porcelain` block. Its `bare` line
#      counts once git confirms it (the shared core.bare, read from here, as
#      a store git refuses for its owner still has; else the entry's own
#      answer): below git 2.25 a --separate-git-dir store is listed bare too.
#      Where that store is this checkout's git dir, this is the primary.
#   3. Any other entry is asked for its work tree (a submodule's through
#      core.worktree). That failing is a refusal, never a fallback (CR 1858).
# An empty top level is none: inside a git dir git 2.17 prints nothing, at
# exit 0, where later git refuses.
resolve_primary() {
  local dir=$1 dirs wt block entry gd reason ver
  local -a g=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR git -C "$dir")
  RP_TREE="" RP_BARE=0 RP_ERR=""
  dirs=$("${g[@]}" rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || dirs=""
  if [ -n "$dirs" ] && [ "${dirs%%$'\n'*}" = "${dirs#*$'\n'}" ] &&
    RP_TREE=$("${g[@]}" rev-parse --show-toplevel 2>/dev/null) && [ -n "$RP_TREE" ]; then
    return 0
  fi
  RP_TREE=""
  if ! wt=$("${g[@]}" worktree list --porcelain 2>/dev/null); then
    reason=$("${g[@]}" worktree list --porcelain 2>&1 >/dev/null) || true
    reason=${reason%%$'\n'*}
    RP_ERR="git worktree list failed in '$dir' (git: ${reason:-no reason given}), so the primary checkout is unknown"
    return 1
  fi
  block=${wt%%$'\n\n'*}
  entry=${block%%$'\n'*}
  entry=${entry#worktree }
  case $'\n'"$block"$'\n' in
    *$'\n'bare$'\n'*)
      if [ "$("${g[@]}" config --bool core.bare 2>/dev/null)" = true ] ||
        [ "$("${g[@]}" -C "$entry" rev-parse --is-bare-repository 2>/dev/null)" = true ]; then
        RP_BARE=1
        RP_TREE=$("${g[@]}" rev-parse --show-toplevel 2>/dev/null) || RP_TREE=""
        return 0
      fi
      gd=$("${g[@]}" rev-parse --git-dir 2>/dev/null) &&
        gd=$(CDPATH='' cd -- "$dir" && CDPATH='' cd -- "$gd" && pwd -P) || gd=""
      if [ -n "$gd" ] && [ "$gd" = "$(CDPATH='' cd -- "$entry" 2>/dev/null && pwd -P)" ] &&
        RP_TREE=$("${g[@]}" rev-parse --show-toplevel 2>/dev/null) && [ -n "$RP_TREE" ]; then
        return 0
      fi
      RP_TREE=""
      ;;
  esac
  if RP_TREE=$("${g[@]}" -C "$entry" rev-parse --show-toplevel 2>/dev/null) && [ -n "$RP_TREE" ]; then
    return 0
  fi
  RP_TREE=""
  reason=$("${g[@]}" -C "$entry" rev-parse --show-toplevel 2>&1 >/dev/null) || true
  reason=${reason%%$'\n'*}
  RP_ERR="could not resolve the primary checkout's work tree from $entry (git: ${reason:-no reason given})"
  if [ "$("${g[@]}" -C "$entry" rev-parse --is-inside-git-dir 2>/dev/null)" = true ]; then
    RP_ERR="$RP_ERR; it is a git dir with no work tree, as a primary whose .git is a file makes it (git init --separate-git-dir), and"
    if [ "${dirs%%$'\n'*}" = --path-format=absolute ]; then
      ver=$(git --version 2>/dev/null) || ver=""
      ver=${ver#git version }
      RP_ERR="$RP_ERR git ${ver:-(unknown version)} predates 2.31, which this layout needs to tell its primary from a linked worktree: upgrade git (from a linked worktree, then run from the primary checkout)"
    else
      RP_ERR="$RP_ERR only that primary knows its work tree, so run this from the primary checkout"
    fi
  fi
  return 1
}
# <<< resolve_primary

# PRIMARY := the primary checkout's working tree, resolved by the block above
# (#612), which run-deploy-command.sh and run-pre-restart.sh share with
# merge-mode.sh. A bare primary has none, so the current checkout's top
# level stands in, as using-git-worktrees resolves it; anything else git
# can't resolve exits 2 with git's reason, since standing in the current
# checkout would run a feature branch's knob (CR 1858).
primary_checkout() {
  resolve_primary . || die "$RP_ERR"
  PRIMARY=$RP_TREE
  if [ "$RP_BARE" = 1 ] && [ -z "$PRIMARY" ]; then
    die "the primary is bare and this is not a working tree"
  fi
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
