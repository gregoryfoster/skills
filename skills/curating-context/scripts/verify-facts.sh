#!/usr/bin/env bash
# verify-facts.sh — mechanically check the falsifiable claims in a policy file.
#
# Emits TSV on stdout: verdict<TAB>class<TAB>location<TAB>claim<TAB>evidence
# Verdicts: TRUE (a command confirmed it), FALSE (a command refuted it),
# UNVERIFIABLE (no mechanical check applies — an agent must judge it).
#
# Only FALSE claims are eligible for deletion. UNVERIFIABLE is never a licence
# to delete: it means this script could not decide, not that the claim is wrong.
#
# FALSE is deliberately narrow. A policy file legitimately names paths that do
# not exist locally — illustrative templates (`references/`), naming conventions
# (`lowercase-kebab.md`), and downstream consumer paths (`skills-vendor/…`) — so
# a missing path is UNVERIFIABLE, not FALSE. Only a broken markdown link and a
# missing target in a runner manifest that does exist earn FALSE. Precision here
# is load-bearing: a FALSE list padded with prose teaches the reader to skim it,
# and this skill deletes on FALSE.
set -euo pipefail

usage() {
  cat <<'USAGE'
verify-facts.sh — mechanically verify falsifiable claims in a policy file

Usage:
  verify-facts.sh [options]

Options:
  --file PATH      Policy file to verify. Default: AGENTS.md, else CLAUDE.md.
  --also PATH      Additional file to verify (repeatable) — e.g. a live doc.
  --issues         Resolve GitHub issue references (#N, owner/repo#N) via gh.
                   Off by default: it costs one API call per reference.
  --repo SLUG      owner/repo for bare #N references. Default: gh's inference.
  -h, --help       Show this help and exit 0.

Claim classes checked:
  path      Backticked token that looks like a repo path -> does it exist?
  link      Relative markdown link target -> does it exist?
  command   `make X` / `npm run X` / `uv run X` / `just X` -> is the target
            defined in Makefile / package.json / pyproject.toml / justfile?
            A directory prefix moves the manifest: `cd frontend && npm run
            build` and `make -C frontend dist` resolve against frontend/.
            A `cd` into a directory that is not here is FALSE; a directory
            with no manifest is UNVERIFIABLE.
  unit      `foo.service` -> is that unit named anywhere in the repo?
  issue     #N / owner/repo#N -> open, closed, or nonexistent (with --issues)

Everything else — behavioural rules, rationale, conventions, architecture
prose — is UNVERIFIABLE by this script and belongs to the agent's judgement.
See references/fact-verification.md for how to adjudicate those.

Exit codes:
  0  verification ran (findings on stdout; FALSE rows are not a failure)
  1  usage error, or no policy file found
  2  infrastructure failure
USAGE
}

POLICY=""
# An array, not a space-joined string: a --also path containing a space would
# word-split into two nonexistent files and be silently skipped with a WARN.
EXTRA=()
CHECK_ISSUES=0
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --also) EXTRA+=("${2:?--also needs a path}"); shift 2 ;;
    --issues) CHECK_ISSUES=1; shift ;;
    --repo) REPO="${2:?--repo needs owner/repo}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

if [ -z "$POLICY" ]; then
  for cand in AGENTS.md CLAUDE.md; do
    [ -f "$cand" ] && { POLICY="$cand"; break; }
  done
fi
if [ -z "$POLICY" ] || [ ! -f "$POLICY" ]; then
  echo "ERROR no policy file found (looked for AGENTS.md, CLAUDE.md under $ROOT)" >&2
  exit 1
fi

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

