#!/usr/bin/env bash
# _prune-lib.sh — what prune-plan.sh and prune.sh share: the components the
# probe knows, what each one is on this host (its packages, the units they
# ship, apt's simulation of a removal and a purge, its paths and its group),
# and the plan file that carries it. Sourced after _knob-lib.sh,
# _probe-lib.sh and _gate-lib.sh.
# The C_*, D_*, PD_*, SIM_* and PLAN_* variables are its output.
# shellcheck disable=SC2034
set -euo pipefail

prune_lib_usage() {
  cat <<'USAGE'
Usage: . _prune-lib.sh    (sourced by prune-plan.sh and prune.sh; running it
                          does nothing)

  PRUNE_COMPONENTS          the components it knows
  prune_component NAME      C_ROOTS, C_CONFIG, C_DATA, C_GROUP, and for one
                            from outside apt C_UNIT and C_BINARY; 1 for a
                            name the probe doesn't know
  read_packages             PKG_NAME, PKG_STATE: every package dpkg knows;
                            1 when it can't list them
  path_kib VAR PATH         PATH's size in KiB, as root; empty only when it
                            isn't there, and - when it is at a size du
                            couldn't read, with PATH_KIB_WHY
  units_of PACKAGE...       UNITS: the units they ship; 1 with UNITS_WHY
                            when the list couldn't be read
  purge_deletes PACKAGE...  PD_*: the lines in their purge scripts that
                            delete; a package with no postrm has none, and
                            any other failed read returns 1 with PD_WHY
  conffiles_of PACKAGE...   CONFFILES: their conffiles outside C_CONFIG that
                            exist, CONFFILES_UNSAVED those with whitespace;
                            1 with CONFFILES_WHY when unread
  pg_clusters               D_CLUSTERS: each Postgres cluster and its data,
                            or D_CLUSTERS_WHY
  derive NAME               D_*: the component as the host stands now; 1 for
                            a name it doesn't know, 2 with D_WHY for a read
                            that failed
  calendar NAME             CAL_*: the prune stage the knob declares for it
  signature VAR             the lines a plan and a fresh derive must share
  write_plan HOST COMPONENT the plan file's lines, on stdout
  read_plan FILE            PLAN_*: a plan file's lines, PLAN_BAD for the
                            rest; 1 when FILE can't be read or isn't a plan
USAGE
}

case "${0##*/}" in
  _prune-lib.sh) case "${1-}" in -h | --help) prune_lib_usage; exit 0 ;; esac ;;
esac

PRUNE_COMPONENTS="docker postgres redis nginx ollama qdrant"

# Each component the probe knows: the package globs that are it (a server,
# never a client or a library other packages use), its config and its data,
# and the group whose members it lets in. watcher's Docker removal left
# exedev in the docker group, root-equivalent the moment Docker came back
# (policy.md). Ollama and Qdrant come from outside apt: a unit and a binary.
C_ROOTS="" C_CONFIG="" C_DATA="" C_GROUP="" C_UNIT="" C_BINARY=""
# unit_show sets it by name.
U_LoadState=""
prune_component() {  # <name>
  C_ROOTS="" C_CONFIG="" C_DATA="" C_GROUP="" C_UNIT="" C_BINARY=""
  case $1 in
    docker)
      C_ROOTS='docker.io docker-ce docker-ce-cli docker-ce-rootless-extras docker-buildx-plugin docker-compose-plugin docker-compose containerd containerd.io runc'
      C_CONFIG=/etc/docker C_DATA='/var/lib/docker /var/lib/containerd' C_GROUP=docker ;;
    postgres)
      C_ROOTS='postgresql postgresql-[0-9]* postgresql-contrib postgresql-common'
      # postgresql-common's purge script deletes its createcluster.conf.
      C_CONFIG='/etc/postgresql /etc/postgresql-common' C_DATA=/var/lib/postgresql ;;
    redis)
      C_ROOTS='redis redis-server'
      C_CONFIG=/etc/redis C_DATA=/var/lib/redis ;;
    nginx)
      C_ROOTS='nginx nginx-common nginx-core nginx-full nginx-light nginx-extras libnginx-mod-*'
      C_CONFIG=/etc/nginx C_DATA='/var/www /var/log/nginx' ;;
    ollama)
      C_UNIT=ollama.service C_BINARY=/usr/local/bin/ollama
      C_DATA=/usr/share/ollama C_GROUP=ollama ;;
    qdrant)
      C_UNIT=qdrant.service C_BINARY=/usr/local/bin/qdrant
      C_CONFIG=/etc/qdrant C_DATA=/var/lib/qdrant ;;
    *) return 1 ;;
  esac
}

