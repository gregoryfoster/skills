#!/usr/bin/env bash
# measure-context.sh — baseline metrics for a repo's agent-context surface.
#
# Emits one JSON object on stdout describing the policy file (AGENTS.md), its
# per-section token census, the reference-doc tree, and the link graph between
# them. Diagnostics go to stderr. Exit 2 on infrastructure failure so a caller
# can never mistake a broken measurement for a clean one.
set -euo pipefail

usage() {
  cat <<'USAGE'
measure-context.sh — measure a repo's agent-context surface

Usage:
  measure-context.sh [options]

Options:
  --file PATH        Policy file to measure. Default: AGENTS.md, else CLAUDE.md.
  --docs-dir DIR     Reference-doc root. Default: docs
  --budget N         Token budget for the policy file (default 4000).
  --doc-budget N     Token budget per reference doc (default 10000).
  --archival NAMES   Space-separated docs/ subdirectory names treated as an
                     archive rather than live context: excluded from the doc
                     inventory, and not traversed for links. Default:
                     "plans specs research audits archive". Pass "" to measure
                     everything. Plans and audits are dated snapshots — a stale
                     path inside one is a correct historical record, so counting
                     them as orphans or dead links buries the live signal.
  --exact            Count tokens via the Anthropic count_tokens endpoint
                     instead of the bytes/4 estimate. The endpoint is FREE — it
                     is rate-limited per usage tier but consumes no tokens and
                     is billed nothing, with limits independent of message
                     creation. Requires python3 plus a credential: ANTHROPIC_API_KEY,
                     or an `ant auth login` profile (used as a Bearer token).
                     Falls back to the estimate with a WARN on any failure.
  --model ID         Model for --exact token counting. Default: claude-opus-5
  -h, --help         Show this help and exit 0.

Output (stdout, JSON):
  policy    { path, lines, bytes, tokens, tokens_exact, budget, over_budget }
  sections  [ { title, lines, bytes, tokens, share } ]  descending by size
  docs      [ { path, lines, bytes, tokens, linked, over_budget } ]  live only
  links     { refs, dead, orphans }
  totals    { tokens_policy, tokens_docs, tokens_live, files_docs, archival_skipped }

  tokens_live is the number that matters: the policy file plus every live
  reference doc reachable from it. That is the ceiling on what one session can
  pull into context from this repo's own guidance.

Exit codes:
  0  measurement completed (with or without budget violations)
  1  usage error, or no policy file found
  2  infrastructure failure (unreadable file, awk/find failure)
USAGE
}

POLICY=""
DOCS_DIR="docs"
BUDGET=4000
DOC_BUDGET=10000
ARCHIVAL="plans specs research audits archive"
EXACT=0
MODEL="claude-opus-5"

while [ $# -gt 0 ]; do
  case "$1" in
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --budget) BUDGET="${2:?--budget needs a number}"; shift 2 ;;
    --doc-budget) DOC_BUDGET="${2:?--doc-budget needs a number}"; shift 2 ;;
    --archival) ARCHIVAL="${2-}"; shift 2 ;;
    --exact) EXACT=1; shift ;;
    --model) MODEL="${2:?--model needs an id}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Repo root, so the measurement is stable regardless of cwd. The silent
# fallback to cwd covers running outside a git repo at all.
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
TAB="$(printf '\t')"

