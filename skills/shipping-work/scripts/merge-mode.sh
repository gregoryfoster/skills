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
# primary's is known only from inside it. Grammar: one word; blank lines and
# whole-line `#` comments are ignored.

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

case "${1:-}" in
  --help | -h)
    usage
    exit 0
    ;;
  "") ;;
  *) die "unknown argument: $1 (see --help)" ;;
esac

WT_LIST=$(git worktree list --porcelain) || die "git worktree list failed: not in a git checkout?"
# The primary is the first porcelain block, up to the first blank line. Its
# entry is a git dir, not a work tree, in two layouts (CR 1860): `repo.git`
# for a bare primary, and `<super>/.git/modules/<n>` in a submodule. A block
# with a `bare` line has no work tree, so the knob can only live in the
# current checkout; any other entry is asked for its work tree (a
# submodule's via core.worktree). That ask failing is exit 2, never a
# fallback to another checkout: "dubious ownership" would read its knob.
# One exception, which is no other checkout (CR 1892): a primary whose .git
# is a pointer file (`git init --separate-git-dir`) lists its store, which
# names no work tree. From that primary itself, the work tree is this one:
# its git dir is the common dir. From a linked worktree git knows no path to
# it, so that stays exit 2, and says so.
PRIMARY_BLOCK=${WT_LIST%%$'\n\n'*}
PRIMARY_ENTRY=${PRIMARY_BLOCK%%$'\n'*}
PRIMARY_ENTRY=${PRIMARY_ENTRY#worktree }
case $'\n'"$PRIMARY_BLOCK"$'\n' in
  *$'\n'bare$'\n'*)
    PRIMARY=$(git rev-parse --show-toplevel) ||
      die "the primary is bare and this is not a work tree, so there is no checkout to read .skills/merge_mode from"
    ;;
  *)
    if ! PRIMARY=$(git -C "$PRIMARY_ENTRY" rev-parse --show-toplevel 2>/dev/null); then
      DIRS=$(git rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || DIRS=""
      if [ -z "$DIRS" ] || [ "${DIRS%%$'\n'*}" != "${DIRS#*$'\n'}" ] ||
        ! PRIMARY=$(git rev-parse --show-toplevel 2>/dev/null); then
        # Asked again for git's reason, which goes to stderr.
        git -C "$PRIMARY_ENTRY" rev-parse --show-toplevel >/dev/null || true
        HINT=""
        if [ "$(git -C "$PRIMARY_ENTRY" rev-parse --is-inside-git-dir 2>/dev/null)" = true ]; then
          HINT="; it is a git dir with no work tree, as a primary whose .git is a file makes it (git init --separate-git-dir), and only that primary knows its work tree, so run this from the primary checkout"
        fi
        die "could not resolve the primary checkout '$PRIMARY_ENTRY' (git's reason is above)$HINT"
      fi
    fi
    ;;
esac

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
