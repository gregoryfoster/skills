#!/usr/bin/env bash
# _context-lib.sh — measurement primitives shared by curating-context's scripts.
#
# Sourced, not run. It exists because measure-context.sh, context-budget-guard.sh
# and context-delta.sh must agree, to the token, on four things: the
# bytes-per-token ratio, which subtrees are archival, where reference docs live,
# and how a symlinked policy file is compared against git. When those lived as
# copies they drifted — the bytes/4 correction had to land in three places and a
# fourth copy was missed, which made a section census contradict its own file
# total by 38%. The skill's rubric calls verbatim duplication warrant #1 for
# deletion; this is that warrant applied to the skill's own scripts.
#
# Callers source it via the bootstrap documented in references/write-guard-hook.md,
# which resolves the symlink chain first: the guard is installed as a symlink into
# .claude/hooks/, so ${BASH_SOURCE[0]}'s dirname holds no library.
set -euo pipefail

usage() {
  cat <<'USAGE'
_context-lib.sh — shared measurement primitives for curating-context

This file is a library. Source it; do not run it:

  . "<dir>/_context-lib.sh"

Provides:
  ctx_read_num_knob <override> <env> <file> <default>
      Numeric knob lookup: override, then env var, then a single-line file,
      then the default. Non-numeric content falls back to the default.

  ctx_read_str_knob <override> <env> <file> <default>
      String knob lookup, same precedence. Strips a leading ./ and a trailing
      slash; rejects an absolute path in favour of the default.

  ctx_docs_dir <root> [override]
      Reference-doc root: override, then CONTEXT_DOCS_DIR, then
      <root>/.skills/context-docs-dir, then "docs".

  ctx_bytes_per_token_x100 <root>
      Bytes per token times 100. Default 270; a plausible ratio in
      <root>/.skills/context-token-ratio wins. Assign the result to
      CTX_BPT_X100 before calling ctx_est_from_bytes.

  ctx_est_from_bytes <bytes>
      Offline token estimate, using CTX_BPT_X100.

  ctx_is_archival <path>
      True when any path component names an archival subtree. Reads
      CTX_ARCHIVAL, which defaults to CTX_ARCHIVAL_DEFAULT.

  ctx_resolve_rel <root> <repo-relative-path>
      Follow a symlink chain to its real repo-relative path. Empty when the
      chain leaves the repo.

  ctx_prev_bytes <ref> <repo-relative-path>
      Byte count of the committed version at <ref>, or empty when there is no
      comparable one — notably when the blob is a symlink, whose content is a
      path rather than the file.

Exit codes:
  0  always (this help)
USAGE
}

# Only honour --help when executed directly. When sourced, $0 and $1 belong to
# the CALLER, so an unguarded check would exit the caller whenever its own first
# argument happened to be --help.
case "${0##*/}" in
  _context-lib.sh)
    case "${1-}" in
      -h|--help) usage; exit 0 ;;
    esac
    ;;
esac

# Dated snapshots, not live context: a since-moved path inside a plan is a
# correct historical record, so counting these as orphans or dead links buries
# the live signal. Matched at any depth, because vendored skill trees nest them
# (docs/superpowers/plans/) and a depth-1 test reports every one as a live orphan.
CTX_ARCHIVAL_DEFAULT="plans specs research audits archive"
CTX_ARCHIVAL="${CTX_ARCHIVAL:-$CTX_ARCHIVAL_DEFAULT}"

# Bytes per token, times 100 so bash's integer-only arithmetic can carry it.
# 270 is measured: across 16 markdown files in this cohort (policy files,
# reference docs, READMEs) the real ratio sits between 2.40 and 2.69, tightly
# enough that one constant serves. The conventional bytes/4 heuristic
# under-reports this content by ~60% — it is calibrated for flowing prose, not
# for markdown dense with paths, flags, code fences and tables — and a budget
# checked against it is 60% too lenient.
CTX_BPT_DEFAULT_X100=270
CTX_BPT_X100="${CTX_BPT_X100:-$CTX_BPT_DEFAULT_X100}"

ctx_read_num_knob() {
  local override="${1-}" envval="${2-}" file="${3-}" fallback="${4-}" v=""
  if [ -n "$override" ]; then v="$override"
  elif [ -n "$envval" ]; then v="$envval"
  elif [ -n "$file" ] && [ -f "$file" ]; then
    v="$(head -1 "$file" 2>/dev/null | tr -dc '0-9')"
  fi
  case "$v" in
    ''|*[!0-9]*) printf '%s' "$fallback" ;;
    *) printf '%s' "$v" ;;
  esac
}