emit() { printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5"; }

# --- path claims ----------------------------------------------------------
# A backticked token is a path claim when it contains a slash or ends in a known
# source extension. Tokens with shell metacharacters, spaces, or placeholder
# brackets are prose, not paths.
check_paths() {
  local f="$1" line tok
  # The backticks are regex literals — this greps Markdown code spans out of a
  # doc — so single quotes are correct and expansion is not wanted.
  # shellcheck disable=SC2016
  grep -oE '`[^`]+`' "$f" 2>/dev/null | sed -e 's/^`//' -e 's/`$//' | sort -u \
    | grep -vE '[ <>*$|(){}]' \
    | grep -E '/|\.(py|js|ts|tsx|php|go|rb|sh|json|toml|yaml|yml|md|service|timer|sql)$' \
    >"$TMP/paths" || true
  while IFS= read -r tok; do
    [ -n "$tok" ] || continue
    # Strip a trailing slash and a leading ./ so `src/core/` matches the dir.
    local p="${tok#./}"; p="${p%/}"
    case "$p" in
      /*|~*|http*) emit UNVERIFIABLE path "$f" "$tok" "absolute or remote — outside the repo"; continue ;;
    esac
    if [ -e "$p" ]; then
      emit TRUE path "$f" "$tok" "exists"
    elif git ls-files --error-unmatch "$p" >/dev/null 2>&1; then
      emit TRUE path "$f" "$tok" "tracked by git"
    elif [ -n "$(git ls-files -- "*$p" 2>/dev/null | head -1)" ]; then
      emit UNVERIFIABLE path "$f" "$tok" "not at this path; a suffix match exists — likely moved"
    else
      emit UNVERIFIABLE path "$f" "$tok" "absent here — illustrative, downstream, or stale; confirm before removing"
    fi
  done <"$TMP/paths"
}

# --- link claims ----------------------------------------------------------
check_links() {
  local f="$1" raw dir tgt
  dir="$(dirname "$f")"; [ "$dir" = "." ] && dir=""
  grep -oE '\]\([^)]+\)' "$f" 2>/dev/null \
    | sed -e 's/^](//' -e 's/)$//' -e 's/#.*$//' \
    | grep -vE '^(https?:|mailto:|//|$)' \
    | grep -vE '[<>*]|, ' | sort -u >"$TMP/links" || true
  while IFS= read -r raw; do
    [ -n "$raw" ] || continue
    case "$raw" in
      /*) tgt="${raw#/}" ;;
      *) tgt="${dir:+$dir/}$raw" ;;
    esac
    # Collapse a single leading ../ pair produced by dir-relative joining.
    while case "$tgt" in *?/../*) true ;; *) false ;; esac; do
      tgt="$(printf '%s' "$tgt" | sed -e 's|[^/][^/]*/\.\./||')"
    done
    if [ -e "$tgt" ]; then
      emit TRUE link "$f" "$raw" "resolves to $tgt"
    else
      emit FALSE link "$f" "$raw" "resolves to $tgt, which does not exist"
    fi
  done <"$TMP/links"
}

# --- command claims -------------------------------------------------------
# A documented command that no longer exists is the highest-cost stale fact in a
# policy file: an agent runs it, it fails, and the whole file loses authority.
#
# A documented command also carries where it runs. `cd frontend && npm run build`
# is the ordinary shape of a monorepo's frontend build, and the manifest that
# decides it is frontend/package.json — resolving it against the root one turns a
# correct claim into FALSE, the single verdict this skill deletes on. So peel the
# directory-scoping prefixes off and resolve the manifest where the command says
# it runs.

# Join a directory segment onto an accumulated prefix; an absolute segment wins.
join_dir() {
  case "$2" in
    /*) printf '%s' "$2" ;;
    *) if [ -n "$1" ]; then printf '%s/%s' "$1" "$2"; else printf '%s' "$2"; fi ;;
  esac
}

check_commands() {
  local f="$1" line runner target found dir base where i n
  local -a toks
  # Scan only code context — inline backticks and fenced blocks. Scanning prose
  # matches English ("make it possible", "just once") and produces confident
  # nonsense; a documented command lives in code formatting or it isn't one.
  LC_ALL=C awk '
    /^[[:space:]]*```/ { fence = !fence; next }
    fence { print; next }
    { while (match($0, /`[^`]+`/)) {
        print substr($0, RSTART + 1, RLENGTH - 2)
        $0 = substr($0, RSTART + RLENGTH)
      } }
  ' "$f" >"$TMP/code" 2>/dev/null || : >"$TMP/code"
  # Capture any leading `cd <dir> &&` chain (optionally inside a subshell) and a
  # directory-scoping flag between the runner and its target, so the parser below
  # can see where the command runs. sed then normalises whitespace and pads `&&`,
  # which both keeps the emitted claim TSV-safe (a literal tab would split a row)
  # and lets the parser split on single spaces.
  grep -oE '(\()?((cd|pushd)[[:space:]]+[^[:space:]&|;()]+[[:space:]]*&&[[:space:]]*)*\b(make|just|npm run|pnpm run|yarn|uv run|poetry run|composer)[[:space:]]+((-C|--directory|--prefix)([[:space:]]+|=)[^[:space:]&|;()]+[[:space:]]+)?[a-zA-Z0-9:_-]+' "$TMP/code" 2>/dev/null \
    | sed -e 's/^(//' -e 's/&&/ \&\& /g' -e 's/[[:space:]][[:space:]]*/ /g' \
          -e 's/^ //' -e 's/ $//' \
    | sort -u >"$TMP/cmds" || true
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    toks=()
    IFS=' ' read -r -a toks <<<"$line"
    n="${#toks[@]}"
    i=0
    dir=""
    # Peel `cd <dir> &&` / `pushd <dir> &&`, including a chain of them.
    while [ "$i" -lt "$n" ]; do
      case "${toks[$i]}" in
        cd|pushd) ;;
        *) break ;;
      esac
      # Needs `<dir> && <runner> <target>` still to come, or it is not a prefix.
      if [ $((i + 3)) -ge "$n" ] || [ "${toks[$((i + 2))]}" != "&&" ]; then break; fi
      dir="$(join_dir "$dir" "${toks[$((i + 1))]}")"
      i=$((i + 3))
    done
    # Two-word runners (`npm run`, `uv run`) consume a second token.
    runner="${toks[$i]:-}"
    case "$runner" in
      npm|pnpm|uv|poetry) runner="$runner ${toks[$((i + 1))]:-}"; i=$((i + 2)) ;;
      *) i=$((i + 1)) ;;
    esac
    # A directory-scoping flag moves the authoritative manifest exactly as `cd`
    # does — `make -C frontend dist` is decided by frontend/Makefile. Deferred:
    # `npm --prefix <dir> run x` puts the flag before `run`, so the extraction
    # never matches it at all; that is a silent miss, not a false FALSE, and
    # widening the runner pattern to cover it is a larger change than this fix.
    case "${toks[$i]:-}" in
      -C|--directory|--prefix)
        if [ -n "${toks[$((i + 1))]:-}" ]; then
          dir="$(join_dir "$dir" "${toks[$((i + 1))]}")"
          i=$((i + 2))
        fi ;;
      --directory=*|--prefix=*)
        dir="$(join_dir "$dir" "${toks[$i]#*=}")"; i=$((i + 1)) ;;
    esac
    target="${toks[$i]:-}"
    case "$target" in
      ""|-*)
        # `make -C frontend` scopes a directory and names no target. Reporting
        # FALSE for a target called `-C` is the same false FALSE in miniature.
        emit UNVERIFIABLE command "$f" "$line" "no target named — a bare runner or a flag"
        continue ;;
    esac
    base=""
    where="this repo"
    if [ -n "$dir" ]; then
      dir="${dir#./}"; dir="${dir%/}"
      [ "$dir" = "." ] && dir=""
    fi
    if [ -n "$dir" ]; then
      case "$dir" in
        /*|~*|*'$'*|*'<'*|*'>'*|*'*'*)
          emit UNVERIFIABLE command "$f" "$line" "runs in '$dir' — outside this checkout or a placeholder; no manifest to resolve against"
          continue ;;
      esac
      if [ ! -d "$dir" ]; then
        # The checkout refutes this one: the directory the command changes into
        # is not here, so the command cannot run as documented. Blame the
        # directory, not the runner — that is the half the operator must fix.
        emit FALSE command "$f" "$line" "no directory '$dir' in this repo — the command cannot run as written"
        continue
      fi
      base="$dir/"
      where="$dir"
    fi
    # Built-in subcommands are not manifest entries. `composer install` and
    # `yarn add` are always valid and would otherwise report FALSE forever.
    case "$runner $target" in
      "composer install"|"composer update"|"composer require"|"composer remove"\
      |"composer validate"|"composer outdated"|"composer show"|"composer audit"\
      |"composer dump-autoload"|"composer run-script"|"composer create-project"\
      |"yarn install"|"yarn add"|"yarn remove"|"yarn upgrade"|"yarn why")
        emit TRUE command "$f" "$line" "built-in subcommand"
        continue ;;
    esac
    found=""
    case "$runner" in
      make)
        [ -f "${base}Makefile" ] && grep -qE "^${target}[[:space:]]*:" "${base}Makefile" && found="${base}Makefile" ;;
      just)
        [ -f "${base}justfile" ] && grep -qE "^${target}([[:space:]]|:)" "${base}justfile" && found="${base}justfile" ;;
      "npm run"|"pnpm run"|yarn)
        [ -f "${base}package.json" ] && grep -qE "\"$target\"[[:space:]]*:" "${base}package.json" && found="${base}package.json" ;;
      composer)
        [ -f "${base}composer.json" ] && grep -qE "\"$target\"[[:space:]]*:" "${base}composer.json" && found="${base}composer.json" ;;
      "uv run"|"poetry run")
        # A console script, a module, or an installed tool — several legitimate
        # shapes, so confirm presence rather than claim absence.
        if grep -rqE "(^|[\"'[:space:]])${target}[\"'[:space:]]*=" "${base}pyproject.toml" 2>/dev/null; then
          found="${base}pyproject.toml"
        elif [ -x "${base}.venv/bin/$target" ]; then
          found="${base}.venv/bin/$target"
        fi ;;
    esac
    if [ -n "$found" ]; then
      emit TRUE command "$f" "$line" "defined in $found"
      continue
    fi
    # FALSE only when the manifest that would define the target actually exists.
    # No Makefile at all means the command belongs to a different repo or a
    # different era — stale, but not refuted. A directory that exists but holds
    # no manifest is the same case, one level down.
    case "$runner" in
      make)
        if [ -f "${base}Makefile" ]; then
          emit FALSE command "$f" "$line" "no '$target' target in ${base}Makefile"
        else
          emit UNVERIFIABLE command "$f" "$line" "no Makefile in $where — may document another surface"
        fi ;;
      just)
        if [ -f "${base}justfile" ]; then
          emit FALSE command "$f" "$line" "no '$target' recipe in ${base}justfile"
        else
          emit UNVERIFIABLE command "$f" "$line" "no justfile in $where"
        fi ;;
      "npm run"|"pnpm run"|yarn)
        if [ -f "${base}package.json" ]; then
          emit FALSE command "$f" "$line" "no '$target' script in ${base}package.json"
        else
          emit UNVERIFIABLE command "$f" "$line" "no package.json in $where"
        fi ;;
      composer)
        if [ -f "${base}composer.json" ]; then
          emit FALSE command "$f" "$line" "no '$target' script in ${base}composer.json"
        else
          emit UNVERIFIABLE command "$f" "$line" "no composer.json in $where"
        fi ;;
      *)
        emit UNVERIFIABLE command "$f" "$line" "no declaration found; may be a module or installed tool — run it" ;;
    esac
  done <"$TMP/cmds"
}

# --- systemd unit claims --------------------------------------------------
check_units() {
  local f="$1" unit
  grep -oE '\b[a-zA-Z0-9_.-]+\.(service|timer)\b' "$f" 2>/dev/null | sort -u >"$TMP/units" || true
  while IFS= read -r unit; do
    [ -n "$unit" ] || continue
    if [ -n "$(git grep -l -F "$unit" -- . ':!'"$f" 2>/dev/null | head -1)" ]; then
      emit TRUE unit "$f" "$unit" "referenced elsewhere in the repo"
    else
      emit UNVERIFIABLE unit "$f" "$unit" "named only here — verify against the host, not the repo"
    fi
  done <"$TMP/units"
}

# --- GitHub issue claims --------------------------------------------------
check_issues() {
  local f="$1" ref slug num state
  [ "$CHECK_ISSUES" -eq 1 ] || return 0
  if ! command -v gh >/dev/null 2>&1; then
    echo "WARN --issues requested but gh is not installed; skipping issue checks" >&2
    return 0
  fi
  grep -oE '(\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[0-9]+' "$f" 2>/dev/null | sort -u >"$TMP/issues" || true
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    num="${ref##*#}"
    slug="${ref%#*}"
    [ -z "$slug" ] && slug="$REPO"
    state=""
    if [ -n "$slug" ]; then
      state="$(gh issue view "$num" --repo "$slug" --json state --jq .state 2>/dev/null || true)"
    else
      state="$(gh issue view "$num" --json state --jq .state 2>/dev/null || true)"
    fi
    case "$state" in
      OPEN) emit TRUE issue "$f" "$ref" "open" ;;
      CLOSED) emit TRUE issue "$f" "$ref" "closed — check whether the prose still describes it as pending" ;;
      "") emit UNVERIFIABLE issue "$f" "$ref" "gh could not resolve it (may be a PR, another repo, or private)" ;;
      *) emit TRUE issue "$f" "$ref" "$state" ;;
    esac
  done <"$TMP/issues"
}

# ${EXTRA[@]+...} guards the empty-array case, which `set -u` treats as unbound
# on bash 3.2 (still the system bash on macOS).
for f in "$POLICY" ${EXTRA[@]+"${EXTRA[@]}"}; do
  [ -f "$f" ] || { echo "WARN skipping $f — not a file" >&2; continue; }
  check_paths "$f"
  check_links "$f"
  check_commands "$f"
  check_units "$f"
  check_issues "$f"
done
