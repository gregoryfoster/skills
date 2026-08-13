#!/usr/bin/env bash
# worktree-destroy.sh
# Destroys the worktree for <branch>. Refuses if the branch is NOT merged
# into the base ref AND --descoped <reason> was not supplied (Iron Law).
#
# Usage: bash <SKILL_SCRIPTS>/worktree-destroy.sh <branch> [--base <ref>] [--descoped <reason>] [--force] [--unlock] [--dry-run] [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" <branch> [--base <ref>] [--descoped <reason>] [--force] [--unlock] [--dry-run]"
  echo ""
  echo "Destroys the worktree for <branch>. Iron Law: refuses if the branch has"
  echo "NOT been merged into the base ref unless --descoped <reason> is supplied."
  echo ""
  echo "Worktree lookup:"
  echo "  The branch is looked up in git's worktree registry, so any layout works"
  echo "  ('.worktrees/', '.claude/worktrees/', anywhere else) regardless of how"
  echo "  the directory leaf is named. Only when the branch has no registered"
  echo "  worktree does it fall back to worktree-create.sh's '<root>/<slug>'"
  echo "  scheme, so a mistyped branch still reports a concrete path."
  echo ""
  echo "Side effects:"
  echo "  - If <worktree>/.port exists, kills any process bound to that port"
  echo "    via 'lsof -ti tcp:<port>' (portable to macOS + Linux)."
  echo "  - Kills any process whose argv references the worktree path"
  echo "    (pgrep -f), catching dev-server stragglers that lost their port."
  echo "  - Removes the worktree directory (git worktree remove)."
  echo "  - Runs git worktree prune to clean stale metadata."
  echo ""
  echo "Merge verification:"
  echo "  Refuses if the branch is not an ancestor of the base ref."
  echo "  Default base resolution: .skills/default_branch -> origin's HEAD -> 'main'."
  echo "  Prefers origin/<base> over local <base> (authoritative remote state)."
  echo ""
  echo "  --base <ref> overrides the default resolution and verifies merge into"
  echo "  the explicit ref instead. The ref is used as-given (no origin/<ref>"
  echo "  preference), so callers can target a local-only integration branch"
  echo "  such as 'batch/<x>' in a multi-agent orchestration. The Iron Law still"
  echo "  applies — the branch must be an ancestor of the supplied ref."
  echo ""
  echo "  Precedence: --descoped takes precedence over --base. If both are"
  echo "  supplied, the merge check is skipped entirely and --base is ignored."
  echo ""
  echo "  --force propagates to 'git worktree remove --force'. Required when the"
  echo "  worktree contains checked-out submodules (git refuses to remove those"
  echo "  without --force). Note: --force ALSO bypasses git's dirty-working-tree"
  echo "  check, so any uncommitted changes in the worktree are discarded. The"
  echo "  Iron Law's merge gate is unaffected — --force only changes removal"
  echo "  mechanics, not merge verification."
  echo ""
  echo "  --unlock releases a 'git worktree lock' before removing. A lock marks a"
  echo "  worktree as in-use; the Claude Code Agent tool locks every worktree its"
  echo "  isolation mode provisions, so an orchestrated batch cannot be torn down"
  echo "  without it. --force is NOT the remedy: it is a single -f and git demands"
  echo "  '-f -f' to remove a locked worktree. --unlock is deliberately narrow —"
  echo "  it releases the lock and nothing else, so uncommitted work still blocks"
  echo "  removal. Without it, a locked worktree is reported and exits 2."
  echo ""
  echo "  --dry-run reports what would happen — resolved path, base ref, merge"
  echo "  verdict, lock state, removal command — and exits WITHOUT side effects."
  echo "  It exits with the code the real run would: 1 on an Iron Law violation,"
  echo "  2 on a lock with no --unlock. A preview that always succeeds predicts"
  echo "  nothing. Safe to point at a live worktree, including one in use."
  echo ""
  echo "Does NOT delete the branch ref. Use 'git branch -d <branch>' afterward"
  echo "if you also want to drop the local ref."
  echo ""
  echo "Exit codes:"
  echo "  0  Worktree removed (or --dry-run reported a removable worktree)"
  echo "  1  Iron Law violation (unmerged work without --descoped)"
  echo "  2  Tooling/infra failure (not a git repo, missing arg, worktree not"
  echo "     found, worktree locked without --unlock, target is the worktree this"
  echo "     command runs from, git list/unlock/remove failed)"
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
  echo "ERROR: <branch> argument required" >&2
  usage >&2
  exit 2
