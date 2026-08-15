#!/usr/bin/env bash
# managing-skills-doctor: do not remove this marker — install-doctor.sh greps it
# doctor.sh — diagnose and self-heal dangling skill and hook symlinks.
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
# vendor chain is broken. It walks skills/* and .claude/hooks/* symlinks,
# attempts a `git submodule update --init --recursive` if any dangle, and
# prints a clear actionable error if self-healing fails.
#
# .claude/hooks/ is in scope because skill installers link hooks there too
# (issue #99). A dangling skills/<name> surfaces only when that skill is
# invoked; a dangling hook symlink surfaces on every Edit|Write|MultiEdit —
# the highest-frequency tool event there is — as exit 127 naming a path that
# `ls` plainly shows exists. Same failure class, different directory, and one
# heal path covers any future hook a skill installs.
#
# Because the installed copy is a copy, it re-syncs itself from the vendored
# source whenever that source is reachable — see sync_self below.
#
# Designed for use as a Phase 1 preflight in every reviewing-* / shipping-*
# SKILL.md invocation. The doctor runs first so that the resolution loop that
# follows sees a freshly healed symlink chain (issue #63):
#
#   { [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
#   for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
#     [ -f "$d/$S" ] && { SD="$d"; break; }
#   done
#   bash "$SD/$S"
#
# Usage: bash .skills/doctor.sh [--check-only] [--verbose] [--no-preflight] [--help]
set -euo pipefail

# Diagnostic stamp only — reported by --version so a bug report can name the
# copy that produced it. Nothing branches on it: sync_self keeps the installed
# copy equal to the vendored source, which makes drift transient and a
# version-comparison mechanism unnecessary.
VERSION="2026-08-14-1"

CHECK_ONLY=0
VERBOSE=0
NO_PREFLIGHT=0
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=1 ;;
    --verbose|-v) VERBOSE=1 ;;
    --no-preflight) NO_PREFLIGHT=1 ;;
    --version) echo "$VERSION"; exit 0 ;;
    --help|-h)
      cat <<EOF
Usage: bash .skills/doctor.sh [--check-only] [--verbose] [--no-preflight]

Diagnose and self-heal dangling symlinks in skills/ and .claude/hooks/.

If any symlink in those directories does not resolve and a .git directory
is present, runs 'git submodule update --init --recursive' and re-checks.
Exits 0 silently when healthy. Exits non-zero with an actionable error
when self-healing fails or is not possible (e.g. no .git directory).

.claude/hooks/ is scanned because skill installers link hooks there into
the same vendor chain; a dangling one fails on every file edit rather than
only when a skill is invoked.

Re-syncs .skills/doctor.sh from the vendored source under skills-vendor/
when the two differ, so upstream fixes reach consumers that did not
install the auto-refresh hook. Best-effort — never affects the exit code;
failures are reported only under --verbose. The refresh applies from the
following run. Skipped entirely under --check-only, which makes no writes.

When submodule init fails with a well-known SSH/HTTPS auth signature
(Permission denied, Could not read from remote repository, Authentication
failed for 'https://'), a targeted remediation block is printed instead
of the generic 'submodule update failed' line. The same block is printed
by the pre-flight SSH check when .gitmodules references SSH remotes and
the agent isn't reachable from this shell. A separate remediation block
covers host-key-verification failures (ssh-keyscan-based fix).

Options:
  --check-only    Report broken symlinks but make no changes: no submodule
                  init, no self-sync. (The archive-checkout path when .git
                  is absent overrides the reporting, printing its own
                  diagnosis — it makes no changes either.)
  --no-preflight  Skip the SSH pre-flight ping. Useful when the operator
                  knows the agent state and doesn't want the 3-second
                  ConnectTimeout on every invocation.
  --verbose, -v   Print resolution details even when healthy.
  --version       Print the script's diagnostic version stamp and exit.
  --help, -h      Show this help and exit.

Exit codes:
  0  All scanned symlinks resolve (or neither directory exists).
  1  One or more symlinks remain broken after self-heal attempt, or
     pre-flight SSH check failed.
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

