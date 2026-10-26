#!/usr/bin/env bash
# install-disk-gc.sh — install or update the canonical disk GC from a
# staging tree pull-disk-gc.sh checked, as the contract says (#425).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash install-disk-gc.sh --staging DIR [--approve] [--reinstall]
                               [--root DIR] [--systemctl CMD]

Installs the files a staging tree's MANIFEST lists, from pull-disk-gc.sh's
--into DIR. Without --approve it prints the plan and changes nothing.

The staging tree belongs to whoever pulled it, so nothing in it is trusted
as it stands: it is copied into a new private directory (root-owned, under
sudo) and every check below reads that copy, which is what gets installed.
Its MANIFEST must have the sha256 that _pin.sh names, which binds every
file it lists to the pinned release.

The installed MANIFEST is the commit marker: it is written last, so it
names what was installed only once everything else is done. It decides
from it, and from the installed VERSION it records:
  install    no MANIFEST installed
  update     the staged VERSION is higher; or an earlier run of this same
             release stopped before writing its MANIFEST (interrupted),
             which a re-run finishes
  current    the staged MANIFEST is the installed one, and the installed
             files still match it: nothing to install. With --approve it
             still runs daemon-reload, in case a run stopped after its
             MANIFEST but its reload didn't take
  reinstall  the same VERSION again, with --reinstall
A staged VERSION lower than the installed one refuses: no downgrade. So
does a VERSION on disk that is neither the marker's nor the staged one: an
update that stopped part-way before the pin moved. Finish it with the skill
at the old pin, then update. A MANIFEST whose VERSION is gone is a remove
that stopped part-way: finish it with remove-disk-gc.sh, then install.

The install, as root:
  1. each MANIFEST file but MANIFEST: install -D -o root -g root -m <its
     staged mode>
  2. sha256sum --strict -c of the staged MANIFEST, from the root
  3. an update removes each path the installed MANIFEST lists that the new
     one doesn't, and nothing else; a unit among them is first
     `systemctl disable --now`
  4. systemctl daemon-reload, and systemctl restart systemd-journald only
     when a journald.conf.d drop-in differs from what the installed
     MANIFEST records or from the file on disk, it lists one the new
     MANIFEST drops, or the run is a reinstall or a resumed update, which
     may be finishing a run that stopped before its restart
  5. MANIFEST, mode 644: the commit marker
A run that fails before step 5 leaves the old MANIFEST (or none) in place,
so a re-run sees the same plan and finishes it.

It never touches /etc/cannobserv/disk-gc/ (the host's disk-gc.conf and
checkin.key), the GC's state under /var/lib, or a timer it keeps: an
enabled timer stays enabled, and a new install leaves both off. Only a unit
the new MANIFEST drops is disabled, before it goes.

Before anything changes it refuses (exit 3), with every reason in refused:
  - staging: MANIFEST missing or not the pinned one, a line not in
    sha256sum's format, a path outside usr/local/lib/, a link or special
    file, a file MANIFEST doesn't list, a file mode other than 0644 or 0755
    or a directory mode other than 0755, `sha256sum --strict -c` failing,
    or a VERSION that isn't an integer
  - the installed copy: a MANIFEST that names a path outside
    usr/local/lib/ (an update would remove it), an unreadable VERSION, or,
    at the same VERSION, files that differ from it (--reinstall replaces
    them) or a different MANIFEST
  - a symlink at, or above, any path it would write or remove
  - --approve into / without root

Options:
  --staging DIR     the staging tree (required)
  --approve         the owner's approval, given in the host's own session
  --reinstall       install the same VERSION again, over drift
  --root DIR        install under DIR instead of / (a scratch root, for a
                    test or a rehearsal); systemctl isn't called unless
                    --systemctl names one
  --systemctl CMD   the systemctl to call (default: systemctl, under / only)
  -h, --help        show this help

Paths may hold only [A-Za-z0-9._+@/-].

Output (stdout, JSON): ok, action, applied, root, staging,
installed_version, staged_version, interrupted, files, removed,
journald_restart, systemctl (the calls, made or planned), systemctl_ran,
refused, failed.

