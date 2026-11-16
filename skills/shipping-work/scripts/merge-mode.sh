#!/usr/bin/env bash
# merge-mode.sh
# Prints how this project lands work on its default branch, read from
# .skills/merge_mode (#342): `direct` (merge locally, then push) or `pr` (push
# the branch and open a pull request; the merge happens on GitHub).
#
# ABSENT MEANS `direct`, which is what shipping-work and using-git-worktrees
# did before the knob existed (the operator's decision, 2026-10-30, on #342).
#
# PRESENT BUT UNUSABLE IS EXIT 2, NEVER `direct`. A typo that fell back to the
# default would merge locally in a repo that asked for review, which is the one
# direction the knob exists to prevent. An empty file is unusable too: a repo
# that wants the default deletes the file.
#
# ONE DEFINITION, TWO COPIES. shipping-work and using-git-worktrees each ship
# this file, because each skill resolves its own scripts (#63, #301).
# tests/structural/test_merge_mode_knob.py holds them byte-identical.
# THREE INLINE READERS also hold its grammar, for consumers that vendor
# neither skill: curating-context's install-cadence.sh and the workflow step
# it renders (tests/structural/test_cadence_merge_mode.py), and
# managing-skills' skills-submodule-update.sh
# (tests/structural/test_refresh_hook_pr_mode.py). Each feeds its reader the
# inputs test_merge_mode_knob.py feeds this file, wherever they can reach
# that reader, and wants this file's answer.
#
# THE KNOB is read from the primary checkout (the first `git worktree list`
# entry's work tree), as .skills/deploy_command is: an untracked file does
# not exist in a linked worktree, so asking the current checkout would read
# `direct` from every worktree of a `pr` repo. A bare primary has no work
# tree, so there the current checkout's is read; a `--separate-git-dir`
# primary's is known only from inside it. resolve_primary below is the one
# rule, shared with eight other readers (#612). Grammar: one word; blank
# lines and whole-line `#` comments are ignored.

set -euo pipefail

usage() {
  cat <<EOF
Usage: bash "$0"

Prints the project's merge mode, from the primary checkout's
.skills/merge_mode: 'direct' (merge locally, then push) or 'pr' (push the
branch and open a pull request). An absent file means 'direct'. A bare
primary has no checkout, so there the current checkout's file is read.

Grammar: one word, 'pr' or 'direct'. Blank lines and whole-line '#' comments
are ignored.

Exit codes:
  0  The mode is printed on stdout
  2  Nothing printed: the file is present but unusable (another word, more
     than one, none at all, not a readable file), git failed, or a bad
     argument
EOF
}

die() {
  echo "merge-mode: $*" >&2
  exit 2
}

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
resolve_primary() {
  local dir=$1 dirs wt block entry gd reason ver
  local -a g=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR git -C "$dir")
  RP_TREE="" RP_BARE=0 RP_ERR=""
  dirs=$("${g[@]}" rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || dirs=""
  if [ -n "$dirs" ] && [ "${dirs%%$'\n'*}" = "${dirs#*$'\n'}" ] &&
    RP_TREE=$("${g[@]}" rev-parse --show-toplevel 2>/dev/null); then
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
        RP_TREE=$("${g[@]}" rev-parse --show-toplevel 2>/dev/null); then
        return 0
      fi
      RP_TREE=""
      ;;
  esac
  if RP_TREE=$("${g[@]}" -C "$entry" rev-parse --show-toplevel 2>/dev/null); then
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

case "${1:-}" in
  --help | -h)
    usage
    exit 0
    ;;
  "") ;;
  *) die "unknown argument: $1 (see --help)" ;;
esac

# The primary, as the block above resolves it for eight other readers. A
# bare primary has no work tree, so its knob can only be this checkout's.
resolve_primary . || die "$RP_ERR"
if [ "$RP_BARE" = 1 ] && [ -z "$RP_TREE" ]; then
  die "the primary is bare and this is not a work tree, so there is no checkout to read .skills/merge_mode from"
fi
PRIMARY=$RP_TREE

KNOB="$PRIMARY/.skills/merge_mode"
REMEDY="write one word, 'pr' or 'direct', or delete the file for the default ('direct')"
if [ ! -e "$KNOB" ] && [ ! -L "$KNOB" ]; then
  echo direct
  exit 0
fi
{ [ -f "$KNOB" ] && [ -r "$KNOB" ]; } || die "$KNOB is present but not a readable file: $REMEDY"

# A checked open (docs/STYLE.md, `exec 3<`): `done <"$KNOB"` cannot branch on
# a failed open, and set -e would report it at exit 1.
if ! exec 3<"$KNOB"; then
  die "could not open $KNOB: $REMEDY"
fi
WORD=""
COUNT=0
while IFS= read -r line <&3 || [ -n "$line" ]; do
  line=${line%$'\r'}
  read -r -a words <<<"$line"
  [ "${#words[@]}" -gt 0 ] || continue
  case ${words[0]} in \#*) continue ;; esac
  COUNT=$((COUNT + ${#words[@]}))
  WORD=${words[0]}
done
exec 3<&-

[ "$COUNT" -gt 0 ] || die "$KNOB names no mode: $REMEDY"
[ "$COUNT" -eq 1 ] || die "$KNOB has $COUNT words; it takes one: $REMEDY"
case $WORD in
  pr | direct) echo "$WORD" ;;
  *) die "$KNOB says '$WORD', which is not a merge mode: $REMEDY" ;;
esac
