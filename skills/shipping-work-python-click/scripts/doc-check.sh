#!/usr/bin/env bash
# doc-check.sh (Python/Click variant)
# Spot-check that documentation inventories haven't drifted from code.
#
# Lists files changed on the current branch vs the upstream default branch,
# and flags any that match SENSITIVE_PATHS — files whose existence, names,
# or structure is referenced from project docs (e.g., AGENTS.md, README.md).
# When sensitive paths change, the matching documentation sections likely
# need updates too.
#
# Python/Click defaults below. Projects tailor them by committing
# `.skills/doc-sensitive-paths` (what to watch) and `.skills/doc-sections`
# (what to spot-check on a hit) at the repo root — no fork required. Exits 0
# if no sensitive paths changed, 1 if any did, or 2 on an infra/tooling
# failure that prevented the check from running.
#
# Usage: bash <SKILL_SCRIPTS>/doc-check.sh [--help] [--base <ref>]
set -euo pipefail

# --- Project-configurable section ---------------------------------------------
# Add paths (one per line) — filenames, or directories, conventionally written
# with a trailing / (a slash-less entry still matches a directory).
# Entries match path SEGMENTS, not just the start of the path: `src/` matches
# `src/x.py` and `packages/co-core/src/x.py`, and `pyproject.toml` matches the
# root file and `packages/*/pyproject.toml`. Nested-package layouts (uv and
# hatch workspaces, Bedrock plugin trees) are the ordinary shape of the stacks
# these skills target, and root-anchored matching missed every file in them
# while still printing a clean green (#252). The cost of segment matching is
# that vendored and generated trees match too; for a spot-check that exits 1
# and asks a human to look, over-matching is the cheap failure and
# under-matching is the expensive one. Do not re-anchor these patterns.
#
# Projects tailor the list without forking this script by committing
# `.skills/doc-sensitive-paths` at the repo root — one path per line, blank
# lines and `#`-comments ignored, same grammar as `.skills/import-targets`.
# That file REPLACES the defaults below rather than extending them.
SENSITIVE_PATHS=(
  "AGENTS.md"
  "README.md"
  "pyproject.toml"
  "uv.lock"
  "src/"
  ".env.example"
)
# Advice printed on a hit: the doc sections to spot-check. Projects tailor it
# by committing `.skills/doc-sections` at the repo root — one section per
# line, same grammar as `.skills/doc-sensitive-paths`, and it too REPLACES
# the defaults below. The path list says what the gate watches; this says
# what to do about a hit. A repo that tailors one and not the other gets
# advice that is wrong for the repo it was tailored to — a section it does
# not keep, or silence about the directory whose docs actually drift (#261).
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory, command inventory"
  "README.md: orientation + curated links into canonical docs; only the README-owned bits (e.g. top-level CLI list, two-line quick start) should change here"
)
# ------------------------------------------------------------------------------

usage() {
  echo "Usage: bash \"$0\" [--help] [--base <ref>]"
  echo ""
  echo "Lists files changed on the current branch vs the upstream default branch"
  echo "and flags any that match the project's sensitive-path list."
  echo ""
  echo "  --base <ref>   Compare against <ref> instead of the auto-detected default."
  echo ""
  echo "Path list: .skills/doc-sensitive-paths at the repo root when present (one"
  echo "path per line), otherwise the built-in defaults. Entries match path"
  echo "segments, so src/ also matches packages/<pkg>/src/."
  echo ""
  echo "Advice on a hit: .skills/doc-sections at the repo root when present (one"
  echo "doc section per line — prose, not patterns), otherwise the built-in"
  echo "defaults. Both files ignore blank lines and #-comments, and each REPLACES"
  echo "its defaults rather than extending them."
  echo ""
  echo "Exit codes:"
  echo "  0  no sensitive paths changed (or no changes at all)"
  echo "  1  one or more sensitive paths changed"
  echo "  2  infra/tooling failure — the gate did not run. Covers: an unknown"
  echo "     or incomplete argument, a base ref auto-detection failure, a git"
  echo "     diff or git ls-files failure, a .skills/doc-sensitive-paths or"
  echo "     .skills/doc-sections that is empty or unusable (unreadable, a"
  echo "     broken symlink, not a regular file), an unsearchable .skills/, or"
  echo "     a path list where no entry matches any tracked file (a list that"
  echo "     cannot hit anything is not a pass). Other unexpected failures"
  echo "     (e.g., running outside a git repo) may surface git's own exit code"
  echo "     instead; check stderr in either case."
}

BASE_REF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --base)
      BASE_REF="${2:-}"
      if [[ -z "$BASE_REF" ]]; then
        echo "ERROR: --base requires a ref argument" >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      # Silently ignoring an unrecognized argument would compare against the
      # auto-detected base and report a confident result for the wrong diff.
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

