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
# read from the primary checkout (the first `git worktree list` entry), where
# Step 8 runs, like deploy_command and pre_restart. Deploying stays with
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
     comments; or git failed. Fix it; never fall back to the stack file
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

WT_LIST=$(git worktree list --porcelain) || die "git worktree list failed: not in a git checkout?"
PRIMARY=${WT_LIST%%$'\n'*}
PRIMARY=${PRIMARY#worktree }
[ -d "$PRIMARY" ] || die "could not resolve the primary checkout (got '$PRIMARY')"
# A bare primary or a submodule lists a git dir first, which holds no .skills/
# (CR 1839b): normalised as _command-knob.sh's primary_checkout does, and a
# bare primary's "must be run in a work tree" is the expected answer here.
PRIMARY=$(git -C "$PRIMARY" rev-parse --show-toplevel 2>/dev/null) ||
  PRIMARY=$(git rev-parse --show-toplevel) ||
  die "could not resolve a working tree for the primary checkout"
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
