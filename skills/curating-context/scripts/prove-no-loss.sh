#!/usr/bin/env bash
# prove-no-loss.sh — assert that nothing was silently dropped by a curation run.
#
# Every non-blank line of the policy file as it was at <base> must still be
# present verbatim, either inline or in a destination file. Lines that are not
# are reported; each one must be justified as duplicated, disproven, or a trained
# default before the run ships.
#
# This exists because the obvious check is not strong enough. "Grep a distinctive
# phrase from each moved block" passes when a block was moved AND reworded — the
# phrase is present, the line is not — and a paraphrase during a move is an
# unreviewable content change wearing a refactor's clothes. That failure was found
# on the first real run of this skill, by a line-level check, one line out of 226.
set -euo pipefail

usage() {
  cat <<'USAGE'
prove-no-loss.sh — verify a curation relocated content instead of dropping it

Usage:
  prove-no-loss.sh [options]

Options:
  --base REF       Revision holding the pre-curation policy file. Default: HEAD.
                   Use the branch point when the curation spans several commits.
  --file PATH      Policy file. Default: AGENTS.md, else CLAUDE.md.
  --docs-dir DIR   Reference-doc root searched for relocated content. Default:
                   CONTEXT_DOCS_DIR, then .skills/context-docs-dir, then docs.
  --also PATH      Additional destination to search (repeatable) — use when a
                   block was demoted somewhere other than the docs tree, e.g.
                   a skill's references/ directory.
  --show-relocated Also list which destination each moved line landed in.
  -h, --help       Show this help and exit 0.

What counts as "present":
  A line matches an entire line of the current policy file or of a destination —
  not a fragment of one — after normalising the two differences a move
  legitimately forces:

    heading level   `### Foo` in a policy file becomes `## Foo` at the top of its
                    own document.
    link depth      a relative link moving into docs/ gains one level, so
                    `](tests/x.py)` becomes `](../tests/x.py)`.

  Nothing else is normalised. Reflowed prose, changed wording, appended clauses,
  and dropped lines all fail, which is the point. Whole-line matching is what
  makes that true: substring matching passed a dropped `1. Commit and push`
  because it appeared inside "Step 9: 1. Commit and push when ready." elsewhere.

  The report goes to stdout in full, including the LOST list, so it stays in
  order through a pipe.

Exit codes:
  0  every line accounted for
  1  usage error, or no policy file found
  2  infrastructure failure (base revision unreadable, python3 missing)
  3  one or more lines unaccounted for — the run must justify or restore them
USAGE
}

BASE="HEAD"
POLICY=""
DOCS_DIR=""
SHOW_RELOCATED=0
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a revision}"; shift 2 ;;
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --also) EXTRA+=("${2:?--also needs a path}"); shift 2 ;;
    --show-relocated) SHOW_RELOCATED=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