ctx_read_str_knob() {
  local override="${1-}" envval="${2-}" file="${3-}" fallback="${4-}" v=""
  if [ -n "$override" ]; then v="$override"
  elif [ -n "$envval" ]; then v="$envval"
  elif [ -n "$file" ] && [ -f "$file" ]; then
    v="$(head -1 "$file" 2>/dev/null | tr -d '[:space:]')"
  fi
  [ -n "$v" ] || v="$fallback"
  v="${v#./}"; v="${v%/}"
  case "$v" in
    ''|/*) printf '%s' "$fallback" ;;
    *) printf '%s' "$v" ;;
  esac
}

ctx_docs_dir() {
  # The knob is what keeps the weekly run and both continuous surfaces — which
  # have no flags — looking at one tree. Without it a repo keeping references
  # elsewhere gets a correct measurement and two surfaces that silently classify
  # nothing.
  local root="$1" override="${2-}"
  ctx_read_str_knob "$override" "${CONTEXT_DOCS_DIR-}" \
    "$root/.skills/context-docs-dir" docs
}

ctx_bytes_per_token_x100() {
  # measure-context.sh --exact writes the repo's observed ratio to
  # .skills/context-token-ratio; when present and plausible it wins.
  local root="$1" r w f out="$CTX_BPT_DEFAULT_X100"
  if [ -f "$root/.skills/context-token-ratio" ]; then
    r="$(head -1 "$root/.skills/context-token-ratio" 2>/dev/null | tr -dc '0-9.')"
    case "$r" in
      ''|.*|*.*.*) ;;
      # The literal 1 prefix on the fractional part stops a leading zero being
      # read as octal ("08" would abort under set -e); the -100 removes it again.
      *.*) w="${r%%.*}"; f="${r#*.}00"
           out=$(( ${w:-0} * 100 + 1${f:0:2} - 100 )) ;;
      *) out=$(( r * 100 )) ;;
    esac
    [ "$out" -ge 100 ] || out="$CTX_BPT_DEFAULT_X100"
  fi
  printf '%s' "$out"
}

ctx_est_from_bytes() {
  echo $(( $1 * 100 / CTX_BPT_X100 ))
}

ctx_is_archival() {
  local p="$1" name
  for name in $CTX_ARCHIVAL; do
    [ -n "$name" ] || continue
    case "/$p/" in
      */"$name"/*) return 0 ;;
    esac
  done
  return 1
}

ctx_resolve_rel() {
  # The cohort norm is CLAUDE.md -> ./AGENTS.md in every member repo, and Claude
  # Code's `#` memory shortcut writes by the CLAUDE.md name. `wc -c` follows the
  # link but `git show HEAD:CLAUDE.md` does not — it returns the link target
  # STRING, eleven bytes. Comparing live content against that pins the previous
  # size near zero, makes every edit look like growth, and turns a measured
  # reduction into a reported gain. Resolve before measuring.
  local root="$1" p="$2" t d abs n=0
  while [ -L "$p" ] && [ "$n" -lt 10 ]; do
    t="$(readlink "$p" 2>/dev/null)" || break
    case "$t" in
      /*) p="$t" ;;
      *) d="$(dirname "$p")"; p="${d%/}/$t" ;;
    esac
    n=$(( n + 1 ))
  done
  d="$(cd "$(dirname "$p")" 2>/dev/null && pwd -P)" || return 0
  abs="$d/$(basename "$p")"
  case "$abs" in
    "$root"/*) printf '%s' "${abs#"$root"/}" ;;
  esac
}

# Set by ctx_prev_bytes when it declined to compare, so a caller with somewhere
# to put diagnostics can explain the zero. A return channel rather than a print:
# the library cannot know whether its caller's stdout is a JSON hook reply, a
# report table, or a log file.
CTX_PREV_NOTE=""

# CTX_PREV_NOTE is this function's second return value, read by callers and
# never within this file — which is exactly what SC2034 reports. A directive
# cannot sit in front of an individual case branch (SC1124), and putting one
# there silently breaks parsing of the whole library, so it goes here.
# shellcheck disable=SC2034
ctx_prev_bytes() {
  # A 120000-mode blob is a symlink, whose content is the target path rather
  # than the file — the mirror of the case ctx_resolve_rel handles, reached when
  # a path was a symlink at the ref and is a real file now. Report no comparable
  # version rather than eleven bytes of content.
  local ref="$1" rel="$2" mode
  CTX_PREV_NOTE=""
  mode="$(git ls-tree "$ref" -- "$rel" 2>/dev/null | awk '{print $1; exit}')" || return 0
  case "$mode" in
    100644|100755) git show "$ref:$rel" 2>/dev/null | LC_ALL=C wc -c 2>/dev/null | tr -d ' ' ;;
    '') ;;
    *) CTX_PREV_NOTE="$ref:$rel is mode $mode, not a regular file; treating as uncommitted" ;;
  esac
}