fi
shift

DESCOPED=0
DESCOPE_REASON=""
BASE_OVERRIDE=""
FORCE=0
UNLOCK=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --descoped)
      DESCOPED=1
      DESCOPE_REASON="${2:-}"
      if [[ -z "$DESCOPE_REASON" ]]; then
        echo "ERROR: --descoped requires a <reason> argument" >&2
        usage >&2
        exit 2
      fi
      shift 2
      ;;
    --base)
      BASE_OVERRIDE="${2:-}"
      if [[ -z "$BASE_OVERRIDE" ]]; then
        echo "ERROR: --base requires a <ref> argument" >&2
        usage >&2
        exit 2
      fi
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --unlock)
      UNLOCK=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      echo "ERROR: unknown flag '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}

SLUG="${BRANCH//\//-}"
FALLBACK_PATH="$ROOT/$SLUG"

# Locate the worktree by BRANCH, via git's own registry, rather than by
# reconstructing worktree-create.sh's '<root>/<slug>' path. That scheme only
# describes worktrees this skill created. Externally provisioned ones put the
# branch and the directory leaf under different names — the Claude Code Agent
# tool's isolation mode checks out 'worktree-agent-<id>' at
# '.claude/worktrees/agent-<id>/' — so no WORKTREE_ROOT override can reach
# them: the root is wrong AND the leaf is wrong. The registry knows both.
# The constructed path stays as the fallback, so a mistyped branch with no
# registered worktree still reports a concrete path to look at.
#
# Parsing notes — each guards a case the obvious one-liner gets wrong:
#   - RS="" reads one worktree block per record. git emits 'locked' AFTER
#     'branch', so a line-at-a-time scan that prints on the branch match has
#     not seen the lock yet.
#   - substr($i, 10) takes the path as the entire remainder of the line.
#     Splitting on whitespace ($2) truncates any path containing a space.
#   - -v want= passes the branch as DATA. Interpolating it into the awk
#     program text is an injection: git permits '"' in refnames, which closes
#     awk's string literal and makes the program a syntax error.
#   - A detached-HEAD worktree emits 'detached' and no 'branch' line, and a
#     bare one emits 'bare', so neither can ever match.
#   - Gate discipline: this output decides which directory gets removed, so a
#     failing 'git worktree list' must be an error, not an empty result that
#     silently falls back to the constructed path. pipefail makes the
#     substitution fail, and the '||' turns it into exit 2.
WT_RECORD=$(git worktree list --porcelain | awk -v want="branch refs/heads/$BRANCH" '
  BEGIN { RS = ""; FS = "\n" }
  {
    path = ""; matched = 0; lock = ""
    for (i = 1; i <= NF; i++) {
      if (substr($i, 1, 9) == "worktree ") path = substr($i, 10)
      else if ($i == want) matched = 1
      else if ($i == "locked") lock = "(no reason recorded)"
      else if (substr($i, 1, 7) == "locked ") lock = substr($i, 8)
    }
    if (matched) { printf "%s\n%s\n", lock, path; exit }
  }
') || {
  echo "ERROR: failed to enumerate worktrees (git worktree list --porcelain)" >&2
  exit 2
}

# Line 1 is the lock reason (empty if unlocked), line 2 the path. Both are
# empty when the branch has no registered worktree.
LOCK_REASON="${WT_RECORD%%$'\n'*}"
WORKTREE_PATH="${WT_RECORD#*$'\n'}"
WORKTREE_PATH="${WORKTREE_PATH%$'\n'}"

