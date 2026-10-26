#!/usr/bin/env bash
# remove-disk-gc.sh — take the canonical disk GC off a host, as the
# contract says (#425).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash remove-disk-gc.sh [--approve] [--even-modified] [--root DIR]
                              [--systemctl CMD]

Removes the canonical disk GC the installed MANIFEST describes. Without
--approve it prints the plan and changes nothing. With it, as root:

  1. systemctl disable --now cannobserv-disk-gc.timer
     cannobserv-disk-headroom.timer, then systemctl stop of both services,
     so a run in progress doesn't outlive its files
  2. each file MANIFEST lists
  3. systemctl daemon-reload, and systemctl restart systemd-journald when
     a journald.conf.d drop-in went
  4. MANIFEST, last, then the GC's directory if that leaves it empty. Until
     MANIFEST goes, a re-run finds what is left and finishes the job

It keeps the host's /etc/cannobserv/disk-gc/ (disk-gc.conf, checkin.key),
the GC's state in /var/lib/cannobserv-disk-gc/, and any file MANIFEST
doesn't list. Ask for the co-status monitor to be disabled too: with the
sensor gone, it pages "has stopped reporting".

It refuses (exit 3) before anything changes when MANIFEST names a path
outside usr/local/lib/ or isn't in sha256sum's format, when a path it would
remove is (or sits under) a symlink, when --approve is given for / without
root, and when a listed file differs from its MANIFEST hash: someone edited
it. --even-modified removes edited files anyway.

Options:
  --approve         the owner's approval, given in the host's own session
  --even-modified   remove files that differ from MANIFEST too
  --root DIR        remove under DIR instead of / (a scratch root); systemctl
                    isn't called unless --systemctl names one
  --systemctl CMD   the systemctl to call (default: systemctl, under / only)
  -h, --help        show this help

Output (stdout, JSON): ok, action (remove, or absent when no MANIFEST is
installed), applied, root, files, modified, missing, kept, journald_restart,
systemctl, systemctl_ran, refused, failed.

Exit codes:
  0  planned, done, or nothing installed
  1  failed part-way, and failed says where
  2  usage
  3  refused: nothing changed
USAGE
}

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_manifest-lib.sh
. "$HERE/_manifest-lib.sh"

ROOT=/ APPROVE=0 EVEN_MODIFIED=0 SYSTEMCTL="" RUN_SYSTEMCTL=0
usage_error() { echo "remove-disk-gc: $1" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --root | --systemctl)
      [ $# -ge 2 ] || usage_error "$1 needs a value"
      if [ "$1" = --root ]; then ROOT=$2; else SYSTEMCTL=$2 RUN_SYSTEMCTL=1; fi
      shift 2
      ;;
    --approve) APPROVE=1; shift ;;
    --even-modified) EVEN_MODIFIED=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done
for v in "$ROOT" "$SYSTEMCTL"; do
  [[ $v =~ ^[A-Za-z0-9._+@/-]*$ ]] || usage_error "$v: paths may hold only [A-Za-z0-9._+@/-]"
done
[ -d "$ROOT" ] || usage_error "$ROOT is not a directory"
ROOT=$(canon_dir "$ROOT")
R=${ROOT%/}
if [ "$ROOT" = / ] && [ -z "$SYSTEMCTL" ]; then SYSTEMCTL=systemctl RUN_SYSTEMCTL=1; fi
if [ "$APPROVE" = 1 ] && [ "$ROOT" = / ] && [ "$(id -u)" != 0 ]; then
  refuse "removing from / needs root"
fi

