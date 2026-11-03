#!/usr/bin/env bash
# gather-context.sh (PHP variant)
# Prints a structured summary of current repo state for use during code review.
# Also runs PHP-specific checks: composer validate (root + each discovered
# composer dir under themes/ and plugins/) and php -l on changed PHP files.
#
# Exit codes:
#   0 = success
#   2 = an argument other than --help (#549), or a tooling/infra
#       failure on a gate-like discovery step (find for
#       composer.json failed, mktemp failed). Reporting-only sections
#       (git status, diff, log) intentionally degrade silently and do not
#       map to exit 2.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, changed files,"
  echo "then runs composer validate at each composer.json location and php -l on"
  echo "changed PHP files."
  echo ""
  echo "Changed files run from the merge base with the first of origin/HEAD,"
  echo "origin/main, origin/master, main, master and @{upstream} whose merge base"
  echo "is not HEAD itself, plus the working tree and untracked files. With no"
  echo "such base the list is the working tree only, and its header says so."
  echo "The context-budget block measures from the same base."
  echo ""
  echo "Takes no arguments: a range or base is refused, not ignored. To review"
  echo "another range, run git diff --name-only <range> yourself."
  echo ""
  echo "Exit codes:"
  echo "  0 = success"
  echo "  2 = an argument other than --help, or a tooling/infra failure"
  echo "      (find for composer.json failed, mktemp failed)"
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "gather-context.sh: unexpected argument '$1'; it takes none but --help." >&2
  echo "Changed files already run from the branch's merge base; for another range, run git diff --name-only <range> yourself." >&2
  exit 2
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

# --- Review base (#389, #549) ------------------------------------------------
# One merge base, resolved here and read twice: by the changed-files list and
# by the context-budget block's --base. A review whose changes are already
# committed — a batch branch, a PR branch, anything but a dirty tree — diffs
# empty against HEAD. The list was the working tree alone until #549, so a
# fully committed branch showed nothing to review and said nothing; the budget
# block, on HEAD until #389, stayed silent through three review rounds while
# one batch branch added ~150 tokens to AGENTS.md (#169 was the cadence's
# sighting of the same default).
#
# The default branch comes before @{upstream}, and a ref whose merge base is
# HEAD itself is skipped (#389). On a branch pushed with -u the upstream IS
# HEAD, so trying it first diffed nothing on every PR branch; after a further
# local commit it diffed only the unpushed tail. origin/HEAD leads: a local
# main is often stale, and a branch cut from a fresher origin/main would then
# count other people's commits as its own (CR 696). It also covers a clone
# with no local main. origin/main and origin/master follow it, because a
# checkout made with `git init` + `remote add` + `fetch` has no origin/HEAD
# (CR 698). On main itself, origin/HEAD's merge base is the last push, which
# is the base.
#
# Falls back to HEAD when no candidate qualifies — a repo whose default branch
# is named something else, or main with everything pushed — and the list's
# header then says it is the working tree only.
_cd_base=""
_cd_head=$(git rev-parse HEAD 2>/dev/null) || _cd_head=""
for _ref in origin/HEAD origin/main origin/master main master "@{upstream}"; do
  _cd_base=$(git merge-base HEAD "$_ref" 2>/dev/null) && [ -n "$_cd_base" ] &&
    [ "$_cd_base" != "$_cd_head" ] && break
  _cd_base=""
done
[ -n "$_cd_base" ] || _cd_base=HEAD
_cd_ref=HEAD
[ "$_cd_base" = HEAD ] || _cd_ref=$_ref

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Git status ==="
git status --short

echo ""
echo "=== Staged diff ==="
git diff --staged --stat 2>/dev/null || true

echo ""
echo "=== Unstaged diff ==="
git diff --stat 2>/dev/null || true

echo ""
echo "=== Recent commits ==="
git log --oneline -10 2>/dev/null || true

# Changed files: since the review base, plus the working tree and untracked
# files, deduplicated (#549). Never silent: an empty list says so and why, and
# a git that failed is reported rather than read as "nothing changed". Unlike
# the sections above, git's stderr is kept: this list's emptiness is a claim.
echo ""
if [ "$_cd_base" = HEAD ]; then
  echo "=== Changed files (working tree vs HEAD only: no merge base with the default branch or @{upstream}) ==="
else
  echo "=== Changed files (since merge base ${_cd_base:0:12} ($_cd_ref), plus the working tree) ==="