# Every package dpkg knows, and its state: ii installed, hi installed and
# held, rc removed with its config left. Fields split on |, which no name or
# version holds: a tab is whitespace to read, so an empty field would
# collapse.
PKG_STATE=() PKG_NAME=() PKG_VER=()
read_packages() {
  local _rp_out _rp_s _rp_n _rp_v
  PKG_STATE=() PKG_NAME=() PKG_VER=()
  # dpkg-query's own fields, not shell expansions.
  # shellcheck disable=SC2016
  capture _rp_out dpkg-query -W -f '${db:Status-Abbrev}|${Package}|${Version}\n'
  [ "$CAP_RC" -eq 0 ] || return 1
  while IFS='|' read -r _rp_s _rp_n _rp_v; do
    [ -n "$_rp_n" ] || continue
    PKG_STATE+=("${_rp_s%% *}") PKG_NAME+=("$_rp_n") PKG_VER+=("$_rp_v")
  done <<<"$_rp_out"
}

# apt's own answer to a removal or a purge: every package it would take,
# with what the request drags along. A removal that would install anything
# is no removal (SIM_INST). SIM_ORPHANS is what apt says it leaves "no
# longer required": a later autoremove's, with any it would take already.
SIM_SET=() SIM_INST="" SIM_WHY="" SIM_ORPHANS=""
apt_sim() {  # <remove|purge> <package>...
  local _as_k=$1 _as_out _as_l _as_x _as_n _as_v _as_in=0
  shift
  SIM_SET=() SIM_INST="" SIM_WHY="" SIM_ORPHANS=""
  [ "$#" -gt 0 ] || return 0
  # Never an autoremove, whatever apt.conf.d says.
  capture _as_out apt-get -s -o APT::Get::AutomaticRemove=false "$_as_k" "$@"
  if [ "$CAP_RC" -ne 0 ]; then
    SIM_WHY="apt-get -s $_as_k failed: ${CAP_ERR:-exit $CAP_RC}"
    return 1
  fi
  while IFS= read -r _as_l; do
    # Its list's lines are indented; the line after them isn't.
    if [ "$_as_in" -eq 1 ]; then
      case $_as_l in
        ' '*) SIM_ORPHANS="$SIM_ORPHANS $_as_l"; continue ;;
        *) _as_in=0 ;;
      esac
    fi
    case $_as_l in
      'The following package'*' automatically installed and '*' no longer required:')
        _as_in=1 ;;
      'Remv '* | 'Purg '*)
        read -r _as_x _as_n _as_v _as_x <<<"$_as_l" || true
        _as_v=${_as_v#[}
        _as_v=${_as_v%]}
        SIM_SET+=("$_as_n ${_as_v:--}") ;;
      'Inst '*)
        read -r _as_x _as_n _as_x <<<"$_as_l" || true
        SIM_INST="$SIM_INST $_as_n" ;;
    esac
  done <<<"$_as_out"
  SIM_INST=${SIM_INST# }
  words_of SIM_ORPHANS "$SIM_ORPHANS"
}

