#!/usr/bin/env bash
# gather-context.sh
# Prints a structured summary of current repo state for use during code review.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
# Exit codes: 0 = success; 2 = an argument other than --help (#549).
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, and changed files."
  echo "Automatically resolves the git project root regardless of invocation directory."
  echo ""
  echo "Changed files run from the merge base with the first of origin/HEAD,"
  echo "origin/main, origin/master, main and master that has one, or with"
  echo "@{upstream} when none does, plus the working tree and untracked files."
  echo "When that merge base is HEAD itself, or there is none, the list is the"
  echo "working tree only, and its header says why. The context-budget block"
  echo "measures from the same base."
  echo ""
  echo "Takes no arguments: a range or base is refused, not ignored. To review"
  echo "another range, run git diff --name-only <range> yourself."
  echo ""
  echo "Exit codes:"
  echo "  0 = success"
  echo "  2 = an argument other than --help"
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
# The default branch comes before @{upstream} (#389). On a branch pushed with
# -u the upstream IS HEAD, so trying it first diffed nothing on every PR
# branch; after a further local commit it diffed only the unpushed tail.
# origin/HEAD leads: a local main is often stale, and a branch cut from a
# fresher origin/main would then count other people's commits as its own
# (CR 696). It also covers a clone with no local main. origin/main and
# origin/master follow it, because a checkout made with `git init` + `remote
# add` + `fetch` has no origin/HEAD (CR 698). On main itself, origin/HEAD's
# merge base is the last push, which is the base.
#
# The first ref with any merge base decides, even when that base is HEAD
# itself (CR 1805). Skipping such a ref fell through to staler ones: a branch
# freshly cut from origin/main, its work still uncommitted, took a stale local
# main as its base and listed other people's commits. A base of HEAD means no
# commit lies beyond that ref, and the list is the working tree alone. So
# @{upstream} is read only when no default-branch ref has a merge base, as in
# a repo whose default branch has another name.
#
# _cd_why says why the list is the working tree only, for its header and its
# empty line: HEAD is its own merge base (CR 1788), or no candidate shares
# history with HEAD at all.
_cd_base=""
_cd_head=$(git rev-parse HEAD 2>/dev/null) || _cd_head=""
for _ref in origin/HEAD origin/main origin/master main master "@{upstream}"; do
  _cd_base=$(git merge-base HEAD "$_ref" 2>/dev/null) && [ -n "$_cd_base" ] && break
  _cd_base=""
done
[ -n "$_cd_base" ] || _cd_base=HEAD
_cd_ref=HEAD _cd_why="" _cd_fix="; name the review scope explicitly"
if [ "$_cd_base" = HEAD ]; then
  _cd_why="none of origin/HEAD, origin/main, origin/master, main, master or @{upstream} shares history with HEAD here"
elif [ "$_cd_base" = "$_cd_head" ]; then
  _cd_base=HEAD
  _cd_why="HEAD is its own merge base with $_ref, so no commit lies beyond it"
else
  _cd_ref=$_ref
fi

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
  echo "=== Changed files (working tree vs HEAD only: $_cd_why) ==="
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
  echo "(none: the working tree is clean, and no commit is listed: $_cd_why$_cd_fix)"
elif [ -z "$CHANGED" ]; then
  echo "(none: nothing differs from the merge base, and the working tree is clean)"
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
