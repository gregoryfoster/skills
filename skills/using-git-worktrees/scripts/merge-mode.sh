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
#
# THE KNOB is read from the primary checkout (the first `git worktree list`
# entry), as .skills/deploy_command is: an untracked file does not exist in a
# linked worktree, so asking the current checkout would read `direct` from
# every worktree of a `pr` repo. Grammar: one word; blank lines and
# whole-line `#` comments are ignored.

set -euo pipefail

usage() {
  cat <<EOF
Usage: bash "$0"

Prints the project's merge mode, from the primary checkout's
.skills/merge_mode: 'direct' (merge locally, then push) or 'pr' (push the
branch and open a pull request). An absent file means 'direct'.

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
PRIMARY=${WT_LIST%%$'\n'*}
PRIMARY=${PRIMARY#worktree }
[ -d "$PRIMARY" ] || die "could not resolve the primary checkout (got '$PRIMARY')"

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