# The units the packages ship: sockets, timers and paths first, so none
# starts the service again once it's stopped, then services. A template's
# loaded instances stand in for it: postgresql@.service is postgresql@16-main.
# A list it couldn't read returns 1 with UNITS_WHY: no unit is never what
# a failed read says.
UNITS=() UNITS_WHY=""
units_of() {  # <package>...
  local _uo_p _uo_out _uo_f _uo_u _uo_i _uo_l _uo_x _uo_first="" _uo_last=""
  UNITS=() UNITS_WHY=""
  for _uo_p in "$@"; do
    capture _uo_out dpkg-query -L "$_uo_p"
    if [ "$CAP_RC" -ne 0 ]; then
      UNITS_WHY="dpkg-query -L $_uo_p failed: ${CAP_ERR:-exit $CAP_RC}"
      return 1
    fi
    while IFS= read -r _uo_f; do
      case $_uo_f in
        */systemd/system/*/*) continue ;;
        */systemd/system/*.service | */systemd/system/*.socket | */systemd/system/*.timer | */systemd/system/*.path) ;;
        *) continue ;;
      esac
      _uo_u=${_uo_f##*/}
      case $_uo_u in
        *@.*)
          capture _uo_l systemctl list-units --all --plain --no-legend --full -- "${_uo_u%%@*}@*.${_uo_u##*.}"
          if [ "$CAP_RC" -ne 0 ]; then
            UNITS_WHY="systemctl couldn't list $_uo_u's instances: ${CAP_ERR:-exit $CAP_RC}"
            return 1
          fi
          while read -r _uo_i _uo_x; do
            [ -n "$_uo_i" ] || continue
            in_words "$_uo_i" "$_uo_first $_uo_last" || _uo_last="$_uo_last $_uo_i"
          done <<<"$_uo_l" ;;
        *.service)
          in_words "$_uo_u" "$_uo_first $_uo_last" || _uo_last="$_uo_last $_uo_u" ;;
        *)
          in_words "$_uo_u" "$_uo_first $_uo_last" || _uo_first="$_uo_first $_uo_u" ;;
      esac
    done <<<"$_uo_out"
  done
  read -r -a UNITS <<<"$_uo_first $_uo_last" || true
}

# The lines in the packages' purge scripts that delete: each postrm, which
# dpkg runs with "purge". nginx-common's takes /var/log/nginx with it, and
# postgresql-16's drops every cluster: it sets postrm_purge_data to true
# itself before it asks, and with no terminal nothing answers, so a false
# answer set beforehand keeps nothing (measured on noble).
PRUNE_RM_RE='(^|[^[:alnum:]_-])(rm|rmdir|deluser|delgroup|userdel|groupdel)[[:space:]]'
# A package with no postrm has nothing to run: dpkg-query says "control
# file 'postrm' does not exist" (exit 2, noble). Any other failure returns
# 1 with PD_WHY, since an unread script may delete a data path.
PD_PKG=() PD_LINE=() PD_TEXT=() PD_WHY=""
purge_deletes() {  # <package>...
  local _pd_p _pd_x _pd_l _pd_n
  PD_PKG=() PD_LINE=() PD_TEXT=() PD_WHY=""
  for _pd_p in "$@"; do
    capture _pd_x dpkg-query --control-show "$_pd_p" postrm
    if [ "$CAP_RC" -ne 0 ]; then
      case $CAP_ERR in *"control file 'postrm' does not exist"*) continue ;; esac
      PD_WHY="$_pd_p's purge script couldn't be read: ${CAP_ERR:-exit $CAP_RC}"
      return 1
    fi
    _pd_n=0
    while IFS= read -r _pd_l; do
      _pd_n=$((_pd_n + 1))
      [[ $_pd_l =~ $PRUNE_RM_RE ]] || continue
      words_of _pd_l "$_pd_l"
      PD_PKG+=("$_pd_p") PD_LINE+=("$_pd_n") PD_TEXT+=("$_pd_l")
    done <<<"$_pd_x"
  done
}