# --- shared library -------------------------------------------------------
# Before the cd, deliberately: a relative invocation from a subdirectory leaves
# ${BASH_SOURCE[0]} relative to the ORIGINAL cwd, and resolving it after the cd
# looked for the library in the wrong tree and blamed the library for it.
_self="${BASH_SOURCE[0]}"
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 10 ]; do
  _t="$(readlink "$_self" 2>/dev/null)" || break
  case "$_t" in
    /*) _self="$_t" ;;
    *) _self="$(dirname "$_self")/$_t" ;;
  esac
  _n=$(( _n + 1 ))
done
_libdir="$(cd "$(dirname "$_self")" 2>/dev/null && pwd -P)" || _libdir=""
[ -n "$_libdir" ] && [ -f "$_libdir/_context-lib.sh" ] || {
  echo "ERROR _context-lib.sh not found next to $_self" >&2; exit 2; }
# shellcheck source=_context-lib.sh
. "$_libdir/_context-lib.sh"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR not inside a git repository" >&2; exit 2; }
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

DOCS_DIR="$(ctx_docs_dir "$ROOT" "$DOCS_DIR")"

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

# The pre-curation policy file. A symlink blob would give the link target rather
# than content, the same trap ctx_prev_bytes closes for the guard.
MODE="$(git ls-tree "$BASE" -- "$POLICY" 2>/dev/null | awk '{print $1; exit}')" || MODE=""
case "$MODE" in
  100644|100755) ;;
  '') echo "ERROR $POLICY does not exist at $BASE — nothing to compare against" >&2; exit 2 ;;
  *) echo "ERROR $BASE:$POLICY is mode $MODE, not a regular file" >&2; exit 2 ;;
esac
git show "$BASE:$POLICY" >"$TMP/before" 2>/dev/null || {
  echo "ERROR cannot read $BASE:$POLICY" >&2; exit 2; }

# Destinations: the policy file itself (content that stayed), every live
# reference doc, and anything named with --also.
: >"$TMP/dests"
printf '%s\n' "$POLICY" >>"$TMP/dests"
if [ -d "$DOCS_DIR" ]; then
  # Gate-like: this find populates the destination list, and a partial failure
  # silently shrinks it — lines that WERE relocated then report as LOST and the
  # run is blocked citing the wrong cause. Tempfile plus explicit exit-code
  # capture, the FIND_RC pattern from measure-context.sh and docs/STYLE.md,
  # because a process substitution's exit code is invisible to the parent shell.
  FIND_RC=0
  find "$DOCS_DIR" -type f -name '*.md' >"$TMP/docfiles" 2>"$TMP/find.err" || FIND_RC=$?
  if [ "$FIND_RC" -ne 0 ]; then
    echo "ERROR find over $DOCS_DIR failed (exit $FIND_RC): $(cat "$TMP/find.err")" >&2
    exit 2
  fi
  [ -s "$TMP/find.err" ] && echo "WARN find over $DOCS_DIR: $(cat "$TMP/find.err")" >&2
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    ctx_is_archival "$d" && continue
    printf '%s\n' "$d" >>"$TMP/dests"
  done <"$TMP/docfiles"
fi
for e in ${EXTRA[@]+"${EXTRA[@]}"}; do
  if [ -f "$e" ]; then printf '%s\n' "$e" >>"$TMP/dests"
  else echo "WARN --also $e is not a file; ignoring" >&2; fi
done
sort -u "$TMP/dests" >"$TMP/dests.u"

RC=0
python3 - "$TMP/before" "$POLICY" "$TMP/dests.u" "$SHOW_RELOCATED" <<'PY' || RC=$?
import re
import sys

before_path, policy, dests_path, show = sys.argv[1:5]

HEADING = re.compile(r"^#{1,6}\s+(.*)$")

def normalise(raw):
    """One line -> its comparable form, or "" when it carries no content.

    Exactly two differences a move legitimately forces are erased:

      link depth    a block moving into docs/ gains a level, so
                    `](tests/x.py)` becomes `](../tests/x.py)`.
      heading level a `###` subsection promoted to its own document's `##`.

    Heading text is tagged rather than merely stripped of its hashes. Stripping
    alone would let a `# comment` inside a fenced block collide with the prose
    line `comment`, which is a false match in the direction that hides loss.
    """
    line = raw.strip()
    if not line:
        return ""
    line = line.replace("](../", "](")
    m = HEADING.match(line)
    return "H:" + m.group(1).strip() if m else line

try:
    before = open(before_path, encoding="utf-8", errors="replace").read().splitlines()
    dest_paths = [p for p in open(dests_path, encoding="utf-8").read().splitlines() if p]
    # A SET of whole lines per destination, not the raw text. Substring matching
    # against the text was the original implementation and it was far weaker than
    # it looked: a dropped line counted as "relocated verbatim" whenever it
    # happened to appear as a fragment inside unrelated prose. Measured on a
    # five-line deletion, four of the five passed — `1. Commit and push` matched
    # inside "Step 9: 1. Commit and push when ready.", and a bare ``` matched
    # almost anything. Short and common lines were effectively unchecked, and a
    # policy file is mostly those.
    dests = {}
    for path in dest_paths:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
        dests[path] = {n for n in (normalise(l) for l in lines) if n}
except OSError as exc:
    print(f"ERROR {exc}", file=sys.stderr)
    sys.exit(2)

inline = dests.get(policy, set())
others = [p for p in dest_paths if p != policy]
kept, relocated, lost = 0, {}, []

for raw in before:
    line = normalise(raw)
    if not line:
        continue
    if line in inline:
        kept += 1
        continue
    where = next((p for p in others if line in dests[p]), None)
    if where:
        relocated.setdefault(where, []).append(raw.strip())
    else:
        lost.append(raw.strip())

# One stream for the whole report. Split across stdout and stderr it interleaved
# through a pipe, and the failure list printed above the counts explaining it.
out = sys.stdout
total = kept + sum(len(v) for v in relocated.values()) + len(lost)
print(f"policy file at base: {total} non-blank lines", file=out)
print(f"  still inline:               {kept}", file=out)
for path in sorted(relocated):
    print(f"  relocated verbatim -> {path}: {len(relocated[path])}", file=out)
    if show == "1":
        for line in relocated[path]:
            print(f"      {line[:120]}", file=out)
print(f"  UNACCOUNTED FOR:            {len(lost)}", file=out)

if lost:
    print(
        "\nEach line below is missing from the policy file AND from every "
        "destination.\nA curation may only drop a line with a named warrant — "
        "verbatim duplication\nelsewhere in the surface, a command that "
        "disproved it, or a trained default.\nOtherwise it was lost in transit; "
        "restore it verbatim.\n",
        file=out,
    )
    for line in lost:
        print(f"  LOST  {line[:160]}", file=out)
    out.flush()
    sys.exit(3)

print("\nOK — every line is either still inline or relocated verbatim.", file=out)

PY

exit "$RC"
