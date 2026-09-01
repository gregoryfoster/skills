#!/usr/bin/env bash
# install-hook.sh — wire a vendored SessionStart hook into a consumer repo.
#
# The contract is TWO artifacts, and that is the whole reason this script
# exists:
#
#   1. .claude/hooks/<hook>.sh   — a symlink into the vendor (or a copy)
#   2. an entry in .claude/settings.json — the SessionStart registration
#
# The symlink alone does nothing. Claude Code runs what settings.json names, so
# a repo carrying artifact 1 without artifact 2 looks installed to anyone who
# lists .claude/hooks/ and never runs anything. Four of twelve audited consumers
# were in exactly that state — symlink present and tracked, registration absent
# — pinned at one commit for over a week while the rest of the cohort moved
# through four skill versions (#167).
#
# That was a hand-executed three-step procedure in SKILL.md. install-doctor.sh
# has been a script since the beginning and has no comparable failure
# population; the difference is not the operators, it is that one of the two
# installs was a script and the other was prose. So this is the prose, executed.
#
# WHY IT TAKES A HOOK NAME (#200). This mechanism was install-refresh.sh: 435
# lines, of which ~400 were the generic contract — the jq merge, the
# reader/writer drift fixes, --check/--uninstall, and four rounds of ordering
# hardening (#178). Three hooks want it: skills-submodule-update.sh from
# managing-skills, and socraticode-reminder.sh / socraticode-health.sh from
# init-socraticode. #179's implementing agent refused to write the second copy
# on the ground that settles this file's shape:
#
#   An install-health.sh differs in two constants. Writing it means either
#   copy-pasting that history — guaranteeing the two drift, which is the
#   failure #179 is *about* — or generalizing.
#
# So the constants are arguments and there is exactly one implementation. This
# file contains no per-hook branch: every hook-specific value arrives on the
# command line, and a caller that needs a new one adds a flag rather than a
# case arm. install-refresh.sh is a wrapper that supplies refresh's constants,
# because its path is named in README.md, docs/SKILLS.md and in cohort repos.
# Not in doctor.sh's repair advice — that named it until #224, which taught the
# doctor to read each hook's arguments from a <hook>.install manifest and print
# THIS script instead.
#
# Idempotent: a re-run repairs whichever half is missing and reports the other
# unchanged. It never commits.
set -euo pipefail

SETTINGS_REL=".claude/settings.json"