# Each package's conffiles outside the component's config directories, that
# exist: a purge deletes them with the rest, so the savepoint keeps them.
# nginx-common's /etc/default/nginx and /etc/logrotate.d/nginx,
# redis-server's /etc/default/redis-server (measured on noble). A path with
# whitespace can't be one word of an action: CONFFILES_UNSAVED names it.
CONFFILE_RE='^ (/.*) ([0-9a-f]{32}|newconffile)( obsolete| remove-on-upgrade)*$'
CONFFILES="" CONFFILES_UNSAVED=() CONFFILES_WHY=""
conffiles_of() {  # <package>...: returns 1 with CONFFILES_WHY when unread
  local _co_out _co_l _co_f _co_c _co_k
  CONFFILES="" CONFFILES_UNSAVED=() CONFFILES_WHY=""
  [ "$#" -gt 0 ] || return 0
  # dpkg-query's own field, not a shell expansion.
  # shellcheck disable=SC2016
  capture _co_out dpkg-query -W -f '${Conffiles}\n' "$@"
  if [ "$CAP_RC" -ne 0 ]; then
    CONFFILES_WHY="dpkg-query couldn't read the conffiles: ${CAP_ERR:-exit $CAP_RC}"
    return 1
  fi
  while IFS= read -r _co_l; do
    [[ $_co_l =~ $CONFFILE_RE ]] || continue
    _co_f=${BASH_REMATCH[1]}
    for _co_c in $C_CONFIG; do
      case $_co_f in "$_co_c"/*) continue 2 ;; esac
    done
    case $_co_f in *[[:space:]]*)
      CONFFILES_UNSAVED+=("$_co_f")
      continue ;;
    esac
    in_words "$_co_f" "$CONFFILES" && continue
    path_kib _co_k "$_co_f"
    if [ -n "$_co_k" ]; then CONFFILES="$CONFFILES $_co_f"; fi
  done <<<"$_co_out"
  CONFFILES=${CONFFILES# }
}

# Each Postgres cluster, and where its data is. A purge drops them wherever
# they are, and which script does it decides what goes: with
# postgresql-common still installed, pg_dropcluster deletes the data
# directory wherever it is; with it purged first, postgresql-16's own
# fallback deletes /var/lib/postgresql/<version>/<cluster>, or its pgdata
# link's target, and a data_directory elsewhere stays (both measured on
# noble). So a purge names every cluster's data. pg_lsclusters reads them
# while postgresql-common is installed; after a remove, each cluster's own
# config is read as both scripts read it: its pgdata link, else its
# data_directory, else the default.
PG_DATADIR_SED='s/^[[:space:]]*data_directory[[:space:]]*=[[:space:]]*'"'"'\([^'"'"']*\)'"'"'.*/\1/p'
D_CLUSTERS="" D_CLUSTERS_WHY=""
pg_clusters() {
  local _pc_o _pc_v _pc_c _pc_x _pc_d
  D_CLUSTERS="" D_CLUSTERS_WHY=""
  if have pg_lsclusters; then
    capture _pc_o pg_lsclusters -h
    if [ "$CAP_RC" -ne 0 ]; then
      D_CLUSTERS_WHY="pg_lsclusters couldn't be read (${CAP_ERR:-exit $CAP_RC})"
      return 0
    fi
    while read -r _pc_v _pc_c _pc_x _pc_x _pc_x _pc_d _pc_x; do
      [ -n "$_pc_v" ] || continue
      D_CLUSTERS="$D_CLUSTERS$_pc_v/$_pc_c $_pc_d"$'\n'
    done <<<"$_pc_o"
    return 0
  fi
  if [ "$P_PRIV" = none ]; then
    D_CLUSTERS_WHY="pg_lsclusters isn't on PATH, and each cluster's config needs root to read"
    return 0
  fi
  # The script runs as root, in sh: its expansions are its own.
  # shellcheck disable=SC2016
  capture _pc_o as_root sh -c '
    for c in /etc/postgresql/*/*/postgresql.conf; do
      [ -f "$c" ] || continue
      d=${c%/postgresql.conf} t=""
      if [ -L "$d/pgdata" ]; then t=$(readlink -f "$d/pgdata"); fi
      [ -n "$t" ] || t=$(sed -n "$1" "$c" | tail -n 1)
      printf "%s %s\n" "${d#/etc/postgresql/}" "${t:-/var/lib/postgresql/${d#/etc/postgresql/}}"
    done' sh "$PG_DATADIR_SED"
  if [ "$CAP_RC" -ne 0 ]; then
    D_CLUSTERS_WHY="the clusters' config couldn't be read (${CAP_ERR:-exit $CAP_RC})"
    return 0
  fi
  if [ -n "$_pc_o" ]; then D_CLUSTERS="$_pc_o"$'\n'; fi
}

# A path's size in KiB, read as root where it can be: data under a 0700
# directory can't be measured from outside it. Empty when it doesn't exist.
# Empty only for a path that isn't there: GNU du says "cannot access '<path>':
# No such file or directory" of the path itself (9.4, noble). Any other
# failure, such as a file gone mid-walk, which a live data directory
# often has, leaves it there at a size unknown, -, with PATH_KIB_WHY set:
# a path taken as absent would drop out of what a purge must name. Each
# such failure is kept in SIZES_UNREAD too, which derive resets.
PATH_KIB_WHY="" SIZES_UNREAD=""
path_kib() {  # <var> <path>
  local _pk=""
  PATH_KIB_WHY=""
  if [ "$P_PRIV" != none ]; then
    capture _pk as_root du -sk "$2"
    if [ "$CAP_RC" -eq 0 ]; then
      _pk=${_pk%%[[:space:]]*}
      is_int "$_pk" || { _pk=-; PATH_KIB_WHY="du -sk $2 printed no size"; }
    else
      case $CAP_ERR in
        *"cannot access '$2': No such file or directory"*) _pk="" ;;
        *) _pk=- PATH_KIB_WHY="du -sk $2 failed: ${CAP_ERR:-exit $CAP_RC}" ;;
      esac
    fi
    if [ -n "$PATH_KIB_WHY" ]; then SIZES_UNREAD="$SIZES_UNREAD$PATH_KIB_WHY"$'\n'; fi
  elif [ -e "$P_ROOT$2" ]; then
    # Without root it exists, at a size unknown.
    _pk=-
  fi
  printf -v "$1" '%s' "$_pk"
}

