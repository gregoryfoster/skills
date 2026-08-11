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

# Namespaced, unlike every other script's plain `usage`. Sourcing this file into
# a caller that defines its own `usage` would otherwise silently replace it, and
# the caller's --help would print the library's help instead of its own. That is
# only invisible because all callers happen to parse arguments before sourcing;
# the first one to call usage() afterwards — an unknown-argument branch, say —
# would get the wrong text with nothing to indicate why.
ctx_lib_usage() {
  cat <<'USAGE'
_context-lib.sh — shared measurement primitives for curating-context

This file is a library. Source it; do not run it:

  . "<dir>/_context-lib.sh"

Provides:
  ctx_read_num_knob <override> <env> <file> <default>
      Numeric knob lookup: override, then env var, then a single-line file,
      then the default. The file's first whitespace-delimited token must be a
      bare integer ("6000 # tokens" is fine, "v2 6000" is not); anything else
      warns on stderr and uses the default.

  ctx_read_str_knob <override> <env> <file> <default>
      String knob lookup, same precedence. Strips a leading ./ and a trailing
      slash; rejects an absolute path, an empty value and a value containing
      whitespace in favour of the default, warning on stderr when the file was
      the source.

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

  ctx_skill_version <libdir>
      Print "<version>\t<short-commit>" for the skill owning <libdir>, read from
      the sibling SKILL.md frontmatter and the skill repo's git HEAD. Either
      field may be empty.

  ctx_api_key_from_env_file <root> [names...]
      Print ANTHROPIC_API_KEY read from the first secrets file found at <root>
      (default names: .env, then env). Empty when absent. PARSED, never
      sourced, and only this one variable is extracted.

  ctx_prev_bytes <ref> <repo-relative-path>
      "<bytes>" for the committed version at <ref>, or "<TAB><reason>" when
      there is no comparable one — notably when the blob is a symlink, whose
      content is a path rather than the file. Split on the tab: field 1 is the
      count, field 2 the reason a caller can log. Split on $CTX_TAB.

  ctx_read_roster <cohort-file>
      Parse the cohort roster. Emits one line per entry, fields separated by
      $CTX_US: "<kind><US><entry><US><wave><US><pair>", kind being repo or
      local. wave and pair may be empty. Unknown annotations warn and are
      ignored, as does a repeated entry — emitted once, never twice.
      Read it with: IFS="$CTX_US" read -r kind entry wave pair

  ctx_fetch_ledger <kind> <entry> <ledger-path> <branch> <outfile>
      Write one repo's ledger to <outfile>. Returns 0 fetched, 3 no ledger,
      4 unreadable (with a WARN on stderr). Callers needing `repo` entries must
      check for gh themselves; this reports its absence as unreadable.

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
      -h|--help) ctx_lib_usage; exit 0 ;;
    esac
    ;;
esac

# Dated snapshots, not live context: a since-moved path inside a plan is a
# correct historical record, so counting these as orphans or dead links buries
# the live signal. Matched at any depth, because vendored skill trees nest them
# (docs/superpowers/plans/) and a depth-1 test reports every one as a live orphan.
# The delimiter ctx_prev_bytes emits, published so callers split on a named value
# rather than a literal tab typed into a parameter expansion — invisible in review,
# and silently destroyed by any tab-to-space conversion.
#
# Read only by callers, never within this file, which is what SC2034 reports.
# shellcheck disable=SC2034
CTX_TAB="$(printf '\t')"