REGISTERED=1
if [[ -z "$WORKTREE_PATH" ]]; then
  REGISTERED=0
  LOCK_REASON=""
  WORKTREE_PATH="$FALLBACK_PATH"
fi

if [[ ! -d "$WORKTREE_PATH" ]]; then
  echo "ERROR: no worktree at '$WORKTREE_PATH'" >&2
  exit 2
fi

# Self-destruction guard. Resolving by branch is what makes this reachable:
# before, a harness worktree could not be addressed at all, so an agent could
# not target its own. PROJECT_ROOT is this invocation's own worktree top
# level, and both it and the registry path come from git already resolved.
if [[ "$PROJECT_ROOT" == "$WORKTREE_PATH" ]]; then
  echo "ERROR: refusing to destroy '$WORKTREE_PATH' — it is the worktree this command is running from" >&2
  echo "cd to the main checkout first: git worktree list | head -n1" >&2
  exit 2
fi

# Iron Law: verify the branch has been merged into the base ref.
# "Verified merge" = the branch tip is an ancestor of the base ref. Pushing
# alone is NOT enough — a pushed-but-unmerged branch would still lose work on
# destroy.
#
# Base resolution:
#   - If --base <ref> was supplied, use it verbatim (no origin/<ref> preference
#     — the caller is being explicit, possibly targeting a local-only branch
#     like 'batch/<x>' from a multi-agent orchestration).
#   - Otherwise resolve the project default:
#     1. .skills/default_branch (single-line file)
#     2. git symbolic-ref refs/remotes/origin/HEAD (whatever origin's HEAD points to)
#     3. "main" fallback
#     Then prefer origin/<base> over local <base> for authoritative remote state.
BASE_REF=""
if [[ $DESCOPED -eq 0 ]]; then
  if [[ -n "$BASE_OVERRIDE" ]]; then
    if git rev-parse --verify --quiet "$BASE_OVERRIDE" >/dev/null; then
      BASE_REF="$BASE_OVERRIDE"
    else
      echo "ERROR: --base ref '$BASE_OVERRIDE' does not exist" >&2
      exit 2
    fi
  else
    BASE=""
    if [[ -f "$PROJECT_ROOT/.skills/default_branch" ]]; then
      BASE=$(head -n1 "$PROJECT_ROOT/.skills/default_branch" | tr -d '[:space:]')
    fi
    if [[ -z "$BASE" ]]; then
      BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)
    fi
    if [[ -z "$BASE" ]]; then
      BASE="main"
    fi

    # Resolve the base ref. Prefer origin/<base> (authoritative — what the team
    # has merged), fall back to local <base> if no remote tracking exists.
    if git rev-parse --verify --quiet "origin/$BASE" >/dev/null; then
      BASE_REF="origin/$BASE"
    elif git rev-parse --verify --quiet "$BASE" >/dev/null; then
      BASE_REF="$BASE"
    fi

    if [[ -z "$BASE_REF" ]]; then
      echo "ERROR: could not resolve base branch '$BASE' (neither origin/$BASE nor local $BASE exists)" >&2
      echo "Set .skills/default_branch to your project's base branch name, pass --base <ref>, or pass --descoped <reason>." >&2
      exit 2
    fi
  fi

  if ! git rev-parse --verify --quiet "$BRANCH" >/dev/null; then
    echo "ERROR: branch '$BRANCH' does not exist locally — cannot verify merge status" >&2
    exit 2
  fi

  if ! git merge-base --is-ancestor "$BRANCH" "$BASE_REF"; then
    UNMERGED=$(git rev-list --count "$BASE_REF..$BRANCH" 2>/dev/null || echo "?")
    echo "ERROR: branch '$BRANCH' is not merged into '$BASE_REF' ($UNMERGED commit(s) ahead)" >&2
    echo "Merge it first, or pass --descoped <reason> to acknowledge the descope." >&2
    exit 1
  fi
else
  echo "Descoped: $DESCOPE_REASON"
fi

