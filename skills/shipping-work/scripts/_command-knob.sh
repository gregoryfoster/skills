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

# here_git <args>: git for resolving the primary, without an inherited
# GIT_DIR or GIT_WORK_TREE (#605, set R's CR 1895). Git exports GIT_DIR to
# every hook, absolute in a linked worktree, and it beats -C: asked for a
# submodule's work tree, git named the entry itself, and the knob read as
# absent. merge-mode.sh holds the same rule. Every call below answers for the
# checkout this runs in (docs/STYLE.md, #189).
here_git() {
  env -u GIT_DIR -u GIT_WORK_TREE git "$@"
}

# The first entry is a git dir, not a working tree, in two layouts (CR 1839b):
# a bare primary (`repo.git`) and a submodule (`<super>/.git/modules/<name>`).
# Neither holds a .skills/, so a knob there read as absent. --show-toplevel
# names the submodule's working tree; a bare primary has none, so the current
# checkout's top level stands in, as using-git-worktrees resolves it.
# Only a `bare` line in the first porcelain block means bare (CR 1858): any
# other rev-parse failure, "dubious ownership" say, exits 2 with git's reason,
# since standing in the current checkout would run a feature branch's knob.
# One exception, which is no other checkout (#605, set R's CR 1892): a
# primary whose .git is a pointer file (`git init --separate-git-dir`) lists
# its store, which names no work tree. From that primary itself, the work
# tree is this one: its git dir is the common dir. From a linked worktree git
# knows no path to it, so that stays exit 2, and says so.
primary_checkout() {
  local wt_list block entry dirs hint ver
  wt_list=$(here_git worktree list --porcelain) || die "git worktree list failed: not in a git checkout?"
  block=${wt_list%%$'\n\n'*}
  entry=${block%%$'\n'*}
  entry=${entry#worktree }
  [ -d "$entry" ] || die "could not resolve the primary checkout (got '$entry')"
  case $'\n'"$block"$'\n' in
    *$'\n'bare$'\n'*)
      PRIMARY=$(here_git rev-parse --show-toplevel) ||
        die "the primary ($entry) is bare and this is not a working tree"
      ;;
    *)
      if ! PRIMARY=$(here_git -C "$entry" rev-parse --show-toplevel 2>/dev/null); then
        dirs=$(here_git rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || dirs=""
        if [ -z "$dirs" ] || [ "${dirs%%$'\n'*}" != "${dirs#*$'\n'}" ] ||
          ! PRIMARY=$(here_git rev-parse --show-toplevel 2>/dev/null); then
          # Asked again for git's reason, which goes to stderr.
          here_git -C "$entry" rev-parse --show-toplevel >/dev/null || true
          hint=""
          if [ "$(here_git -C "$entry" rev-parse --is-inside-git-dir 2>/dev/null)" = true ]; then
            # Below git 2.31, rev-parse echoes the flag back as a line, so
            # the fallback above can't fire even from the primary (CR 1999).
            # The core phrase is chain W's resolver's, word for word.
            if [ "${dirs%%$'\n'*}" = --path-format=absolute ]; then
              ver=$(here_git --version 2>/dev/null) || ver=""
              ver=${ver#git version }
              hint="; it is a git dir with no work tree, as a primary whose .git is a file makes it (git init --separate-git-dir), and git ${ver:-(unknown version)} predates 2.31, which this layout needs to tell its primary from a linked worktree: upgrade git"
            else
              hint="; it is a git dir with no work tree, as a primary whose .git is a file makes it (git init --separate-git-dir), and only that primary knows its work tree, so run this from the primary checkout"
            fi
          fi
          die "could not resolve the primary checkout's working tree from $entry (git's reason is above)$hint"
        fi
      fi
      ;;
  esac
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
