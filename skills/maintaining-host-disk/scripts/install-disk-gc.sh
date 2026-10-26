#!/usr/bin/env bash
# install-disk-gc.sh — install or update the canonical disk GC from a
# staging tree pull-disk-gc.sh checked, as the contract says (#425).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash install-disk-gc.sh --staging DIR [--approve] [--reinstall]
                               [--root DIR] [--aside DIR] [--systemctl CMD]

Installs the files a staging tree's MANIFEST lists, from pull-disk-gc.sh's
--into DIR. Without --approve it prints the plan and changes nothing.

The staging tree belongs to whoever pulled it, so nothing in it is trusted
as it stands: it is copied into a new private directory (root-owned, under
sudo) and every check below reads that copy, which is what gets installed.
Its MANIFEST must have the sha256 that _pin.sh names, which binds every
file it lists to the pinned release.

It decides from the installed VERSION, read beside the installed MANIFEST:
  install    nothing installed yet
  update     the staged VERSION is higher
  current    the same VERSION, and the installed files still match their
             MANIFEST: nothing to do
  reinstall  the same VERSION again, with --reinstall
A staged VERSION lower than the installed one refuses: no downgrade.

The install, as root (the contract's own steps):
  1. an update first copies the installed MANIFEST into --aside, since the
     install overwrites it
  2. each MANIFEST file: install -D -o root -g root -m <its staged mode>
  3. MANIFEST itself, mode 644
  4. sha256sum --strict -c MANIFEST, from the root
  5. an update removes each path the old MANIFEST listed that the new one
     doesn't, and nothing else
  6. systemctl daemon-reload, and systemctl restart systemd-journald only
     when a journald.conf.d drop-in it installs or removes changed

It never touches /etc/cannobserv/disk-gc/ (the host's disk-gc.conf and
checkin.key), the GC's state under /var/lib, or a timer: an enabled timer
stays enabled, and a new install leaves both off.

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
  --aside DIR       where an update copies the old MANIFEST (default: a new
                    mktemp -d directory); printed as aside
  --systemctl CMD   the systemctl to call (default: systemctl, under / only)
  -h, --help        show this help

Paths may hold only [A-Za-z0-9._+@/-].

Output (stdout, JSON): ok, action, applied, root, staging,
installed_version, staged_version, files, removed, aside, journald_restart,
systemctl (the calls, made or planned), systemctl_ran, refused, failed.

Exit codes:
  0  planned, done, or already current
  1  failed part-way: what's in place is in failed, and the old MANIFEST is
     in aside
  2  usage
  3  refused: nothing changed
USAGE
}

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_manifest-lib.sh
. "$HERE/_manifest-lib.sh"
# shellcheck source=_pin.sh
. "$HERE/_pin.sh"

STAGING="" ROOT=/ ASIDE="" APPROVE=0 REINSTALL=0 SYSTEMCTL="" RUN_SYSTEMCTL=0
usage_error() { echo "install-disk-gc: $1" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --staging | --root | --aside | --systemctl)
      [ $# -ge 2 ] || usage_error "$1 needs a value"
      case "$1" in
        --staging) STAGING=$2 ;;
        --root) ROOT=$2 ;;
        --aside) ASIDE=$2 ;;
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
for v in "$STAGING" "$ROOT" "$ASIDE" "$SYSTEMCTL"; do
  [[ $v =~ ^[A-Za-z0-9._+@/-]*$ ]] || usage_error "$v: paths may hold only [A-Za-z0-9._+@/-]"
done
[ -d "$STAGING" ] || usage_error "$STAGING is not a directory"
[ -d "$ROOT" ] || usage_error "$ROOT is not a directory"
STAGING=$(cd "$STAGING" && pwd)
ROOT=$(cd "$ROOT" && pwd)
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

# --- the staging tree ---------------------------------------------------------