ACTION=remove APPLIED=false FAILED_WHY="" JRESTART=0
PATHS=() MODIFIED=() MISSING=()
KEPT=("etc/cannobserv/disk-gc/" "var/lib/cannobserv-disk-gc/")
I_MAN=$R/$MANIFEST_REL
no_symlink_under "$R" "$MANIFEST_REL"
if [ ${#REFUSED[@]} -eq 0 ] && [ ! -e "$I_MAN" ]; then
  ACTION=absent
elif [ ${#REFUSED[@]} -eq 0 ]; then
  read_manifest "$I_MAN" installed
  PATHS=(${M_PATHS[@]+"${M_PATHS[@]}"})
  for i in ${PATHS[@]+"${!PATHS[@]}"}; do
    p=${PATHS[$i]}
    no_symlink_under "$R" "$p"
    h=$(hash_of "$R/$p")
    if [ "$h" = absent ]; then
      [ ! -e "$R/$p" ] || refuse "$p is not a regular file on the root"
      MISSING+=("$p")
    elif [ "$h" != "${M_HASHES[$i]}" ]; then
      MODIFIED+=("$p")
    fi
    # From the marker, not the disk: a run that removed the drop-in but
    # stopped before the restart left it already absent.
    case "$p" in "$JOURNALD_DIR"*) JRESTART=1 ;; esac
  done
  if [ ${#MODIFIED[@]} -gt 0 ] && [ "$EVEN_MODIFIED" = 0 ]; then
    refuse "edited since install: ${MODIFIED[*]}; --even-modified removes them anyway"
  fi
fi

emit() {
  local ok=true ran=false
  [ ${#REFUSED[@]} -eq 0 ] && [ -z "$FAILED_WHY" ] || ok=false
  [ "$RUN_SYSTEMCTL" = 0 ] || [ "$APPLIED" = false ] || ran=true
  printf '{\n  "ok": %s,\n  "action": "%s",\n  "applied": %s,\n' "$ok" "$ACTION" "$APPLIED"
  printf '  "root": %s,\n' "$(json_str "$ROOT")"
  printf '  "files": %s,\n' "$(json_list ${PATHS[@]+"${PATHS[@]}"})"
  printf '  "modified": %s,\n' "$(json_list ${MODIFIED[@]+"${MODIFIED[@]}"})"
  printf '  "missing": %s,\n' "$(json_list ${MISSING[@]+"${MISSING[@]}"})"
  printf '  "kept": %s,\n' "$(json_list "${KEPT[@]}")"
  printf '  "journald_restart": %s,\n' "$([ "$JRESTART" = 1 ] && echo true || echo false)"
  printf '  "systemctl": %s,\n  "systemctl_ran": %s,\n' "$(json_list ${SYSTEMCTL_CALLS[@]+"${SYSTEMCTL_CALLS[@]}"})" "$ran"
  printf '  "refused": %s,\n' "$(json_list ${REFUSED[@]+"${REFUSED[@]}"})"
  if [ -n "$FAILED_WHY" ]; then printf '  "failed": %s\n}\n' "$(json_str "$FAILED_WHY")"; else printf '  "failed": null\n}\n'; fi
}

if [ ${#REFUSED[@]} -gt 0 ]; then
  for why in "${REFUSED[@]}"; do echo "remove-disk-gc: refused: $why" >&2; done
  emit
  exit 3
fi
if [ "$ACTION" = absent ]; then
  echo "remove-disk-gc: no $MANIFEST_REL under $ROOT: nothing to remove" >&2
  emit
  exit 0
fi
if [ "$APPROVE" = 0 ]; then
  SYSTEMCTL_CALLS=("disable --now $TIMERS" "stop $SERVICES" daemon-reload)
  [ "$JRESTART" = 0 ] || SYSTEMCTL_CALLS+=("restart systemd-journald")
  emit
  exit 0
fi

failed() {
  FAILED_WHY=$1
  echo "remove-disk-gc: failed: $1" >&2
  emit
  exit 1
}

APPLIED=true
# $TIMERS is the two timer names, split into two arguments on purpose.
# shellcheck disable=SC2086
run_systemctl disable --now $TIMERS || failed "systemctl disable --now failed; nothing removed"
# $SERVICES is the two service names, split into two arguments on purpose.
# shellcheck disable=SC2086
run_systemctl stop $SERVICES || failed "systemctl stop failed; nothing removed"
for p in "${PATHS[@]}"; do
  rm -f "$R/$p" || failed "couldn't remove $p"
done
run_systemctl daemon-reload || failed "systemctl daemon-reload failed"
if [ "$JRESTART" = 1 ]; then
  run_systemctl restart systemd-journald || failed "systemctl restart systemd-journald failed"
fi
# The commit marker goes last: until then, a re-run sees what is left.
rm -f "$I_MAN" || failed "couldn't remove MANIFEST"
for d in "$R/$GC_DIR" "$R/${GC_DIR%/*}"; do
  if [ -d "$d" ] && [ -z "$(ls -A "$d")" ]; then rmdir "$d" || failed "couldn't remove the empty $d"; fi
done
emit