usage() {
  cat <<'USAGE'
install-hook.sh — install a vendored SessionStart hook and register it

Usage:
  bash <vendor>/skills/managing-skills/scripts/install-hook.sh \
       --hook <script.sh> --skill <skill-dir> [--marker <token>]... [options]

Required:
  --hook <script.sh>   Basename of the hook script, in the vendored skill's
                       scripts/ directory and in .claude/hooks/.
  --skill <skill-dir>  The skill directory that vendors it, e.g. managing-skills
                       or init-socraticode.

Options:
  --marker <token>     A token that identifies this hook's registration inside a
                       settings.json command string. Repeatable. The FIRST is
                       canonical: it is written as a trailing `# <token>`
                       comment on the registered command, so the entry is
                       recognisable from settings.json alone. Any further
                       markers are legacy aliases — recognised on read, never
                       written — so an older install is upgraded rather than
                       duplicated. Default: the hook's own basename.
  --copy-fallback      When the consumer has no skills-vendor/ tree there is
                       nothing to symlink at; copy this installer's own sibling
                       copy of the hook instead of failing. A copy freezes at
                       install day and .skills/doctor.sh cannot see it (it scans
                       for DANGLING symlinks, and a copy is a valid file), so
                       this is the fallback, never the default (#179).
  --timeout <seconds>  Seconds Claude Code allows this hook before killing it,
                       written as the entry's `timeout` key. Omitted, the
                       harness default applies — which is the wrong budget for
                       a hook that shells out to the network, and the worst
                       possible one for a hook that stamps a once-per-day lock
                       BEFORE doing its work: a timeout kill then consumes the
                       day's attempt and reports nothing (#259). Each hook's
                       figure belongs in its <hook>.install manifest beside its
                       other constants, not in a branch here.

                       A timeout ALREADY on the entry being replaced WINS over
                       this flag, and the run says so. The dedupe-strip removes
                       every matching entry and appends one canonical entry,
                       which is what upgrades a stale command string — but it
                       also silently discarded a timeout the consumer had added
                       by hand, so the tool that prescribed the repair undid it
                       on the next refresh. To CHANGE a value already there,
                       edit it in settings.json, or --uninstall and reinstall;
                       --check reports the disagreement either way.
  --label <name>       Name to speak in, for a wrapper that owns a path of its
                       own (e.g. install-refresh.sh). Default: install-hook.
  --note <text>        Extra text printed after a successful install.
  --check      Report what is installed; change nothing. The contract is TWO
               artifacts, so both are reported independently and the exit code
               reflects either being absent. The registration half reports HOW
               MANY entries it found, because two run the hook twice a session,
               and the entry's `timeout` if it carries one.
               Exit 0 both present, 3 either missing, duplicated or not repaired.
               A registered entry with NO timeout where --timeout names one is
               "not repaired" and exits 3; a registered entry whose timeout
               merely DISAGREES with --timeout is a local choice this installer
               preserves, so it is reported and does not change the exit code.
  --allow-unresolved
               --check only. Accept a hook symlink whose SHAPE is right — a
               relative link into skills-vendor/ — but which does not resolve
               because the vendor content is not checked out. That is the
               routine state in CI and in a fresh worktree, and without this
               --check calls a correct install DANGLING there and cannot gate
               anything (#227). It relaxes resolution and nothing else: an
               absolute target, a target outside skills-vendor/, a link that
               misses a source which IS present, a missing registration and a
               COPY all still exit 3. The copy especially — where vendor
               content may be absent, a copy is the one form that resolves, so
               no resolution check can see it.
  --uninstall  Remove the hook file AND the settings.json registration.
  --quiet, -q  Suppress progress messages (errors and --check still print).
  -h, --help   Show this help and exit 0.

What it does:
  Symlinks .claude/hooks/<hook> at the vendored script, so upstream fixes
  propagate through the normal submodule refresh rather than needing a re-copy.

  Merges a SessionStart entry into .claude/settings.json. The merge is
  dedupe-then-append and matches on this hook's MARKERS rather than the whole
  command, so an entry written in an older form (pre-#110 cwd-relative, or a
  legacy install naming the script file) is recognised and replaced instead of
  duplicated. Markers are per-hook precisely so one hook's strip cannot evict a
  sibling's entry from the same array — and the strip removes matching HOOKS,
  not whole matcher groups, so that holds for a group holding several hooks and
  not only for the one-hook groups this installer writes (#222).

  Neither step clobbers unrelated content: other SessionStart hooks, other hook
  events, and every other key in settings.json are preserved — and since #259
  that includes a `timeout` on the entry this run replaces, which the strip
  used to discard because the append rebuilt the entry from constants only.

Requires jq, which is what merges settings.json without rewriting it.

It does not commit. Review the diff and commit with your normal gate.

Exit codes:
  0  installed, repaired, unchanged, or uninstalled
  1  usage error, not in a consumer repo, no vendored hook script, no jq, or
     settings.json could not be read or rewritten
  3  --check only: an artifact is missing, registered more than once, or
     installed in a form this would repair
USAGE
}

MODE="install"
QUIET=0
HOOK_NAME=""
SKILL=""
MARKERS=()
COPY_FALLBACK=0
ALLOW_UNRESOLVED=0
LABEL=""
NOTE=""
TIMEOUT=""
TIMEOUT_SET=0

# Bare basenames only. Both values are joined into .claude/hooks/ and into a
# vendor glob, so a path component here installs somewhere nobody looks — and
# the markers are assembled into a jq argument, so their charset is what keeps
# that assembly from needing to be trusted.
reject_unless_token() {
  case "$2" in
    "" | *[!A-Za-z0-9._-]* | .. )
      echo "install-hook: $1 must be a plain token ([A-Za-z0-9._-]): $2" >&2
      exit 1 ;;
  esac
}

# `shift 2` on a flag with no value exits non-zero under set -e with no message
# a reader can act on. Checked, so the error names the flag.
need_value() {
  [ "$2" -ge 2 ] || {
    echo "install-hook: $1 requires a value" >&2; exit 1; }
}

while [ $# -gt 0 ]; do
  case "$1" in
    --hook) need_value "$1" $#; HOOK_NAME="$2"; shift 2 ;;
    --skill) need_value "$1" $#; SKILL="$2"; shift 2 ;;
    --marker) need_value "$1" $#; MARKERS+=("$2"); shift 2 ;;
    --timeout) need_value "$1" $#; TIMEOUT="$2"; TIMEOUT_SET=1; shift 2 ;;
    --label) need_value "$1" $#; LABEL="$2"; shift 2 ;;
    --note) need_value "$1" $#; NOTE="$2"; shift 2 ;;
    --copy-fallback) COPY_FALLBACK=1; shift ;;
    --allow-unresolved) ALLOW_UNRESOLVED=1; shift ;;
    --check) MODE="check"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --quiet|-q) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# --help is answered above, so by here a hook name is not optional.
[ -n "$HOOK_NAME" ] || { echo "install-hook: --hook <script.sh> is required" >&2
  usage >&2; exit 1; }
[ -n "$SKILL" ] || { echo "install-hook: --skill <skill-dir> is required" >&2
  usage >&2; exit 1; }
reject_unless_token "--hook" "$HOOK_NAME"
reject_unless_token "--skill" "$SKILL"

# It changes what --check tolerates and nothing about an install. Accepting it
# silently on an install run would imply otherwise, and the caller most likely to
# pass it is a CI job whose whole point is that its assertions mean what they say.
[ "$ALLOW_UNRESOLVED" = "0" ] || [ "$MODE" = "check" ] || {
  echo "install-hook: --allow-unresolved requires --check" >&2; exit 1; }

# The default is the basename, which is what install-refresh.sh matched on
# before this file existed — so a caller that passes no marker gets exactly the
# pre-#200 behaviour, including a registered command with no trailing comment.
[ "${#MARKERS[@]}" -gt 0 ] || MARKERS=("$HOOK_NAME")
for m in "${MARKERS[@]}"; do reject_unless_token "--marker" "$m"; done

