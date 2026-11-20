#!/usr/bin/env bash
# doc-check.sh
# Spot-check that documentation inventories haven't drifted from code.
#
# Lists files changed on the current branch vs the upstream default branch,
# and flags any that match SENSITIVE_PATHS — files whose existence, names,
# or structure is referenced from project docs (e.g., AGENTS.md, README.md).
# When sensitive paths change, the matching documentation sections likely
# need updates too.
#
# This is a SKELETON. Projects should tailor the path list and the advice
# printed on a hit — by committing `.skills/doc-sensitive-paths` and
# `.skills/doc-sections` (preferred) or by editing the SENSITIVE_PATHS and
# DOC_SECTIONS arrays below. Exits 0 if no sensitive paths changed, 1 if
# any did (so it can gate shipping if desired), or 2 on an infra/tooling
# failure that prevented the check from running.
#
# Usage: bash "<doc-check.sh>" [--help] [--base <ref>]
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
  "composer.json"
  "package.json"
  "schema.sql"
  "src/api/"
  "src/models/"
  "skills/"
)
# Advice printed on a hit: the doc sections to spot-check. Projects tailor it
# by committing `.skills/doc-sections` at the repo root — one section per
# line, same grammar as `.skills/doc-sensitive-paths`, and it too REPLACES
# the defaults below. The path list says what the gate watches; this says
# what to do about a hit. A repo that tailors one and not the other gets
# advice that is wrong for the repo it was tailored to — a section it does
# not keep, or silence about the directory whose docs actually drift (#261).
DOC_SECTIONS=(
  "AGENTS.md: project structure, conventions, skill inventory"
  "README.md: orientation + curated links into canonical docs; only the README-owned bits (e.g. top-level CLI list, two-line quick start) should change here"
)

