#!/usr/bin/env bash
# read-next-steps.sh
# Prints a project's own Step 8 rows from .skills/next-steps (#564).
#
# Step 8's next-steps rows came only from the detected framework's stack file
# (references/stack-*.md), so a project whose post-merge work differs, such as
# a Bedrock site deploying by workflow dispatch, had no file the skill reads to
# say so: only an AGENTS.md note, or a scripts/pre-ship.sh wrapper used as a
# messaging channel. pr mode widened the gap: the post-merge pass often runs in
# a later session than the PR pass.
#
# THE FILE has .skills/doc-sections' shape and grammar: one row per line,
# blank lines and whole-line `#` comments dropped, surrounding whitespace
# trimmed, a `#` later in a line kept as content. A row is free text naming
# what triggers it and what to do, e.g.
#   Data reload: data/*.csv changed -> run scripts/reload.sh
# Its rows REPLACE the stack file's table rather than extending it. It is
# read from the primary checkout (the first `git worktree list` entry's work
# tree), where Step 8 runs, like deploy_command and pre_restart. A primary
# made with --separate-git-dir names no work tree to its linked worktrees, so
# only the primary itself can read this. Deploying stays with
# .skills/deploy_command; this is only the notification table.
#
# PRESENT BUT UNUSABLE IS EXIT 2, never a silent fallback to the stack file's
# rows: a dangling symlink, a directory or other non-regular file, a file that
# can't be opened, one with no row after comments, or a .skills that is a
# dangling link, not a directory, or not searchable. read_list_file and
# override_present are doc-check.sh's own, byte for byte, held in step by
# tests/structural/test_next_steps_knob.py.

set -euo pipefail

usage() {
  cat <<EOF
Usage: bash "$0"

Prints the rows of the primary checkout's .skills/next-steps, one per line on
stdout, and names the source on stderr. Its rows replace the detected stack
file's Step 8 table.

Exit codes:
  0  Rows printed: use them, and only them, as Step 8's table
  2  .skills/next-steps (or .skills itself) is present but unusable: a
     dangling symlink, not a regular file, unreadable, or no row after
     comments; or git failed. Fix it; never fall back to the stack file.
     From a linked worktree of a --separate-git-dir primary: run from the
     primary checkout
  3  No .skills/next-steps: the detected framework's stack file, else
     SKILL.md's common categories
EOF
}

die() {
  echo "read-next-steps: $*" >&2
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

# The primary, resolved by the block above (#612). A bare primary has no
# work tree, so the current checkout's top level stands in.
resolve_primary . || die "$RP_ERR"
PRIMARY=$RP_TREE
if [ "$RP_BARE" = 1 ] && [ -z "$PRIMARY" ]; then
  die "the primary is bare and this is not a working tree"
fi
cd "$PRIMARY"

# From doc-check.sh, byte for byte (see the header).
override_present() {
  [[ -e "$1" || -L "$1" ]]
}

# From doc-check.sh, byte for byte (see the header).
read_list_file() {
  local path="$1" line
  if [[ -L "$path" && ! -e "$path" ]]; then
    echo "ERROR: $path is a symlink whose target does not resolve." >&2
    echo "Repoint or remove it: a broken link is not an empty list." >&2
    exit 2
  fi
  if [[ ! -f "$path" ]]; then
    echo "ERROR: $path exists but is not a regular file." >&2
    echo "Replace it with a list file, or remove it to fall back to the defaults." >&2
    exit 2
  fi
  if ! exec 3<"$path"; then
    echo "ERROR: $path exists but could not be opened — permissions, or it" >&2
    echo "changed between the checks above and this read. Bash prints the exact" >&2
    echo "errno on the line before this one when stderr is shown." >&2
    exit 2
  fi
  PARSED=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    # Pure-bash trim of leading/trailing whitespace (no fork+pipe per line).
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    PARSED+=("$line")
  done <&3
  exec 3<&-
}

# A .skills that can't be searched hides the file from `-e` and `-L` alike,
# which would read as absent: doc-check.sh asks the same three questions.
if override_present .skills; then
  [[ -e .skills ]] || die "$PRIMARY/.skills is a symlink whose target does not resolve, so .skills/next-steps can't be seen"
  [[ -d .skills ]] || die "$PRIMARY/.skills exists but is not a directory, so .skills/next-steps can't be seen"
  [[ -x .skills ]] || die "$PRIMARY/.skills/ is not searchable, so .skills/next-steps can't be seen (chmod +x .skills)"
fi

if ! override_present .skills/next-steps; then
  echo "no .skills/next-steps in $PRIMARY: use the detected stack file's Step 8 table"
  exit 3
fi
read_list_file .skills/next-steps
[[ ${#PARSED[@]} -gt 0 ]] ||
  die "$PRIMARY/.skills/next-steps lists no rows. Remove it to use the stack file's table"

echo "read-next-steps: Step 8's rows are .skills/next-steps (in $PRIMARY), not the stack file's" >&2
printf '%s\n' "${PARSED[@]}"
