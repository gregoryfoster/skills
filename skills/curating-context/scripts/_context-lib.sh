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

  ctx_validate_counts <root>
      Report structurally broken rows in <root>/.skills/context-token-counts to
      stderr, once. Advisory — always returns 0. Call it after ROOT resolves and
      before the first estimate; ctx_est_tokens_for skips such rows silently, so
      without this call a broken artifact degrades the estimate without saying so.

  ctx_est_tokens_for <root> <repo-relative-path> <bytes>
      Offline token estimate for ONE named file: "<tokens>\t<source>", source
      being "file" when <root>/.skills/context-token-counts holds a usable
      anchor for that path and "repo" when the global ratio was used. Split on
      $CTX_TAB. Assign CTX_BPT_X100 before calling, as for ctx_est_from_bytes —
      the fallback path uses it.

  ctx_est_pair <root> <repo-relative-path> <now-bytes> <prev-bytes>
      Both sides of a now-vs-then comparison, priced by one method:
      "<now>\t<prev>\t<source>". Either byte count may be empty, giving 0 for
      that side. When the two sides would resolve to different sources, BOTH
      fall back to the repo ratio, so the difference is never taken between two
      incomparable numbers.

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

# The band a bytes-per-token figure has to fall in to be believed at all. Real
# markdown measures 2.0-4.0; outside 1.5-6.0 the file is degenerate or
# unrepresentative (a generated table, a wall of single-character lines) and the
# figure describes that accident rather than the content. Held here rather than
# in measure-context.sh because the writer and BOTH readers — the global ratio
# and the per-file anchor — have to mean the same thing by "plausible"; the
# floor and the ceiling used to be two literals in two files, which is precisely
# the drift this library exists to prevent.
CTX_RATIO_MIN_X100=150
CTX_RATIO_MAX_X100=600

# Per-file calibration, written by measure-context.sh --exact (#145).
#
# One global ratio describes exactly one file well: the one it is derived from,
# which is the policy file. Measured across this repo's own 56-file surface the
# per-file ratio runs 2.04 to 3.03 against a 2.65 global, so the estimate it
# yields is wrong by -23% to +14% — in BOTH directions, and "code-heavy" does
# not predict which. Under-reporting is the direction that matters: an over-flag
# wastes attention, an under-flag lets a file sit over budget in silence.
CTX_COUNTS_BASENAME="context-token-counts"

# How far a file may drift from the size it was measured at before its anchor
# stops describing it. The anchor prices the WHOLE file at its own ratio, so the
# error is the drift times the gap between the old content's ratio and the new
# content's. At 25%, with this repo's observed extremes (2.04 and 3.03 against a
# 2.65 global), the worst case is -5.6%/+2.6% even if every added byte tokenizes
# at the opposite end of the range — better than the global estimator manages on
# its BEST files. At 100% the same worst case reaches -13%, which is global-tier,
# so the anchor has stopped earning its keep well before then.
CTX_DRIFT_PCT=25

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

ctx_validate_counts() {
  # Report structurally broken rows in .skills/context-token-counts, ONCE.
  # Advisory: always returns 0, because a broken calibration artifact degrades
  # the estimate to the repo ratio rather than invalidating the run.
  #
  # Separate from ctx_est_tokens_for because the two answer different questions.
  # "Is this row usable for the file I am pricing?" is asked once per file and
  # must stay quiet. "Is this artifact intact?" is asked once per run and must
  # not. Folding the second into the first is what made one bad row emit one
  # warning per file looked up (CR finding 26); and the state that would let the
  # hot path warn only once cannot live in a shell variable, because callers
  # invoke it inside a command substitution whose subshell cannot write back.
  #
  # Call this after resolving ROOT and before the first estimate.
  local root="$1"
  local file b t p n=0
  file="$root/.skills/$CTX_COUNTS_BASENAME"
  [ -f "$file" ] || return 0
  # Guarded on `b` — see ctx_est_tokens_for; a truncated final row is precisely
  # what this function exists to catch, so it must not be the row that escapes.
  while read -r b t p || [ -n "${b:-}" ]; do
    case "${b:-}" in ''|'#'*) continue ;; esac
    p="${p%$'\r'}"
    case "$b$t" in
      ''|*[!0-9]*)
        printf 'WARN %s: "%s %s %s" is not "<bytes> <tokens> <path>" — the row is ignored\n' \
          "$file" "$b" "$t" "$p" >&2
        n=$(( n + 1 ))
        continue ;;
    esac
    if [ -z "${p:-}" ]; then
      printf 'WARN %s: "%s %s" names no path — the row is ignored\n' \
        "$file" "$b" "$t" >&2
      n=$(( n + 1 ))
      continue
    fi
    # A zero on either side belongs here rather than with the value complaints
    # below it in ctx_est_tokens_for. An implausible RATIO is a real measurement
    # of a degenerate file, and is worth saying at the moment that file is
    # priced. A zero is not a measurement at all — it can never price anything,
    # for any file, so it is a fact about the artifact.
    if [ "$b" -le 0 ] || [ "$t" -le 0 ]; then
      printf 'WARN %s: %s has a zero or negative byte or token count — the row is ignored\n' \
        "$file" "$p" >&2
      n=$(( n + 1 ))
    fi
  done <"$file"
  [ "$n" -eq 0 ] || printf 'WARN %s: %s unusable row(s); those files fall back to the repo ratio. Regenerate with measure-context.sh --exact\n' \
    "$file" "$n" >&2
  return 0
}