fi
_cf_rc=0
CHANGED=$(
  rc=0
  git diff --name-only "$_cd_base" || rc=1
  git diff --name-only --staged "$_cd_base" || rc=1
  git ls-files --others --exclude-standard || rc=1
  exit "$rc"
) || _cf_rc=$?
CHANGED=$(printf '%s\n' "$CHANGED" | sort -u | sed '/^$/d')
[ -z "$CHANGED" ] || echo "$CHANGED"
if [ "$_cf_rc" -ne 0 ]; then
  echo "(incomplete: git failed listing changes against $_cd_base; its error is on stderr)"
elif [ -z "$CHANGED" ] && [ "$_cd_base" = HEAD ]; then
  echo "(none: the working tree is clean, and with no merge base no commit is listed; name the review scope explicitly)"
elif [ -z "$CHANGED" ]; then
  echo "(none: nothing differs from the merge base, and the working tree is clean)"
fi

# --- PHP-specific checks ------------------------------------------------------
#
# Discovery convention: gate-like discovery steps (the `find` below) harden to
# ERROR/exit 2 on tool failure so a degraded composer-dir list never silently
# narrows the review surface. Reporting-only `git ... 2>/dev/null || true` sites
# above intentionally degrade-and-continue — a missing diff stat is acceptable
# context, a missing composer dir is not.

# Tempfile scalars (not an array) for bash 3.2 + `set -u` compatibility — only
# the find step uses tempfiles in this script.
FIND_OUT=""; FIND_ERR=""
trap 'rm -f "$FIND_OUT" "$FIND_ERR"' EXIT

# Discover composer dirs: root + every themes/<name>/ or plugins/<name>/ that
# ships a composer.json. Portable across BSD/GNU find (no -printf).
COMPOSER_DIRS=()
[[ -f composer.json ]] && COMPOSER_DIRS+=(".")

# Build find paths dynamically: passing a missing dir to `find` is itself an
# error (non-zero exit + stderr), which would falsely trip the ERROR handler
# below on repos that have only themes/ or only plugins/.
FIND_PATHS=()
[[ -d themes ]] && FIND_PATHS+=(themes)
[[ -d plugins ]] && FIND_PATHS+=(plugins)
if [[ ${#FIND_PATHS[@]} -gt 0 ]]; then
  FIND_OUT=$(mktemp) || { echo "ERROR: mktemp failed (FIND_OUT)" >&2; exit 2; }
  FIND_ERR=$(mktemp) || { echo "ERROR: mktemp failed (FIND_ERR)" >&2; exit 2; }
  FIND_RC=0
  find "${FIND_PATHS[@]}" -mindepth 2 -maxdepth 2 -name composer.json \
    >"$FIND_OUT" 2>"$FIND_ERR" || FIND_RC=$?
  if [[ $FIND_RC -ne 0 ]]; then
    echo "ERROR: find for composer.json failed (exit $FIND_RC):" >&2
    cat "$FIND_ERR" >&2
    exit 2
  fi
  # `find` can exit 0 yet still write to stderr (e.g. permission-denied on a
  # subdir). Surface those without aborting — discovered dirs are still valid.
  if [[ -s "$FIND_ERR" ]]; then
    echo "WARN: find for composer.json wrote diagnostics:" >&2
    cat "$FIND_ERR" >&2
  fi
  while IFS= read -r f; do
    [[ -n "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done < "$FIND_OUT"
fi

echo ""
echo "=== composer validate ==="
if [[ ${#COMPOSER_DIRS[@]} -eq 0 ]]; then
  echo "No composer.json found. Skipping."
else
  for dir in "${COMPOSER_DIRS[@]}"; do
    echo "--- $dir ---"
    (cd "$dir" && composer validate --no-check-publish) || echo "FAIL: $dir"
  done
fi

echo ""
echo "=== php -l on changed PHP files ==="
# Lint only changed PHP files: the changed-files list above, already
# deduplicated (since the review base, plus the working tree; #549).
PHP_FILES=$(printf '%s\n' "$CHANGED" | grep -E '\.php$' || true)
if [[ -z "$PHP_FILES" ]]; then
  echo "No changed PHP files."
else
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ ! -f "$file" ]] && continue
    php -l "$file" || echo "FAIL: $file"
  done <<< "$PHP_FILES"
fi

# --- Context-budget delta (informational) ------------------------------------
# Delegates to curating-context so the measurement logic lives in one place.
# Silent when that skill isn't vendored here, and never fails this script: a
# context budget is a review signal, not a review gate.
#
# --base is the review base resolved at the top (#389), the one the
# changed-files list runs from.
for _cc in "skills/curating-context/scripts" \
           ".claude/skills/curating-context/scripts" \
           "$HOME/.claude/skills/curating-context/scripts"; do
  if [ -f "$_cc/context-delta.sh" ]; then
    bash "$_cc/context-delta.sh" --base "$_cd_base" || true
    break
  fi
done