# A private copy, so nothing the staging tree's owner does after this point
# reaches what is checked and installed. Under sudo, mktemp's 0700 directory
# and cp's new files are root's.
COPY=$(mktemp -d "${TMPDIR:-/tmp}/disk-gc-install.XXXXXX") || {
  echo "install-disk-gc: couldn't make a private directory under ${TMPDIR:-/tmp}" >&2
  exit 1
}
trap 'rm -rf "$COPY"' EXIT
CP_OK=1
cp -R --preserve=mode "$STAGING" "$COPY/stage" || CP_OK=0
STAGED=$COPY/stage

S_PATHS=() S_HASHES=() S_VER=""
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

I_PATHS=() I_HASHES=() I_VER="" ACTION=install
I_MAN=$R/$MANIFEST_REL
no_symlink_under "$R" "$MANIFEST_REL"
if [ -f "$I_MAN" ] && [ ! -L "$I_MAN" ]; then
  read_manifest "$I_MAN" installed
  I_PATHS=(${M_PATHS[@]+"${M_PATHS[@]}"}) I_HASHES=(${M_HASHES[@]+"${M_HASHES[@]}"})
  if [ -f "$R/$VERSION_REL" ]; then I_VER=$(tr -d '[:space:]' <"$R/$VERSION_REL"); fi
  if ! [[ $I_VER =~ ^[0-9]+$ ]]; then
    refuse "the installed VERSION is not an integer; read it by hand"
  elif [[ $S_VER =~ ^[0-9]+$ ]]; then
    if [ "$S_VER" -gt "$I_VER" ]; then
      ACTION=update
    elif [ "$S_VER" -lt "$I_VER" ]; then
      refuse "staged VERSION $S_VER is older than the installed $I_VER: no downgrade"
    elif [ "$REINSTALL" = 1 ]; then
      ACTION=reinstall
    else
      ACTION=current
      drift=""
      for i in ${I_PATHS[@]+"${!I_PATHS[@]}"}; do
        [ "$(hash_of "$R/${I_PATHS[$i]}")" = "${I_HASHES[$i]}" ] || drift="$drift ${I_PATHS[$i]}"
      done
      [ -z "$drift" ] || refuse "VERSION $I_VER is installed, but differs from its MANIFEST:$drift; --reinstall replaces it"
      cmp -s "$I_MAN" "$S_MAN" || refuse "VERSION $I_VER is installed with a different MANIFEST from the staged one; --reinstall replaces it"
    fi
  fi
fi

# --- what it would write and remove -------------------------------------------

REMOVED=()
for p in ${I_PATHS[@]+"${I_PATHS[@]}"}; do
  contains "$p" ${S_PATHS[@]+"${S_PATHS[@]}"} || REMOVED+=("$p")
done
for p in ${S_PATHS[@]+"${S_PATHS[@]}"} ${REMOVED[@]+"${REMOVED[@]}"}; do
  no_symlink_under "$R" "$p"
  if [ -e "$R/$p" ] && [ ! -L "$R/$p" ] && [ ! -f "$R/$p" ]; then refuse "$p is not a regular file on the root"; fi
done

JRESTART=0
for i in ${S_PATHS[@]+"${!S_PATHS[@]}"}; do
  case "${S_PATHS[$i]}" in
    "$JOURNALD_DIR"*) [ "$(hash_of "$R/${S_PATHS[$i]}")" = "${S_HASHES[$i]}" ] || JRESTART=1 ;;
  esac
done
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  case "$p" in "$JOURNALD_DIR"*) [ "$(hash_of "$R/$p")" = absent ] || JRESTART=1 ;; esac
done

# --- report, and act ------------------------------------------------------------