ctx_est_tokens_for() {
  # Estimate ONE file's tokens, preferring its own last exact measurement over
  # the repo-wide ratio. Emits "<tokens><TAB><source>".
  #
  # Two integers per row rather than a ratio, and the estimate is
  # `tokens * bytes_now / bytes_then` rather than `bytes_now / ratio`. The
  # division by the anchor happens once, in full precision, instead of twice
  # through a two-decimal figure: at the measured size the result is the exact
  # count itself, with no rounding step at all. Storing 2.656 as "2.65" and
  # dividing back costs 13 tokens on this repo's AGENTS.md before anyone has
  # edited anything, and that error is systematic rather than noise.
  #
  # The source is returned, not inferred, because a caller that reports a number
  # should be able to say where it came from — #145 is a case study in an
  # unattributed estimate being copied into a plan, an issue comment and several
  # status reports before anyone checked it. Both halves come back on stdout for
  # the reason ctx_prev_bytes documents: the caller reads this in a command
  # substitution, whose subshell cannot set a variable in the caller's shell.
  local root="$1" rel="$2" bytes="$3"
  local file b t p lo hi
  # `wc -c` pads on BSD/macOS; see ctx_est_pair for what a padded count costs.
  bytes="${bytes//[[:space:]]/}"
  case "$bytes" in ''|*[!0-9]*) bytes=0 ;; esac
  file="$root/.skills/$CTX_COUNTS_BASENAME"
  if [ -f "$file" ]; then
    # Guarded on `b`, not `p`. A final line with no trailing newline leaves
    # `read` non-zero with the fields it did parse still set, and `p` is exactly
    # the field a truncated row is missing — so guarding on `p` dropped
    # "20000 8000" silently, which is the row shape a truncated write leaves and
    # the one ctx_validate_counts exists to report (CR finding 27). `b` is set
    # for any non-empty final line however few fields it has.
    while read -r b t p || [ -n "${b:-}" ]; do
      case "${b:-}" in ''|'#'*) continue ;; esac
      # A CR survives the field split — it is not IFS whitespace — and would
      # make every path in a CRLF checkout miss its lookup silently, which looks
      # exactly like "this repo has no calibration". Stripped the same way the
      # knob readers strip theirs.
      p="${p%$'\r'}"
      # Parsed then validated, never stripped (#132). This value divides every
      # byte count of the file it names, so a row the library cannot understand
      # must produce NO number rather than a different one.
      #
      # Silent here, by design. A malformed row is a fact about the ARTIFACT,
      # not about the file being priced, so reporting it belongs to
      # ctx_validate_counts — which each caller runs once. Warning from this
      # function instead meant one bad row produced one warning per file looked
      # up: four on a three-doc repo, thirty on a thirty-doc one, all identical.
      # That is the advisory fatigue #145 was filed about, reproduced by the fix
      # for it (CR finding 26).
      case "$b$t" in ''|*[!0-9]*) continue ;; esac
      [ -n "${p:-}" ] || continue
      # First row wins. The writer sorts and de-duplicates so this should not
      # arise, but the artifact's header invites regeneration over hand-editing,
      # which concedes that hand-edits happen (CR finding 29).
      #
      # Value complaints below ARE scoped to the file being asked about: an odd
      # measurement is a fact about one file, so it is worth saying at the moment
      # that file is priced.
      [ "$p" = "$rel" ] || continue
      if [ "$b" -le 0 ] || [ "$t" -le 0 ]; then
        printf 'WARN %s: %s has a zero byte or token count — using the repo ratio\n' \
          "$file" "$rel" >&2
        continue
      fi
      if [ $(( b * 100 / t )) -lt "$CTX_RATIO_MIN_X100" ] \
        || [ $(( b * 100 / t )) -gt "$CTX_RATIO_MAX_X100" ]; then
        printf 'WARN %s: %s measures %s.%02d bytes/token, outside the plausible %s.%02d-%s.%02d band — using the repo ratio\n' \
          "$file" "$rel" $(( b * 100 / t / 100 )) $(( b * 100 / t % 100 )) \
          $(( CTX_RATIO_MIN_X100 / 100 )) $(( CTX_RATIO_MIN_X100 % 100 )) \
          $(( CTX_RATIO_MAX_X100 / 100 )) $(( CTX_RATIO_MAX_X100 % 100 )) >&2
        continue
      fi
      # Past the drift band the anchor is not wrong so much as unevidenced, and
      # the global ratio at least describes the repo. Silent, unlike the cases
      # above: a file growing is normal, and a warning on every edit is the
      # advisory-fatigue this whole issue is about.
      lo=$(( b * (100 - CTX_DRIFT_PCT) / 100 ))
      hi=$(( b * (100 + CTX_DRIFT_PCT) / 100 ))
      if [ "$bytes" -lt "$lo" ] || [ "$bytes" -gt "$hi" ]; then
        continue
      fi
      printf '%s\t%s' $(( t * bytes / b )) file
      return 0
    done <"$file"
  fi
  printf '%s\t%s' "$(ctx_est_from_bytes "$bytes")" repo
}