# Read a .skills/ list file into PARSED: one entry per line, blank lines and
# `#`-comment lines dropped, surrounding whitespace trimmed. A `#` later in a
# line is content, not a comment — advice cites issues. `|| [[ -n "$line" ]]`
# keeps a final line the editor left without a trailing newline; without it a
# one-line file resolves to nothing and the override silently becomes the
# default it existed to replace. One reader serves both files, so a guard
# fixed here is fixed for both (#261).
#
# Everything below classifies a file the project HAS committed. Its callers
# test `-e || -L`, not `-f`, so a path present in any shape arrives here to be
# named rather than skipped: `-f` alone reads false for a dangling symlink, a
# symlink loop and a directory, and each of those silently restored the
# built-in defaults on a repo that had tailored the file — the #261 complaint
# one layer down, since a committed tailoring vanished without an error.
#
# The open is CHECKED rather than guarded by an `-r` precondition, which is
# the pattern measure-context.sh settled for the same class of bug (#184): a
# precondition narrows the window instead of closing it, cannot see a
# non-permission failure, and infers a diagnosis where the kernel already
# supplies one. Bash's own message reaches stderr first and names the real
# errno; ours adds the interpretation. Verified on bash 3.2.57 (the floor
# these scripts target): a failed `exec` inside `if !` returns rather than
# exiting, so `set -e` does not pre-empt this branch.
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
    echo "ERROR: $path exists but could not be opened (see the error above)." >&2
    echo "Fix it, or remove it to fall back to the built-in defaults." >&2
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

# Project overrides. Each file replaces its defaults wholesale — a project that
# could only widen a list could never drop an inventory it does not keep.
# Present-but-empty is exit 2 for both: a path list that yields nothing would
# pass everything, and advice that says nothing sends the reader nowhere. Both
# are checked up front rather than on the branch that uses them, so a
# misconfigured file fails on the first run instead of the first hit.
# A .skills/ that exists but cannot be SEARCHED hides both override files from
# every test below — `-e` and `-L` alike have to stat inside it — so both lists
# would quietly fall back to defaults. No widening of the per-file test can see
# this one; it has to be asked here. A missing .skills/ is the ordinary
# no-tailoring case and is not an error.
if [[ -d .skills && ! -x .skills ]]; then
  echo "ERROR: .skills/ exists but is not searchable; its override files" >&2
  echo "cannot be seen. Fix its permissions (chmod +x .skills)." >&2
  exit 2
fi