# The roster's field separator, and deliberately NOT a tab. A roster field may be
# legitimately empty (an unassigned wave), and `IFS=$'\t' read` collapses runs of
# tabs into one delimiter because tab is IFS whitespace — so "repo<T>x<T><T>3"
# would land the pair value in the wave variable and silently mis-assign a repo to
# the wrong arm of the experiment. A unit separator is not IFS whitespace, so
# empty fields survive the read exactly as written.
# shellcheck disable=SC2034
CTX_US="$(printf '\037')"

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
    # PARSED, not stripped. `tr -dc '0-9'` deleted every non-digit and
    # concatenated what was left, so a file this could not understand produced
    # a DIFFERENT number rather than none: `v2 6000` became 26000 and
    # `6000 or 8000` became 60008000. A budget four times the intended one
    # reports `over_budget: false`, and the ledger row then records compliance
    # that was never achieved — for every future week, since nothing says so.
    #
    # Tolerance was right; deletion was the wrong way to get it. The first
    # whitespace-delimited token keeps every benign case a knob file deserves —
    # a trailing newline, a leading space, `6000 # tokens`, and `6000 or 8000`,
    # whose trailing words are indistinguishable from an annotation — while
    # `v2 6000` and `4,000` are simply not a bare integer, and now say so (#132).
    v="$(head -1 "$file" 2>/dev/null | tr -d '\r' | awk '{print $1; exit}')" || v=""
    case "$v" in
      ''|*[!0-9]*)
        # And it says so. A malformed knob FILE degrades to the default — a
        # repo should not fail to measure because somebody annotated one — but
        # silently is how a wrong budget survives. The mirror of the FLAG rule
        # in measure-context.sh, where a malformed --budget is a typo and is
        # refused outright (#126).
        printf 'WARN %s: not a bare integer ("%s") — using %s\n' \
          "$file" "$v" "$fallback" >&2
        v="" ;;
    esac
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
    # The milder half of the same mistake: `tr -d '[:space:]'` turned "my docs"
    # into "mydocs" and "docs # ref" into "docs#ref" — directories that do not
    # exist, so the two continuous surfaces classify nothing and say nothing.
    # Trim the ends, then REJECT anything still holding whitespace rather than
    # guess which half was meant; taking the first token would silently point
    # the whole surface at "my". An absolute path is refused here too, so the
    # rejection the docstring already promised is now audible.
    v="$(head -1 "$file" 2>/dev/null | tr -d '\r')" || v=""
    v="${v#"${v%%[![:space:]]*}"}"
    v="${v%"${v##*[![:space:]]}"}"
    case "${v#./}" in
      ''|*[[:space:]]*|/*)
        printf 'WARN %s: not a single relative path ("%s") — using %s\n' \
          "$file" "$v" "$fallback" >&2
        v="" ;;
    esac
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
  #
  # Parsed the same way as the budget knobs and for the same reason (#132):
  # `tr -dc '0-9.'` read "v2 3.5" as 23.5 bytes per token, which clears the
  # plausibility floor below and under-counts every file measured against it by
  # eight times. This one divides every byte count in all three surfaces, so a
  # mutated value is not merely a wrong number — it is a wrong number that looks
  # like a calibration.
  local root="$1" file r w f out=""
  file="$root/.skills/context-token-ratio"
  if [ -f "$file" ]; then
    r="$(head -1 "$file" 2>/dev/null | tr -d '\r' | awk '{print $1; exit}')" || r=""
    case "$r" in
      ''|*[!0-9.]*|.*|*.*.*) ;;
      # The literal 1 prefix on the fractional part stops a leading zero being
      # read as octal ("08" would abort under set -e); the -100 removes it again.
      # 10# does the same job for the whole part, which the old strip could not
      # reach because a leading zero there was rare enough to go unnoticed.
      *.*) w="${r%%.*}"; f="${r#*.}00"
           out=$(( 10#${w:-0} * 100 + 1${f:0:2} - 100 )) ;;
      *) out=$(( 10#$r * 100 )) ;;
    esac
    # One warning for both ways of being unusable — unparseable, or parsed and
    # under one byte per token. Either way the constant wins, and the run says
    # which value it declined rather than reporting a ratio nobody configured.
    if [ -z "$out" ] || [ "$out" -lt 100 ]; then
      printf 'WARN %s: not a plausible bytes-per-token ratio ("%s") — using %s\n' \
        "$file" "$r" "$CTX_BPT_DEFAULT_X100" >&2
      out=""
    fi
  fi
  printf '%s' "${out:-$CTX_BPT_DEFAULT_X100}"
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

ctx_skill_version() {
  # Which version of the skill produced a measurement. Without this the ledger
  # records what a repo did but not what made it do that, so no skill change can
  # ever be attributed to an outcome — which is the precondition for gating
  # changes on the cohort rather than on judgement.
  #
  # Two values, because each covers the other's gap. The declared `version` is
  # human-comparable and is what an A/B across the cohort groups by; it is only as
  # good as the discipline of bumping it. The short commit is automatic and exact,
  # so an unbumped version is still debuggable after the fact.
  # Separate statements: under `set -u`, a later assignment in the same `local`
  # cannot read an earlier one from the same statement.
  local libdir="$1"
  local skill version="" commit=""
  skill="$libdir/../SKILL.md"
  if [ -f "$skill" ]; then
    # Frontmatter only: stop at the closing delimiter so a `version:` mentioned in
    # the body cannot be mistaken for the declaration.
    version="$(LC_ALL=C awk '
      NR == 1 && $0 == "---" { infm = 1; next }
      infm && $0 == "---" { exit }
      infm && /^[[:space:]]*version:[[:space:]]*/ {
        sub(/^[[:space:]]*version:[[:space:]]*/, "")
        gsub(/^"|"$|^'"'"'|'"'"'$/, "")
        print; exit
      }
    ' "$skill" 2>/dev/null)" || version=""
  fi
  commit="$(git -C "$libdir" rev-parse --short HEAD 2>/dev/null)" || commit=""
  printf '%s\t%s' "$version" "$commit"
}

