#!/usr/bin/env bash
# install-guard.sh — wire context-budget-guard.sh into a repo as a Claude Code
# PostToolUse hook.
#
# Idempotent: a re-run repairs partial state (symlink present but settings.json
# entry missing, or vice versa) without ever producing a duplicate entry.
#
# The hook script is installed as a SYMLINK to the vendored source, so upstream
# fixes propagate on the normal submodule refresh. That is the opposite of the
# doctor, which must be a copy because it exists to repair broken symlinks — this
# guard has no such constraint, and a copy would freeze the way #84's did.
set -euo pipefail

usage() {
  cat <<'USAGE'
install-guard.sh — install the context-budget PostToolUse hook

Usage:
  install-guard.sh [options]

Options:
  --budget N       Write N to .skills/context-budget (policy-file budget).
                   Omit to leave the existing value, or the 6000 default.
  --doc-budget N   Write N to .skills/context-doc-budget (per-reference-doc).
  --uninstall      Remove the settings.json entry and the hook symlink.
  --check          Report whether the hook is installed; change nothing.
                   Exit 0 installed, 3 not installed.
  -h, --help       Show this help and exit 0.

What it does:
  1. Symlinks .claude/hooks/context-budget-guard.sh -> the vendored script
     (relative when the source is inside the repo, absolute otherwise).
  2. Merges a PostToolUse entry matching Edit|Write|MultiEdit into
     .claude/settings.json, stripping any prior entry for this hook first.
  3. Optionally writes the budget knobs.

It does not commit. Review the diff and commit with your normal gate.

Requires: jq (for the settings.json merge). Everything else is POSIX.

Exit codes:
  0  installed, uninstalled, or already correct
  1  usage error, jq missing, not in a git repo, or the settings.json
     rewrite failed (settings.json is left exactly as it was)
  3  --check only: the hook is not installed
USAGE
}

BUDGET=""
DOC_BUDGET=""
MODE="install"

while [ $# -gt 0 ]; do
  case "$1" in
    --budget) BUDGET="${2:?--budget needs a number}"; shift 2 ;;
    --doc-budget) DOC_BUDGET="${2:?--doc-budget needs a number}"; shift 2 ;;
    --uninstall) MODE="uninstall"; shift ;;
    --check) MODE="check"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

for v in $BUDGET $DOC_BUDGET; do
  case "$v" in
    ''|*[!0-9]*) echo "ERROR budgets must be positive integers (got '$v')" >&2; exit 1 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR not inside a git repository" >&2; exit 1; }
# The per-worktree git dir, which is where the guard logs. `$ROOT/.git` is a FILE
# in a linked worktree, so it is never a usable directory there (#109).
GITDIR="$(git rev-parse --absolute-git-dir 2>/dev/null)" || GITDIR="$ROOT/.git"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SRC_DIR/context-budget-guard.sh"
HOOK_DIR="$ROOT/.claude/hooks"
HOOK="$HOOK_DIR/context-budget-guard.sh"
SETTINGS="$ROOT/.claude/settings.json"
# Anchored on $CLAUDE_PROJECT_DIR rather than the hook process's cwd, which was
# an undocumented assumption the old `bash .claude/hooks/…` form was load-bearing
# on (#110). The `:-.` fallback is the house style init-socraticode established:
# with the variable unset, a bare "$CLAUDE_PROJECT_DIR/..." degrades to
# `bash "/.claude/hooks/…"` and errors on every edit, where `.` degrades to
# exactly the old behaviour.
# Single quotes are required: this is the literal string written into
# settings.json for the hook runtime to expand, not for this shell to expand.
# shellcheck disable=SC2016
COMMAND='bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/context-budget-guard.sh"'
# Entries are FOUND by script path, not by exact command string, so an install
# written by an older version of this script is still recognised, replaced and
# removable. Matching only $COMMAND would make every existing install permanent.
COMMAND_MARKER='.claude/hooks/context-budget-guard.sh'

LIB="$SRC_DIR/_context-lib.sh"

# A temp file that cannot outlive the run. merge_settings removes it on its own
# failure path; this covers the signal case it cannot, so a killed run never
# strands a temp file for `git add -A` to collect (#181, and the same CR finding
# 11 that install-hook.sh carries — it moved there from install-refresh.sh when
# #200 generalized the installer).
#
# PID-suffixed, because the trap is what makes a shared name dangerous: it fires
# on EVERY exit, including `--check`, which writes nothing. With a fixed
# `$SETTINGS.tmp` a concurrent `--check` would delete an in-flight write this
# script was midway through — turning a two-writer race into "any invocation
# clobbers any writer". install-doctor.sh already had the right shape (#181 CR).
SETTINGS_TMP="$SETTINGS.tmp.$$"
trap 'rm -f "$SETTINGS_TMP"' EXIT