LIST_SOURCE="built-in defaults"
if [[ -e .skills/doc-sensitive-paths || -L .skills/doc-sensitive-paths ]]; then
  read_list_file .skills/doc-sensitive-paths
  if [[ ${#PARSED[@]} -eq 0 ]]; then
    echo "ERROR: .skills/doc-sensitive-paths exists but lists no paths." >&2
    echo "Remove the file to fall back to the built-in defaults." >&2
    exit 2
  fi
  SENSITIVE_PATHS=("${PARSED[@]}")
  LIST_SOURCE=".skills/doc-sensitive-paths"
fi

SECTIONS_SOURCE="built-in defaults"
if [[ -e .skills/doc-sections || -L .skills/doc-sections ]]; then
  read_list_file .skills/doc-sections
  if [[ ${#PARSED[@]} -eq 0 ]]; then
    echo "ERROR: .skills/doc-sections exists but lists no sections." >&2
    echo "Remove the file to fall back to the built-in defaults." >&2
    exit 2
  fi
  DOC_SECTIONS=("${PARSED[@]}")
  SECTIONS_SOURCE=".skills/doc-sections"
fi

# Segment match. Entries match whole path components at any depth. A
# slash-less entry names a file OR a directory, so `docs` still covers
# `docs/a.md` the way root-anchored prefix matching used to — the trailing
# slash stays a convention rather than a trap for anyone who omits it. Every
# continuation pattern requires a literal / after the entry, which is what
# keeps `pyproject.toml` from also claiming pyproject.toml.bak.
path_matches() {
  local file="$1" entry="$2"
  if [[ "$entry" == */ ]]; then
    case "$file" in "$entry"*|*"/$entry"*) return 0 ;; esac
  else
    case "$file" in
      "$entry"|*"/$entry"|"$entry"/*|*"/$entry"/*) return 0 ;;
    esac
  fi
  return 1
}

# Resolve base ref: explicit > origin/HEAD > origin/main > main
if [[ -z "$BASE_REF" ]]; then
  if git rev-parse --verify --quiet origin/HEAD >/dev/null; then
    BASE_REF=$(git rev-parse --abbrev-ref origin/HEAD)
  elif git rev-parse --verify --quiet origin/main >/dev/null; then
    BASE_REF="origin/main"
  elif git rev-parse --verify --quiet main >/dev/null; then
    BASE_REF="main"
  else
    echo "ERROR: could not resolve a base ref. Pass --base <ref>." >&2
    exit 2
  fi
fi

# core.quotePath=false: git otherwise C-quotes any path with a non-ASCII or
# special character — `src/co/café.py` arrives as `"src/co/caf\303\251.py"`,
# and the leading quote defeats the anchored half of path_matches. That is the
# #252 failure mode (a miss printing as a clean green) reached by a filename
# instead of by nesting. It also keeps the reported paths readable.
DIFF_RC=0
CHANGED=$(git -c core.quotePath=false diff --name-only "${BASE_REF}...HEAD") || DIFF_RC=$?
if [[ $DIFF_RC -ne 0 ]]; then
  echo "ERROR: git diff --name-only ${BASE_REF}...HEAD failed (exit $DIFF_RC)" >&2
  exit 2
fi

if [[ -z "$CHANGED" ]]; then
  echo "No changes vs $BASE_REF."
  exit 0
fi

HITS=()
while IFS= read -r file; do
  for entry in "${SENSITIVE_PATHS[@]}"; do
    if path_matches "$file" "$entry"; then
      HITS+=("$file")
      break
    fi
  done
done <<< "$CHANGED"

if [[ ${#HITS[@]} -eq 0 ]]; then
  # A list that matches nothing in the tree prints exactly what a genuinely
  # doc-neutral branch prints, so its miss is indistinguishable from its pass.
  # Probe the tree here and only here, where that ambiguity lives: on the
  # exit-1 path the list has demonstrably hit, and a dead-entry census would
  # be noise. The probe reuses path_matches so it cannot disagree with the
  # matcher it is vouching for.
  #
  # Scalar capture, not `done < <(git ls-files)`: this output drives a
  # did-we-find-anything branch, and a process substitution hides the exit code
  # from the parent shell. A silently failed ls-files would leave every entry
  # unmatched and turn the verdict below into "the list is misconfigured for
  # this repo" — a confident diagnosis of the wrong problem, pointing the
  # reader at a list that was fine. See docs/STYLE.md, gate-script discipline.
  LS_RC=0
  TRACKED=$(git -c core.quotePath=false ls-files) || LS_RC=$?
  if [[ $LS_RC -ne 0 ]]; then
    echo "ERROR: git ls-files failed (exit $LS_RC); cannot tell a doc-neutral" >&2
    echo "branch from a path list that matches nothing." >&2
    exit 2
  fi

  LIVE=()
  for i in "${!SENSITIVE_PATHS[@]}"; do
    LIVE[i]=0
  done
  while IFS= read -r file; do
    for i in "${!SENSITIVE_PATHS[@]}"; do
      if [[ ${LIVE[i]} -eq 0 ]] && path_matches "$file" "${SENSITIVE_PATHS[i]}"; then
        LIVE[i]=1
      fi
    done
  done <<< "$TRACKED"

  DEAD=()
  for i in "${!SENSITIVE_PATHS[@]}"; do
    if [[ ${LIVE[i]} -eq 0 ]]; then
      DEAD+=("${SENSITIVE_PATHS[i]}")
    fi
  done

  if [[ ${#DEAD[@]} -eq ${#SENSITIVE_PATHS[@]} ]]; then
    echo "ERROR: no entry in the sensitive-path list ($LIST_SOURCE) matches any" >&2
    echo "tracked file, so this check could not have found anything. The list is" >&2
    echo "misconfigured for this repo — that is a gate that did not run, not a pass:" >&2
    printf '  - %s\n' "${SENSITIVE_PATHS[@]}" >&2
    echo "Tailor it in .skills/doc-sensitive-paths (one path per line)." >&2
    exit 2
  fi

  # Name the list on every verdict. A green that does not say what it consulted
  # cannot be audited by the reader who most needs to — the one wondering
  # whether this repo ever tailored the list at all.
  echo "No sensitive paths changed vs $BASE_REF (list: $LIST_SOURCE)."
  if [[ ${#DEAD[@]} -gt 0 ]]; then
    echo ""
    echo "Note: these entries ($LIST_SOURCE) match no tracked file, so they could"
    echo "not have contributed to that result:"
    printf '  - %s\n' "${DEAD[@]}"
  fi
  exit 0
fi

echo "Sensitive paths changed vs $BASE_REF (list: $LIST_SOURCE):"
printf '  - %s\n' "${HITS[@]}"
echo ""
# Name the advice's source the way the verdict names the list's. "Route table"
# printed under "built-in defaults" tells the reader exactly which file to add.
echo "Spot-check these doc sections before shipping (advice: $SECTIONS_SOURCE):"
printf '  - %s\n' "${DOC_SECTIONS[@]}"
exit 1
