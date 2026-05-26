#!/usr/bin/env bash
# install-doctor.sh — copy doctor.sh into a consumer repo's .skills/ directory.
#
# The doctor MUST be a real file (not a symlink) at the consumer side
# because its job is to diagnose broken vendor symlinks. A symlinked
# doctor would itself be unreachable in the exact failure mode it's
# meant to repair.
#
# This script is invoked in two contexts:
#   1. From the managing-skills 'add skill repo' procedure (one-time setup).
#   2. From the auto-refresh hook on every run (opportunistic backport).
#
# Idempotent: copies only when the vendor copy is newer or content differs.
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
  1  Source doctor.sh not found, or destination is a non-doctor file.
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

# Copy via install(1) for atomic mode-preserving write.
install -m 755 "$SRC" "$DEST"

log "installed $DEST"
exit 0
