#!/usr/bin/env bash
# install-refresh.sh — wire the skills auto-refresh hook into a consumer repo.
#
# The contract is TWO artifacts, and that is the whole reason this script
# exists:
#
#   1. .claude/hooks/skills-submodule-update.sh   — a symlink into the vendor
#   2. an entry in .claude/settings.json          — the SessionStart registration
#
# The symlink alone does nothing. Claude Code runs what settings.json names, so
# a repo carrying artifact 1 without artifact 2 looks installed to anyone who
# lists .claude/hooks/ and never refreshes anything. Four of twelve audited
# consumers were in exactly that state — symlink present and tracked,
# registration absent — pinned at one commit for over a week while the rest of
# the cohort moved through four skill versions (#167).
#
# That was a hand-executed three-step procedure in SKILL.md. install-doctor.sh
# has been a script since the beginning and has no comparable failure
# population; the difference is not the operators, it is that one of the two
# installs was a script and the other was prose. So this is the prose,
# executed.
#
# Idempotent: a re-run repairs whichever half is missing and reports the other
# unchanged. It never commits.
set -euo pipefail

HOOK_NAME="skills-submodule-update.sh"
HOOK_REL=".claude/hooks/$HOOK_NAME"
SETTINGS_REL=".claude/settings.json"

usage() {
  cat <<'USAGE'
install-refresh.sh — install the skills auto-refresh SessionStart hook

Usage:
  bash <vendor>/skills/managing-skills/scripts/install-refresh.sh [options]

Options:
  --check      Report what is installed; change nothing. The contract is TWO
               artifacts, so both are reported independently and the exit code
               reflects either being absent.
               Exit 0 both present, 3 either missing.
  --uninstall  Remove the symlink AND the settings.json registration.
  --quiet, -q  Suppress progress messages (errors and --check still print).
  -h, --help   Show this help and exit 0.

What it does:
  Symlinks .claude/hooks/skills-submodule-update.sh at the vendored script, so
  upstream fixes propagate through the normal submodule refresh rather than
  needing a re-copy.

  Merges a SessionStart entry into .claude/settings.json. The merge is
  dedupe-then-append and matches on the SCRIPT PATH rather than the whole
  command, so an entry written in the older cwd-relative form (pre-#110) is
  recognised and replaced instead of duplicated.

  Neither step clobbers unrelated content: other SessionStart hooks, other hook
  events, and every other key in settings.json are preserved.

Requires jq, which is what merges settings.json without rewriting it.

It does not commit. Review the diff and commit with your normal gate:
  git add .claude/hooks/skills-submodule-update.sh .claude/settings.json
  git commit -m "chore: enable skills auto-refresh hook"

Exit codes:
  0  installed, repaired, unchanged, or uninstalled
  1  usage error, not in a consumer repo, no vendored hook script, no jq, or
     settings.json could not be read or rewritten
  3  --check only: one or both artifacts are missing
USAGE
}

MODE="install"
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --quiet|-q) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

log() { [ "$QUIET" = "1" ] || echo "install-refresh: $*"; }
err() { echo "install-refresh: $*" >&2; }

# The consumer root, not this script's location: the script lives inside the
# vendor tree, and is invoked from the checkout it is operating on.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  err "not inside a git repository"; exit 1; }
cd "$ROOT"

HOOK="$ROOT/$HOOK_REL"
SETTINGS="$ROOT/$SETTINGS_REL"

have_jq() { command -v jq >/dev/null 2>&1; }

# A temp file that cannot outlive the run. Without this, a failed rewrite left
# a temp file behind for `git add -A` to pick up (CR finding 11).
#
# PID-suffixed, because the trap is what makes a shared name dangerous: it fires
# on EVERY exit, including runs that never call settings_rewrite. With a fixed
# `$SETTINGS.tmp` a concurrent invocation would delete an in-flight write this
# one was midway through — a two-writer race widened into "any invocation
# clobbers any writer". install-doctor.sh already had the right shape (#181 CR).
SETTINGS_TMP="$SETTINGS.tmp.$$"
trap 'rm -f "$SETTINGS_TMP"' EXIT

# Rewrite settings.json through a temp file, or fail having changed nothing.
#
# `jq … >tmp && mv` with a `log "…"` after it is the shape that reported a
# registration which did not exist: under `set -e` the failure of the FIRST
# element of an && list is exempt, so a jq parse error neither aborted the
# script nor skipped the log line. mv never ran, the temp file was orphaned, and
# install printed `registered the SessionStart entry` and exited 0 against a
# file it had not touched — the #167 lie, produced by the tool written to detect
# it (CR finding 11).
#
# The `if` is what fixes it: the list's status governs the branch, so success is
# logged only when the file actually moved.
settings_rewrite() {
  local desc="$1"; shift
  if jq "$@" "$SETTINGS" >"$SETTINGS_TMP" && mv -f "$SETTINGS_TMP" "$SETTINGS"; then
    log "$desc"
    return 0
  fi
  rm -f "$SETTINGS_TMP"
  # "$SETTINGS_REL was not modified", not "nothing was changed": the install
  # path may already have written the symlink, and a blanket claim contradicted
  # the `linked …` line printed immediately above it (CR finding 14). Say only
  # what this function can vouch for.
  err "could not rewrite $SETTINGS_REL (see the error above) — it was not modified"
  exit 1
}

