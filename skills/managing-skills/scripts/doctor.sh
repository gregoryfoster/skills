#!/usr/bin/env bash
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

VERSION="2026-05-25-1"

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
  --check-only    Report broken symlinks but do not run submodule init.
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
  [ "$VERBOSE" = "1" ] && echo "doctor: no skills/ directory — nothing to check"
  exit 0
fi

# Collect broken top-level symlinks under skills/. A symlink is "broken"
# when it exists but its target does not resolve to an existing path.
# Local overrides (regular directories) are skipped — they're not symlinks.
collect_broken() {
  local broken=()
  local entry
  for entry in skills/*; do
    [ -L "$entry" ] || continue
    if [ ! -e "$entry" ]; then
      broken+=("$entry")
    fi
  done
  printf '%s\n' "${broken[@]:-}"
}

BROKEN_LIST="$(collect_broken)"

if [ -z "$BROKEN_LIST" ]; then
  [ "$VERBOSE" = "1" ] && echo "doctor: all skill symlinks resolve"
  exit 0
fi

# At least one dangling symlink. Decide whether to attempt self-heal.
if [ "$CHECK_ONLY" = "1" ]; then
  echo "doctor: dangling skill symlinks detected:" >&2
  printf '  %s\n' $BROKEN_LIST >&2
  echo "Run 'git submodule update --init --recursive' to repair." >&2
  exit 1
fi

if [ ! -d .git ] && [ ! -f .git ]; then
  echo "doctor: dangling skill symlinks detected and no .git directory present:" >&2
  printf '  %s\n' $BROKEN_LIST >&2
  echo "" >&2
  echo "This checkout was likely created from a source archive (zip/tarball)" >&2
  echo "rather than 'git clone'. The submodule pattern this repo uses is not" >&2
  echo "compatible with archive downloads. Clone with --recurse-submodules" >&2
  echo "instead, or vendor the skill scripts manually." >&2
  exit 1
fi

echo "doctor: dangling skill symlinks detected — initializing submodules..." >&2
if ! git submodule update --init --recursive >&2; then
  echo "doctor: 'git submodule update --init --recursive' failed" >&2
  exit 1
fi

# Re-check after self-heal.
BROKEN_AFTER="$(collect_broken)"
if [ -n "$BROKEN_AFTER" ]; then
  echo "doctor: symlinks still dangling after submodule init:" >&2
  printf '  %s\n' $BROKEN_AFTER >&2
  echo "" >&2
  echo "The .gitmodules entry for the vendor repo may be missing, or the" >&2
  echo "symlink target points to a path that does not exist upstream." >&2
  exit 1
fi

[ "$VERBOSE" = "1" ] && echo "doctor: self-healed; all skill symlinks resolve"
exit 0
