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
             files still match it: nothing to install, and no systemctl
             call (the marker lands only after the reload took)
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
     `systemctl disable --now`, its timers before its services
  4. systemctl daemon-reload, and systemctl restart systemd-journald only
     when a journald.conf.d drop-in differs from what the installed
     MANIFEST records or from the file on disk, it lists one the new
     MANIFEST drops, or the run is a reinstall or a resumed update, which
     may be finishing a run that stopped before its restart
  5. MANIFEST, mode 644: the commit marker
A run that fails before step 5 leaves the old MANIFEST (or none) in place,
so a re-run sees the same plan and finishes it.

It reports, and never refuses, a host's own journald setting the layer's
drop-in meets (journald_overrides). journald reads its main file, by
systemd's version in the root's dpkg database: systemd 255 and older only
/etc/systemd/journald.conf, 256 and newer the first of /etc, /run,
/usr/local/lib and /usr/lib's (an unreadable version reads as 256, with a
note). Then every journald.conf.d/*.conf in those four directories by file
name: a name in a higher directory masks the same name lower down, and
among different names the later one wins each key. A value it can't parse,
an empty one included, it ignores, keeping the one before. So the layer's
zz- drop-in outranks a host's lower cap in its main file or under a name
sorting before it, and a file of the layer's own name in /etc masks the
layer's. Each entry is a host file that sets a key the layer's drop-in
sets: file, key, host (its value, as written when journald ignores it),
layer (the layer's), before and after (the value in effect now, and once
this run lands; null when nothing sets it). The layer's file names and keys
are read from the staged copy; null on a refusal.

It never touches /etc/cannobserv/disk-gc/ (the host's disk-gc.conf and
checkin.key), the GC's state under /var/lib, or a timer it keeps: an
enabled timer stays enabled, and a new install leaves both off. Only a unit
the new MANIFEST drops is disabled, before it goes.

Before anything changes it refuses (exit 3), with every reason in refused:
  - staging: MANIFEST missing or not the pinned one, a line not in
    sha256sum's format, a path outside usr/local/lib/, a link or special
    file, a file MANIFEST doesn't list (bytecode alone says so: re-pull),
    a file mode other than 0644 or 0755
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
journald_restart, journald_overrides, systemctl (the calls, made or
planned), systemctl_ran, refused, failed.

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
STAGING=$(canon_dir "$STAGING") || usage_error "can't resolve $STAGING"
ROOT=$(canon_dir "$ROOT") || usage_error "can't resolve $ROOT"
# Again on the resolved paths: a clean name can link to one that isn't.
for v in "$STAGING" "$ROOT"; do
  [[ $v =~ ^[A-Za-z0-9._+@/-]*$ ]] || usage_error "$v (resolved): paths may hold only [A-Za-z0-9._+@/-]"
done
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
APPLIED=false FAILED_WHY="" J_OVERRIDES=null
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
  printf '  "journald_overrides": %s,\n' "$J_OVERRIDES"
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
  extra=$(comm -23 <(printf '%s\n' "$have") <(printf '%s\n' "$want"))
  if [ -n "$extra" ]; then
    # Bytecode alone has one known cause (#514): something loaded the staged
    # GC with Python, bytecode on. Still refused; the hint names the recovery.
    hint=""
    if ! grep -qv '\(^\|/\)__pycache__/' <<<"$extra"; then
      hint=" (bytecode: Python loaded the staged GC with bytecode on; re-pull into a fresh directory, never edit staging by hand)"
    fi
    refuse "staging holds files MANIFEST doesn't list: $(tr '\n' ' ' <<<"$extra")$hint"
  fi
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
  # First, whether an update stopped part-way: a VERSION on disk that isn't
  # the marker's. Before the current and drift checks, which would read it
  # as drift on an installed VERSION and offer --reinstall: a quiet
  # downgrade that leaves the newer release's own files behind.
  if [ -n "$marked" ] && [ "$on_disk" != absent ] && [ "$on_disk" != "$marked" ]; then
    if [ -n "$staged_v" ] && [ "$on_disk" = "$staged_v" ]; then
      # This release's VERSION is on disk, under the old marker: an
      # earlier run stopped before writing its MANIFEST.
      ACTION=update INTERRUPTED=true
    else
      refuse "an update was interrupted: the installed VERSION ($I_VER) is neither the one its MANIFEST records nor the staged one, so the pin has moved since it stopped. Finish it with this skill at the old pin, the one whose VERSION is $I_VER (a skills-vendor checkout of that commit), then update. Reinstalling the staged release would not finish it"
    fi
  elif [ -f "$S_MAN" ] && cmp -s "$I_MAN" "$S_MAN"; then
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
  elif [ "$on_disk" = absent ]; then
    # MANIFEST outlives its files only in a remove that stopped part-way:
    # remove deletes MANIFEST last.
    refuse "the installed MANIFEST is there but its VERSION is gone: a remove stopped part-way. Finish it with remove-disk-gc.sh, then install"
  else
    refuse "the installed MANIFEST records no VERSION, or an unreadable one: read it by hand"
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
# goes, so no enabled timer is left as a dangling wants link. Timers first:
# a service disabled while its timer is active can be started again by it.
# One already gone, after a run that stopped part-way, has nothing left to
# disable.
DROPPED_TIMERS=() DROPPED_SERVICES=()
for p in ${REMOVED[@]+"${REMOVED[@]}"}; do
  [ -f "$R/$p" ] || continue
  case "$p" in
    usr/local/lib/systemd/system/*.timer) DROPPED_TIMERS+=("${p##*/}") ;;
    usr/local/lib/systemd/system/*.service) DROPPED_SERVICES+=("${p##*/}") ;;
  esac