# --- Dry run ---------------------------------------------------------------
# Everything above this line is read-only; everything below kills processes and
# removes directories. Reporting here — after the Iron Law has run for real —
# is what lets --dry-run exit 1 on an unmerged branch instead of claiming a
# destroy would succeed. A preview that cannot fail is not a preview.
if [[ $DRY_RUN -eq 1 ]]; then
  DRY_RC=0
  REMOVE_PREVIEW="git worktree remove"
  [[ $FORCE -eq 1 ]] && REMOVE_PREVIEW="$REMOVE_PREVIEW --force"
  echo "DRY RUN — no changes made."
  echo "  branch:    $BRANCH"
  echo "  worktree:  $WORKTREE_PATH"
  if [[ $REGISTERED -eq 1 ]]; then
    echo "  resolved:  git worktree registry (by branch)"
  else
    echo "  resolved:  constructed path — branch has NO registered worktree"
  fi
  if [[ $DESCOPED -eq 1 ]]; then
    echo "  merge:     skipped — descoped: $DESCOPE_REASON"
  else
    echo "  merge:     verified — '$BRANCH' is an ancestor of '$BASE_REF'"
  fi
  if [[ -n "$LOCK_REASON" ]]; then
    if [[ $UNLOCK -eq 1 ]]; then
      echo "  locked:    $LOCK_REASON  → would be released by --unlock"
    else
      echo "  locked:    $LOCK_REASON  → WOULD FAIL; re-run with --unlock"
      # Mirror the lock gate's exit code so the preview predicts the real run.
      DRY_RC=2
    fi
  else
    echo "  locked:    no"
  fi
  echo "  removal:   $REMOVE_PREVIEW \"$WORKTREE_PATH\""
  exit "$DRY_RC"
fi

# --- Lock gate -------------------------------------------------------------
# git refuses to remove a locked worktree, and --force does NOT override it:
# --force is a single -f, and git demands '-f -f' for a lock. So --force is
# both insufficient here and too broad — it would also discard uncommitted
# work. --unlock is the narrow instrument: it releases the lock and changes
# nothing else, leaving git's dirty-tree refusal intact.
if [[ -n "$LOCK_REASON" ]]; then
  if [[ $UNLOCK -eq 0 ]]; then
    echo "ERROR: worktree '$WORKTREE_PATH' is locked: $LOCK_REASON" >&2
    echo "A lock marks a worktree as in-use — the Claude Code Agent tool locks every" >&2
    echo "worktree its isolation mode provisions. Confirm nothing is still using it," >&2
    echo "then re-run with --unlock. (--force does not override a lock.)" >&2
    exit 2
  fi
  echo "Releasing lock ($LOCK_REASON)..."
  if ! UNLOCK_ERR=$(git worktree unlock "$WORKTREE_PATH" 2>&1 >/dev/null); then
    echo "ERROR: git worktree unlock failed:" >&2
    echo "$UNLOCK_ERR" >&2
    exit 2
  fi
fi