APPLIED=false FAILED_WHY="" ASIDE_OUT=""
emit() {
  local ok=true iv=null sv=null ran=false
  [ ${#REFUSED[@]} -eq 0 ] && [ -z "$FAILED_WHY" ] || ok=false
  if [[ $I_VER =~ ^[0-9]+$ ]]; then iv=$I_VER; fi
  if [[ $S_VER =~ ^[0-9]+$ ]]; then sv=$S_VER; fi
  [ "$RUN_SYSTEMCTL" = 0 ] || [ "$APPLIED" = false ] || ran=true
  printf '{\n  "ok": %s,\n  "action": "%s",\n  "applied": %s,\n' "$ok" "$ACTION" "$APPLIED"
  printf '  "root": %s,\n  "staging": %s,\n' "$(json_str "$ROOT")" "$(json_str "$STAGING")"
  printf '  "installed_version": %s,\n  "staged_version": %s,\n' "$iv" "$sv"
  printf '  "files": %s,\n' "$(json_list ${S_PATHS[@]+"${S_PATHS[@]}"})"
  printf '  "removed": %s,\n' "$(json_list ${REMOVED[@]+"${REMOVED[@]}"})"
  if [ -n "$ASIDE_OUT" ]; then printf '  "aside": %s,\n' "$(json_str "$ASIDE_OUT")"; else printf '  "aside": null,\n'; fi
  printf '  "journald_restart": %s,\n' "$([ "$JRESTART" = 1 ] && echo true || echo false)"
  printf '  "systemctl": %s,\n  "systemctl_ran": %s,\n' "$(json_list ${SYSTEMCTL_CALLS[@]+"${SYSTEMCTL_CALLS[@]}"})" "$ran"
  printf '  "refused": %s,\n' "$(json_list ${REFUSED[@]+"${REFUSED[@]}"})"
  if [ -n "$FAILED_WHY" ]; then printf '  "failed": %s\n}\n' "$(json_str "$FAILED_WHY")"; else printf '  "failed": null\n}\n'; fi
}

if [ ${#REFUSED[@]} -gt 0 ]; then
  for why in "${REFUSED[@]}"; do echo "install-disk-gc: refused: $why" >&2; done
  emit
  exit 3
fi
if [ "$ACTION" = current ]; then
  emit
  exit 0
fi
if [ "$APPROVE" = 0 ]; then
  SYSTEMCTL_CALLS=(daemon-reload)
  [ "$JRESTART" = 0 ] || SYSTEMCTL_CALLS+=("restart systemd-journald")
  emit
  exit 0
fi

failed() {
  FAILED_WHY=$1
  APPLIED=true
  echo "install-disk-gc: failed: $1" >&2
  emit
  exit 1
}

if [ -f "$I_MAN" ]; then
  if [ -z "$ASIDE" ]; then
    ASIDE=$(mktemp -d "${TMPDIR:-/tmp}/disk-gc-aside.XXXXXX") || failed "couldn't make an aside directory"
  fi
  mkdir -p "$ASIDE" || failed "couldn't make $ASIDE"
  ASIDE_OUT=$ASIDE/MANIFEST
  cp "$I_MAN" "$ASIDE_OUT" || failed "couldn't copy the old MANIFEST aside; nothing installed"
  cmp -s "$I_MAN" "$ASIDE_OUT" || failed "the aside copy of the old MANIFEST doesn't match it; nothing installed"
fi

OWN=()
[ "$(id -u)" != 0 ] || OWN=(-o root -g root)
for p in "${S_PATHS[@]}"; do
  mode=$(stat -c %a "$STAGED/$p") || failed "couldn't read $p's staged mode"
  install -D ${OWN[@]+"${OWN[@]}"} -m "$mode" "$STAGED/$p" "$R/$p" || failed "install of $p failed"
done
install ${OWN[@]+"${OWN[@]}"} -m 644 "$S_MAN" "$I_MAN" || failed "install of MANIFEST failed"
APPLIED=true
(cd "$ROOT" && sha256sum --strict --quiet -c "$MANIFEST_REL") >&2 || failed "the installed files fail sha256sum --strict -c MANIFEST"
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  rm -f "$R/$p" || failed "couldn't remove $p, which the new MANIFEST dropped"
done
run_systemctl daemon-reload || failed "systemctl daemon-reload failed"
if [ "$JRESTART" = 1 ]; then
  run_systemctl restart systemd-journald || failed "systemctl restart systemd-journald failed"
fi
emit