done
DROPPED_UNITS=(${DROPPED_TIMERS[@]+"${DROPPED_TIMERS[@]}"} ${DROPPED_SERVICES[@]+"${DROPPED_SERVICES[@]}"})

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

# --- what a host's own journald settings become (#604) ------------------------

# journald's rule, measured by running systemd-journald itself (CR 1950,
# CR 1951, CR 1963). The main file: on 249 and 255, /etc's only; on 256, 257
# and 259, the first of the four directories that has one, as cat-config
# reads it, an /etc link to /dev/null masking the rest. The drop-ins, on all
# five: every *.conf across the four directories by file name, a name in a
# higher directory masking the same name lower down (a link to /dev/null
# masks with nothing), all applied in C sort order, the last value journald
# can parse winning; cat-config prints the values it ignores as written.
# patching-hosts' read_journal (#515) reads the drop-ins the same way, and
# the main file as 255 and older do.
JOURNALD_DIRS="etc run usr/local/lib usr/lib"
# The keys journald parses as sizes (parse_size, base 1024), held to its
# grammar; a size too big for 64 bits isn't caught, and every other key is
# read as written, an empty value skipped (journald resets some, Compress=
# among them, where it ignores the sizes'). LineMax, a size whose empty
# value resets, isn't listed: none of this matters for SystemMaxUse=, all
# the layer sets (CR 1964).
SIZE_KEYS=" SystemMaxUse SystemKeepFree SystemMaxFileSize RuntimeMaxUse RuntimeKeepFree RuntimeMaxFileSize "

# printable <var> <text>: VAR := text with each byte that isn't printable
# ASCII shown as ?, so the report stays JSON and valid UTF-8 (CR 1966).
printable() {
  local LC_ALL=C
  printf -v "$1" '%s' "${2//[^ -~]/?}"
}

# journald_main_rule: J_MAIN_ANY := 1 when journald takes its main file from
# the first of the four directories (systemd 256 and newer), 0 when from
# /etc only. The version is the root's dpkg database's: an unreadable one,
# or a package not installed, reads as 256, which reports more, and
# J_MAIN_NOTE says so.
journald_main_rule() {
  local got="" st v rc=0
  J_MAIN_ANY=1 J_MAIN_NOTE=""
  if command -v dpkg-query >/dev/null && command -v dpkg >/dev/null; then
    # dpkg-query's own format, not a shell expansion.
    # shellcheck disable=SC2016
    got=$(dpkg-query --admindir="$R/var/lib/dpkg" -W -f='${db:Status-Status} ${Version}' systemd 2>/dev/null) || got=""
  fi
  st=${got%% *} v=${got#* }
  if [ "$st" = installed ] && [ -n "$v" ]; then
    dpkg --compare-versions "$v" lt 256~ 2>/dev/null || rc=$?
    case $rc in
      0) J_MAIN_ANY=0; return 0 ;;
      1) return 0 ;;
    esac
  fi
  J_MAIN_NOTE="couldn't read systemd's version from /var/lib/dpkg, so journald's main file is read as systemd 256 and newer read it: the first of /etc, /run, /usr/local/lib and /usr/lib"
}