# Digits, and a real duration. The value goes into settings.json as a JSON
# NUMBER rather than a string, so it is the one argument here that is not
# quoted on the way in — `--timeout 60s` would otherwise write invalid JSON and
# leave the consumer with a settings file Claude Code cannot parse, which is a
# worse outcome than the missing timeout this flag exists to fix. Zero is
# refused because it reads as "no limit" and means "kill immediately"; the
# ceiling is a day, well past any hook's honest budget and short of the
# overflow a pasted millisecond value would produce.
#
# Keyed on the flag having been SEEN, not on the value being non-empty. A
# manifest whose line ends `--timeout ` — or a wrapper interpolating an unset
# shell variable — otherwise passes the empty string, every `[ -n "$TIMEOUT" ]`
# below reads it as "no ceiling asked for", and the run installs the harness
# default while the caller believes it named one. That is #259 reached from the
# fix for #259.
if [ "$TIMEOUT_SET" = "1" ]; then
  case "$TIMEOUT" in
    "" | *[!0-9]* )
      echo "install-hook: --timeout must be a whole number of seconds: $TIMEOUT" >&2
      exit 1 ;;
  esac
  # `10#` so a manifest written `--timeout 060` is decimal sixty, not an octal
  # parse error that aborts the install under set -e.
  if [ "$((10#$TIMEOUT))" -lt 1 ] || [ "$((10#$TIMEOUT))" -gt 86400 ]; then
    echo "install-hook: --timeout must be between 1 and 86400 seconds: $TIMEOUT" >&2
    exit 1
  fi
  TIMEOUT="$((10#$TIMEOUT))"
fi

# One flag, two derived strings: what to prefix messages with, and what to tell
# an operator to re-run. A wrapper owns a path of its own, and a report that
# names install-hook.sh would send the reader to a command they were never
# given.
if [ -n "$LABEL" ]; then
  TAG="${LABEL%.sh}"
  RERUN="$LABEL"
else
  TAG="install-hook"
  RERUN="install-hook.sh --hook $HOOK_NAME"
fi

log() { [ "$QUIET" = "1" ] || echo "$TAG: $*"; }
err() { echo "$TAG: $*" >&2; }

HOOK_REL=".claude/hooks/$HOOK_NAME"

# This script's own directory, resolved before any cd, and in a subshell so the
# consumer's cwd — which the `git rev-parse` below reads — is untouched. It is
# the fallback source for --copy-fallback: the installer ships beside the skills
# it installs from, so a consumer with no skills-vendor/ tree still has a real
# file to copy rather than a path the caller was asked to substitute.
#
# Parameter expansion rather than `dirname`, which is not a builtin: this runs
# in consumer repos and in the degraded environments the jq-less paths below
# exist for, and needing a second external tool to find our own directory would
# be a new way to fail before doing anything.
SELF_DIR="${BASH_SOURCE[0]}"
case "$SELF_DIR" in */*) SELF_DIR="${SELF_DIR%/*}" ;; *) SELF_DIR="." ;; esac
SELF_DIR="$(cd -- "$SELF_DIR" && pwd)"

# The consumer root, not this script's location: the script lives inside the
# vendor tree, and is invoked from the checkout it is operating on.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  err "not inside a git repository"; exit 1; }
cd "$ROOT"

HOOK="$ROOT/$HOOK_REL"
SETTINGS="$ROOT/$SETTINGS_REL"

have_jq() { command -v jq >/dev/null 2>&1; }

# The markers as a JSON array, for jq's --argjson. Every element passed
# reject_unless_token, so there is nothing here to escape.
markers_json() {
  local out="" m
  for m in "${MARKERS[@]}"; do out="$out,\"$m\""; done
  printf '[%s]' "${out#,}"
}
MARKERS_JSON="$(markers_json)"

# The dedupe strip, defined ONCE and used by both write paths.
#
# It reads at HOOK granularity, matching matching_commands below. The two used
# to disagree: the reader scanned every command in every group, and both writers
# dropped whole matcher GROUPS keyed on `(.hooks // [])[0].command` — index 0
# only. A settings.json where a matcher group holds more than one hook then got
# the wrong answer in both directions (#222):
#
#   A. The marker matched at index 0, so `map(select(...))` over
#      .hooks.SessionStart deleted the entire group and every sibling hook
#      registered beside it. Silent: the install reported success, the evicted
#      hook's symlink stayed a valid file, and .skills/doctor.sh cannot see a
#      missing registration. CannObserv/watcher lost its daily submodule refresh
#      to an init-socraticode install exactly this way.
#   B. The marker matched at index >= 1, so the [0] probe never saw it, the
#      group survived, and the append wrote a SECOND registration — while
#      is_registered (which does scan every index) made the run announce it was
#      "upgrading the registration". The stranded duplicate the dedupe-then-
#      append design exists to prevent, produced by the dedupe.
#
# So this strips the matching hooks out of each group and then drops any group
# THIS strip emptied. The `$n == 0` clause is what keeps that from over-reaching:
# a group that arrived already empty was not ours to delete, and neither is one
# whose .hooks is absent or not an array — the contract is that unrelated
# content survives, and a malformed entry is still someone's content.
#
# `.command?` rather than `.command`: an element that is not an object would
# otherwise abort the whole rewrite, and a filter that cannot survive junk in
# the file it is repairing is the wrong shape for a repair tool.
#
# $m is a jq variable bound by --argjson, not a shell one.
# shellcheck disable=SC2016
STRIP_MATCHING='
  def strip_matching($m):
    map(
      if (.hooks | type) == "array"
      then (.hooks | length) as $n
         | (.hooks |= map(select(((.command? // "") | tostring) as $c
             | ($m | any(. as $t | $c | contains($t))) | not)))
         | select($n == 0 or (.hooks | length) > 0)
      else . end
    );
'

# First matching vendor wins, matching sync_self() in doctor.sh and the `break`
# in skills-submodule-update.sh. When skills-vendor/ is absent the glob stays
# unexpanded and the -f test rejects the literal string, so SRC stays empty and
# either the copy fallback or the error below fires, rather than a symlink being
# pointed at a path that never existed.
vendored_src() {
  local candidate
  for candidate in skills-vendor/*/skills/"$SKILL"/scripts/"$HOOK_NAME"; do
    [ -f "$candidate" ] || continue
    printf '%s' "$candidate"
    return 0
  done
  return 0
}