# The exact command an install writes. Defined once, in shell, and passed to jq
# with --arg rather than typed into each jq program: the basename appeared in
# three jq filters in three notations, which is the reader/writer drift this
# file's own history is about (CR finding 9). Single quotes around the
# ${CLAUDE_PROJECT_DIR:-.} part keep it literal — it is text for Claude Code to
# expand at hook time, not for this script to expand now.
# shellcheck disable=SC2016
HOOK_COMMAND='bash "${CLAUDE_PROJECT_DIR:-.}/'"$HOOK_REL"'"'

# Registration test, shared by every mode so the reader and the writer cannot
# drift — the lesson install-cadence.sh learned when its --check reported "yes"
# against a line the installer no longer wrote.
#
# Emits the registered SessionStart command naming this hook, or empty.
# Returns 0 when the file was read, 2 when it exists and jq could not parse it,
# so a caller can tell "not registered" from "could not tell" (CR finding 10).
#
# jq, and scoped to .hooks.SessionStart[].hooks[].command — NOT a grep over the
# file. The basename appears in settings.json for reasons that are not
# registrations: a `permissions.allow` entry like
# `Bash(bash .claude/hooks/skills-submodule-update.sh)` is the common one, and
# the fewer-permission-prompts skill writes exactly that shape. A whole-file
# grep called that "registered", so --check exited 0 saying `SessionStart entry:
# yes` on a repo whose SessionStart was empty — reproducing the #167 failure
# inside the tool built to detect it. The jq WRITER was always correctly scoped;
# only the reader was not.
#
# The command is returned rather than a boolean so the caller can ask which FORM
# it is in: an install predating the $CLAUDE_PROJECT_DIR form (#110) is
# cwd-relative and still a real registration.
hook_command() {
  [ -f "$SETTINGS" ] || return 0
  have_jq || return 0
  jq -r --arg n "$HOOK_NAME" \
     '[.hooks.SessionStart[]?.hooks[]?.command // ""]
      | map(select(contains($n))) | first // ""' \
      "$SETTINGS" 2>/dev/null || return 2
}

# Honours hook_command's STATUS, not just its output. jq prints the extracted
# command for a leading valid value before erroring on a malformed trailer, so
# hook_command can return 2 WITH non-empty stdout; taking the text alone read
# that as "registered" and routed a file jq cannot parse into the strip. --check
# already honoured the status, so the two readers disagreed about the same file
# — the drift this header is about (CR finding 12).
is_registered() {
  local out rc=0
  out="$(hook_command)" || rc=$?
  [ "$rc" -eq 0 ] || return 1
  [ -n "$out" ]
}

# Registered AND in the current anchored form. The two are deliberately
# different questions, because they answer to different callers:
#
#   is_registered  — "does this hook run at all?" A legacy cwd-relative entry
#                    runs today, so --check must report it as installed and the
#                    doctor must not nag about it. Reporting a working repo as
#                    broken is how a warning gets ignored.
#   is_current     — "is it in the form we now install?" The install path uses
#                    this one, so a re-run UPGRADES a legacy entry instead of
#                    seeing the substring, declaring victory, and leaving the
#                    undocumented cwd assumption (#110) in place forever.
#
# Collapsing these into one test is what made a re-run a no-op on exactly the
# repos that most needed it.
# Equality against the command an install would write, rather than a substring
# probe for the anchored prefix. "Is it the form we now install" IS "would a
# fresh install produce this string", so comparing to the string settles it, and
# it drops the escaping dance the substring form needed.
is_current() {
  [ "$(hook_command)" = "$HOOK_COMMAND" ]
}

# Resolves, not merely exists. A dangling symlink is the state doctor.sh exists
# to repair, and reporting it as installed here would send an operator looking
# anywhere but at the submodule.
is_linked() {
  [ -L "$HOOK" ] && [ -e "$HOOK" ]
}