if [ "$MODE" = "check" ]; then
  ok=0
  [ -e "$HOOK" ] || ok=1
  # Match the marker, not the exact command: an entry written by an older
  # installer is installed and working, and reporting it "not installed" would be
  # a false negative. It is named instead, below.
  [ -f "$SETTINGS" ] && grep -qF "$COMMAND_MARKER" "$SETTINGS" || ok=1
  # The guard sources _context-lib.sh from beside its resolved target. A vendored
  # tree missing the library leaves a hook that looks installed and exits 0 on
  # every edit, which is the one failure mode the ok:/WARN: log cannot reveal
  # because nothing is logged before the library loads.
  lib_ok=yes
  if [ -e "$HOOK" ]; then
    hook_target="$(cd "$(dirname "$HOOK")" && pwd -P)/$(basename "$HOOK")"
    while [ -L "$hook_target" ]; do
      t="$(readlink "$hook_target")" || break
      case "$t" in
        /*) hook_target="$t" ;;
        *) hook_target="$(dirname "$hook_target")/$t" ;;
      esac
    done
    [ -f "$(dirname "$hook_target")/_context-lib.sh" ] || { lib_ok=no; ok=1; }
  fi
  if [ "$ok" -eq 0 ]; then
    echo "installed: $HOOK, and referenced in .claude/settings.json"
    echo "library:   $(cd "$(dirname "$hook_target")" && pwd -P)/_context-lib.sh"
    echo "log:       $GITDIR/context-budget.log"
    # Compared as a PARSED value, not as file text. jq writes the command with
    # its inner quotes JSON-escaped (`bash \"${CLAUDE_PROJECT_DIR:-.}/…\"`), so
    # a grep for the shell form can never match what jq just wrote — the note
    # below fired forever, including on the run immediately after a successful
    # normalize. A check that cannot report success is worse than no check: it
    # trains the reader to ignore it.
    if ! jq -e --arg cmd "$COMMAND" \
        '[.hooks.PostToolUse[]?.hooks[]?.command] | any(. == $cmd)' \
        "$SETTINGS" >/dev/null 2>&1; then
      echo "note: the settings entry uses the older cwd-relative command form."
      echo "      It works, but it depends on the hook process's cwd. Re-run"
      echo "      install-guard.sh to normalize it onto \$CLAUDE_PROJECT_DIR."
    fi
    exit 0
  fi
  echo "not installed (hook symlink present: $([ -e "$HOOK" ] && echo yes || echo no); settings entry: $([ -f "$SETTINGS" ] && grep -qF "$COMMAND_MARKER" "$SETTINGS" && echo yes || echo no); library beside target: $lib_ok)"
  exit 3
fi

command -v jq >/dev/null 2>&1 || {
  echo "ERROR jq is required to merge .claude/settings.json safely" >&2; exit 1; }

merge_settings() {
  # Strip any pre-existing entry for this hook, then append. Both halves matter:
  # the strip is what makes a re-run idempotent, and the //= defaults are what
  # make it work against {} , a settings.json with no hooks block, and one with
  # other hooks already wired.
  #
  # The strip matches on the script path ($marker), not on the exact command
  # string. An install written by an older version of this script used a
  # cwd-relative command; an equality test would leave that entry in place —
  # duplicating the guard on install, and leaving it unremovable on uninstall.
  # `// "" | tostring` keeps a hand-edited entry with a null or non-string
  # command from erroring the whole merge.
  local expr
  # $marker is a jq variable, bound below with --arg; single quotes keep the
  # shell out of it.
  # shellcheck disable=SC2016
  expr='(.hooks //= {}) |
        (.hooks.PostToolUse //= []) |
        .hooks.PostToolUse |= map(select((.hooks // [])
          | map((.command // "") | tostring | contains($marker)) | any | not))'
  if [ "$MODE" = "install" ]; then
    expr="$expr | .hooks.PostToolUse += [{
        \"matcher\": \"Edit|Write|MultiEdit\",
        \"hooks\": [{\"type\": \"command\", \"command\": \$cmd, \"timeout\": 10}]
      }]"
  fi
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' >"$SETTINGS"
  # Reject a malformed settings.json outright rather than overwriting it — the
  # file may hold permissions and env config that would be expensive to lose.
  jq -e . "$SETTINGS" >/dev/null 2>&1 || {
    echo "ERROR $SETTINGS is not valid JSON — fix it before installing the hook" >&2
    exit 1; }
  # `jq … >tmp && mv` with the outcome left unchecked is the shape that let
  # install-refresh.sh report a registration it had not written: under `set -e`
  # the failure of the FIRST element of an && list is exempt, so neither the
  # abort nor the skip happens. Here the list is the last command of a function
  # invoked as a plain command, so errexit does fire on the caller and the
  # `merged …` line is never reached — but the script still died on a bare
  # `jq: error` with exit 5, after having already printed `linked …`, and left
  # the temp file behind. Say which half landed, and clean up.
  #
  # `jq -e .` above rejects malformed JSON; it cannot reject a settings.json
  # that parses but whose `.hooks` is the wrong TYPE, which is what a hand edit
  # produces and what makes this filter error mid-run.
  if jq --arg cmd "$COMMAND" --arg marker "$COMMAND_MARKER" \
      "$expr" "$SETTINGS" >"$SETTINGS_TMP" \
      && mv -f "$SETTINGS_TMP" "$SETTINGS"; then
    return 0
  fi
  rm -f "$SETTINGS_TMP"
  # Name the file, and claim nothing about the symlink: on the install path it
  # has already been written and reported one line above, so a blanket "nothing
  # was changed" would contradict the output the reader just saw (the CR finding
  # 14 install-refresh.sh landed).
  echo "ERROR could not rewrite $SETTINGS (see the jq error above)" >&2
  echo "      — it was not modified. Check that .hooks is an object." >&2
  exit 1
}

if [ "$MODE" = "uninstall" ]; then
  merge_settings
  rm -f "$HOOK"
  echo "uninstalled: removed $HOOK and its .claude/settings.json entry"
  echo "note: .skills/context-budget* knobs were left in place"
  exit 0
fi

[ -f "$SRC" ] || { echo "ERROR guard script not found at $SRC" >&2; exit 1; }
# Refuse to install a guard whose library is missing. Without this the hook wires
# up cleanly and then exits 0 on every edit forever, and nothing is logged
# because the log line that would say so lives past the source.
[ -f "$LIB" ] || {
  echo "ERROR _context-lib.sh not found at $LIB" >&2
  echo "      The guard sources it at run time; installing without it yields a" >&2
  echo "      hook that silently does nothing. Refresh the vendored skill." >&2
  exit 1; }

mkdir -p "$HOOK_DIR"

# Prefer a repo-relative symlink so the checkout stays portable across machines.
# When the skill is installed at the user level (~/.claude/skills/...) the source
# is outside the repo and no relative path exists — fall back to absolute and say
# so, since that link will not resolve for a collaborator.
case "$SRC" in
  "$ROOT"/*)
    REL_SRC="${SRC#"$ROOT"/}"
    # From .claude/hooks/ back to the repo root is two levels.
    ln -sfn "../../$REL_SRC" "$HOOK"
    echo "linked $HOOK -> ../../$REL_SRC"
    ;;
  *)
    ln -sfn "$SRC" "$HOOK"
    echo "linked $HOOK -> $SRC (absolute)"
    echo "note: the guard lives outside this repo, so this link is machine-local."
    echo "      Vendor the skill under skills-vendor/ for a portable install."
    ;;
esac

merge_settings
echo "merged the PostToolUse entry into $SETTINGS"

mkdir -p "$ROOT/.skills"
if [ -n "$BUDGET" ]; then
  echo "$BUDGET" >"$ROOT/.skills/context-budget"
  echo "wrote .skills/context-budget = $BUDGET"
fi
if [ -n "$DOC_BUDGET" ]; then
  echo "$DOC_BUDGET" >"$ROOT/.skills/context-doc-budget"
  echo "wrote .skills/context-doc-budget = $DOC_BUDGET"
fi

# Print the RESOLVED log path, not a hardcoded `.git/context-budget.log`. In a
# linked worktree the log lives under the main checkout's .git/worktrees/<name>/,
# so the hardcoded hint fails there — and a failing verification step reads as
# "the guard is broken" when it is not (#109).
cat <<NEXT

Not committed — review and commit with your normal gate:
  git add .claude/hooks/context-budget-guard.sh .claude/settings.json .skills/
  git commit -m "chore: enable the context-budget write guard"

Verify after the next edit to AGENTS.md:
  tail $GITDIR/context-budget.log
NEXT
