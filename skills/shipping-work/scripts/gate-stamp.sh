#!/usr/bin/env bash
# gate-stamp.sh
# Records that a gate passed on an exact tree, so a later gate on the same tree
# can reuse the pass instead of running the suite again (#537).
#
# The pre-commit hook runs the full suite on what is being committed; the ship
# gate then ran it again on the same files with no record that it had already
# passed. A stamp is that record. It is keyed on the TREE, not the commit, so
# it survives what leaves the files unchanged — an amended message, a rebase or
# a merge that produces the same tree — and a hook's pass on the index tree is
# the ship gate's pass on HEAD^{tree} once it is committed.
#
# WHAT THE KEY COVERS
#
#   tree      `git write-tree` (--index: what is being committed) or HEAD^{tree}
#   os        `uname -sm`
#   env       each --env pattern's matching variables, name and value
#   extra     each --extra string, verbatim (a caller's installed-package list)
#   inputs    the content hash of each untracked input (decision D5):
#             GATE_STAMP_INPUTS (colon-separated), else .skills/gate-stamp-inputs
#             (one path or glob per line, #-comments; REPLACES the default),
#             else `.env`. A missing input is hashed as absent, so creating it
#             later invalidates the stamp. Only hashes enter the key — never a
#             value — and the record names the inputs, not their contents.
#
# A tree is only stampable when the files on disk ARE that tree: no tracked
# change against it, and no untracked, unignored file (a nested repository or
# worktree, which git lists with a trailing slash, is not part of the tree and
# is ignored). Otherwise `key` exits 3 and names what is in the way, so the
# caller runs the suite and writes nothing. A stamp can only ever cost a run,
# never fake a pass.
#
# Stamps live under <git-common-dir>/gate-stamps/, shared by every worktree of
# the repository; the newest 500 are kept.
#
# Usage: bash "<gate-stamp.sh>" key [--index] [--explain] [--env PATTERN]... [--extra TEXT]...
#        bash "<gate-stamp.sh>" check KEY
#        bash "<gate-stamp.sh>" write KEY [--label TEXT] [--seconds N]
#        bash "<gate-stamp.sh>" list [N]
set -euo pipefail

KEEP=500

usage() {
  echo "Usage: bash \"$0\" key [--index] [--explain] [--env PATTERN]... [--extra TEXT]..."
  echo "       bash \"$0\" check KEY"
  echo "       bash \"$0\" write KEY [--label TEXT] [--seconds N]"
  echo "       bash \"$0\" list [N]"
  echo ""
  echo "Records that a gate passed on an exact tree, so a later gate on the same"
  echo "tree reuses the pass instead of running again."
  echo ""
  echo "  key    print the stamp key for HEAD^{tree} (or, with --index, the tree"
  echo "         being committed), the OS, the --env variables, the --extra text"
  echo "         and the untracked inputs' content hashes. --explain prints"
  echo "         what went into the key on stderr, to diagnose a missed reuse"
  echo "  check  exit 0 and print the record if KEY has a stamp; exit 1 if not"
  echo "  write  record a pass for KEY"
  echo "  list   print the newest N records (default 20), tab-separated"
  echo ""
  echo "Untracked inputs: GATE_STAMP_INPUTS (colon-separated), else"
  echo ".skills/gate-stamp-inputs (one path or glob per line), else .env."
  echo "GATE_STAMP=off makes every check a miss and every write a no-op."
  echo ""
  echo "Exit codes:"
  echo "  0  done (check: a stamp exists)"
  echo "  1  check: no stamp for KEY"
  echo "  2  could not run: bad arguments, or not inside a git repository"
  echo "  3  key: the files on disk are not the tree, so nothing can be stamped"
}

