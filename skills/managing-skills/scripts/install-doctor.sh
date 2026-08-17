#!/usr/bin/env bash
# install-doctor.sh — copy doctor.sh into a consumer repo's .skills/ directory.
#
# The doctor MUST be a real file (not a symlink) at the consumer side
# because its job is to diagnose broken vendor symlinks. A symlinked
# doctor would itself be unreachable in the exact failure mode it's
# meant to repair.
#
# This script is invoked in three contexts:
#   1. From the managing-skills 'add skill repo' procedure (one-time setup).
#   2. From the auto-refresh hook on every run (opportunistic backport).
#   3. From doctor.sh's own sync_self, which re-syncs the installed copy
#      from the vendored source on every doctor run (issue #84). That means
#      this script routinely rewrites a doctor.sh that is executing right
#      now — see the write step at the bottom for why the rename matters.
#
# Idempotent: copies only when content differs — never mtime. Git stamps
# checkout times, so an mtime test misreads both a freshly-initialized
# submodule (always looks "newer") and a deliberate rollback ("older").
# Refuses to overwrite an existing .skills/doctor.sh that does not look
# like a doctor (header check), so user-authored files at that path
# cannot be silently clobbered.
#
# Usage: bash install-doctor.sh [--quiet] [--help]
set -euo pipefail

QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet|-q) QUIET=1 ;;
    --help|-h)
      cat <<EOF
Usage: bash <vendor>/managing-skills/scripts/install-doctor.sh [--quiet]

Copies doctor.sh from the vendor location into <consumer-root>/.skills/doctor.sh.
Idempotent — no-op if the destination already matches the source.

Options:
  --quiet, -q   Suppress 'installed' / 'updated' messages (errors still print).
  --help, -h    Show this help and exit.

Exit codes:
  0  Success (installed, updated, or no-op).
  1  Source doctor.sh not found, or the destination is a non-doctor file
     or not a regular file at all (e.g. a directory).
EOF
      exit 0
      ;;
  esac
done

log() { [ "$QUIET" = "1" ] || echo "install-doctor: $*"; }
err() { echo "install-doctor: $*" >&2; }

# Source: doctor.sh lives next to this script.
SRC="$(cd "$(dirname "$0")" && pwd)/doctor.sh"
if [ ! -f "$SRC" ]; then
  err "source doctor.sh not found at $SRC"
  exit 1
fi

# Destination: consumer repo root. The consumer's repo root is whichever
# directory contains skills-vendor/ — but since install-doctor.sh is invoked
# from inside the consumer's checkout, the CWD is authoritative. Fall back
# to git rev-parse for robustness when invoked from a subdirectory.
DEST_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DEST_DIR="$DEST_ROOT/.skills"
DEST="$DEST_DIR/doctor.sh"

mkdir -p "$DEST_DIR"

# Sweep temp files orphaned by a hard kill — SIGKILL and machine loss both
# bypass the EXIT trap installed further down. Runs before the no-op check so
# orphans are still collected on runs that have nothing to install. The age
# floor is what makes this safe: a concurrent installer's in-flight temp file
# is minutes old at most, so it can never be swept out from under it.
#
# stderr is deliberately NOT silenced. `|| true` already makes this
# non-blocking, so a find that fails for an unexpected reason (permissions,
# an exotic filesystem) costs nothing by printing — whereas swallowing it
# would make "swept nothing" and "could not look" indistinguishable.
find "$DEST_DIR" -maxdepth 1 -name '.doctor.sh.tmp.*' -mmin +1440 -delete || true

# Refuse a destination that exists but is not a regular file — in practice a
# directory. Every check below is `[ -f "$DEST" ]`, so such a path falls through
# all of them, and then SURVIVES the write: `mv -f "$TMP" "$DEST"` moves the temp
# file *into* a directory and exits 0. The installer printed `installed …
# /.skills/doctor.sh` and exited 0 with the doctor stranded inside under its temp
# name, which the auto-refresh hook and sync_self both read as success (#181).
#
# `-f` is true through a symlink to a file, so the case the doctor exists to
# repair — a symlinked .skills/doctor.sh, which mv then replaces with a real
# file — is deliberately not caught here.
if [ -e "$DEST" ] && [ ! -f "$DEST" ]; then
  err "refusing to write $DEST — it exists and is not a regular file"
  err "remove it manually if you want to install the doctor"
  exit 1
fi

# If destination exists and isn't recognizably a doctor, refuse to clobber.
# Grep for the stable marker comment that doctor.sh carries near the top of
# the file (intentionally orthogonal to the wording of the doctor's intro
# paragraph, which is allowed to change).
if [ -f "$DEST" ] && ! head -n 3 "$DEST" | grep -q '^# managing-skills-doctor:'; then
  err "refusing to overwrite $DEST — file exists and is not a managing-skills doctor"
  err "remove the file manually if you want to install the doctor"
  exit 1
fi

# No-op if content already matches.
if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
  log "no-op (already up to date)"
  exit 0
fi

# Write to a temp file in the destination directory, then rename into place.
#
# The destination may be executing right now: doctor.sh re-syncs itself from
# the vendored source (sync_self), and the SessionStart hook can fire while a
# preflight-invoked doctor is mid-run. Bash reads a script incrementally from
# an open fd, so a truncating in-place write makes the running instance resume
# at a byte offset into new content and execute garbage. rename(2) is atomic
# within a filesystem and leaves the running instance holding the old inode,
# which it reads to completion undisturbed.
#
# `install -m 755` is NOT a safe substitute here: BSD install (macOS) renames,
# but GNU coreutils install opens the destination O_TRUNC. Consumers run both.
TMP="$DEST_DIR/.doctor.sh.tmp.$$"
# Trap covers the window between cp and mv; after a successful mv the rm is a
# harmless no-op on a path that no longer exists.
trap 'rm -f "$TMP"' EXIT
cp "$SRC" "$TMP"
chmod 755 "$TMP"
mv -f "$TMP" "$DEST"

log "installed $DEST"
exit 0