if [ "$MODE" = "check" ]; then
  # Reported independently. The two are separate failure modes — a symlink with
  # no registration never runs, a registration with no symlink errors on every
  # session start — and gating the second report on the first hides whichever
  # one you were not looking for.
  rc=0
  if is_linked; then
    echo "hook symlink:       $HOOK_REL -> $(readlink "$HOOK")"
  elif [ -L "$HOOK" ]; then
    echo "hook symlink:       DANGLING ($HOOK_REL) — run .skills/doctor.sh, or"
    echo "                    git submodule update --init --recursive"
    rc=3
  else
    echo "hook symlink:       MISSING ($HOOK_REL)"
    rc=3
  fi
  # Read once, and keep the status: "not registered" and "could not tell" are
  # different answers and a probe people are told to trust must not merge them.
  hc_rc=0
  registered_cmd="$(hook_command)" || hc_rc=$?
  if ! have_jq; then
    # UNKNOWN, not "MISSING" and not "yes". Reading the hook list needs jq, and
    # the whole-file grep that used to stand in for it is what made this report
    # lie (finding 1). A probe that cannot answer must say so — the per-repo
    # repair issues tell people to trust this exit code.
    echo "SessionStart entry: UNKNOWN — jq is not installed, and the hook list"
    echo "                    cannot be read safely without it. Install jq and"
    echo "                    re-run; a guess here is what this check exists to"
    echo "                    replace."
    rc=3
  elif [ "$hc_rc" -ne 0 ]; then
    echo "SessionStart entry: UNREADABLE — $SETTINGS_REL is not valid JSON, so"
    echo "                    the hook list cannot be read. Reporting MISSING"
    echo "                    here would send you to re-run this installer,"
    echo "                    which would fail on the same parse error."
    # `|| true` is load-bearing: this jq is EXPECTED to fail — printing why is
    # its whole purpose — and under `set -euo pipefail` the failing pipeline
    # otherwise aborts the script before `rc=3`, so --check exited with jq's
    # code instead of its own documented 3.
    jq . "$SETTINGS" 2>&1 >/dev/null | sed 's/^/                    /' || true
    rc=3
  elif [ -n "$registered_cmd" ]; then
    echo "SessionStart entry: yes (in $SETTINGS_REL)"
  elif [ -L "$HOOK" ]; then
    # The half-installed state this script exists for. Say what it costs, not
    # just what is absent — "MISSING" alone reads as cosmetic next to a symlink
    # that is visibly right there.
    echo "SessionStart entry: MISSING — the hook is on disk but Claude Code never"
    echo "                    runs it, so this repo's vendored skills are frozen"
    echo "                    at their current commit. Re-run install-refresh.sh."
    rc=3
  else
    echo "SessionStart entry: MISSING ($SETTINGS_REL)"
    rc=3
  fi
  exit "$rc"
fi

need_jq() {
  command -v jq >/dev/null 2>&1 || {
    err "jq is required to edit $SETTINGS_REL safely"
    err "install jq, or follow the manual steps in managing-skills/SKILL.md"
    exit 1; }
}