die() {
  echo "ERROR: $*" >&2
  exit 2
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
CMD=$1
shift
if [[ "$CMD" == "--help" ]]; then
  usage
  exit 0
fi

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git repository"
COMMON=$(git rev-parse --git-common-dir) || die "git rev-parse --git-common-dir failed"
STAMPS="$COMMON/gate-stamps"
cd "$ROOT"

disabled() {
  [[ "${GATE_STAMP:-}" == "off" ]]
}

# A key names a file under $STAMPS, so anything but hex is refused before it
# is used as a path — by check as much as by write, since a hit there means
# "skip the suite" (CR 1391).
require_key() {
  [[ "$1" =~ ^[0-9a-f]{40,64}$ ]] || die "'$1' is not a stamp key"
}

# The untracked inputs, one pattern per line.
input_patterns() {
  if [[ -n "${GATE_STAMP_INPUTS:-}" ]]; then
    tr ':' '\n' <<<"$GATE_STAMP_INPUTS"
  elif [[ -f .skills/gate-stamp-inputs ]]; then
    sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' .skills/gate-stamp-inputs
  else
    echo ".env"
  fi
}

key() {
  local index=0 explain=0 tree env_pats=() extras=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --index) index=1; shift ;;
      --explain) explain=1; shift ;;
      --env) [[ $# -ge 2 ]] || die "--env needs a pattern"; env_pats+=("$2"); shift 2 ;;
      --extra) [[ $# -ge 2 ]] || die "--extra needs a value"; extras+=("$2"); shift 2 ;;
      *) die "unknown key argument '$1'" ;;
    esac
  done

  # Is what is on disk the tree? Each probe's own exit code is captured: a
  # failing git must not read as "no difference".
  local rc=0
  if [[ "$index" -eq 1 ]]; then
    git diff --quiet -- || rc=$?
  else
    git diff --quiet HEAD -- || rc=$?
  fi
  case "$rc" in
    0) ;;
    1) echo "gate-stamp: tracked files differ from the tree — not stampable" >&2; exit 3 ;;
    *) die "git diff failed (exit $rc)" ;;
  esac

  local others others_rc=0
  others=$(git ls-files --others --exclude-standard) || others_rc=$?
  [[ "$others_rc" -eq 0 ]] || die "git ls-files --others failed (exit $others_rc)"
  others=$(grep -v '/$' <<<"$others" || true)
  if [[ -n "$others" ]]; then
    echo "gate-stamp: untracked files are present — not stampable:" >&2
    head -5 <<<"$others" | sed 's/^/  /' >&2
    exit 3
  fi

  if [[ "$index" -eq 1 ]]; then
    tree=$(git write-tree) || die "git write-tree failed"
  else
    tree=$(git rev-parse 'HEAD^{tree}') || die "HEAD has no tree"
  fi

  local material
  material=$(
    echo "tree $tree"
    echo "os $(uname -sm)"
    local pat name seen
    for pat in "${env_pats[@]+"${env_pats[@]}"}"; do
      seen=0
      while IFS= read -r name; do
        # The pattern is a glob on purpose: --env '*_REQUIRED'.
        # shellcheck disable=SC2053
        if [[ "$name" == $pat ]]; then
          echo "env $name=${!name}"
          seen=1
        fi
      done < <(compgen -e | LC_ALL=C sort)  # unhardened: compgen is a builtin and cannot fail
      if [[ "$seen" -eq 0 ]]; then
        echo "env $pat unset"
      fi
    done
    local extra
    for extra in "${extras[@]+"${extras[@]}"}"; do
      echo "extra $extra"
    done
    local p f matched
    while IFS= read -r p; do
      [[ -n "$p" ]] || continue
      matched=0
      shopt -s nullglob dotglob
      # Unquoted on purpose: a pattern is one line, and its glob expansion is
      # the point (a path with spaces needs a glob character, e.g. `my?file`).
      # shellcheck disable=SC2206
      local hits=($p)
      shopt -u nullglob dotglob
      for f in "${hits[@]+"${hits[@]}"}"; do
        if [[ -d "$f" ]]; then
          while IFS= read -r sub; do
            echo "input $sub $(git hash-object --no-filters -- "$sub")"
            matched=1
          done < <(find "$f" -type f | LC_ALL=C sort)  # unhardened: an unreadable input dir hashes as fewer files, and the stamp then misses, never passes
        elif [[ -f "$f" ]]; then
          echo "input $f $(git hash-object --no-filters -- "$f")"
          matched=1
        fi
      done
      if [[ "$matched" -eq 0 ]]; then
        echo "input $p absent"
      fi
    done < <(input_patterns)  # unhardened: input_patterns reads a file this script just tested for
  )
  if [[ "$explain" -eq 1 ]]; then
    printf 'gate-stamp: %s\n' "${material//$'\n'/$'\n'gate-stamp: }" >&2
  fi
  git hash-object --stdin <<<"$material"
}

check() {
  [[ $# -eq 1 ]] || die "check takes exactly one KEY"
  require_key "$1"
  if disabled; then
    echo "gate-stamp: GATE_STAMP=off — not reusing any pass" >&2
    exit 1
  fi
  if [[ -f "$STAMPS/$1" ]]; then
    cat "$STAMPS/$1"
    exit 0
  fi
  exit 1
}

write() {
  [[ $# -ge 1 ]] || die "write needs a KEY"
  local k=$1 label="" seconds=""
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) [[ $# -ge 2 ]] || die "--label needs a value"; label=$2; shift 2 ;;
      --seconds) [[ $# -ge 2 ]] || die "--seconds needs a value"; seconds=$2; shift 2 ;;
      *) die "unknown write argument '$1'" ;;
    esac
  done
  require_key "$k"
  if disabled; then
    exit 0
  fi
  mkdir -p "$STAMPS"
  local tmp
  tmp=$(mktemp "$STAMPS/.tmp.XXXXXX")
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${seconds:--}" "${label:--}" "$k" >"$tmp" \
    || { rm -f "$tmp"; die "could not write the stamp"; }
  mv "$tmp" "$STAMPS/$k"
  # Keep the newest $KEEP. ls -t is portable across BSD and GNU, and the names
  # are hex keys, so the ls-parsing hazard SC2012 warns about cannot occur.
  # shellcheck disable=SC2012
  ls -t "$STAMPS" | tail -n +$((KEEP + 1)) | while IFS= read -r old; do
    rm -f "${STAMPS:?}/$old"
  done
}

list() {
  local n=${1:-20}
  [[ "$n" =~ ^[0-9]+$ ]] || die "list takes a number"
  [[ -d "$STAMPS" ]] || exit 0
  # Hex-only filenames: the ls-parsing hazard SC2012 warns about cannot occur.
  # shellcheck disable=SC2012
  ls -t "$STAMPS" | head -n "$n" | while IFS= read -r f; do
    cat "$STAMPS/$f"
  done
}

case "$CMD" in
  key) key "$@" ;;
  check) check "$@" ;;
  write) write "$@" ;;
  list) list "$@" ;;
  *) echo "ERROR: unknown command '$CMD'" >&2; usage >&2; exit 2 ;;
esac