Exit codes:
  0  planned, done, or already current
  1  failed part-way: failed says where; the old MANIFEST is still the
     marker, so run it again once the cause is fixed
  2  usage
  3  refused: nothing changed
USAGE
}

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_manifest-lib.sh
. "$HERE/_manifest-lib.sh"
# shellcheck source=_pin.sh
. "$HERE/_pin.sh"

STAGING="" ROOT=/ APPROVE=0 REINSTALL=0 SYSTEMCTL="" RUN_SYSTEMCTL=0
usage_error() { echo "install-disk-gc: $1" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --staging | --root | --systemctl)
      [ $# -ge 2 ] || usage_error "$1 needs a value"
      case "$1" in
        --staging) STAGING=$2 ;;
        --root) ROOT=$2 ;;
        --systemctl) SYSTEMCTL=$2 RUN_SYSTEMCTL=1 ;;
      esac
      shift 2
      ;;
    --approve) APPROVE=1; shift ;;
    --reinstall) REINSTALL=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done
[ -n "$STAGING" ] || usage_error "--staging DIR is required"
for v in "$STAGING" "$ROOT" "$SYSTEMCTL"; do
  [[ $v =~ ^[A-Za-z0-9._+@/-]*$ ]] || usage_error "$v: paths may hold only [A-Za-z0-9._+@/-]"
done
[ -d "$STAGING" ] || usage_error "$STAGING is not a directory"
[ -d "$ROOT" ] || usage_error "$ROOT is not a directory"
STAGING=$(canon_dir "$STAGING")
ROOT=$(canon_dir "$ROOT")
R=${ROOT%/}
if [ "$ROOT" = / ] && [ -z "$SYSTEMCTL" ]; then SYSTEMCTL=systemctl RUN_SYSTEMCTL=1; fi
if [ "$APPROVE" = 1 ] && [ "$ROOT" = / ] && [ "$(id -u)" != 0 ]; then
  refuse "installing into / needs root"
fi

contains() {
  local want=$1 x
  shift
  for x in "$@"; do [ "$x" = "$want" ] && return 0; done
  return 1
}

# --- the report ----------------------------------------------------------------