# Re-sync the installed copy of this script from the vendored source.
#
# The doctor is installed as a real file rather than a symlink so it stays
# reachable when the vendor submodule is uninitialized — the exact state it
# exists to repair. The cost of that choice is drift: upstream fixes reach a
# consumer only when something re-runs install-doctor.sh. The auto-refresh
# hook does that each session, but consumers that declined the hook would
# otherwise run a stale doctor indefinitely (issue #84). Since every
# reviewing-* / shipping-* preflight invokes the doctor, this is the one code
# path guaranteed to run in a hook-less consumer.
#
# The vendored copy is authoritative and CONTENT decides, not mtime. Git sets
# mtimes at checkout time, so a freshly-initialized submodule always looks
# "newer" and a deliberate submodule rollback always looks "older" — an mtime
# comparison misfires in both directions. Content equality also gives pinning
# the right semantics: a consumer pinned to an older submodule gets that
# older doctor, which is what pinning means.
#
# Wholly best-effort. A missing vendor, a missing installer, a destination
# the installer refuses to clobber, or a failed copy must all leave this
# script's exit code untouched: Phase 1 preflights invoke the doctor with
# `|| exit 1`, so a self-sync failure would otherwise block a review over
# something cosmetic.
sync_self() {
  # --check-only is contractually non-mutating — it is the mode a CI health
  # probe reaches for, and .skills/doctor.sh is a tracked file, so a write
  # here would dirty the working tree and trip a `git diff --exit-code`
  # cleanliness gate on the next submodule bump, with nothing connecting the
  # failure back to the bump.
  if [ "$CHECK_ONLY" = "1" ]; then
    return 0
  fi

  local self="$ROOT/.skills/doctor.sh"
  # Only refresh an already-installed doctor — never create one. Installation
  # is Step 2c's job (and the hook's); a preflight shouldn't materialize files
  # the operator didn't ask for. In the preflight path this always exists,
  # since that path tests `-x .skills/doctor.sh` before invoking us.
  [ -f "$self" ] || return 0

  local src installer out rc
  # First matching vendor wins, matching skills-submodule-update.sh's `break`.
  # When skills-vendor/ is absent the glob stays unexpanded and the -f test
  # rejects the literal string, so the loop falls through to `return 0`.
  for src in skills-vendor/*/skills/managing-skills/scripts/doctor.sh; do
    [ -f "$src" ] || continue
    if cmp -s "$src" "$self"; then
      return 0
    fi
    installer="$(dirname "$src")/install-doctor.sh"
    [ -f "$installer" ] || return 0

    # Capture rather than discard. A permanently-failing sync is otherwise
    # invisible: a consumer with a user-authored file at .skills/doctor.sh
    # can never receive doctor updates, and the installer's precise
    # explanation of why would go to /dev/null on every preflight forever.
    # Surfaced only under --verbose so the default path stays quiet.
    # `--quiet` means a successful run produces no output, so `out` is
    # non-empty only when something went wrong.
    rc=0
    out="$(bash "$installer" --quiet 2>&1)" || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "doctor: refreshed .skills/doctor.sh from $src — the update applies from the next run" >&2
    elif [ "$VERBOSE" = "1" ]; then
      echo "doctor: self-sync failed (rc=$rc); the installed copy is unchanged:" >&2
      printf '%s\n' "$out" >&2
    fi
    return 0
  done
  return 0
}

# Call site 1 of 2: the healthy path exits early a few lines below, which is
# the overwhelming majority of invocations. A self-sync placed after the heal
# logic would almost never run.
sync_self

# The auto-refresh hook's contract is TWO artifacts — the symlink and the
# SessionStart registration in .claude/settings.json — and only the second one
# makes it run. A repo carrying the symlink without the registration looks
# installed to anyone who lists .claude/hooks/ and refreshes nothing, so its
# vendored skills freeze at whatever commit they were on.
#
# Four of twelve audited consumers were in exactly that state, pinned at one
# commit for over a week while the rest of the cohort moved through four skill
# versions (#167). Nothing detected it, because a half-installed hook is silent
# by construction: the missing half is the half that would have run.
#
# Reported HERE, for the same reason sync_self lives here — the doctor is the
# one code path that still runs in a repo whose refresh hook does not, whether
# through a reviewing-*/shipping-* preflight or a SessionStart entry of its
# own. Warn only; a wiring gap is not a dangling symlink and must not change
# this script's exit code, which Phase 1 preflights gate on with `|| exit 1`.
#
# Only when the symlink is present: that is what distinguishes "somebody
# installed this and it half-landed" from "this consumer never wanted the
# hook", and nagging the second group trains everyone to ignore the first.
check_refresh_registration() {
  local hook=".claude/hooks/skills-submodule-update.sh"
  local settings=".claude/settings.json"
  [ -L "$hook" ] || return 0
  # NOT `[ -f "$settings" ] || return 0`. No settings.json at all is the
  # strongest form of unregistered, so it must fall through to the warning
  # rather than out of the function — an early return there made the doctor
  # silent on the plainest half-install there is.
  #
  # Scoped to .hooks.SessionStart[].hooks[].command, not a grep over the file.
  # The basename appears in settings.json for reasons that are not
  # registrations — a `permissions.allow` entry naming the hook is the common
  # one — and a whole-file grep counted those, so this warning stayed silent on
  # exactly the half-installed repos it was added for (CR finding 1).
  #
  # No jq, no warning. The doctor is advisory and runs on every session start,
  # so a wrong warning is worse than none: it would fire in every consumer
  # without jq, including correctly-installed ones, and train the reader to
  # ignore the message. install-refresh.sh --check reports UNKNOWN in that case,
  # which is the right place for a demand that jq be installed.
  command -v jq >/dev/null 2>&1 || return 0
  if [ -f "$settings" ] && jq -e '[.hooks.SessionStart[]?.hooks[]?.command // ""]
            | any(contains("skills-submodule-update.sh"))' \
       "$settings" >/dev/null 2>&1; then
    return 0
  fi
  echo "doctor: $hook is installed but $settings does not register it," >&2
  echo "doctor: so the auto-refresh hook never runs and this repo's vendored" >&2
  echo "doctor: skills stay frozen at their current commit. Repair with:" >&2
  # Resolved here rather than printed as a glob. `bash skills-vendor/*/…` passes
  # every extra match as an argument to the first, and install-refresh.sh
  # rejects unknown arguments — so the paste-under-pressure path would fail on
  # any repo vendoring a second skills repo.
  local installer
  for installer in skills-vendor/*/skills/managing-skills/scripts/install-refresh.sh; do
    [ -f "$installer" ] || continue
    echo "doctor:   bash $installer" >&2
    return 0
  done
  echo "doctor:   bash <vendor>/skills/managing-skills/scripts/install-refresh.sh" >&2
  return 0
}

check_refresh_registration

# Directories whose direct children are scanned for dangling symlinks.
# skills/ is the vendored-skill chain; .claude/hooks/ holds the hook symlinks
# skill installers write into a consumer (issue #99). .claude/skills/ needs no
# entry — it links through skills/<name>, so a break there is already reported
# at its source rather than twice.
SCAN_DIRS=(skills .claude/hooks)

# An `if`, not `[ -d "$d" ] && present=1` — under `set -e` the && form makes the
# loop's exit status that of the last test, so a run whose final scan dir is
# absent would abort the script instead of reporting.
present=0
for d in "${SCAN_DIRS[@]}"; do
  if [ -d "$d" ]; then
    present=1
  fi
done

# Nothing to check if the consumer uses none of those patterns.
if [ "$present" -eq 0 ]; then
  [ "$VERBOSE" = "1" ] && echo "doctor: no skills/ or .claude/hooks/ directory — nothing to check" >&2
  exit 0
fi

# BROKEN is the output channel of scan_broken — declared at top scope so the
# function's communication pattern is visible without reading every call
# site. Using an array (rather than a single string) preserves
# paths-with-spaces correctly when later expanded as "${BROKEN[@]}".
declare -a BROKEN=()

# Walks each SCAN_DIRS entry and populates BROKEN with any dangling symlinks.
# A symlink is "broken" when it exists but its target does not resolve. Local
# overrides (regular directories) and project-authored hook scripts (regular
# files) are skipped — they're not symlinks.
scan_broken() {
  BROKEN=()
  local dir entry
  for dir in "${SCAN_DIRS[@]}"; do
    [ -d "$dir" ] || continue
    for entry in "$dir"/*; do
      [ -L "$entry" ] || continue
      if [ ! -e "$entry" ]; then
        BROKEN+=("$entry")
      fi
    done
  done
}

scan_broken

if [ "${#BROKEN[@]}" -eq 0 ]; then
  [ "$VERBOSE" = "1" ] && echo "doctor: all scanned symlinks resolve" >&2
  exit 0
fi

# At least one dangling symlink. Distinguish archive-checkout (no .git) from
# the normal git-submodule case before either self-healing or reporting,
# so --check-only never suggests a `git submodule` command in a checkout
# that doesn't have a .git dir.
if [ ! -d .git ] && [ ! -f .git ]; then
  echo "doctor: dangling symlinks detected and no .git directory present:" >&2
  printf '  %s\n' "${BROKEN[@]}" >&2
  echo "" >&2
  echo "This checkout was likely created from a source archive (zip/tarball)" >&2
  echo "rather than 'git clone'. The submodule pattern this repo uses is not" >&2
  echo "compatible with archive downloads. Clone with --recurse-submodules" >&2
  echo "instead, or vendor the skill scripts manually." >&2
  exit 1
fi

if [ "$CHECK_ONLY" = "1" ]; then
  echo "doctor: dangling symlinks detected:" >&2
  printf '  %s\n' "${BROKEN[@]}" >&2
  echo "Run 'git submodule update --init --recursive' to repair." >&2
  exit 1
fi

# Targeted remediation printed when an auth failure is detected — either by
# the pre-flight ping below or by classifying submodule init's stderr.
# Kept generic across hosts (github.com is the dominant case but we don't
# hard-code it in the message) and explicit about each layer the user
# might need to fix: agent reachable, key loaded, agent visible to
# subprocesses, fallback to HTTPS.
print_ssh_remediation() {
  cat >&2 <<'EOF'

doctor: the auth check above failed — auth to one of the submodule
remotes was refused. Common causes (and fixes):

  1. SSH agent not reachable from this shell.
       ssh-add -l
     "Error connecting to authentication agent" → start the agent and
     re-add keys.

  2. Agent has no identities loaded.
     Add the default key (macOS keychain integration):
       ssh-add --apple-use-keychain ~/.ssh/id_ed25519
     (adjust the key path if yours isn't id_ed25519 — `ls ~/.ssh/id_*`
     shows what's available.)
     And persist via ~/.ssh/config so the key auto-loads:
       Host github.com
         AddKeysToAgent yes
         UseKeychain yes
         IdentityFile ~/.ssh/id_ed25519

  3. Auth works in your terminal but not from a wrapper script.
       ssh -T git@github.com
     If that succeeds interactively but fails here, a wrapper in the
     chain (e.g. dev.sh) is scrubbing SSH_AUTH_SOCK from the env.

  4. Public submodule, no SSH credentials available.
     Force HTTPS for github.com globally (affects ALL repos on this
     machine — use only if you understand the scope):
       git config --global url."https://github.com/".insteadOf "git@github.com:"

EOF
}

# Companion remediation for the host-key-verification failure path. Surfaced
# when the pre-flight ping under StrictHostKeyChecking=yes is rejected
# because the remote's host key isn't in ~/.ssh/known_hosts. The agent
# remediation above doesn't apply here — the operator just needs to trust
# the host key.
print_host_key_remediation() {
  cat >&2 <<'EOF'

doctor: SSH refused to talk to one of the submodule remotes because its
host key isn't in ~/.ssh/known_hosts. Trust the host key (verify the
fingerprint against the forge's published list first):

  ssh-keyscan github.com >> ~/.ssh/known_hosts

GitHub publishes its current host-key fingerprints at
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints —
compare the ssh-keyscan output before appending. For other forges, check
their docs for the equivalent.

EOF
}

# Pre-flight: when .gitmodules references SSH remotes, verify SSH auth to
# each referenced host before attempting submodule init. Catches the
# common "agent not reachable / key not loaded" case with a clean
# message instead of letting submodule init produce a wall of clone
# errors. Skipped when .gitmodules is HTTPS-only or absent, and skippable
# entirely with --no-preflight.
preflight_ssh_check() {
  [ "$NO_PREFLIGHT" = "1" ] && return 0
  [ -f .gitmodules ] || return 0

  # Extract unique host names from SSH-style submodule URLs:
  #   url = git@<host>:<path>
  #   url = ssh://git@<host>[:<port>]/<path>
  local hosts
  hosts="$(awk '
    /^[[:space:]]*url[[:space:]]*=[[:space:]]*git@/ {
      # url = git@host:path → split on @ and :
      sub(/^[^@]*@/, "", $0); sub(/:.*$/, "", $0); print
    }
    /^[[:space:]]*url[[:space:]]*=[[:space:]]*ssh:\/\/git@/ {
      # url = ssh://git@host[:port]/path → strip scheme+user, then host
      sub(/^.*@/, "", $0); sub(/[:\/].*$/, "", $0); print
    }
  ' .gitmodules | sort -u)"
  [ -n "$hosts" ] || return 0

  local host out failed=0
  local -a auth_failed=()
  local -a hostkey_failed=()
  for host in $hosts; do
    # GitHub (and most forges) return exit 1 even on successful auth
    # because there's no shell to allocate ("PTY allocation request
    # failed" / "successfully authenticated"). The reliable signal is in
    # the output, not the exit code. Two failure modes worth
    # distinguishing:
    #
    #   - "Permission denied (...)" — auth refused. The parenthesized
    #     methods vary by server config (publickey / password /
    #     publickey,password,keyboard-interactive / etc.), so we match
    #     on the open-paren form to catch all variants without false-
    #     positiving on banners that happen to contain the literal
    #     string "Permission denied".
    #   - "Host key verification failed" — server's host key isn't in
    #     known_hosts. We run with StrictHostKeyChecking=yes
    #     deliberately: the alternative (accept-new) silently expands
    #     the operator's known_hosts on first contact, which is a
    #     security choice this script shouldn't make on the operator's
    #     behalf. BatchMode=yes prevents the script from hanging on the
    #     interactive trust prompt.
    #
    # Other failures (DNS, timeout, network) are not classified — we
    # don't want false positives that block valid retries on flaky
    # network conditions.
    out="$(ssh -T -o BatchMode=yes -o ConnectTimeout=3 \
              -o StrictHostKeyChecking=yes "git@${host}" 2>&1 || true)"
    if printf '%s\n' "$out" | grep -qE "Permission denied \("; then
      auth_failed+=("$host")
      failed=1
    elif printf '%s\n' "$out" | grep -qi "Host key verification failed"; then
      hostkey_failed+=("$host")
      failed=1
    fi
  done

  if [ "$failed" -eq 1 ]; then
    if [ "${#auth_failed[@]}" -gt 0 ]; then
      echo "doctor: SSH pre-flight failed — agent cannot authenticate to: ${auth_failed[*]}" >&2
      print_ssh_remediation
    fi
    if [ "${#hostkey_failed[@]}" -gt 0 ]; then
      echo "doctor: SSH pre-flight failed — host key not trusted for: ${hostkey_failed[*]}" >&2
      print_host_key_remediation
    fi
    return 1
  fi
  return 0
}

if ! preflight_ssh_check; then
  exit 1
fi

echo "doctor: dangling symlinks detected — initializing submodules..." >&2

# Capture stderr for post-hoc classification while also streaming it live
# so the user sees git's output during slow clones. We use a named pipe
# (fifo) + explicit-backgrounded tee with a known PID instead of the
# more compact `2> >(tee … >&2)` process-substitution form: bash 3.2
# (the default on macOS without Homebrew) does not track process
# substitutions in the jobs table, so `wait` can't reliably reap the
# tee, leaving a microsecond-wide race between tee's final flush and
# our grep. A real backgrounded job with `wait "$TEE_PID"` works on
# every bash from 3.2 onward. Both temp paths live inside a single
# mktemp -d directory so the trap can `rm -rf` once.
SUBMODULE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/doctor-submodule.XXXXXX")"
# Install the cleanup trap before any further setup that could fail (mkfifo,
# tee &) so a partial-init failure still removes the tempdir.
trap 'rm -rf "$SUBMODULE_TMP"' EXIT
SUBMODULE_FIFO="$SUBMODULE_TMP/stderr"
SUBMODULE_ERR="$SUBMODULE_TMP/captured"
mkfifo "$SUBMODULE_FIFO"

tee "$SUBMODULE_ERR" < "$SUBMODULE_FIFO" >&2 &
TEE_PID=$!

RC=0
# When git exits, the fifo write side closes; tee reads EOF and exits.
git submodule update --init --recursive 2>"$SUBMODULE_FIFO" || RC=$?
# `|| true` so a non-zero tee exit (e.g., write error) doesn't trip set -e.
wait "$TEE_PID" || true

if [ "$RC" -ne 0 ]; then
  # Match the open-paren form of SSH auth refusal so we catch every
  # variant (publickey / password / publickey,password,keyboard-interactive
  # / ...). HTTPS auth has its own signature unrelated to SSH; "Could not
  # read from remote repository" appears for both SSH and HTTPS clone
  # failures rooted in auth.
  if grep -qE "Permission denied \(|Could not read from remote repository|Authentication failed for 'https://" "$SUBMODULE_ERR"; then
    print_ssh_remediation
  else
    echo "doctor: 'git submodule update --init --recursive' failed" >&2
  fi
  exit 1
fi

# Call site 2 of 2: the vendor tree may have only just become readable — call
# site 1 ran before the init and would have found nothing to sync against.
sync_self

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

[ "$VERBOSE" = "1" ] && echo "doctor: self-healed; all scanned symlinks resolve" >&2
exit 0