# Free the port if the worktree recorded one. Use lsof (portable: macOS + Linux)
# rather than fuser (Linux-only). Silently no-op if lsof isn't installed and
# warn explicitly so the operator knows the port wasn't actually freed.
PORT_FILE="$WORKTREE_PATH/.port"
if [[ -f "$PORT_FILE" ]]; then
  PORT=$(head -n1 "$PORT_FILE" | tr -d '[:space:]')
  if [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "Freeing port $PORT..."
    if command -v lsof >/dev/null 2>&1; then
      PIDS=$(lsof -ti "tcp:$PORT" 2>/dev/null || true)
      if [[ -n "$PIDS" ]]; then
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
      fi
    else
      echo "WARN: lsof not installed; could not free port $PORT" >&2
    fi
  else
    echo "WARN: $PORT_FILE did not contain a numeric port; skipping port cleanup" >&2
  fi
fi

# Path-based kill: catches processes that lost their port binding (e.g.,
# uvicorn parents whose workers crashed or were reparented to init). Every
# process spawned from inside the worktree carries the worktree's absolute
# path in its argv (typically via .venv/bin/<interpreter>), so pgrep -f on
# $WORKTREE_PATH is a more authoritative primitive than the .port file.
# TERM first, then KILL stragglers after a 1s grace.
#
# Escape regex metacharacters in $WORKTREE_PATH before handing to pgrep -f,
# which treats its argument as an extended regex. Path slashes and dots are
# regex-meaningful; a worktree slug containing other meta characters could
# otherwise produce surprising matches.
ESC_WT_PATH=$(printf '%s\n' "$WORKTREE_PATH" | sed 's/[][\\.*^$/()+?{|}]/\\&/g')

PIDS=$(pgrep -f "$ESC_WT_PATH" 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
  echo "Killing processes referencing $WORKTREE_PATH..."
  echo "$PIDS" | xargs kill 2>/dev/null || true
  sleep 1
  STRAGGLERS=$(pgrep -f "$ESC_WT_PATH" 2>/dev/null || true)
  if [[ -n "$STRAGGLERS" ]]; then
    echo "$STRAGGLERS" | xargs kill -9 2>/dev/null || true
  fi
fi

# Removal: pass --force only when explicitly requested. --force bypasses BOTH
# git's submodule-presence refusal AND its dirty-working-tree refusal, so we
# keep it opt-in rather than auto-detecting submodules — silent auto-force
# would also silently discard uncommitted changes in the worktree.
#
# Capture stderr so we can (a) hint at --force when git's refusal looks like
# the submodule case, and (b) surface git's non-fatal warnings on success
# (which the prior fire-and-forget invocation passed straight to the terminal
# — preserve that visibility under the captured-stderr pattern). The Iron
# Law's merge gate has already cleared (passed or explicitly descoped) by
# this point; the hint is purely about removal mechanics.
REMOVE_ARGS=()
[[ $FORCE -eq 1 ]] && REMOVE_ARGS+=(--force)
# ${arr[@]+"${arr[@]}"} is the bash-3.2-safe expansion for "maybe-empty array
# under set -u" — macOS still ships bash 3.2, where a plain "${arr[@]}" on an
# empty array trips nounset.
if ! REMOVE_ERR=$(git worktree remove ${REMOVE_ARGS[@]+"${REMOVE_ARGS[@]}"} "$WORKTREE_PATH" 2>&1 >/dev/null); then
  echo "ERROR: git worktree remove failed:" >&2
  echo "$REMOVE_ERR" >&2
  if [[ $FORCE -eq 0 && "$REMOVE_ERR" == *submodule* ]]; then
    echo "" >&2
    echo "Hint: the worktree contains submodules. Re-run with --force to bypass." >&2
    echo "      (--force also bypasses git's dirty-tree check; verify the worktree is clean first.)" >&2
  fi
  exit 2
fi
[[ -n "$REMOVE_ERR" ]] && printf '%s\n' "$REMOVE_ERR" | sed 's/^/WARN: /' >&2
git worktree prune || exit 2

# Post-removal sweep: warn (do not fail) if anything still references the path.
# Informational only — surfaces leaks the operator can investigate.
STRAGGLERS=$(pgrep -f "$ESC_WT_PATH" 2>/dev/null || true)
if [[ -n "$STRAGGLERS" ]]; then
  echo "WARN: processes still reference $WORKTREE_PATH after destroy:" >&2
  # ps -p accepts a comma-separated PID list on both BSD (macOS) and GNU,
  # whereas space-separated/multiple-flag forms diverge across the two.
  PID_LIST=$(echo "$STRAGGLERS" | tr '\n' ',' | sed 's/,$//')
  # Redirection order: `>&2` first reroutes ps's stdout to stderr (so the
  # operator sees the process table as part of the WARN message). `2>/dev/null`
  # then silences ps's OWN stderr (e.g., complaints about an already-dead PID).
  ps -p "$PID_LIST" >&2 2>/dev/null || true
fi

echo "Worktree removed: $WORKTREE_PATH"