# Everything emit reads, set before anything can fail.
S_PATHS=() S_HASHES=() S_VER="" I_PATHS=() I_HASHES=() I_VER=""
ACTION=install INTERRUPTED=false REMOVED=() JRESTART=0
APPLIED=false FAILED_WHY=""
emit() {
  local ok=true iv=null sv=null ran=false
  [ ${#REFUSED[@]} -eq 0 ] && [ -z "$FAILED_WHY" ] || ok=false
  if [[ $I_VER =~ ^[0-9]+$ ]]; then iv=$I_VER; fi
  if [[ $S_VER =~ ^[0-9]+$ ]]; then sv=$S_VER; fi
  [ "$RUN_SYSTEMCTL" = 0 ] || [ "$APPROVE" = 0 ] || [ ${#SYSTEMCTL_CALLS[@]} -eq 0 ] || ran=true
  printf '{\n  "ok": %s,\n  "action": "%s",\n  "applied": %s,\n' "$ok" "$ACTION" "$APPLIED"
  printf '  "root": %s,\n  "staging": %s,\n' "$(json_str "$ROOT")" "$(json_str "$STAGING")"
  printf '  "installed_version": %s,\n  "staged_version": %s,\n' "$iv" "$sv"
  printf '  "interrupted": %s,\n' "$INTERRUPTED"
  printf '  "files": %s,\n' "$(json_list ${S_PATHS[@]+"${S_PATHS[@]}"})"
  printf '  "removed": %s,\n' "$(json_list ${REMOVED[@]+"${REMOVED[@]}"})"
  printf '  "journald_restart": %s,\n' "$([ "$JRESTART" = 1 ] && echo true || echo false)"
  printf '  "systemctl": %s,\n  "systemctl_ran": %s,\n' "$(json_list ${SYSTEMCTL_CALLS[@]+"${SYSTEMCTL_CALLS[@]}"})" "$ran"
  printf '  "refused": %s,\n' "$(json_list ${REFUSED[@]+"${REFUSED[@]}"})"
  if [ -n "$FAILED_WHY" ]; then printf '  "failed": %s\n}\n' "$(json_str "$FAILED_WHY")"; else printf '  "failed": null\n}\n'; fi
}

# APPLIED turns true at the first file installed, and only there: a failure
# before it changed nothing.
failed() {
  FAILED_WHY=$1
  echo "install-disk-gc: failed: $1" >&2
  emit
  exit 1
}

# --- the staging tree ---------------------------------------------------------

# A private copy, so nothing the staging tree's owner does after this point
# reaches what is checked and installed. Under sudo, mktemp's 0700 directory
# and cp's new files are root's. As root it ignores TMPDIR: sudo can keep a
# user's, whose owner could rename the directory away and put their own in
# its place. /run is root's on a systemd host; /root where there is none.
if [ "$(id -u)" = 0 ]; then
  PRIVATE_BASE=/run
  [ -d "$PRIVATE_BASE" ] && [ ! -L "$PRIVATE_BASE" ] || PRIVATE_BASE=/root
else
  PRIVATE_BASE=${TMPDIR:-/tmp}
fi
COPY=$(mktemp -d "$PRIVATE_BASE/disk-gc-install.XXXXXX") ||
  failed "couldn't make a private directory under $PRIVATE_BASE; nothing installed"
trap 'rm -rf "$COPY"' EXIT
CP_OK=1
# STAGING is the physical path (canon_dir), so cp copies the tree it names,
# never a link back into it; and the copy must be a real directory.
cp -R --preserve=mode "$STAGING" "$COPY/stage" || CP_OK=0
STAGED=$COPY/stage
if [ -L "$STAGED" ] || [ ! -d "$STAGED" ]; then CP_OK=0; fi

S_MAN=$STAGED/$MANIFEST_REL
if [ "$CP_OK" = 0 ]; then
  refuse "couldn't copy the staging tree into a private directory"
elif [ ! -f "$S_MAN" ] || [ -L "$S_MAN" ]; then
  refuse "staging has no $MANIFEST_REL"
else
  read_manifest "$S_MAN" staged
  S_PATHS=(${M_PATHS[@]+"${M_PATHS[@]}"}) S_HASHES=(${M_HASHES[@]+"${M_HASHES[@]}"})
  got=$(hash_of "$S_MAN")
  [ "$got" = "$DISK_GC_MANIFEST_SHA256" ] || refuse "staging's MANIFEST has sha256 $got, not the pin's $DISK_GC_MANIFEST_SHA256"
  odd=$(cd "$STAGED" && find . ! -type f ! -type d | sed 's|^\./||' | sort)
  [ -z "$odd" ] || refuse "staging holds a link or special file: $(echo "$odd" | tr '\n' ' ')"
  badf=$(cd "$STAGED" && find . -type f ! -perm 0644 ! -perm 0755 | sed 's|^\./||' | sort | tr '\n' ' ')
  [ -z "$badf" ] || refuse "staging holds a file whose mode is not 0644 or 0755: $badf"
  badd=$(cd "$STAGED" && find . -type d ! -perm 0755 | sed 's|^\./||' | sort | tr '\n' ' ')
  [ -z "$badd" ] || refuse "staging holds a directory whose mode is not 0755: $badd"
  have=$(cd "$STAGED" && find . -type f | sed 's|^\./||' | sort)
  want=$(printf '%s\n' "$MANIFEST_REL" ${S_PATHS[@]+"${S_PATHS[@]}"} | sort)
  extra=$(comm -23 <(printf '%s\n' "$have") <(printf '%s\n' "$want") | tr '\n' ' ')
  [ -z "$extra" ] || refuse "staging holds files MANIFEST doesn't list: $extra"
  if [ ${#REFUSED[@]} -eq 0 ] && ! (cd "$STAGED" && sha256sum --strict --quiet -c "$MANIFEST_REL") >&2; then
    refuse "staging fails sha256sum --strict -c MANIFEST"
  fi
  if [ -f "$STAGED/$VERSION_REL" ]; then S_VER=$(tr -d '[:space:]' <"$STAGED/$VERSION_REL"); fi
  [[ $S_VER =~ ^[0-9]+$ ]] || refuse "staging's VERSION is not an integer"
fi

# --- what's installed ---------------------------------------------------------

I_MAN=$R/$MANIFEST_REL
no_symlink_under "$R" "$MANIFEST_REL"
if [ -f "$I_MAN" ] && [ ! -L "$I_MAN" ]; then
  read_manifest "$I_MAN" installed
  I_PATHS=(${M_PATHS[@]+"${M_PATHS[@]}"}) I_HASHES=(${M_HASHES[@]+"${M_HASHES[@]}"})
  if [ -f "$R/$VERSION_REL" ]; then I_VER=$(tr -d '[:space:]' <"$R/$VERSION_REL"); fi
  on_disk=$(hash_of "$R/$VERSION_REL") marked="" staged_v=""
  for i in ${I_PATHS[@]+"${!I_PATHS[@]}"}; do
    [ "${I_PATHS[$i]}" != "$VERSION_REL" ] || marked=${I_HASHES[$i]}
  done
  for i in ${S_PATHS[@]+"${!S_PATHS[@]}"}; do
    [ "${S_PATHS[$i]}" != "$VERSION_REL" ] || staged_v=${S_HASHES[$i]}
  done
  if [ -f "$S_MAN" ] && cmp -s "$I_MAN" "$S_MAN"; then
    if [ "$REINSTALL" = 1 ]; then
      ACTION=reinstall
    else
      ACTION=current
      drift=""
      for i in ${I_PATHS[@]+"${!I_PATHS[@]}"}; do
        [ "$(hash_of "$R/${I_PATHS[$i]}")" = "${I_HASHES[$i]}" ] || drift="$drift ${I_PATHS[$i]}"
      done
      [ -z "$drift" ] || refuse "VERSION $I_VER is installed, but differs from its MANIFEST:$drift; --reinstall replaces it"
    fi
  elif [ -n "$marked" ] && [ "$on_disk" = "$marked" ] && [[ $I_VER =~ ^[0-9]+$ ]]; then
    if ! [[ $S_VER =~ ^[0-9]+$ ]]; then
      :
    elif [ "$S_VER" -gt "$I_VER" ]; then
      ACTION=update
    elif [ "$S_VER" -lt "$I_VER" ]; then
      refuse "staged VERSION $S_VER is older than the installed $I_VER: no downgrade"
    elif [ "$REINSTALL" = 1 ]; then
      ACTION=reinstall
    else
      refuse "VERSION $I_VER is installed with a different MANIFEST from the staged one; --reinstall replaces it"
    fi
  elif [ -n "$staged_v" ] && [ "$on_disk" = "$staged_v" ]; then
    # This release's VERSION is on disk, under the old marker: an earlier
    # run stopped before writing its MANIFEST.
    ACTION=update INTERRUPTED=true
  elif [ "$on_disk" = absent ]; then
    # MANIFEST outlives its files only in a remove that stopped part-way:
    # remove deletes MANIFEST last.
    refuse "the installed MANIFEST is there but its VERSION is gone: a remove stopped part-way. Finish it with remove-disk-gc.sh, then install"
  else
    refuse "the installed VERSION ($I_VER) is neither the one its MANIFEST records nor the staged one: an earlier update most likely stopped part-way, and the pin has moved since. Finish it with this skill at the old pin, the release whose VERSION is on disk (a skills-vendor checkout of that commit), then update; otherwise read it by hand"
  fi
fi

# --- what it would write and remove -------------------------------------------

for p in ${I_PATHS[@]+"${I_PATHS[@]}"}; do
  contains "$p" ${S_PATHS[@]+"${S_PATHS[@]}"} || REMOVED+=("$p")
done
for p in ${S_PATHS[@]+"${S_PATHS[@]}"} ${REMOVED[@]+"${REMOVED[@]}"}; do
  no_symlink_under "$R" "$p"
  if [ -e "$R/$p" ] && [ ! -L "$R/$p" ] && [ ! -f "$R/$p" ]; then refuse "$p is not a regular file on the root"; fi
done

# A unit the new MANIFEST drops is disabled (and stopped) before its file
# goes, so no enabled timer is left as a dangling wants link. One already
# gone, after a run that stopped part-way, has nothing left to disable.
DROPPED_UNITS=()
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  case "$p" in
    usr/local/lib/systemd/system/*.service | usr/local/lib/systemd/system/*.timer)
      [ ! -f "$R/$p" ] || DROPPED_UNITS+=("${p##*/}")
      ;;
  esac
done

# journald restarts when a drop-in differs from what the installed MANIFEST
# records, not from the bytes on disk: a run that stopped after writing the
# drop-in but before the restart left them already equal.
marked_hash() {
  local want=$1 i
  for i in ${I_PATHS[@]+"${!I_PATHS[@]}"}; do
    [ "${I_PATHS[$i]}" != "$want" ] || { printf '%s\n' "${I_HASHES[$i]}"; return 0; }
  done
  printf 'absent\n'
}
for i in ${S_PATHS[@]+"${!S_PATHS[@]}"}; do
  case "${S_PATHS[$i]}" in
    "$JOURNALD_DIR"*)
      # Against the marker (a run that stopped before its restart), and
      # against the disk (a drop-in edited since, which --reinstall puts back).
      [ "$(marked_hash "${S_PATHS[$i]}")" = "${S_HASHES[$i]}" ] || JRESTART=1
      [ "$(hash_of "$R/${S_PATHS[$i]}")" = "${S_HASHES[$i]}" ] || JRESTART=1
      ;;
  esac
done
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  case "$p" in "$JOURNALD_DIR"*) JRESTART=1 ;; esac
done
# A reinstall, or a resumed update, may re-run one that already wrote the
# drop-in and stopped before its restart: then neither the marker nor the
# disk shows a difference, so any drop-in in the plan restarts journald.
if [ "$ACTION" = reinstall ] || [ "$INTERRUPTED" = true ]; then
  for p in ${S_PATHS[@]+"${S_PATHS[@]}"}; do
    case "$p" in "$JOURNALD_DIR"*) JRESTART=1 ;; esac
  done
fi

# --- report, and act ------------------------------------------------------------


if [ ${#REFUSED[@]} -gt 0 ]; then
  for why in "${REFUSED[@]}"; do echo "install-disk-gc: refused: $why" >&2; done
  emit
  exit 3
fi
if [ "$APPROVE" = 0 ]; then
  if [ "$ACTION" != current ]; then
    for u in ${DROPPED_UNITS[@]+"${DROPPED_UNITS[@]}"}; do SYSTEMCTL_CALLS+=("disable --now $u"); done
    SYSTEMCTL_CALLS+=(daemon-reload)
    [ "$JRESTART" = 0 ] || SYSTEMCTL_CALLS+=("restart systemd-journald")
  fi
  emit
  exit 0
fi


if [ "$ACTION" = current ]; then
  run_systemctl daemon-reload || failed "systemctl daemon-reload failed"
  emit
  exit 0
fi

OWN=()
[ "$(id -u)" != 0 ] || OWN=(-o root -g root)
for p in "${S_PATHS[@]}"; do
  mode=$(stat -c %a "$STAGED/$p") || failed "couldn't read $p's staged mode"
  install -D ${OWN[@]+"${OWN[@]}"} -m "$mode" "$STAGED/$p" "$R/$p" || failed "install of $p failed"
  APPLIED=true
done
(cd "$ROOT" && sha256sum --strict --quiet -c "$S_MAN") >&2 || failed "the installed files fail sha256sum --strict -c of the staged MANIFEST"
for u in ${DROPPED_UNITS[@]+"${DROPPED_UNITS[@]}"}; do
  run_systemctl disable --now "$u" || failed "systemctl disable --now $u failed; nothing removed"
done
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  rm -f "$R/$p" || failed "couldn't remove $p, which the new MANIFEST dropped"
done
run_systemctl daemon-reload || failed "systemctl daemon-reload failed"
if [ "$JRESTART" = 1 ]; then
  run_systemctl restart systemd-journald || failed "systemctl restart systemd-journald failed"
fi
# The commit marker, last: until it lands, a re-run sees this same plan.
install ${OWN[@]+"${OWN[@]}"} -m 644 "$S_MAN" "$I_MAN" || failed "install of MANIFEST, the commit marker, failed"
emit