# Framework defaults (#537, plan Step 5 row 23). The per-stack copies of this
# script differed only in the two lists above, so this one asks
# detect-stack.sh for the repo's frameworks and, when it finds any, watches
# AGENTS.md, README.md and exactly the paths each framework's copy watched,
# and names each one's inventory in the AGENTS.md advice. A repo with no
# framework keeps the generic lists above. The .skills/ files still REPLACE
# whichever defaults apply. A copy shipped without detect-stack.sh keeps the
# generic lists too; one whose detect-stack.sh fails is a tooling failure.
# Outside a git repository there is nothing to detect: this block runs before
# the arguments are read, and `--help` must work anywhere, so it steps aside
# and leaves the body to run on the generic lists (CR 1393).
#
# detect-stack.sh is looked for beside this script's target, through the
# symlink chain (CR 1865): under a consumer's per-script symlink
# (managing-skills' local-overrides.md) the link's own directory has none, and
# the framework watch list was silently lost. `cd -P`, not a logical cd:
# through a .claude/skills/<dir-link> prefix a relative link's `..` must cross
# the directory link as the kernel does, not by spelling.
_self=${BASH_SOURCE[0]}
_n=0
while [[ -L $_self && $_n -lt 10 ]]; do
  _t=$(readlink "$_self") || break
  case $_t in
    /*) _self=$_t ;;
    *) _self=$(dirname "$_self")/$_t ;;
  esac
  _n=$((_n + 1))
done
SCRIPT_DIR=$(cd -P "$(dirname "$_self")" && pwd -P) || {
  echo "ERROR: could not resolve this script's directory (from $_self)" >&2
  exit 2
}
DETECT="$SCRIPT_DIR/detect-stack.sh"
if [[ -f "$DETECT" ]] && git rev-parse --show-toplevel >/dev/null 2>&1; then
  STACK=$(bash "$DETECT") || {
    echo "ERROR: detect-stack.sh failed (exit $?), so the default path list is unknown." >&2
    exit 2
  }
  FRAMEWORK_PATHS=()
  INVENTORIES=""
  for fw in fastapi click php; do
    grep -qx "framework	$fw" <<<"$STACK" || continue
    case "$fw" in
      fastapi)
        FRAMEWORK_PATHS+=("CHANGELOG.md" "pyproject.toml" "uv.lock" "schema.sql"
          "alembic/versions/" "deploy/" "src/api/" "src/models/" "src/core/"
          ".env.example")
        INVENTORIES="$INVENTORIES, route table" ;;
      click)
        FRAMEWORK_PATHS+=("pyproject.toml" "uv.lock" "src/" ".env.example")
        INVENTORIES="$INVENTORIES, command inventory" ;;
      php)
        FRAMEWORK_PATHS+=("composer.json" "composer.lock" "package.json"
          "web/app/themes/" "web/app/plugins/" "web/app/acf-json/" ".env.example")
        INVENTORIES="$INVENTORIES, CPT/Skills tables" ;;
    esac
  done
  if [[ ${#FRAMEWORK_PATHS[@]} -gt 0 ]]; then
    SENSITIVE_PATHS=("AGENTS.md" "README.md")
    for p in "${FRAMEWORK_PATHS[@]}"; do
      seen=0
      for q in "${SENSITIVE_PATHS[@]}"; do
        if [[ "$q" == "$p" ]]; then seen=1; fi
      done
      if [[ $seen -eq 0 ]]; then SENSITIVE_PATHS+=("$p"); fi
    done
    DOC_SECTIONS[0]="${DOC_SECTIONS[0]}$INVENTORIES"
  fi
fi
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
  echo "The two files resolve independently, so either may be tailored alone. When"
  echo "exactly one is, a hit ends with a note naming the half that is still this"
  echo "skill's default. The exit code is unchanged."
  echo ""
  echo "Exit codes:"
  echo "  0  no sensitive paths changed (or no changes at all)"
  echo "  1  one or more sensitive paths changed"
  echo "  2  infra/tooling failure — the gate did not run. Covers: an unknown"
  echo "     or incomplete argument, a base ref auto-detection failure, a git"
  echo "     diff or git ls-files failure, a .skills/doc-sensitive-paths or"
  echo "     .skills/doc-sections that is empty or unusable (unreadable, a"
  echo "     broken symlink, not a regular file), a .skills that is not a"
  echo "     resolvable searchable directory, or a path list where no entry"
  echo "     matches any tracked file (a list that cannot hit anything is not"
  echo "     a pass). Other unexpected failures (e.g., running outside a git"
  echo "     repo) may surface git's own exit code instead; check stderr in"
  echo "     either case."
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
# Present in ANY shape, which is the point: `-f` follows symlinks and reads
# false for a dangling link, a loop and a directory, so it skipped exactly the
# files this reader exists to name. Named rather than inlined so the next
# simplification has to argue with the name (#261).
override_present() {
  [[ -e "$1" || -L "$1" ]]
}

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

# Project overrides. Each file replaces its defaults wholesale — a project that
# could only widen a list could never drop an inventory it does not keep.
# Present-but-empty is exit 2 for both: a path list that yields nothing would
# pass everything, and advice that says nothing sends the reader nowhere. Both
# are checked up front rather than on the branch that uses them, so a
# misconfigured file fails on the first run instead of the first hit.
# A .skills/ that exists but cannot be reached hides both override files from
# every test below — `-e` and `-L` alike have to stat inside it — so both lists
# would quietly fall back to defaults. No widening of the per-file test can see
# any of these shapes; they have to be asked here, and through the same
# `override_present` the files use: gating this on `-e` alone repeated the
# defect one level up, since `-e` follows symlinks and reads false for a
# dangling .skills or a loop, which then went silently untailored. A missing
# .skills/ is the ordinary no-tailoring case and is not an error.
if override_present .skills; then
  if [[ ! -e .skills ]]; then
    echo "ERROR: .skills is a symlink whose target does not resolve, so no" >&2
    echo "override file under it can be seen. Repoint or remove it." >&2
    exit 2
  fi
  if [[ ! -d .skills ]]; then
    echo "ERROR: .skills exists but is not a directory, so no override file" >&2
    echo "under it can be seen. .skills/ is a reserved directory name." >&2
    exit 2
  fi
  if [[ ! -x .skills ]]; then
    echo "ERROR: .skills/ exists but is not searchable; its override files" >&2
    echo "cannot be seen. Fix its permissions (chmod +x .skills)." >&2
    exit 2
  fi
fi

# The label a source prints when nothing overrode it. One definition, because
# the half-tailoring note at the foot of this script decides which half is
# still generic by comparing each source against it (#284).
DEFAULTS_LABEL="built-in defaults"

LIST_SOURCE="$DEFAULTS_LABEL"
if override_present .skills/doc-sensitive-paths; then
  read_list_file .skills/doc-sensitive-paths
  if [[ ${#PARSED[@]} -eq 0 ]]; then
    echo "ERROR: .skills/doc-sensitive-paths exists but lists no paths." >&2
    echo "Remove the file to fall back to the built-in defaults." >&2
    exit 2
  fi
  SENSITIVE_PATHS=("${PARSED[@]}")
  LIST_SOURCE=".skills/doc-sensitive-paths"
fi

SECTIONS_SOURCE="$DEFAULTS_LABEL"
if override_present .skills/doc-sections; then
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

# Resolve base ref: explicit > origin/HEAD > a bare repository's own HEAD
# (origin/<it>, then <it>: `clone --bare` keeps no origin/HEAD, #615) >
# origin/main > main
bare_head() {
  [[ "$(git config --bool core.bare 2>/dev/null)" == true ]] || return 1
  git --git-dir="$(git rev-parse --git-common-dir)" symbolic-ref --quiet --short HEAD 2>/dev/null
}
if [[ -z "$BASE_REF" ]]; then
  if git rev-parse --verify --quiet origin/HEAD >/dev/null; then
    BASE_REF=$(git rev-parse --abbrev-ref origin/HEAD)
  elif BARE_HEAD=$(bare_head) &&
    git rev-parse --verify --quiet "origin/$BARE_HEAD" >/dev/null; then
    BASE_REF="origin/$BARE_HEAD"
  elif [[ -n "${BARE_HEAD:-}" ]] && git rev-parse --verify --quiet "$BARE_HEAD" >/dev/null; then
    BASE_REF="$BARE_HEAD"
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

# A knob an installed artifact is rendered by (#647). Today's one is
# .skills/merge_mode, by which curating-context's install-cadence.sh renders
# .github/workflows/context-cadence.yml. Nothing re-ran the renderer when the
# knob changed, so a cohort host's workflow kept pushing to the default branch
# under `pr`. The renderer reads the knob from the primary checkout, which on
# this branch (from a linked worktree, at least) still holds the old mode, so
# a plain re-render here renders that, in silence. Its --merge-mode (#674)
# names the mode instead: this reads the knob as this branch COMMITS it, the
# file the job will read, and asks --check whether the branch's workflow is
# already that mode's render. If it is, the branch carries its own re-render
# and there is nothing to do; if not, the in-branch command comes first and
# "re-render after the merge" second. A hit, exit 1, either way: the branch
# changes how work lands, and the merge leaves a check to read. A renderer
# missing or failing is said, never exit 2: the doc check itself ran. The
# renderer is looked for where the workflow looks.
RENDER_WF=".github/workflows/context-cadence.yml"
RENDER_NOTE=0
# committed_merge_mode: the branch's committed .skills/merge_mode, in
# merge-mode.sh's grammar (one word, `pr` or `direct`; blank lines and
# whole-line `#` comments ignored; absent is `direct`). Sets CM_MODE; or
# CM_ERR when the committed file is unusable, as the job's read step would
# find it; or CM_UNREAD when this can't tell (git failing included). HEAD's tree, not the working
# file: the job reads what is committed.
#
# The job reads with `[ -f ]`, which follows links (CR 2568). So does this,
# one in-tree hop for .skills and one for the knob, each target relative to
# the link's own directory. Anything further (a target outside the tree, a
# link to a link, a path through another link) is CM_UNREAD: said, and left
# to a person, never guessed.
TE_MODE="" TE_SHA=""
tree_entry() {
  local out
  TE_MODE="" TE_SHA=""
  out=$(git ls-tree HEAD -- "$1") || return 1
  [[ -n "$out" ]] || return 0
  TE_MODE=${out%% *}
  out=${out#* }
  out=${out#* }
  TE_SHA=${out%%$'\t'*}
}
# The repo-relative path a link in <dir> to <target> names, normalised.
# Fails for an absolute target or one that climbs out of the tree.
link_target_path() {
  local dir=$1 target=$2 part
  local -a parts out=()
  [[ $target != /* ]] || return 1
  IFS=/ read -r -a parts <<<"${dir:+$dir/}$target"
  for part in "${parts[@]}"; do
    case $part in
      '' | .) ;;
      ..)
        [[ ${#out[@]} -gt 0 ]] || return 1
        out=("${out[@]:0:${#out[@]}-1}")
        ;;
      *) out+=("$part") ;;
    esac
  done
  [[ ${#out[@]} -gt 0 ]] || return 1
  (IFS=/ && printf '%s\n' "${out[*]}")
}
# Whether any directory on the way to <path> is a link in HEAD's tree:
# ls-tree finds nothing past one, so "absent" there means "unread".
through_a_link() {
  local path=$1 prefix=""
  local -a parts
  IFS=/ read -r -a parts <<<"$path"
  local i
  for ((i = 0; i < ${#parts[@]} - 1; i++)); do
    prefix=${prefix:+$prefix/}${parts[i]}
    tree_entry "$prefix" || return 0
    [[ $TE_MODE != 120000 ]] || return 0
  done
  return 1
}
committed_merge_mode() {
  local dir=.skills knob target blob line word="" count=0
  local -a words
  CM_MODE="" CM_ERR="" CM_UNREAD="" CM_PATH=""
  if ! tree_entry .skills; then
    CM_UNREAD="git ls-tree HEAD failed"
    return 0
  fi
  if [[ $TE_MODE == 120000 ]]; then
    target=$(git cat-file blob "$TE_SHA") || { CM_UNREAD="git cat-file failed"; return 0; }
    if ! dir=$(link_target_path "" "$target"); then
      CM_UNREAD=".skills is a link out of the tree, to $target"
      return 0
    fi
    tree_entry "$dir" || { CM_UNREAD="git ls-tree HEAD failed"; return 0; }
    if [[ $TE_MODE == 120000 ]] || through_a_link "$dir"; then
      CM_UNREAD=".skills is a link to $target, which doc-check doesn't follow further"
      return 0
    fi
    if [[ -z $TE_MODE ]]; then
      # Dangling: the job finds no .skills/merge_mode, which is `direct`.
      CM_MODE="direct"
      return 0
    fi
  fi
  knob=$dir/merge_mode
  CM_PATH=$knob
  tree_entry "$knob" || { CM_UNREAD="git ls-tree HEAD failed"; return 0; }
  if [[ $TE_MODE == 120000 ]]; then
    target=$(git cat-file blob "$TE_SHA") || { CM_UNREAD="git cat-file failed"; return 0; }
    if ! knob=$(link_target_path "$dir" "$target"); then
      CM_UNREAD="it is a link out of the tree, to $target"
      return 0
    fi
    CM_PATH=$knob
    tree_entry "$knob" || { CM_UNREAD="git ls-tree HEAD failed"; return 0; }
    if [[ $TE_MODE == 120000 ]] || { [[ -z $TE_MODE ]] && through_a_link "$knob"; }; then
      CM_UNREAD="it is a link to $target, which doc-check doesn't follow further"
      return 0
    fi
    if [[ -z $TE_MODE ]]; then
      CM_ERR="it is a link to $target, which isn't in the tree"
      return 0
    fi
  elif [[ -z $TE_MODE ]]; then
    CM_MODE="direct"
    return 0
  fi
  if [[ $TE_MODE != 100* ]]; then
    CM_ERR="it is committed as something other than a regular file"
    return 0
  fi
  if ! blob=$(git cat-file blob "$TE_SHA" 2>&1); then
    CM_UNREAD="git cat-file failed: $blob"
    return 0
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line"
    [[ ${#words[@]} -gt 0 ]] || continue
    case ${words[0]} in \#*) continue ;; esac
    count=$((count + ${#words[@]}))
    word=${words[0]}
  done <<<"$blob"
  if [[ $count -eq 0 ]]; then
    CM_ERR="it names no mode"
  elif [[ $count -ne 1 ]]; then
    CM_ERR="it has $count words; it takes one"
  else
    case $word in
      pr | direct) CM_MODE=$word ;;
      *) CM_ERR="it says '$word', which is not a merge mode" ;;
    esac
  fi
}
# The hit: the knob changes on this branch while the workflow is installed.
# Through a link the diff names the link or its target, never the knob's own
# path, so all three count (CR 2568). Read once, here.
if [[ -f "$RENDER_WF" ]]; then
  committed_merge_mode
  if grep -qxF -e ".skills/merge_mode" -e ".skills" ${CM_PATH:+-e "$CM_PATH"} <<<"$CHANGED"; then
    RENDER_NOTE=1
  fi
fi
print_render_note() {
  local d renderer="" out rc=0
  for d in scripts .claude/skills/curating-context/scripts skills/curating-context/scripts; do
    if [[ -f "$d/install-cadence.sh" ]]; then
      renderer="$d/install-cadence.sh"
      break
    fi
  done
  echo ""
  echo "Knob-rendered artifact: .skills/merge_mode changes on this branch, and"
  echo "$RENDER_WF is rendered by it."
  if [[ -n "$CM_UNREAD" ]]; then
    echo "  doc-check can't read this branch's committed .skills/merge_mode:"
    echo "  $CM_UNREAD. So check it by hand, and re-render for the mode it names."
    return 0
  fi
  if [[ -n "$CM_ERR" ]]; then
    echo "  This branch's committed .skills/merge_mode is unusable: $CM_ERR."
    echo "  Fix it (one word, 'pr' or 'direct', or delete the file for 'direct')"
    echo "  before re-rendering; the job's read step refuses it too."
    return 0
  fi
  if [[ -z "$renderer" ]]; then
    echo "Re-render it on this branch with install-cadence.sh --merge-mode $CM_MODE,"
    echo "or after this branch merges, once the default branch has the knob."
    echo "  (no install-cadence.sh in scripts/, .claude/skills/curating-context/scripts/"
    echo "  or skills/curating-context/scripts/, so its --check was not run)"
    return 0
  fi
  out=$(bash "$renderer" --check --merge-mode "$CM_MODE" </dev/null 2>&1) || rc=$?
  if [[ $rc -ne 0 && $rc -ne 3 ]]; then
    echo "  bash $renderer --check --merge-mode $CM_MODE exited $rc:"
    printf '%s\n' "$out" | sed 's/^/    /'
    return 0
  fi
  # --check reads the working file, and Step 1.5 runs before the commit, so
  # a render in this tree is the branch's only once HEAD has it (CR 2570).
  # What --check prints after the merge: no merge mode line at all for a
  # direct knob, the pr line for pr.
  local after="'re-render: none'"
  [[ $CM_MODE != pr ]] || after="$after and 'merge mode: pr'"
  if grep -q '^re-render: *none' <<<"$out" &&
    git ls-files --error-unmatch -- "$RENDER_WF" >/dev/null 2>&1 &&
    git diff --quiet HEAD -- "$RENDER_WF"; then
    echo "This branch already carries its $CM_MODE render, so nothing is left to"
    echo "re-render. After the merge, from the primary checkout:"
    echo "  bash $renderer --check"
    echo "should read $after."
  elif grep -q '^re-render: *none' <<<"$out"; then
    echo "This tree carries the $CM_MODE render, but $RENDER_WF"
    echo "is not committed as it reads: commit it with the knob, so the branch"
    echo "carries it. After the merge, --check from the primary should read"
    echo "$after."
  else
    echo "Re-render it on this branch, so the knob and its render land together:"
    echo "  bash $renderer --merge-mode $CM_MODE"
    echo "(it keeps the installed schedule), review the diff and commit it with"
    echo "the knob. Or re-render after this branch merges, once the default"
    echo "branch has the knob: in the primary checkout, run the command"
    echo "install-cadence.sh --check names on its re-render: line."
  fi
  echo "  bash $renderer --check --merge-mode $CM_MODE says:"
  printf '%s\n' "$out" |
    awk '/^[^ ]/ { keep = ($0 ~ /^(merge mode|re-render):/) } keep { print "    " $0 }'
}

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
  if [[ $RENDER_NOTE -eq 1 ]]; then
    print_render_note
    exit 1
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

# Half a tailoring, said out loud (#284). The two files still RESOLVE
# independently: the list says what to watch, the advice what to do about a
# hit, and either can be right on its own. What this closes is the silence. A
# repo that tailored its list against the PHP defaults and never its advice was
# told, on every hit from then on, to check AGENTS.md and README.md, never the
# docs/COMMANDS.md that actually drifted, while both source labels printed
# above already disagreed and nothing said so.
#
# Only the disagreement is decidable. Whether an advice line routes a given
# entry is a question about prose, and a checker for it would be satisfied by
# pasting paths into the advice, which makes the advice worse. Whether the
# advice is the project's at all is two variables already in scope. They are
# compared through the default label, not to each other: the tailored labels
# name different files, so "both tailored" is a mismatch by string and a match
# by meaning.
#
# Both directions, and the hit path only. Default advice beside a tailored
# list describes a layout that may not be this repo's. Tailored advice beside a
# default list names this repo's docs while watching the skill's paths, so a
# change those docs describe can pass unflagged. On the green path neither
# note is about the verdict printed, and one line on every clean run is the
# reporter that gets tuned out.
if [[ "$LIST_SOURCE" != "$DEFAULTS_LABEL" && "$SECTIONS_SOURCE" == "$DEFAULTS_LABEL" ]]; then
  echo ""
  echo "Note: this project tailors .skills/doc-sensitive-paths but not"
  echo ".skills/doc-sections, so the sections above are this skill's defaults and"
  echo "describe a project layout that may not be yours. Commit .skills/doc-sections"
  echo "to route these hits at your own docs."
elif [[ "$LIST_SOURCE" == "$DEFAULTS_LABEL" && "$SECTIONS_SOURCE" != "$DEFAULTS_LABEL" ]]; then
  echo ""
  echo "Note: this project tailors .skills/doc-sections but not"
  echo ".skills/doc-sensitive-paths, so the paths above were matched against this"
  echo "skill's defaults, which may not watch the files your sections describe — a"
  echo "change to one of those can pass unflagged. Commit .skills/doc-sensitive-paths"
  echo "to watch the paths your docs depend on."
fi
if [[ $RENDER_NOTE -eq 1 ]]; then
  print_render_note
fi
exit 1