ctx_api_key_from_env_file() {
  # An interactive Claude Code session has no ANTHROPIC_API_KEY exported and, in
  # practice, no `ant` CLI either — so without this an interactive run silently
  # falls back to the offline estimate and writes a row that cannot be compared
  # against the scheduled run's exact rows. The cohort keeps the key in `.env` at
  # the repo root (bare `env` before 2026-08-05).
  #
  # PARSED, not sourced, and only ANTHROPIC_API_KEY is extracted. Sourcing a
  # secrets file executes whatever it contains, which is not a thing a
  # measurement script should ever do to obtain a token count.
  local root="$1"; shift
  local names="${*:-.env env}" f line val
  for f in $names; do
    [ -f "$root/$f" ] || continue
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line#export }"
      case "$line" in
        ANTHROPIC_API_KEY=*) ;;
        *) continue ;;
      esac
      val="${line#ANTHROPIC_API_KEY=}"
      val="${val%$'\r'}"
      case "$val" in
        \"*\") val="${val#\"}"; val="${val%\"}" ;;
        \'*\') val="${val#\'}"; val="${val%\'}" ;;
      esac
      # A value with whitespace or a shell metacharacter is not a usable key and
      # is far more likely to be a placeholder or a mangled line.
      case "$val" in
        ''|*[[:space:]]*|*'$'*|*'`'*) continue ;;
      esac
      printf '%s' "$val"
      return 0
    done <"$root/$f"
  done
}

ctx_prev_bytes() {
  # Emits "<bytes><TAB><reason>", either side possibly empty. Both values come
  # back on stdout rather than one through a global: a caller reads this in a
  # command substitution, whose subshell cannot set a variable in the caller's
  # shell, so a global would have forced a second invocation — two `git ls-tree`
  # calls on a path the hook runs for every edit, with a window for the two to
  # disagree if the index moved between them.
  #
  # A 120000-mode blob is a symlink, whose content is the target path rather
  # than the file — the mirror of the case ctx_resolve_rel handles, reached when
  # a path was a symlink at the ref and is a real file now. Report no comparable
  # version rather than eleven bytes of content.
  local ref="$1" rel="$2" mode bytes="" note=""
  mode="$(git ls-tree "$ref" -- "$rel" 2>/dev/null | awk '{print $1; exit}')" || mode=""
  case "$mode" in
    100644|100755)
      bytes="$(git show "$ref:$rel" 2>/dev/null | LC_ALL=C wc -c 2>/dev/null | tr -d ' ')" || bytes="" ;;
    '') ;;
    *) note="$ref:$rel is mode $mode, not a regular file; treating as uncommitted" ;;
  esac
  printf '%s\t%s' "$bytes" "$note"
}