layer_dropin() {  # <rel>: whether it's one of the staged layer's journald drop-ins
  case "$1" in
    "$JOURNALD_DIR"*/*) return 1 ;;
    "$JOURNALD_DIR"*.conf) contains "$1" ${S_PATHS[@]+"${S_PATHS[@]}"} ;;
    *) return 1 ;;
  esac
}

# journald_files <after>: J_SRC, J_SHOW and J_HOST := the files journald
# reads, in its order: the file to read, its path on the host, and 1 for the
# host's own, 0 for one the layer installs or did. With <after> 1, as they
# will be once this run lands: the layer's drop-ins read from the staged
# copy, and any it drops gone. The main file is by journald_main_rule. A
# name is sorted NUL-separated, so one holding a tab or a newline is merged
# like the rest (CR 1966), and shown through printable.
journald_files() {
  local after=$1 d dir rel f n i shown
  local -a here=() seen=() names=() srcs=() shows=() hosts=()
  J_SRC=() J_SHOW=() J_HOST=()
  for d in $JOURNALD_DIRS; do
    [ "$J_MAIN_ANY" = 1 ] || [ "$d" = etc ] || continue
    rel=$d/systemd/journald.conf
    if [ -e "$R/$rel" ] || [ -L "$R/$rel" ]; then
      if [ -f "$R/$rel" ]; then J_SRC+=("$R/$rel") J_SHOW+=("/$rel") J_HOST+=(1); fi
      break
    fi
  done
  for d in $JOURNALD_DIRS; do
    dir=$d/systemd/journald.conf.d
    here=()
    for f in "$R/$dir"/*.conf; do
      if [ -e "$f" ] || [ -L "$f" ]; then here+=("${f##*/}"); fi
    done
    if [ "$after" = 1 ]; then
      for rel in ${S_PATHS[@]+"${S_PATHS[@]}"}; do
        if layer_dropin "$rel" && [ "${rel%/*}" = "$dir" ]; then here+=("${rel##*/}"); fi
      done
    fi
    for n in ${here[@]+"${here[@]}"}; do
      if contains "$n" ${seen[@]+"${seen[@]}"}; then continue; fi
      rel=$dir/$n
      # One this run removes masks nothing once it's gone.
      if [ "$after" = 1 ] && contains "$rel" ${REMOVED[@]+"${REMOVED[@]}"}; then continue; fi
      seen+=("$n")
      f=$R/$rel
      if [ "$after" = 1 ] && layer_dropin "$rel"; then f=$STAGED/$rel; fi
      [ -f "$f" ] || continue
      printable shown "$n"
      names+=("$n") srcs+=("$f") shows+=("/$dir/$shown")
      if contains "$rel" ${S_PATHS[@]+"${S_PATHS[@]}"} ${I_PATHS[@]+"${I_PATHS[@]}"}; then
        hosts+=(0)
      else
        hosts+=(1)
      fi
    done
  done
  [ ${#names[@]} -gt 0 ] || return 0
  # Names are unique here, so each sorted one finds its own index.
  while IFS= read -r -d '' n; do
    for i in "${!names[@]}"; do
      if [ "${names[$i]}" = "$n" ]; then
        J_SRC+=("${srcs[$i]}") J_SHOW+=("${shows[$i]}") J_HOST+=("${hosts[$i]}")
        break
      fi
    done
  done < <(printf '%s\0' "${names[@]}" | LC_ALL=C sort -z)
}

trim() {  # <var> <text>: VAR := text without its leading and trailing whitespace
  local _t=$2
  _t=${_t#"${_t%%[![:space:]]*}"}
  _t=${_t%"${_t##*[![:space:]]}"}
  printf -v "$1" '%s' "$_t"
}

# size_ok <value>: whether journald's parse_size reads it: components of
# digits, an optional fraction, optional whitespace and a unit, E P T G M K
# or B, falling in order; a bare number only last. "200 M", "1G 512M" and
# "1.5" are sizes; "", "300m", "300MiB", "10%" and "512M1G" aren't.
size_ok() {
  local p=$1 re='^\+?[0-9]+(\.[0-9]*)?[[:space:]]*' units=EPTGMKB rank=-1 r u
  [ -n "$p" ] || return 1
  while [ -n "$p" ]; do
    p=${p#"${p%%[![:space:]]*}"}
    [[ $p =~ $re ]] || return 1
    p=${p:${#BASH_REMATCH[0]}}
    u=${p:0:1}
    case $u in
      [EPTGMKB]) r=${units%%"$u"*} r=${#r} p=${p:1} ;;
      *) r=7 ;;
    esac
    [ "$r" -gt "$rank" ] || return 1
    rank=$r
  done
}

# value_ok <key> <value>: whether journald takes it: never an empty one, and
# for a size key only one size_ok reads. Others are taken as written.
value_ok() {
  [ -n "$2" ] || return 1
  case $SIZE_KEYS in *" $1 "*) size_ok "$2" ;; *) return 0 ;; esac
}

# journald_keys <file>: J_KEYS := each key the file's [Journal] section
# assigns, once each, in order; J_VALS := each one's last value journald
# takes (J_OK 1), else its last as written (J_OK 0). Comments start with #
# or ;, and whitespace around the key and the value goes, as systemd's
# parser has it.
journald_keys() {
  local line k v ok sect="" i found
  J_KEYS=() J_VALS=() J_OK=()
  while IFS= read -r line || [ -n "$line" ]; do
    trim line "$line"
    case $line in
      '' | '#'* | ';'*) continue ;;
      '['*']') sect=$line; continue ;;
      *=*) ;;
      *) continue ;;
    esac
    [ "$sect" = '[Journal]' ] || continue
    trim k "${line%%=*}"
    trim v "${line#*=}"
    ok=0
    if value_ok "$k" "$v"; then ok=1; fi
    # The report carries both as JSON strings.
    printable k "$k"
    printable v "$v"
    found=""
    for i in ${J_KEYS[@]+"${!J_KEYS[@]}"}; do
      [ "${J_KEYS[$i]}" = "$k" ] || continue
      found=1
      # One journald ignores keeps the value before it.
      if [ "$ok" = 1 ] || [ "${J_OK[$i]}" = 0 ]; then J_VALS[i]=$v J_OK[i]=$ok; fi
    done
    if [ -z "$found" ]; then J_KEYS+=("$k") J_VALS+=("$v") J_OK+=("$ok"); fi
  done <"$1"
}