# --- token counting -------------------------------------------------------
# Default is bytes/4 — a documented estimate, not a measurement. --exact calls
# messages/count_tokens, the only accurate tokenizer for Claude models (tiktoken
# is OpenAI's and undercounts Claude text by 15-20%, more on code).
# Counting is free, so --exact costs nothing but a credential. An unset API key
# does NOT mean there are no credentials: an `ant auth login` profile works too,
# via a short-lived Bearer token. Try the key first, then the profile.
EXACT_OK=0
if [ "$EXACT" -eq 1 ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARN --exact requires python3; using bytes/4 estimate" >&2
  elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    EXACT_OK=1
  elif command -v ant >/dev/null 2>&1 \
    && ANTHROPIC_OAUTH_TOKEN="$(ant auth print-credentials --access-token 2>/dev/null)" \
    && [ -n "$ANTHROPIC_OAUTH_TOKEN" ]; then
    # OAuth tokens go on `Authorization: Bearer`, not `x-api-key`, and need the
    # oauth beta header — converting from a key is a header change, not a swap.
    export ANTHROPIC_OAUTH_TOKEN
    EXACT_OK=1
    echo "INFO --exact using the active \`ant auth\` profile (no API key set)" >&2
  else
    echo "WARN --exact needs ANTHROPIC_API_KEY or an \`ant auth login\` profile; using bytes/4 estimate" >&2
  fi
fi

if [ "$EXACT_OK" -eq 1 ]; then
  cat >"$TMP/count.py" <<'PY'
import json, os, sys, urllib.error, urllib.request

path, model = sys.argv[1], sys.argv[2]
body = json.dumps({
    "model": model,
    "messages": [
        {"role": "user", "content": open(path, encoding="utf-8", errors="replace").read()}
    ],
}).encode()
headers = {
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}
if os.environ.get("ANTHROPIC_API_KEY"):
    headers["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
else:
    # An OAuth profile token authenticates on Authorization: Bearer and needs the
    # oauth beta header; /v1/messages* rejects it without one.
    headers["authorization"] = "Bearer " + os.environ["ANTHROPIC_OAUTH_TOKEN"]
    headers["anthropic-beta"] = "oauth-2025-04-20"

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages/count_tokens",
    data=body,
    headers=headers,
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(json.load(resp)["input_tokens"])
except urllib.error.HTTPError as exc:
    # The response body carries the actionable reason (bad model id, expired
    # key, exhausted credit); the status line alone does not.
    detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ")
    print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
    sys.exit(1)
except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
    print(f"count_tokens failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
fi

est_tokens() { echo $(( $(LC_ALL=C wc -c <"$1" | tr -d ' ') / 4 )); }

count_tokens() {
  # count_tokens <file> -> token count on stdout. Falls back to bytes/4 on any
  # per-file failure, so one bad response degrades a number rather than the run.
  local f="$1" est out rc=0
  est="$(est_tokens "$f")"
  if [ "$EXACT_OK" -ne 1 ]; then printf '%s' "$est"; return 0; fi
  out="$(python3 "$TMP/count.py" "$f" "$MODEL" 2>"$TMP/ct.err")" || rc=$?
  if [ "$rc" -ne 0 ] || ! printf '%s' "$out" | grep -qE '^[0-9]+$'; then
    echo "WARN exact count failed for $f ($(tr -d '\n' <"$TMP/ct.err")); using estimate" >&2
    printf '%s' "$est"
  else
    printf '%s' "$out"
  fi
}

jesc() {
  # Minimal JSON string escaping for the values this script emits (repo-relative
  # paths and markdown headings): backslash, double quote, tab.
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e "s/$TAB/\\\\t/g"
}

# --- policy file ----------------------------------------------------------
P_LINES=$(LC_ALL=C wc -l <"$POLICY" | tr -d ' ')
P_BYTES=$(LC_ALL=C wc -c <"$POLICY" | tr -d ' ')
P_TOKENS=$(count_tokens "$POLICY")
[ "$P_BYTES" -gt 0 ] || P_BYTES=1

# --- section census -------------------------------------------------------
# LC_ALL=C makes awk's length() byte-based rather than character-based, so the
# per-section bytes sum to wc -c.
AWK_RC=0
LC_ALL=C awk -v tab="$TAB" '
  function flush() { if (started) printf "%d%s%d%s%s\n", lines, tab, bytes, tab, title }
  /^## / { flush(); started=1; title=substr($0, 4); lines=1; bytes=length($0)+1; next }
  { if (!started) { started=1; title="(preamble)"; lines=0; bytes=0 }
    lines++; bytes += length($0)+1 }
  END { flush() }
' "$POLICY" >"$TMP/sections.tsv" || AWK_RC=$?
if [ "$AWK_RC" -ne 0 ]; then
  echo "ERROR section census failed (awk exit $AWK_RC)" >&2
  exit 2
fi

# --- link graph -----------------------------------------------------------
# Reachability from the policy file over relative markdown links, computed
# transitively: the cohort convention is AGENTS.md -> docs/SKILLS.md -> deeper
# docs, so a direct-links-only check reports every second-hop doc as an orphan.
norm() {
  # norm <dir> <target> -> repo-relative path with . and .. resolved.
  local dir="$1" tgt="$2" combined out part oldifs
  case "$tgt" in
    /*) combined="${tgt#/}" ;;
    *) combined="${dir:+$dir/}$tgt" ;;
  esac
  out=""
  oldifs="$IFS"
  IFS='/'
  for part in $combined; do
    case "$part" in
      ""|.) ;;
      ..) case "$out" in */*) out="${out%/*}" ;; *) out="" ;; esac ;;
      *) out="${out:+$out/}$part" ;;
    esac
  done
  IFS="$oldifs"
  printf '%s' "$out"
}