ctx_read_roster() {
  # The roster is read by two scripts with different jobs — cohort-report.sh
  # rolls every member up, score-cohort.sh compares two arms of it — and they
  # must agree on which repo is in which arm. A second parser would be a second
  # opinion about the experiment's own assignment.
  #
  # Annotations are whitespace-separated key:value fields after the entry:
  #
  #   CannObserv/usa-wa   wave:a pair:1
  #
  # Unknown keys warn rather than fail, so an older copy of this library reading
  # a newer roster degrades to ignoring the field instead of refusing the file.
  # A repeated entry is warned about and processed once. Merged silently it
  # halved an experiment without saying so: a roster declaring four entries and
  # two pairs produced a report with one pair, no note, and a verdict of ADOPT —
  # the same "quietly shrinks its own sample" failure that out-of-arm reporting
  # was added to prevent, reached through a different input error. In the roll-up
  # the same duplication inflated `runs` to 4 for a two-row ledger.
  #
  # bash 3.2 has no associative arrays, so the seen-set is a US-delimited string;
  # the entry is quoted inside the pattern, which keeps glob characters literal.
  local file="$1" line entry rest field key val wave pair kind
  local seen="$CTX_US"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] || continue
    entry="${line%%[[:space:]]*}"
    rest="${line#"$entry"}"
    case "$seen" in
      *"$CTX_US$entry$CTX_US"*)
        printf 'WARN %s: listed more than once in the roster; the repeat is ignored\n' \
          "$entry" >&2
        continue ;;
    esac
    seen="$seen$entry$CTX_US"
    wave=""
    pair=""
    for field in $rest; do
      key="${field%%:*}"
      val="${field#*:}"
      case "$key" in
        wave) wave="$(printf '%s' "$val" | tr '[:upper:]' '[:lower:]')" ;;
        pair) pair="$val" ;;
        *) printf 'WARN %s: unknown roster annotation "%s" (ignored)\n' \
             "$entry" "$field" >&2 ;;
      esac
    done
    case "$entry" in
      /*|.*|~*) kind=local ;;
      *) kind=repo ;;
    esac
    printf '%s%s%s%s%s%s%s\n' \
      "$kind" "$CTX_US" "$entry" "$CTX_US" "$wave" "$CTX_US" "$pair"
  done <"$file"
}

ctx_fetch_ledger() {
  # `gh api` prints nothing AND exits non-zero on 404, so an empty-output test
  # alone cannot tell "this repo has not adopted the skill" from "the request
  # failed". Those two must stay distinguishable: the first is the expected state
  # before adoption, the second is an error that would otherwise silently shrink
  # the sample an A/B is computed over.
  local kind="$1" entry="$2" ledger="$3" branch="$4" out="$5"
  local ref="" rc=0 err=""
  : >"$out" || return 4
  if [ "$kind" = local ]; then
    [ -f "$entry/$ledger" ] || return 3
    cat "$entry/$ledger" >"$out" || return 4
    [ -s "$out" ] || return 3
    return 0
  fi
  [ -n "$branch" ] && ref="?ref=$branch"
  err="$(gh api "repos/$entry/contents/$ledger$ref" \
           -H "Accept: application/vnd.github.raw" 2>&1 >"$out")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    case "$err" in
      *404*) return 3 ;;
    esac
    printf 'WARN %s: gh api failed (exit %s): %s\n' "$entry" "$rc" \
      "$(printf '%s' "$err" | tr -d '\n')" >&2
    return 4
  fi
  [ -s "$out" ] || return 3
  return 0
}