ctx_est_pair() {
  # Both sides of a "now vs then" comparison, priced by ONE method. Emits
  # "<now><TAB><prev><TAB><source>"; either byte count may be empty or
  # non-numeric, which yields 0 for that side and lets the other decide.
  #
  # The two sides can genuinely resolve differently: a file's committed size may
  # sit outside its anchor's drift band while the working copy sits inside it.
  # Differencing a calibrated number against a global one reports the gap
  # between two methods as if it were growth someone wrote — on a file 10% off
  # the global that is a phantom several hundred tokens wide, and it appears in
  # the one sentence the guard puts in front of a human. So when the sides
  # disagree, both drop to the repo ratio: a slightly worse pair of numbers
  # beats a difference between two incomparable ones.
  #
  # This is the rule record-telemetry.sh already applies to the ledger, where a
  # row whose method differs from the previous one is refused rather than
  # silently differenced. It lives here because the guard and context-delta.sh
  # both need it, and two copies of a rule about agreement is the drift this
  # library exists to prevent.
  local root="$1" rel="$2" nb="$3" pb="$4"
  local now=0 prev=0 nsrc="" psrc="" out
  # Callers hand this straight from `wc -c`, which pads with leading spaces on
  # BSD/macOS. Arithmetic and `[` both tolerate that; the digit test below does
  # not, and rejecting a padded count would silently zero the side it came from
  # — a guard that reported every file as 0 tokens and therefore never spoke.
  nb="${nb//[[:space:]]/}"
  pb="${pb//[[:space:]]/}"
  case "$nb" in ''|*[!0-9]*) nb="" ;; esac
  case "$pb" in ''|*[!0-9]*) pb="" ;; esac
  if [ -n "$nb" ]; then
    out="$(ctx_est_tokens_for "$root" "$rel" "$nb")"
    now="${out%%"$CTX_TAB"*}"
    nsrc="${out#*"$CTX_TAB"}"
  fi
  if [ -n "$pb" ]; then
    out="$(ctx_est_tokens_for "$root" "$rel" "$pb")"
    prev="${out%%"$CTX_TAB"*}"
    psrc="${out#*"$CTX_TAB"}"
  fi
  if [ -n "$nsrc" ] && [ -n "$psrc" ] && [ "$nsrc" != "$psrc" ]; then
    now="$(ctx_est_from_bytes "$nb")"
    prev="$(ctx_est_from_bytes "$pb")"
    nsrc=repo
  fi
  printf '%s\t%s\t%s' "$now" "$prev" "${nsrc:-$psrc}"
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