extract_links() {
  # Relative markdown link targets, with anchors and absolute URLs stripped.
  # Targets containing <>, *, or a comma-space are prose that happens to sit in
  # bracket-paren form — `[label](references/<name>.md)` documenting a naming
  # convention, or a parenthesised list. Reporting them as dead links trains the
  # reader to ignore the dead-link list, so they are dropped here.
  grep -oE '\]\([^)]+\)' "$1" 2>/dev/null \
    | sed -e 's/^](//' -e 's/)$//' -e 's/#.*$//' \
    | grep -vE '^(https?:|mailto:|//|$)' \
    | grep -vE '[<>*]|, ' || true
}

is_archival() {
  # True when any path component of <path> is an archival directory name. Matched
  # at any depth, not just directly under DOCS_DIR: vendored skill trees nest
  # them (docs/superpowers/plans/, docs/superpowers/specs/), and a depth-1-only
  # test reports every one of those snapshots as a live orphan.
  local p="$1" name
  for name in $ARCHIVAL; do
    [ -n "$name" ] || continue
    case "/$p/" in
      */"$name"/*) return 0 ;;
    esac
  done
  return 1
}

in_scope() {
  # The curated surface: the policy file, plus live reference docs under
  # DOCS_DIR. Only these are traversed and only their links are reported as
  # dead. A root CHANGELOG.md or README.md is reachable but not curated — its
  # links to since-moved source files are a historical record, and reporting
  # them buries the rot that actually needs fixing.
  local p="$1"
  [ "$p" = "$POLICY" ] && return 0
  case "$p" in
    "$DOCS_DIR"/*) is_archival "$p" && return 1; return 0 ;;
  esac
  return 1
}

: >"$TMP/reachable"
: >"$TMP/refs"
: >"$TMP/dead"
QUEUE=("$POLICY")
qi=0
while [ "$qi" -lt "${#QUEUE[@]}" ]; do
  cur="${QUEUE[$qi]}"
  qi=$(( qi + 1 ))
  grep -Fxq "$cur" "$TMP/reachable" && continue
  printf '%s\n' "$cur" >>"$TMP/reachable"
  curdir="$(dirname "$cur")"
  [ "$curdir" = "." ] && curdir=""
  extract_links "$cur" >"$TMP/links.raw"
  while IFS= read -r raw; do
    [ -n "$raw" ] || continue
    tgt="$(norm "$curdir" "$raw")"
    [ -n "$tgt" ] || continue
    if [ "$cur" = "$POLICY" ]; then printf '%s\n' "$tgt" >>"$TMP/refs"; fi
    if [ ! -e "$tgt" ]; then
      printf '%s -> %s\n' "$cur" "$tgt" >>"$TMP/dead"
      continue
    fi
    # Out-of-scope targets (archival docs, root-level history files) are recorded
    # as reachable — so they never count as orphans — but are not traversed.
    if in_scope "$tgt"; then
      case "$tgt" in
        *.md) if [ -f "$tgt" ]; then QUEUE+=("$tgt"); fi ;;
      esac
    else
      printf '%s\n' "$tgt" >>"$TMP/reachable"
    fi
  done <"$TMP/links.raw"
done

# --- reference docs -------------------------------------------------------
: >"$TMP/docs.tsv"
if [ -d "$DOCS_DIR" ]; then
  FIND_RC=0
  find "$DOCS_DIR" -type f -name '*.md' >"$TMP/docfiles" 2>"$TMP/find.err" || FIND_RC=$?
  if [ "$FIND_RC" -ne 0 ]; then
    echo "ERROR find over $DOCS_DIR failed (exit $FIND_RC): $(cat "$TMP/find.err")" >&2
    exit 2
  fi
  [ -s "$TMP/find.err" ] && echo "WARN find over $DOCS_DIR: $(cat "$TMP/find.err")" >&2
  ARCHIVAL_SKIPPED=0
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    if is_archival "$d"; then
      ARCHIVAL_SKIPPED=$(( ARCHIVAL_SKIPPED + 1 ))
      continue
    fi
    dl=$(LC_ALL=C wc -l <"$d" | tr -d ' ')
    db=$(LC_ALL=C wc -c <"$d" | tr -d ' ')
    dt=$(count_tokens "$d")
    linked=false
    grep -Fxq "$d" "$TMP/reachable" && linked=true
    printf '%s%s%s%s%s%s%s%s%s\n' "$dl" "$TAB" "$db" "$TAB" "$dt" "$TAB" "$linked" "$TAB" "$d" >>"$TMP/docs.tsv"
  done <"$TMP/docfiles"
else
  ARCHIVAL_SKIPPED=0
  echo "WARN no $DOCS_DIR directory — reference-doc metrics will be empty" >&2
fi
if [ "$ARCHIVAL_SKIPPED" -gt 0 ]; then
  echo "INFO skipped $ARCHIVAL_SKIPPED archival doc(s) under: $ARCHIVAL" >&2
fi

# --- emit -----------------------------------------------------------------
json_list() {
  # json_list <file> — one value per line -> JSON array of strings.
  local f="$1" line n=0
  printf '['
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    [ "$n" -eq 0 ] || printf ', '
    n=1
    printf '"%s"' "$(jesc "$line")"
  done <"$f"
  printf ']'
}

over_policy=false
[ "$P_TOKENS" -gt "$BUDGET" ] && over_policy=true
exact_flag=false
[ "$EXACT_OK" -eq 1 ] && exact_flag=true

sort -t"$TAB" -k2,2nr "$TMP/sections.tsv" >"$TMP/sections.sorted"
sort -t"$TAB" -k3,3nr "$TMP/docs.tsv" >"$TMP/docs.sorted"
awk -F"$TAB" '$4 == "false" { print $5 }' "$TMP/docs.tsv" | sort >"$TMP/orphans"
sort -u "$TMP/refs" >"$TMP/refs.sorted"
sort -u "$TMP/dead" >"$TMP/dead.sorted"

printf '{\n'
printf '  "policy": {"path": "%s", "lines": %s, "bytes": %s, "tokens": %s, "tokens_exact": %s, "budget": %s, "over_budget": %s},\n' \
  "$(jesc "$POLICY")" "$P_LINES" "$P_BYTES" "$P_TOKENS" "$exact_flag" "$BUDGET" "$over_policy"

printf '  "sections": [\n'
first=1
while IFS="$TAB" read -r sl sb st; do
  [ -n "${sl:-}" ] || continue
  [ "$first" -eq 1 ] || printf ',\n'
  first=0
  printf '    {"title": "%s", "lines": %s, "bytes": %s, "tokens": %s, "share": %s}' \
    "$(jesc "$st")" "$sl" "$sb" "$(( sb / 4 ))" "$(( sb * 100 / P_BYTES ))"
done <"$TMP/sections.sorted"
[ "$first" -eq 1 ] || printf '\n'
printf '  ],\n'

printf '  "docs": [\n'
first=1
docs_tokens=0
while IFS="$TAB" read -r dl db dt dlinked dpath; do
  [ -n "${dl:-}" ] || continue
  docs_tokens=$(( docs_tokens + dt ))
  dover=false
  [ "$dt" -gt "$DOC_BUDGET" ] && dover=true
  [ "$first" -eq 1 ] || printf ',\n'
  first=0
  printf '    {"path": "%s", "lines": %s, "bytes": %s, "tokens": %s, "linked": %s, "over_budget": %s}' \
    "$(jesc "$dpath")" "$dl" "$db" "$dt" "$dlinked" "$dover"
done <"$TMP/docs.sorted"
[ "$first" -eq 1 ] || printf '\n'
printf '  ],\n'

printf '  "links": {"refs": '
json_list "$TMP/refs.sorted"
printf ', "dead": '
json_list "$TMP/dead.sorted"
printf ', "orphans": '
json_list "$TMP/orphans"
printf '},\n'

# tokens_live = policy + every live (non-archival) doc reachable from it. This
# is the ceiling on what one session can pull in from the repo's own guidance.
live_tokens="$P_TOKENS"
while IFS="$TAB" read -r dl db dt dlinked dpath; do
  [ -n "${dl:-}" ] || continue
  [ "$dlinked" = "true" ] && live_tokens=$(( live_tokens + dt ))
done <"$TMP/docs.tsv"

printf '  "totals": {"tokens_policy": %s, "tokens_docs": %s, "tokens_live": %s, "files_docs": %s, "archival_skipped": %s}\n' \
  "$P_TOKENS" "$docs_tokens" "$live_tokens" "$(LC_ALL=C wc -l <"$TMP/docs.tsv" | tr -d ' ')" "$ARCHIVAL_SKIPPED"
printf '}\n'