# A temp file that cannot outlive the run. Without this, a failed rewrite left
# a temp file behind for `git add -A` to pick up (CR finding 11).
#
# PID-suffixed, because the trap is what makes a shared name dangerous: it fires
# on EVERY exit, including runs that never call settings_rewrite. With a fixed
# `$SETTINGS.tmp` a concurrent invocation would delete an in-flight write this
# one was midway through — a two-writer race widened into "any invocation
# clobbers any writer". install-doctor.sh already had the right shape (#181 CR).
# With three hooks now installed by three back-to-back invocations of this same
# script, the concurrent case stopped being hypothetical.
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
  # path may already have written the hook file, and a blanket claim contradicted
  # the `linked …` line printed immediately above it (CR finding 14). Say only
  # what this function can vouch for.
  err "could not rewrite $SETTINGS_REL (see the error above) — it was not modified"
  exit 1
}

# The exact command an install writes. Assembled once, in shell, and passed to
# jq with --arg rather than typed into each jq program: the basename appeared in
# three jq filters in three notations, which is the reader/writer drift this
# mechanism's own history is about (CR finding 9). Single quotes around the
# ${CLAUDE_PROJECT_DIR:-.} part keep it literal — it is text for Claude Code to
# expand at hook time, not for this script to expand now.
#
# The trailing `# <marker>` comment is what puts the dedupe token in the command
# string itself rather than only inside the script file, so the merge can
# recognise the entry from settings.json alone. It is omitted when the caller
# passed no marker, because then the marker IS the basename and the command
# already contains it — which keeps the command install-refresh.sh writes
# byte-identical to the one every installed consumer already carries.
# shellcheck disable=SC2016
HOOK_COMMAND='bash "${CLAUDE_PROJECT_DIR:-.}/'"$HOOK_REL"'"'
if [ "${MARKERS[0]}" != "$HOOK_NAME" ]; then
  HOOK_COMMAND="$HOOK_COMMAND # ${MARKERS[0]}"
fi