if [ "$MODE" = "uninstall" ]; then
  # need_jq FIRST — before anything is removed, not merely before the strip.
  #
  # Routing the registration test through jq meant a jq-less machine read "not
  # registered", skipped the strip, and exited 0 having removed only the symlink
  # — an entry left running bash on a path that no longer exists, every session
  # start. A silent half-UNINSTALL, the mirror of the half-install this script
  # exists for (CR finding 7).
  #
  # Demanding jq up here rather than just before the strip means a machine that
  # cannot finish the job does not start it, so there is no partial state to
  # reason about at all — only "nothing happened, and here is why". Skipped
  # entirely when there is no settings.json, since then there is nothing to
  # strip and jq is not needed to remove a symlink.
  #
  # An unparseable settings.json is fatal for the same reason, and is checked
  # here rather than at the strip: jq cannot remove an entry from a file it
  # cannot read, and discovering that after the symlink is gone leaves exactly
  # the half-state this ordering exists to prevent (CR findings 11, 12).
  UNINSTALL_CMD=""
  if [ -f "$SETTINGS" ]; then
    need_jq
    hc_rc=0
    UNINSTALL_CMD="$(hook_command)" || hc_rc=$?
    [ "$hc_rc" -eq 0 ] || {
      err "$SETTINGS_REL is not valid JSON, so the SessionStart entry cannot be"
      err "removed. Nothing was changed — fix the JSON and re-run."
      exit 1; }
  fi
  if [ -L "$HOOK" ] || [ -e "$HOOK" ]; then
    rm -f "$HOOK"
    log "removed $HOOK_REL"
  else
    log "nothing to remove: no $HOOK_REL"
  fi
  if [ -n "$UNINSTALL_CMD" ]; then
    # $n is a jq variable bound by --arg, not a shell one. shellcheck can see
    # that when the filter is an argument to `jq` itself; behind a wrapper it
    # cannot.
    # shellcheck disable=SC2016
    settings_rewrite "removed the SessionStart entry from $SETTINGS_REL" \
      --arg n "$HOOK_NAME" \
      'if .hooks.SessionStart then
         .hooks.SessionStart |= map(select(((.hooks // [])[0].command // "")
           | tostring | contains($n) | not))
       else . end'
  fi
  log "not committed — review and commit with your normal gate."
  exit 0
fi

# --- install ---------------------------------------------------------------

# First matching vendor wins, matching sync_self() in doctor.sh and the `break`
# in skills-submodule-update.sh. When skills-vendor/ is absent the glob stays
# unexpanded and the -f test rejects the literal string, so SRC stays empty and
# the error below fires rather than a symlink being pointed at a path that
# never existed.
SRC=""
for candidate in skills-vendor/*/skills/managing-skills/scripts/"$HOOK_NAME"; do
  [ -f "$candidate" ] || continue
  SRC="$candidate"
  break
done
[ -n "$SRC" ] || {
  err "no vendored $HOOK_NAME found under skills-vendor/*/skills/managing-skills/scripts/"
  err "add the skills repo as a submodule first — see managing-skills/SKILL.md"
  exit 1; }

need_jq

# Validate the settings file BEFORE the symlink is written, mirroring the
# uninstall branch. Failing at the registration instead left the repo holding a
# symlink and no entry — the half-installed state this whole script exists to
# prevent — and printed it one line under `linked …`, so the run both created
# the state and reported it as nothing having happened (CR finding 14).
#
# A run that cannot finish must not start. Checked here rather than inside
# settings_rewrite because by then the symlink is already on disk.
if [ -f "$SETTINGS" ]; then
  hc_rc=0
  hook_command >/dev/null || hc_rc=$?
  [ "$hc_rc" -eq 0 ] || {
    err "$SETTINGS_REL is not valid JSON, so the SessionStart entry cannot be"
    err "written. Nothing was changed — fix the JSON and re-run."
    exit 1; }
fi

# Relative, and derived from the vendor directory that was actually found
# rather than from a placeholder the caller was asked to substitute. The
# <owner>-<repo> in SKILL.md's ln command is the kind of hand-substitution that
# produces a symlink pointing at a plausible path which does not exist.
# ../../ climbs out of .claude/hooks/ to the repo root.
mkdir -p "$ROOT/.claude/hooks"
TARGET="../../$SRC"
if is_linked && [ "$(readlink "$HOOK")" = "$TARGET" ]; then
  log "unchanged: $HOOK_REL already points at $SRC"
else
  # -f so a re-run replaces a stale or dangling symlink rather than failing.
  ln -sfn "$TARGET" "$HOOK"
  log "linked $HOOK_REL -> $SRC"
fi

[ -f "$SETTINGS" ] || { echo '{}' >"$SETTINGS"; log "created $SETTINGS_REL"; }

if is_current; then
  log "unchanged: $SETTINGS_REL already registers the hook"
else
  # An `if`, not `is_registered && log ...` — doctor.sh carries the same note:
  # under set -e the && form leaves the statement's exit status at the failing
  # test, and this one fails on every fresh install.
  if is_registered; then
    log "upgrading the registration to the \$CLAUDE_PROJECT_DIR form (#110)"
  fi
  # Defensive in the two ways SKILL.md documents: it creates .hooks and
  # .hooks.SessionStart when absent, and it strips any pre-existing entry for
  # this hook before appending so a re-run cannot produce duplicates.
  #
  # $CLAUDE_PROJECT_DIR, not the hook process's cwd (#110). Claude Code
  # normally runs hooks from the project dir, so the bare form works today, but
  # that is an undocumented assumption. The :-. fallback matters: with the
  # variable unset a bare "$CLAUDE_PROJECT_DIR/..." becomes "/.claude/hooks/..."
  # and errors on every session start, where "." degrades to the old behaviour.
  # $n and $cmd are jq variables bound by --arg, not shell ones — see the
  # matching note on the uninstall rewrite.
  # shellcheck disable=SC2016
  settings_rewrite "registered the SessionStart entry in $SETTINGS_REL" \
    --arg n "$HOOK_NAME" --arg cmd "$HOOK_COMMAND" \
    '(.hooks //= {}) |
     (.hooks.SessionStart //= []) |
     .hooks.SessionStart |= map(select(((.hooks // [])[0].command // "")
       | tostring | contains($n) | not)) |
     .hooks.SessionStart += [{
       "matcher": ".*",
       "hooks": [{
         "type": "command",
         "command": $cmd
       }]
     }]'
fi

[ "$QUIET" = "1" ] || cat <<NEXT

Not committed — review and commit with your normal gate. BOTH artifacts:
  git add $HOOK_REL $SETTINGS_REL
  git commit -m "chore: enable skills auto-refresh hook"

The hook runs at most once per UTC day, on main only, and auto-commits the
pointer bumps. To confirm it ran, check .git/skills-update.log after a session
start on main.
NEXT
