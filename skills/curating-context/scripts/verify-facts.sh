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
EXTRA=""
CHECK_ISSUES=0
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --also) EXTRA="$EXTRA ${2:?--also needs a path}"; shift 2 ;;
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
check_commands() {
  local f="$1" line runner target found
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
  grep -oE '\b(make|just|npm run|pnpm run|yarn|uv run|poetry run|composer)[[:space:]]+[a-zA-Z0-9:_-]+' "$TMP/code" 2>/dev/null \
    | sort -u >"$TMP/cmds" || true
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    target="${line##* }"
    runner="${line% *}"
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
        [ -f Makefile ] && grep -qE "^${target}[[:space:]]*:" Makefile && found=Makefile ;;
      just)
        [ -f justfile ] && grep -qE "^${target}([[:space:]]|:)" justfile && found=justfile ;;
      "npm run"|"pnpm run"|yarn)
        [ -f package.json ] && grep -qE "\"$target\"[[:space:]]*:" package.json && found=package.json ;;
      composer)
        [ -f composer.json ] && grep -qE "\"$target\"[[:space:]]*:" composer.json && found=composer.json ;;
      "uv run"|"poetry run")
        # A console script, a module, or an installed tool — several legitimate
        # shapes, so confirm presence rather than claim absence.
        if grep -rqE "(^|[\"'[:space:]])${target}[\"'[:space:]]*=" pyproject.toml 2>/dev/null; then
          found=pyproject.toml
        elif [ -x ".venv/bin/$target" ]; then
          found=".venv/bin/$target"
        fi ;;
    esac
    if [ -n "$found" ]; then
      emit TRUE command "$f" "$line" "defined in $found"
      continue
    fi
    # FALSE only when the manifest that would define the target actually exists.
    # No Makefile at all means the command belongs to a different repo or a
    # different era — stale, but not refuted.
    case "$runner" in
      make)
        if [ -f Makefile ]; then
          emit FALSE command "$f" "$line" "no '$target' target in Makefile"
        else
          emit UNVERIFIABLE command "$f" "$line" "no Makefile in this repo — may document another surface"
        fi ;;
      just)
        if [ -f justfile ]; then
          emit FALSE command "$f" "$line" "no '$target' recipe in justfile"
        else
          emit UNVERIFIABLE command "$f" "$line" "no justfile in this repo"
        fi ;;
      "npm run"|"pnpm run"|yarn)
        if [ -f package.json ]; then
          emit FALSE command "$f" "$line" "no '$target' script in package.json"
        else
          emit UNVERIFIABLE command "$f" "$line" "no package.json in this repo"
        fi ;;
      composer)
        if [ -f composer.json ]; then
          emit FALSE command "$f" "$line" "no '$target' script in composer.json"
        else
          emit UNVERIFIABLE command "$f" "$line" "no composer.json in this repo"
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

for f in $POLICY $EXTRA; do
  [ -f "$f" ] || { echo "WARN skipping $f — not a file" >&2; continue; }
  check_paths "$f"
  check_links "$f"
  check_commands "$f"
  check_units "$f"
  check_issues "$f"
done
