#!/usr/bin/env bash
# managing-skills-doctor: do not remove this marker — install-doctor.sh greps it
# doctor.sh — diagnose and self-heal dangling skill symlinks.
#
# When this repo is vendored via the managing-skills git-submodule + symlink
# pattern, a consumer checkout that hasn't initialized submodules
# (fresh `git worktree add`, shallow CI clone, etc.) leaves the
# .claude/skills/<name> → ../../skills/<name> → ../skills-vendor/.../<name>
# chain dangling. Scripts referenced from SKILL.md then fail with confusing
# "No such file or directory" errors even though the symlinks exist.
#
# This script is installed as a real (non-symlinked) file at
# <repo-root>/.skills/doctor.sh so it remains reachable even when the
# vendor chain is broken. It walks skills/* symlinks, attempts a
# `git submodule update --init --recursive` if any dangle, and prints a
# clear actionable error if self-healing fails.
#
# Designed for use as a Phase 1 preflight in every reviewing-* / shipping-*
# SKILL.md invocation:
#
#   bash .skills/doctor.sh
#   bash scripts/gather-context.sh
#
# Usage: bash .skills/doctor.sh [--check-only] [--verbose] [--help]
set -euo pipefail

VERSION="2026-05-26-2"

CHECK_ONLY=0
VERBOSE=0
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=1 ;;
    --verbose|-v) VERBOSE=1 ;;
    --version) echo "$VERSION"; exit 0 ;;
    --help|-h)
      cat <<EOF
Usage: bash .skills/doctor.sh [--check-only] [--verbose]

Diagnose and self-heal dangling skill symlinks in skills/.

If any skills/<name> symlink does not resolve and a .git directory is
present, runs 'git submodule update --init --recursive' and re-checks.
Exits 0 silently when healthy. Exits non-zero with an actionable error
when self-healing fails or is not possible (e.g. no .git directory).

Options:
  --check-only    Report broken symlinks but do not run submodule init
                  (overridden by the archive-checkout path when .git is
                  absent — the archive case prints its own diagnosis).
  --verbose, -v   Print resolution details even when healthy.
  --version       Print script version and exit.
  --help, -h      Show this help and exit.

Exit codes:
  0  All skill symlinks resolve (or skills/ does not exist).
  1  One or more symlinks remain broken after self-heal attempt.
  2  Invalid invocation (e.g. unknown flag).
EOF
      exit 0
      ;;
    *)
      echo "doctor.sh: unknown option: $arg" >&2
      echo "Try 'bash .skills/doctor.sh --help' for usage." >&2
      exit 2
      ;;
  esac
done

# Resolve the project root. The doctor is normally invoked from the repo
# root, but we tolerate being called from a subdirectory.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

# Nothing to check if the consumer doesn't use the skills/ pattern.
if [ ! -d skills ]; then
  [ "$VERBOSE" = "1" ] && echo "doctor: no skills/ directory — nothing to check" >&2
  exit 0
fi

# BROKEN is the output channel of scan_broken — declared at top scope so the
# function's communication pattern is visible without reading every call
# site. Using an array (rather than a single string) preserves
# paths-with-spaces correctly when later expanded as "${BROKEN[@]}".
declare -a BROKEN=()

# Walks skills/* and populates BROKEN with any dangling symlinks. A symlink
# is "broken" when it exists but its target does not resolve. Local
# overrides (regular directories) are skipped — they're not symlinks.
scan_broken() {
  BROKEN=()
  local entry
  for entry in skills/*; do
    [ -L "$entry" ] || continue
    if [ ! -e "$entry" ]; then
      BROKEN+=("$entry")
    fi
  done
}

scan_broken

if [ "${#BROKEN[@]}" -eq 0 ]; then
  [ "$VERBOSE" = "1" ] && echo "doctor: all skill symlinks resolve" >&2
  exit 0
fi

# At least one dangling symlink. Distinguish archive-checkout (no .git) from
# the normal git-submodule case before either self-healing or reporting,
# so --check-only never suggests a `git submodule` command in a checkout
# that doesn't have a .git dir.
if [ ! -d .git ] && [ ! -f .git ]; then
  echo "doctor: dangling skill symlinks detected and no .git directory present:" >&2
  printf '  %s\n' "${BROKEN[@]}" >&2
  echo "" >&2
  echo "This checkout was likely created from a source archive (zip/tarball)" >&2
  echo "rather than 'git clone'. The submodule pattern this repo uses is not" >&2
  echo "compatible with archive downloads. Clone with --recurse-submodules" >&2
  echo "instead, or vendor the skill scripts manually." >&2
  exit 1
fi

if [ "$CHECK_ONLY" = "1" ]; then
  echo "doctor: dangling skill symlinks detected:" >&2
  printf '  %s\n' "${BROKEN[@]}" >&2
  echo "Run 'git submodule update --init --recursive' to repair." >&2
  exit 1
fi

echo "doctor: dangling skill symlinks detected — initializing submodules..." >&2
if ! git submodule update --init --recursive >&2; then
  echo "doctor: 'git submodule update --init --recursive' failed" >&2
  exit 1
fi

# Re-check after self-heal.
scan_broken
if [ "${#BROKEN[@]}" -gt 0 ]; then
  echo "doctor: symlinks still dangling after submodule init:" >&2
  printf '  %s\n' "${BROKEN[@]}" >&2
  echo "" >&2
  echo "The .gitmodules entry for the vendor repo may be missing, or the" >&2
  echo "symlink target points to a path that does not exist upstream." >&2
  exit 1
fi

[ "$VERBOSE" = "1" ] && echo "doctor: self-healed; all skill symlinks resolve" >&2
exit 0