# Registration test, shared by every mode so the reader and the writer cannot
# drift — the lesson install-cadence.sh learned when its --check reported "yes"
# against a line the installer no longer wrote.
#
# Emits EVERY registered SessionStart command matching this hook's markers, one
# per line; empty when there are none. Returns 0 when the file was read, 2 when
# it exists and jq could not parse it, so a caller can tell "not registered"
# from "could not tell" (CR finding 10).
#
# All of them, not the first: a settings.json can carry a canonical entry AND a
# legacy duplicate left by an earlier verbatim re-run of the prose this script
# replaced. Reading only the first made `is_current` true, so the installer
# logged `unchanged` and left the duplicate running the hook twice per session
# — the reference doc asks for the extras to go, and a reader that cannot see
# them cannot ask the writer to remove them.
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
#
# The selector is a constant and the projection is the argument, because three
# callers want the same selection and different things from it: the commands
# themselves, how MANY there are, and — since #259 — the `timeout` sitting
# beside each command. Spelling the selector twice is the same reader/writer
# drift one level in, and it is a strip filter written twice that #222 is about.
#
# It selects the hook OBJECTS, not the command strings, which is the whole
# reason #259 could be fixed without a second selector: the timeout is a
# sibling key of `command`, so a selector that had already thrown the object
# away could not see it. Every projection below re-derives `.command` the same
# defensive way the select does, so a non-object element still cannot abort the
# read.
# shellcheck disable=SC2016
MATCHING_SELECT='[.hooks.SessionStart[]?.hooks[]?
      | select(((.command? // "") | tostring) as $c
          | ($m | any(. as $t | $c | contains($t))))]'

matching() {
  [ -f "$SETTINGS" ] || return 0
  have_jq || return 0
  jq -r --argjson m "$MARKERS_JSON" "$MATCHING_SELECT $1" \
      "$SETTINGS" 2>/dev/null || return 2
}

matching_commands() { matching '| map((.command? // "") | tostring) | .[]'; }

# One line per matching entry: the entry's `timeout`, or `-` where it carries
# none. A sentinel rather than a blank line, because "no timeout" and "no
# entries" are different answers and an empty projection cannot tell them apart
# — which is the same absent-vs-unanswerable split every other reader here
# already makes.
matching_timeouts() { matching '| map(.timeout? // "-" | tostring) | .[]'; }

# How many, not merely whether. --check said `yes` for one entry and for two, so
# a repo left holding a stranded duplicate — the state #222's group-scoped strip
# produced — read as healthy, while the hook ran once per entry every session.
# The reader already scanned every index; only the report threw the number away.
#
# Prints 0 rather than nothing when there is no settings.json or no jq, so the
# caller's arithmetic never sees an empty string; --check's have_jq branch runs
# before this value is used, so 0 is never mistaken for an answer.
matching_count() {
  local out rc=0
  out="$(matching '| length')" || rc=$?
  [ "$rc" -eq 0 ] || return 2
  printf '%s' "${out:-0}"
}

# The first match, for the callers that ask "is it registered at all" and
# "which FORM is it in" — an install predating the $CLAUDE_PROJECT_DIR form
# (#110) is cwd-relative and still a real registration.
hook_command() {
  local out rc=0
  out="$(matching_commands)" || rc=$?
  [ "$rc" -eq 0 ] || return 2
  printf '%s' "${out%%$'\n'*}"
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

# The timeout the registration ALREADY carries — the first matching entry that
# has one — or empty when none does, when nothing is registered, or when the
# file cannot be read. Empty is safe for all four: the caller falls back to
# whatever --timeout named, which is what a fresh install writes anyway.
#
# An `if`, not `[ "$line" = "-" ] && continue`: under set -e an AND-list that is
# the last statement in a loop body carries its failing test's status out of the
# body, which is the shape this file has been bitten by twice (#181).
existing_timeout() {
  local out line rc=0
  out="$(matching_timeouts)" || rc=$?
  [ "$rc" -eq 0 ] || return 0
  while IFS= read -r line; do
    if [ -n "$line" ] && [ "$line" != "-" ]; then
      printf '%s' "$line"
      return 0
    fi
  done <<EOF
$out
EOF
  return 0
}

# What this run will write: the value already there if there is one, else
# --timeout. PRESERVE beats prescribe, which is #259's actual finding — the
# dedupe-then-append rebuilt the entry from constants, so a consumer who added a
# timeout by hand (on this installer's own advice, in the per-repo issues) lost
# it to the next refresh, silently, and had no way to keep it short of not
# re-running the installer.
#
# The disagreement is REPORTED rather than resolved by precedence. Nothing here
# can tell a figure an operator chose from one a manifest supplied — both arrive
# as --timeout — so a rule that let the argument win would undo the repair again
# for the one caller that matters, and a rule that let it lose silently would
# freeze a raised default forever. Saying both numbers costs a line and leaves
# the choice where it belongs.
EFFECTIVE_TIMEOUT=""
resolve_timeout() {
  local existing
  existing="$(existing_timeout)"
  if [ -z "$existing" ]; then
    EFFECTIVE_TIMEOUT="$TIMEOUT"
    return 0
  fi
  EFFECTIVE_TIMEOUT="$existing"
  if [ -n "$TIMEOUT" ] && [ "$TIMEOUT" != "$existing" ]; then
    # err, not log: this is the one line that says the run deliberately ignored
    # an argument it was given, and every other log line is genuine progress.
    # Through log() it was suppressed by --quiet — and the quiet caller is the
    # automated one, least likely to notice the difference any other way.
    err "keeping the registered timeout of ${existing}s; this hook now prescribes"
    err "${TIMEOUT}s. A value already in $SETTINGS_REL is never overwritten (#259)"
    err "— edit it there, or --uninstall and re-install, if you want the new one."
  fi
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
#
# Against ALL the matches joined, so two entries can never compare equal to one
# — a duplicate is not the state a fresh install produces either.
#
# The timeout is compared too, against the RESOLVED value rather than the
# argument, so preserving an operator's differing figure still reads as
# unchanged. Comparing against $TIMEOUT instead would make every re-run on such
# a repo report "upgrading the registration" and rewrite the file to the same
# bytes — an idempotent tool that says it changed something is how a real change
# stops being noticed.
is_current() {
  [ "$(matching_commands)" = "$HOOK_COMMAND" ] &&
    [ "$(matching_timeouts)" = "${EFFECTIVE_TIMEOUT:--}" ]
}

# Resolves, not merely exists. A dangling symlink is the state doctor.sh exists
# to repair, and reporting it as installed here would send an operator looking
# anywhere but at the submodule.
is_linked() {
  [ -L "$HOOK" ] && [ -e "$HOOK" ]
}

if [ "$MODE" = "check" ]; then
  # Reported independently. The two are separate failure modes — a hook file
  # with no registration never runs, a registration with no file errors on every
  # session start — and gating the second report on the first hides whichever
  # one you were not looking for.
  rc=0
  if is_linked; then
    # SHAPE is checked on the resolving branch too (#233). Resolution proves
    # the content is here, not that the link survives anyone else's checkout:
    # an absolute target resolves on exactly the machine that wrote it and
    # dangles everywhere else — and until #233 the shape case below ran only
    # once the link was already dangling, so the one machine where the defect
    # is invisible was the one machine that got a green check. The 2026-08-27
    # cohort sweep found zero absolute hook symlinks across all twelve
    # consumers, so gating this turns nobody's working green red.
    #
    # A relative target that does not spell skills-vendor/ gets a second
    # reading before any verdict: resolved physically. The hooks this script
    # manages are installed as direct vendor links, but other installers
    # legitimately link through skills/ or .claude/skills/ indirection
    # (curating-context's context-budget-guard.sh), and those chains land in
    # the vendor tree — condemning them on spelling would misreport a correct
    # install if this script is ever pointed at such a hook. So on THIS
    # branch, where the chain can actually be walked, shape is judged by
    # where the link lands, not only by what it says. The dangling branch
    # cannot walk anything and keeps judging the spelling.
    link_target="$(readlink "$HOOK")"
    case "$link_target" in
      /*) link_shape="absolute" ;;
      *skills-vendor/*) link_shape="vendor" ;;
      *) link_shape="other" ;;
    esac
    if [ "$link_shape" = "other" ]; then
      case "$link_target" in
        */*) target_dir="${link_target%/*}" ;;
        *) target_dir="." ;;
      esac
      # Subshells, so the consumer's cwd survives; cd -P resolves every
      # directory-level symlink in the chain, which is where the indirection
      # lives. Compared against the PHYSICAL repo root — the repo itself may
      # be checked out through a symlinked path (macOS /tmp is one).
      resolved_dir="$(cd -- "${HOOK%/*}" 2>/dev/null \
        && cd -P -- "$target_dir" 2>/dev/null && pwd -P)" || resolved_dir=""
      root_phys="$(pwd -P)"
      case "$resolved_dir" in
        "$root_phys"/skills-vendor/*) link_shape="vendor" ;;
      esac
    fi
    case "$link_shape" in
      vendor)
        echo "hook symlink:       $HOOK_REL -> $link_target" ;;
      absolute)
        echo "hook symlink:       ABSOLUTE ($HOOK_REL) -> $link_target"
        echo "                    It resolves because this is the machine that"
        echo "                    wrote it; in every other checkout of this"
        echo "                    repo the link dangles. Re-run $RERUN."
        rc=3 ;;
      *)
        echo "hook symlink:       $HOOK_REL -> $link_target"
        echo "                    The target resolves, but not into"
        echo "                    skills-vendor/, so vendor refreshes never"
        echo "                    reach the file it names. Re-run $RERUN."
        rc=3 ;;
    esac
  elif [ -L "$HOOK" ]; then
    # SHAPE and RESOLUTION are different questions, and in a submodule-less
    # checkout they have different answers (#227). `actions/checkout` omits
    # skills-vendor/ deliberately (init-project-fastapi's github-ci.md says so)
    # and `git worktree add` never populates it, so every vendor symlink dangles
    # there — and a check that requires resolution calls a correct install
    # broken in exactly the place a consumer most wants to gate on it.
    #
    # Shape is checkable everywhere and is what carries the copy-vs-symlink
    # guarantee; resolution is only checkable where the content exists. So both
    # are reported, and --allow-unresolved accepts the second being unanswerable
    # WITHOUT relaxing the first.
    link_target="$(readlink "$HOOK")"
    echo "hook symlink:       DANGLING ($HOOK_REL) -> $link_target"
    case "$link_target" in
      /*) shape_ok=0 ;;
      *skills-vendor/*) shape_ok=1 ;;
      *) shape_ok=0 ;;
    esac
    if [ -n "$(vendored_src)" ]; then
      # The vendor IS checked out and the link still misses it, so "the content
      # is not here" is not the explanation and --allow-unresolved must not
      # pretend it is — that would make the flag mean "never mind the symlink".
      echo "                    A vendored $HOOK_NAME is present, so the link is"
      echo "                    pointing somewhere else. Re-run $RERUN."
      rc=3
    elif [ "$shape_ok" = "0" ]; then
      echo "                    The target is not a relative path into"
      echo "                    skills-vendor/, so no submodule checkout will"
      echo "                    resolve it. Re-run $RERUN."
      rc=3
    elif [ "$ALLOW_UNRESOLVED" = "1" ]; then
      echo "                    Shape is correct — a relative symlink into"
      echo "                    skills-vendor/ — and only the vendor content is"
      echo "                    absent. Accepted: --allow-unresolved."
    else
      echo "                    Shape is correct — a relative symlink into"
      echo "                    skills-vendor/ — and only the vendor content is"
      echo "                    absent. Routine in CI and in a fresh worktree:"
      echo "                    pass --allow-unresolved to accept it. Otherwise"
      echo "                    run .skills/doctor.sh, or"
      echo "                    git submodule update --init --recursive"
      rc=3
    fi
  elif [ -f "$HOOK" ]; then
    # A copy. .skills/doctor.sh cannot see this state at all — it scans for
    # DANGLING symlinks, and a copy is a perfectly valid regular file — so this
    # is the only probe that can report it (#179). Whether it is a defect
    # depends on whether there is anything to link at: with a vendored source
    # present the copy is drift a re-run repairs; without one it is the
    # documented fallback and nothing better is possible.
    echo "hook symlink:       COPY ($HOOK_REL) — frozen at install day;"
    if [ -n "$(vendored_src)" ]; then
      echo "                    upstream fixes never arrive. A vendored source"
      echo "                    exists, so re-run $RERUN to"
      echo "                    replace it with a symlink."
      rc=3
    elif [ "$ALLOW_UNRESOLVED" = "1" ]; then
      # The inversion --allow-unresolved exists to catch (#227). Where vendor
      # content may be absent, a copy is the one variant that RESOLVES — so
      # every resolution-based check passes on exactly the install #179 argues
      # against, and fails on the symlink this installer prescribes. The flag is
      # the caller saying absence is expected, which is precisely why absence
      # can no longer be read as "this repo vendors nothing to link at".
      echo "                    upstream fixes never arrive. --allow-unresolved"
      echo "                    says vendor content may be absent here, so a"
      echo "                    missing source is no longer evidence that this"
      echo "                    repo vendors none — and a copy is the one form"
      echo "                    that resolves in that state, so no resolution"
      echo "                    check can tell you this. Re-run $RERUN"
      echo "                    where the vendor tree is checked out."
      rc=3
    else
      echo "                    upstream fixes arrive only on a re-run of the"
      echo "                    installer. Expected: this repo vendors no"
      echo "                    skills-vendor/ tree to link at."
    fi
  else
    echo "hook symlink:       MISSING ($HOOK_REL)"
    rc=3
  fi
  # Read once, and keep the status: "not registered" and "could not tell" are
  # different answers and a probe people are told to trust must not merge them.
  mc_rc=0
  registered_n="$(matching_count)" || mc_rc=$?
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
  elif [ "$mc_rc" -ne 0 ]; then
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
  elif [ "$registered_n" -gt 1 ]; then
    # Reported, not merely counted. Two registrations run the hook twice every
    # session, and #222's group-scoped strip is how a repo arrived here without
    # anyone doing anything wrong.
    echo "SessionStart entry: $registered_n entries in $SETTINGS_REL — the hook is"
    echo "                    registered more than once, so it runs $registered_n times"
    echo "                    every session. Re-run $RERUN"
    echo "                    to collapse them to one."
    rc=3
  elif [ "$registered_n" -eq 1 ]; then
    echo "SessionStart entry: yes (1 entry in $SETTINGS_REL)"
    # Reported on its own line, because the two failures it stands between are
    # both invisible from the entry alone (#259). With no timeout the harness
    # default applies, and for a hook that stamps a once-per-day lock BEFORE
    # doing its work a kill consumes the day's attempt and reports nothing. With
    # a timeout that disagrees with this hook's prescription, the difference is
    # a choice someone made and this installer will keep.
    registered_timeout="$(existing_timeout)"
    if [ -z "$registered_timeout" ]; then
      echo "timeout:            none — the harness default applies"
      if [ -n "$TIMEOUT" ]; then
        echo "                    This hook prescribes ${TIMEOUT}s. Re-run $RERUN"
        echo "                    to add it; a re-run preserves it thereafter."
        rc=3
      fi
    elif [ -n "$TIMEOUT" ] && [ "$registered_timeout" != "$TIMEOUT" ]; then
      # Not rc=3. This installer PRESERVES the registered value, so there is
      # nothing here for a re-run to repair, and failing the check would push a
      # consumer toward deleting a deliberate local figure to get a green light.
      echo "timeout:            ${registered_timeout}s — this hook prescribes ${TIMEOUT}s."
      echo "                    Kept as-is: a re-run never overwrites a value"
      echo "                    already in $SETTINGS_REL. Edit it there to change it."
    else
      echo "timeout:            ${registered_timeout}s"
    fi
  elif [ -L "$HOOK" ] || [ -f "$HOOK" ]; then
    # The half-installed state this script exists for. Say what it costs, not
    # just what is absent — "MISSING" alone reads as cosmetic next to a hook
    # that is visibly right there.
    echo "SessionStart entry: MISSING — the hook is on disk but Claude Code never"
    echo "                    runs it, so whatever it maintains is frozen at"
    echo "                    whatever state it was in when the hook was"
    echo "                    installed. Re-run $RERUN."
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
  # registered", skipped the strip, and exited 0 having removed only the hook
  # file — an entry left running bash on a path that no longer exists, every
  # session start. A silent half-UNINSTALL, the mirror of the half-install this
  # script exists for (CR finding 7).
  #
  # Demanding jq up here rather than just before the strip means a machine that
  # cannot finish the job does not start it, so there is no partial state to
  # reason about at all — only "nothing happened, and here is why". Skipped
  # entirely when there is no settings.json, since then there is nothing to
  # strip and jq is not needed to remove a file.
  #
  # An unparseable settings.json is fatal for the same reason, and is checked
  # here rather than at the strip: jq cannot remove an entry from a file it
  # cannot read, and discovering that after the hook file is gone leaves exactly
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
    # $m is a jq variable bound by --argjson, not a shell one. shellcheck can
    # see that when the filter is an argument to `jq` itself; behind a wrapper
    # it cannot.
    # shellcheck disable=SC2016
    settings_rewrite "removed the SessionStart entry from $SETTINGS_REL" \
      --argjson m "$MARKERS_JSON" \
      "$STRIP_MATCHING"'if .hooks.SessionStart then
         .hooks.SessionStart |= strip_matching($m)
       else . end'
  fi
  log "not committed — review and commit with your normal gate."
  exit 0
fi

# --- install ---------------------------------------------------------------

SRC="$(vendored_src)"
MODE_WORD="linked"
if [ -z "$SRC" ] && [ "$COPY_FALLBACK" = "1" ]; then
  # The installer ships beside the skills it installs from, so its own sibling
  # tree is a real file rather than a path the caller was asked to substitute.
  # Only reached when there is nothing to link at: an absolute symlink into a
  # plugin cache would be committed and break on every other machine, so a copy
  # is the honest degradation.
  FALLBACK_SRC="$SELF_DIR/../../$SKILL/scripts/$HOOK_NAME"
  [ -f "$FALLBACK_SRC" ] || FALLBACK_SRC=""
  SRC="$FALLBACK_SRC"
  MODE_WORD="copied"
fi
[ -n "$SRC" ] || {
  err "no vendored $HOOK_NAME found under skills-vendor/*/skills/$SKILL/scripts/"
  # Both places that were looked in, when both were. A message naming only the
  # vendor glob would send someone to fix a submodule on a machine where the
  # copy source is what is actually absent.
  [ "$COPY_FALLBACK" = "0" ] || err "and none beside this installer at $SELF_DIR/../../$SKILL/scripts/"
  err "add the skills repo as a submodule first — see managing-skills/SKILL.md"
  exit 1; }

need_jq

# Validate the settings file BEFORE the hook file is written, mirroring the
# uninstall branch. Failing at the registration instead left the repo holding a
# symlink and no entry — the half-installed state this whole script exists to
# prevent — and printed it one line under `linked …`, so the run both created
# the state and reported it as nothing having happened (CR finding 14).
#
# A run that cannot finish must not start. Checked here rather than inside
# settings_rewrite because by then the hook file is already on disk.
if [ -f "$SETTINGS" ]; then
  hc_rc=0
  hook_command >/dev/null || hc_rc=$?
  [ "$hc_rc" -eq 0 ] || {
    err "$SETTINGS_REL is not valid JSON, so the SessionStart entry cannot be"
    err "written. Nothing was changed — fix the JSON and re-run."
    exit 1; }
fi

mkdir -p "$ROOT/.claude/hooks"
if [ "$MODE_WORD" = "copied" ]; then
  # rm first: cp FOLLOWS an existing symlink and writes its target, so copying
  # over a previously-linked hook would edit the vendored script instead of
  # replacing the link.
  rm -f "$HOOK"
  if ! cp "$SRC" "$HOOK"; then
    err "could not copy $HOOK_NAME into $HOOK_REL — nothing else was changed"
    exit 1
  fi
  chmod +x "$HOOK"
  log "copied $HOOK_REL from the installer's own tree — no skills-vendor/ to"
  log "link at, so it is FROZEN at today's version and .skills/doctor.sh cannot"
  log "see that (it scans for dangling symlinks). Re-run to refresh it."
else
  # Relative, and derived from the vendor directory that was actually found
  # rather than from a placeholder the caller was asked to substitute. The
  # <owner>-<repo> in SKILL.md's ln command is the kind of hand-substitution that
  # produces a symlink pointing at a plausible path which does not exist.
  # ../../ climbs out of .claude/hooks/ to the repo root.
  TARGET="../../$SRC"
  if is_linked && [ "$(readlink "$HOOK")" = "$TARGET" ]; then
    log "unchanged: $HOOK_REL already points at $SRC"
  else
    # -f so a re-run replaces a stale or dangling symlink — or a legacy
    # hand-typed copy — rather than failing.
    ln -sfn "$TARGET" "$HOOK"
    log "linked $HOOK_REL -> $SRC"
  fi
fi

[ -f "$SETTINGS" ] || { echo '{}' >"$SETTINGS"; log "created $SETTINGS_REL"; }

# After the file is guaranteed to exist and before is_current reads it: the
# resolved value is half of what "current" means.
resolve_timeout

if is_current; then
  log "unchanged: $SETTINGS_REL already registers the hook"
else
  # An `if`, not `is_registered && log ...` — doctor.sh carries the same note:
  # under set -e the && form leaves the statement's exit status at the failing
  # test, and this one fails on every fresh install.
  if is_registered; then
    log "upgrading the registration to the canonical command form (#110)"
  fi
  # Defensive in the two ways SKILL.md documents: it creates .hooks and
  # .hooks.SessionStart when absent, and it strips any pre-existing entry for
  # this hook before appending so a re-run cannot produce duplicates — which
  # also collapses a duplicate pair left by an earlier verbatim re-run of the
  # prose this script replaced.
  #
  # $CLAUDE_PROJECT_DIR, not the hook process's cwd (#110). Claude Code
  # normally runs hooks from the project dir, so the bare form works today, but
  # that is an undocumented assumption. The :-. fallback matters: with the
  # variable unset a bare "$CLAUDE_PROJECT_DIR/..." becomes "/.claude/hooks/..."
  # and errors on every session start, where "." degrades to the old behaviour.
  #
  # $t is the resolved timeout, or JSON null when neither the caller nor the
  # entry being replaced named one. `null` and not 0: absent means "the harness
  # default applies", which is a real state a consumer may want, and writing a
  # number for it would invent a policy nobody chose.
  #
  # $m, $cmd and $t are jq variables bound by --argjson/--arg, not shell ones —
  # see the matching note on the uninstall rewrite.
  # shellcheck disable=SC2016
  settings_rewrite "registered the SessionStart entry in $SETTINGS_REL" \
    --argjson m "$MARKERS_JSON" --arg cmd "$HOOK_COMMAND" \
    --argjson t "${EFFECTIVE_TIMEOUT:-null}" \
    "$STRIP_MATCHING"'(.hooks //= {}) |
     (.hooks.SessionStart //= []) |
     .hooks.SessionStart |= strip_matching($m) |
     .hooks.SessionStart += [{
       "matcher": ".*",
       "hooks": [
         {
           "type": "command",
           "command": $cmd
         }
         | if $t == null then . else .timeout = $t end
       ]
     }]'
fi

if [ "$QUIET" != "1" ]; then
  # BOTH paths named, because staging one of the two artifacts is how a repo
  # ends up committing a hook nothing registers — the #167 state, reached from
  # a correct install.
  cat <<NEXT

Not committed — review and commit with your normal gate. BOTH artifacts:
  git add $HOOK_REL $SETTINGS_REL
  git commit -m "chore: install the ${HOOK_NAME%.sh} hook"
NEXT
  [ -z "$NOTE" ] || printf '\n%s\n' "$NOTE"
fi