# The component as the host stands now. D_REMOVE and D_PURGE hold
# "<package> <version>" for each package apt would take. D_HELD names those
# apt-mark holds: apt-get -s takes them, but apt-get -y refuses to
# ("Held packages were changed and -y was used without
# --allow-change-held-packages", measured on noble).
D_ROOTS="" D_RESIDUE="" D_UNITS=() D_REMOVE=() D_PURGE=() D_INST="" D_WHY="" D_HELD="" D_ORPHANS=""
D_CONFIG="" D_DATA="" D_SIZES="" D_MEMBERS="" D_GROUP_EXISTS=0 D_UNPACKAGED=0 D_PRESENT=0
D_CONFFILES="" D_UNSAVED=()
derive() {  # <name>
  local _d_i _d_p _d_u _d_k _d_names="" _d_line _d_pn=""
  D_ROOTS="" D_RESIDUE="" D_UNITS=() D_REMOVE=() D_PURGE=() D_INST="" D_WHY="" D_HELD="" D_ORPHANS=""
  D_CONFIG="" D_DATA="" D_SIZES="" D_MEMBERS="" D_GROUP_EXISTS=0 D_UNPACKAGED=0 D_PRESENT=0
  D_CONFFILES="" D_UNSAVED=() D_CLUSTERS="" D_CLUSTERS_WHY="" SIZES_UNREAD=""
  prune_component "$1" || return 1
  if [ -n "$C_UNIT" ]; then
    D_UNPACKAGED=1
    _d_u=""
    if unit_show "$C_UNIT" LoadState; then _d_u=$U_LoadState; fi
    case $_d_u in '' | not-found) _d_u="" ;; *) D_UNITS=("$C_UNIT") ;; esac
    path_kib _d_k "$C_BINARY"
    if [ -n "$_d_k" ]; then D_SIZES="$D_SIZES$C_BINARY $_d_k"$'\n'; fi
    if [ -n "$_d_u$_d_k" ]; then D_PRESENT=1; fi
  else
    if ! read_packages; then
      D_WHY="dpkg-query couldn't list the packages: ${CAP_ERR:-exit $CAP_RC}"
      return 2
    fi
    for _d_i in ${PKG_NAME[@]+"${!PKG_NAME[@]}"}; do
      glob_match "${PKG_NAME[$_d_i]}" "$C_ROOTS" || continue
      case ${PKG_STATE[$_d_i]} in
        ii | hi) D_ROOTS="$D_ROOTS ${PKG_NAME[$_d_i]}" ;;
        rc) D_RESIDUE="$D_RESIDUE ${PKG_NAME[$_d_i]}" ;;
      esac
    done
    D_ROOTS=${D_ROOTS# } D_RESIDUE=${D_RESIDUE# }
    if [ -n "$D_ROOTS$D_RESIDUE" ]; then D_PRESENT=1; fi
    # Word lists, each a package name.
    # shellcheck disable=SC2086
    if ! apt_sim remove $D_ROOTS; then
      D_WHY=$SIM_WHY
      return 2
    fi
    D_REMOVE=(${SIM_SET[@]+"${SIM_SET[@]}"}) D_INST=$SIM_INST
    # Word lists, each a package name.
    # shellcheck disable=SC2086
    if ! apt_sim purge $D_ROOTS $D_RESIDUE; then
      D_WHY=$SIM_WHY
      return 2
    fi
    D_PURGE=(${SIM_SET[@]+"${SIM_SET[@]}"}) D_INST="$D_INST $SIM_INST" D_ORPHANS=$SIM_ORPHANS
    D_INST=${D_INST# }
    D_INST=${D_INST% }
    for _d_line in ${D_REMOVE[@]+"${D_REMOVE[@]}"}; do _d_names="$_d_names ${_d_line%% *}"; done
    for _d_line in ${D_PURGE[@]+"${D_PURGE[@]}"}; do
      for _d_i in ${PKG_NAME[@]+"${!PKG_NAME[@]}"}; do
        [ "${PKG_NAME[$_d_i]}" = "${_d_line%% *}" ] || continue
        case ${PKG_STATE[$_d_i]} in h*) in_words "${_d_line%% *}" "$D_HELD" || D_HELD="$D_HELD ${_d_line%% *}" ;; esac
      done
    done
    D_HELD=${D_HELD# }
    for _d_line in ${D_PURGE[@]+"${D_PURGE[@]}"}; do _d_pn="$_d_pn ${_d_line%% *}"; done
    # A word list, each a package name.
    # shellcheck disable=SC2086
    if ! conffiles_of $_d_pn; then
      D_WHY=$CONFFILES_WHY
      return 2
    fi
    D_CONFFILES=$CONFFILES D_UNSAVED=(${CONFFILES_UNSAVED[@]+"${CONFFILES_UNSAVED[@]}"})
    # Word lists, each a package name.
    # shellcheck disable=SC2086
    if ! units_of $_d_names; then
      D_WHY=$UNITS_WHY
      return 2
    fi
    D_UNITS=(${UNITS[@]+"${UNITS[@]}"})
    if [ "$1" = postgres ] && [ "$D_PRESENT" -eq 1 ]; then pg_clusters; fi
  fi
  for _d_p in $C_CONFIG $C_DATA; do
    path_kib _d_k "$_d_p"
    [ -n "$_d_k" ] || continue
    D_SIZES="$D_SIZES$_d_p $_d_k"$'\n'
    if in_words "$_d_p" "$C_CONFIG"; then D_CONFIG="$D_CONFIG $_d_p"; else D_DATA="$D_DATA $_d_p"; fi
  done
  D_CONFIG=${D_CONFIG# } D_DATA=${D_DATA# }
  if [ -n "$C_GROUP" ]; then
    capture _d_line getent group "$C_GROUP"
    if [ "$CAP_RC" -eq 0 ] && [ -n "$_d_line" ]; then
      D_GROUP_EXISTS=1
      _d_line=${_d_line##*:}
      D_MEMBERS=${_d_line//,/ }
    fi
  fi
}

# The stage the knob declares, as policy.md's exceptions: keep:<name> while
# the owner keeps it, whatever stage the prune reached, else purged:,
# removed: or disabled:. CAL_PASSED is 1 once its review-by date has passed:
# the soak is over, and the next stage may run. An earlier review-by date
# shortens a soak.
CAL_STAGE="" CAL_PASSED=0 CAL_REVIEW="" CAL_LINE=""
calendar() {  # <name>
  local _cl_x _cl_r
  local -a _cl_f=()
  CAL_STAGE=none CAL_PASSED=0 CAL_REVIEW="" CAL_LINE=""
  for _cl_x in keep purged removed disabled; do
    for _cl_r in ${KNOB_EXCEPTION[@]+"${KNOB_EXCEPTION[@]}"}; do
      IFS=$KNOB_US read -r -a _cl_f <<<"$_cl_r"
      [ "${_cl_f[0]}" = "$_cl_x:$1" ] || continue
      # A keep that passed its review-by keeps nothing: the stage lines say
      # where the prune is.
      if [ "$_cl_x" = keep ] && [ "${_cl_f[3]}" = 1 ]; then continue; fi
      CAL_STAGE=$_cl_x CAL_REVIEW=${_cl_f[1]} CAL_PASSED=${_cl_f[3]} CAL_LINE=${_cl_f[4]}
      return 0
    done
  done
}

# What a plan binds: the packages, the units, the conffiles the savepoint
# takes, Postgres's clusters and their data, and the group's members. A
# stage refuses when a fresh derive gives other lines.
signature() {  # <var>
  local _sg_s="" _sg_x _sg_y
  for _sg_x in $D_ROOTS; do _sg_s="${_sg_s}root $_sg_x"$'\n'; done
  for _sg_x in $D_RESIDUE; do _sg_s="${_sg_s}residue $_sg_x"$'\n'; done
  for _sg_x in ${D_UNITS[@]+"${D_UNITS[@]}"}; do _sg_s="${_sg_s}unit $_sg_x"$'\n'; done
  for _sg_x in ${D_REMOVE[@]+"${D_REMOVE[@]}"}; do _sg_s="${_sg_s}remove ${_sg_x%% *}"$'\n'; done
  for _sg_x in ${D_PURGE[@]+"${D_PURGE[@]}"}; do _sg_s="${_sg_s}purge ${_sg_x%% *}"$'\n'; done
  for _sg_x in $D_CONFFILES; do _sg_s="${_sg_s}conffile $_sg_x"$'\n'; done
  while read -r _sg_x _sg_y; do
    if [ -n "$_sg_x" ]; then _sg_s="${_sg_s}cluster $_sg_x $_sg_y"$'\n'; fi
  done <<<"$D_CLUSTERS"
  for _sg_x in $D_MEMBERS; do _sg_s="${_sg_s}member $C_GROUP $_sg_x"$'\n'; done
  printf -v "$1" '%s' "$_sg_s"
}

# The plan file: one record per line, the derive it was written from.
PLAN_HEADER="patching-hosts prune plan"
write_plan() {  # <host> <component>
  local _wp_x _wp_sig
  printf '%s\n' "$PLAN_HEADER"
  printf 'component %s\nhost %s\ntaken %s\n' "$2" "$1" "$P_NOW"
  if [ "$D_UNPACKAGED" -eq 1 ]; then printf 'unpackaged %s %s\n' "$C_UNIT" "$C_BINARY"; fi
  signature _wp_sig
  printf '%s' "$_wp_sig"
  for _wp_x in ${D_REMOVE[@]+"${D_REMOVE[@]}"}; do printf 'version %s\n' "$_wp_x"; done
  for _wp_x in $D_CONFIG; do printf 'config %s\n' "$_wp_x"; done
  for _wp_x in $D_DATA; do printf 'data %s\n' "$_wp_x"; done
  if [ "$D_GROUP_EXISTS" -eq 1 ]; then printf 'group %s\n' "$C_GROUP"; fi
}

PLAN_COMPONENT="" PLAN_HOST="" PLAN_TAKEN="" PLAN_SIG="" PLAN_CONFIG="" PLAN_DATA=""
PLAN_GROUP="" PLAN_UNPACKAGED=0 PLAN_VERSIONS="" PLAN_BAD="" PLAN_CONFFILES="" PLAN_CLUSTERS=""
read_plan() {  # <file>: returns 1 when it can't be read or isn't a plan
  local _rd_t _rd_l _rd_k _rd_a _rd_b _rd_n=0
  PLAN_COMPONENT="" PLAN_HOST="" PLAN_TAKEN="" PLAN_SIG="" PLAN_CONFIG="" PLAN_DATA=""
  PLAN_GROUP="" PLAN_UNPACKAGED=0 PLAN_VERSIONS="" PLAN_BAD="" PLAN_CONFFILES="" PLAN_CLUSTERS=""
  [ -f "$1" ] && [ -r "$1" ] || return 1
  _rd_t=$(cat -- "$1") || return 1
  while IFS= read -r _rd_l; do
    _rd_n=$((_rd_n + 1))
    if [ "$_rd_n" -eq 1 ]; then
      [ "$_rd_l" = "$PLAN_HEADER" ] || return 1
      continue
    fi
    read -r _rd_k _rd_a _rd_b <<<"$_rd_l" || true
    case $_rd_k:$_rd_b in
      component:) PLAN_COMPONENT=$_rd_a ;;
      host:) PLAN_HOST=$_rd_a ;;
      taken:) PLAN_TAKEN=$_rd_a ;;
      root: | residue: | unit: | remove: | purge:) PLAN_SIG="$PLAN_SIG$_rd_l"$'\n' ;;
      conffile:)
        PLAN_SIG="$PLAN_SIG$_rd_l"$'\n'
        PLAN_CONFFILES="$PLAN_CONFFILES $_rd_a" ;;
      member:?*) PLAN_SIG="$PLAN_SIG$_rd_l"$'\n' ;;
      cluster:?*)
        PLAN_SIG="$PLAN_SIG$_rd_l"$'\n'
        PLAN_CLUSTERS="$PLAN_CLUSTERS$_rd_a $_rd_b"$'\n' ;;
      version:?*) PLAN_VERSIONS="$PLAN_VERSIONS$_rd_a $_rd_b"$'\n' ;;
      config:) PLAN_CONFIG="$PLAN_CONFIG $_rd_a" ;;
      data:) PLAN_DATA="$PLAN_DATA $_rd_a" ;;
      group:) PLAN_GROUP=$_rd_a ;;
      unpackaged:?*) PLAN_UNPACKAGED=1 ;;
      *) PLAN_BAD="${PLAN_BAD:+$PLAN_BAD; }line $_rd_n" ;;
    esac
  done <<<"$_rd_t"
  PLAN_CONFIG=${PLAN_CONFIG# } PLAN_DATA=${PLAN_DATA# } PLAN_CONFFILES=${PLAN_CONFFILES# }
}