# key_value <var> <key> [any]: VAR := KEY's value journald takes from what
# journald_keys read; 1 when there's none. With "any", its value as written
# when journald takes none, and 1 only when the key isn't assigned at all.
key_value() {
  local i
  for i in ${J_KEYS[@]+"${!J_KEYS[@]}"}; do
    if [ "${J_KEYS[$i]}" = "$2" ] && { [ "${J_OK[$i]}" = 1 ] || [ "${3:-}" = any ]; }; then
      printf -v "$1" '%s' "${J_VALS[$i]}"
      return 0
    fi
  done
  return 1
}

# effective <key> <file>...: KEY's value in effect, as JSON: the last one
# journald takes across the files, read in order; null when none sets it.
effective() {
  local key=$1 f v out=null
  shift
  for f in "$@"; do
    journald_keys "$f"
    if key_value v "$key"; then out=$(json_str "$v"); fi
  done
  printf '%s\n' "$out"
}

# J_OVERRIDES := each host file journald reads, now or once this run lands,
# that sets a key the layer's drop-ins set, with that key's value in effect
# before and after. It reports; a lower cap is the host's decision.
journald_overrides() {
  local rel i j k v before after
  local -a layers=() lk=() lv=() hf=() hs=() bsrc=() asrc=() entries=()
  for rel in ${S_PATHS[@]+"${S_PATHS[@]}"}; do
    if layer_dropin "$rel"; then layers+=("$rel"); fi
  done
  # The layer's keys, and its value for each, from its drop-ins in name order.
  if [ ${#layers[@]} -gt 0 ]; then
    while IFS= read -r rel; do
      journald_keys "$STAGED/$rel"
      for i in ${J_KEYS[@]+"${!J_KEYS[@]}"}; do
        [ "${J_OK[$i]}" = 1 ] || continue
        j=""
        for k in ${lk[@]+"${!lk[@]}"}; do
          if [ "${lk[$k]}" = "${J_KEYS[$i]}" ]; then j=$k; fi
        done
        if [ -n "$j" ]; then lv[j]=${J_VALS[$i]}; else lk+=("${J_KEYS[$i]}") lv+=("${J_VALS[$i]}"); fi
      done
    done < <(printf '%s\n' "${layers[@]}" | LC_ALL=C sort)
  fi
  journald_main_rule
  if [ -n "$J_MAIN_NOTE" ] && [ ! -e "$R/etc/systemd/journald.conf" ] && [ ! -L "$R/etc/systemd/journald.conf" ]; then
    for rel in run usr/local/lib usr/lib; do
      if [ -e "$R/$rel/systemd/journald.conf" ]; then
        echo "install-disk-gc: note: $J_MAIN_NOTE" >&2
        break
      fi
    done
  fi
  # The host's files: those read once this run lands, then any read only
  # now (one in /usr/lib under the layer's own name, which it will mask).
  journald_files 1
  asrc=(${J_SRC[@]+"${J_SRC[@]}"})
  for i in ${J_SRC[@]+"${!J_SRC[@]}"}; do
    if [ "${J_HOST[$i]}" = 1 ]; then hf+=("${J_SRC[$i]}") hs+=("${J_SHOW[$i]}"); fi
  done
  journald_files 0
  bsrc=(${J_SRC[@]+"${J_SRC[@]}"})
  for i in ${J_SRC[@]+"${!J_SRC[@]}"}; do
    if [ "${J_HOST[$i]}" = 1 ] && ! contains "${J_SHOW[$i]}" ${hs[@]+"${hs[@]}"}; then
      hf+=("${J_SRC[$i]}") hs+=("${J_SHOW[$i]}")
    fi
  done
  for k in ${lk[@]+"${!lk[@]}"}; do
    before=$(effective "${lk[$k]}" ${bsrc[@]+"${bsrc[@]}"})
    after=$(effective "${lk[$k]}" ${asrc[@]+"${asrc[@]}"})
    for i in ${hf[@]+"${!hf[@]}"}; do
      journald_keys "${hf[$i]}"
      key_value v "${lk[$k]}" any || continue
      entries+=("{\"file\": $(json_str "${hs[$i]}"), \"key\": $(json_str "${lk[$k]}"), \"host\": $(json_str "$v"), \"layer\": $(json_str "${lv[$k]}"), \"before\": $before, \"after\": $after}")
      if ! key_value v "${lk[$k]}"; then
        echo "install-disk-gc: note: ${hs[$i]} sets ${lk[$k]}=$v, which journald can't parse and ignores; once this run lands $after is in effect (journald_overrides)" >&2
      elif [ "$after" != "$(json_str "$v")" ]; then
        echo "install-disk-gc: note: ${hs[$i]} sets ${lk[$k]}=$v, and once this run lands $after is in effect (journald_overrides)" >&2
      fi
    done
  done
  J_OVERRIDES="["
  for i in ${entries[@]+"${!entries[@]}"}; do
    [ "$i" = 0 ] || J_OVERRIDES="$J_OVERRIDES, "
    J_OVERRIDES="$J_OVERRIDES${entries[$i]}"
  done
  J_OVERRIDES="$J_OVERRIDES]"
}

# --- report, and act ------------------------------------------------------------


if [ ${#REFUSED[@]} -gt 0 ]; then
  for why in "${REFUSED[@]}"; do echo "install-disk-gc: refused: $why" >&2; done
  emit
  exit 3
fi
journald_overrides
if [ "$APPROVE" = 0 ]; then
  if [ "$ACTION" != current ]; then
    for u in ${DROPPED_UNITS[@]+"${DROPPED_UNITS[@]}"}; do SYSTEMCTL_CALLS+=("disable --now $u"); done
    SYSTEMCTL_CALLS+=(daemon-reload)
    [ "$JRESTART" = 0 ] || SYSTEMCTL_CALLS+=("restart systemd-journald")
  fi
  emit
  exit 0
fi


# The reload comes before the marker (step 4), so an installed MANIFEST
# means it took: current has nothing to call.
if [ "$ACTION" = current ]; then
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
