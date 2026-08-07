#!/usr/bin/env bash
# check-seams.sh — find the cross-reference seams a curation run leaves behind.
#
# prove-no-loss.sh proves moved content ARRIVED. Nothing before this proved the
# rest of the surface still DESCRIBES where it went. On the first cohort adoption
# (observo, their #412) a clean run — 0 dead links, 0 orphans, no-loss ok —
# shipped ten review findings, every one created by the curation itself: a doc
# whose header said its own contents lived in AGENTS.md, prose sending readers to
# a section that had moved into the very file they were reading, and duplicate
# command blocks appended next to the canonical ones. All were invisible to
# links.dead, because a resolvable link to the wrong content is not dead.
#
# A seam is REPORTED, not auto-fixed: a reference to the policy file is often
# legitimate. The count still matters — it goes onto the ledger row (--seams on
# record-telemetry.sh) so a skill change that claims to reduce this class is
# visible to the validation gate that judges it.
set -euo pipefail

usage() {
  cat <<'USAGE'
check-seams.sh — Phase 6.5: sweep the live surface for stale cross-references

Usage:
  check-seams.sh [options]

Options:
  --base REF       Revision holding the pre-curation policy file. Default: HEAD.
                   Use the branch point when the curation spans several commits.
  --file PATH      Policy file. Default: AGENTS.md, else CLAUDE.md.
  --docs-dir DIR   Reference-doc root. Default: CONTEXT_DOCS_DIR, then
                   .skills/context-docs-dir, then docs.
  --ack-file PATH  Acknowledgement file. Default: .skills/context-seams-ok.
                   One substring per line (# comments and blanks ignored); a hit
                   whose "<class> <path> <line content>" contains the substring
                   is reported under acknowledged, excluded from the count, and
                   does not trip exit 3. Substrings match content rather than
                   line numbers, so edits elsewhere in a file do not invalidate
                   an entry — and an entry stops matching the moment the line it
                   acknowledged changes, which is exactly when it should be
                   re-judged.
  -h, --help       Show this help and exit 0.

What it reports, in three classes:

  back-references  Every mention of the policy file's name (AGENTS.md or
                   CLAUDE.md) inside a live reference doc. A doc that says "see
                   AGENTS.md for X" is wrong the moment X moves — and the run
                   that moved X is the run reading this report. Each hit needs a
                   human decision; a mention is not automatically wrong.

  moved-title refs Prose or link references, anywhere in the live surface, to
                   the title of a section that LEFT the policy file since
                   --base. These are the highest-confidence seams: something
                   still points at a home that no longer exists.

  heading defects  Within each live doc: duplicate normalised headings (the
                   destination already covered the topic and the demotion
                   appended a second copy), and headings carrying provenance —
                   "from AGENTS.md" or an issue number — which ages into noise
                   and bakes the run into permanent anchor slugs.

Sections whose titles still exist in the policy file are not reported as moved.
The report goes to stdout in full. The last line is machine-readable:

  seams: <N>

which is the number to record with `record-telemetry.sh --seams N` after the
hits have been resolved or judged legitimate (re-run to confirm the count).

A hit judged LEGITIMATE goes in the acknowledgement file, not in the bin: a
reference to the policy file is often correct navigation, and deleting it to
zero the count is the same mistake as optimising tokens_live — the metric
improves while the surface gets worse. The number to watch across runs is the
DELTA, not the absolute; a stable acknowledged set with 0 new hits is the
healthy steady state.

Known noise: renaming a section flags prose that still uses the old title —
which is real rename fallout worth seeing — and can flag nothing else, because
a successor heading that merely contains the old title is skipped.

Exit codes:
  0  no unacknowledged seams
  1  usage error, or no policy file found
  2  infrastructure failure (base revision unreadable, python3 missing)
  3  one or more NEW seams to review — judge each: fix what lies, acknowledge
     what is legitimate, re-run
USAGE
}

BASE="HEAD"
POLICY=""
DOCS_DIR=""
ACK_FILE=".skills/context-seams-ok"

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a revision}"; shift 2 ;;
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --ack-file) ACK_FILE="${2:?--ack-file needs a path}"; shift 2 ;;
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

if [ -z "$POLICY" ]; then
  for f in AGENTS.md CLAUDE.md; do
    [ -f "$f" ] && { POLICY="$f"; break; }
  done
fi
[ -n "$POLICY" ] && [ -f "$POLICY" ] || {
  echo "ERROR no policy file found (looked for AGENTS.md, CLAUDE.md)" >&2; exit 1; }

DOCS_DIR="$(ctx_docs_dir "$ROOT" "$DOCS_DIR")"

TMP="$(mktemp -d)" || { echo "ERROR mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

# The policy file as it was before the run. Resolve a symlinked policy path the
# same way every other script does — `git show BASE:CLAUDE.md` returns the link
# target string, not the file.
REL="$(ctx_resolve_rel "$ROOT" "$POLICY")"
[ -n "$REL" ] || REL="$POLICY"
if ! git show "$BASE:$REL" >"$TMP/base_policy" 2>"$TMP/git.err"; then
  echo "ERROR cannot read $REL at $BASE: $(tr -d '\n' <"$TMP/git.err")" >&2
  exit 2
fi

# Live docs: every .md under the docs root, minus archival subtrees. The gate
# scripts use find | sort into a file rather than process substitution — the
# gate-script discipline this repo's STYLE.md requires.
: >"$TMP/docs"
if [ -d "$DOCS_DIR" ]; then
  FIND_RC=0
  find "$DOCS_DIR" -type f -name '*.md' 2>/dev/null | LC_ALL=C sort >"$TMP/docs.all" || FIND_RC=$?
  [ "$FIND_RC" -eq 0 ] || { echo "ERROR find failed under $DOCS_DIR" >&2; exit 2; }
  while IFS= read -r f; do
    ctx_is_archival "$f" || printf '%s\n' "$f" >>"$TMP/docs"
  done <"$TMP/docs.all"
fi

RC=0
python3 - "$TMP/base_policy" "$REL" "$TMP/docs" "$ACK_FILE" <<'PY' || RC=$?
import re
import sys

base_policy_path, policy_rel, docs_list, ack_file = sys.argv[1:5]

with open(base_policy_path, encoding="utf-8", errors="replace") as fh:
    base_lines = fh.read().splitlines()
with open(policy_rel, encoding="utf-8", errors="replace") as fh:
    now_text = fh.read()
now_lines = now_text.splitlines()

docs = [d for d in open(docs_list, encoding="utf-8").read().splitlines() if d]

HEADING = re.compile(r"^(#{2,6})\s+(.*?)\s*$")


def headings(lines):
    return [(m.group(1), m.group(2)) for m in map(HEADING.match, lines) if m]


def norm_title(t):
    """Backticks and trailing punctuation are formatting, not identity."""
    return re.sub(r"[`*_]", "", t).strip().rstrip(".:").lower()


base_titles = {norm_title(t): t for _, t in headings(base_lines)}
now_titles = {norm_title(t) for _, t in headings(now_lines)}
# Titles that LEFT the policy file since base. Short titles are excluded from
# the prose sweep below: grepping the surface for "Overview" or "Testing"
# drowns the real seams in coincidental matches, and a title that generic was
# never a useful pointer anyway.
moved = {k: v for k, v in base_titles.items() if k not in now_titles}
sweepable = {k: v for k, v in moved.items() if len(k) >= 8}

policy_names = ("AGENTS.md", "CLAUDE.md")
seams = []


def doc_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


# -- class 1: back-references — the policy file named inside a reference doc.
for d in docs:
    for i, line in enumerate(doc_lines(d), 1):
        if any(n in line for n in policy_names):
            seams.append(("back-reference", f"{d}:{i}", line.strip()[:120]))

# -- class 2: references to a title that left the policy file. Searched in the
#    docs AND in the policy file itself — "now lives in docs/X.md" pointing at
#    a section the same run renamed is a seam too. The moved title's own new
#    heading is not a seam, so heading lines matching the title exactly are
#    skipped.
for k, orig in sweepable.items():
    pat = re.compile(re.escape(orig), re.IGNORECASE)
    for path in [policy_rel] + docs:
        for i, line in enumerate(doc_lines(path), 1):
            if not pat.search(line):
                continue
            m = HEADING.match(line)
            if m and k in norm_title(m.group(2)):
                # The relocated section's own heading — or, after a RENAME, the
                # successor heading that still contains the old title. Flagging
                # the successor put a guaranteed-noise hit beside every real
                # rename-fallout hit; the prose references still catch the
                # fallout itself.
                continue
            seams.append(("moved-title", f"{path}:{i}",
                          f"references '{orig}' — {line.strip()[:100]}"))

# -- class 3a: duplicate headings inside one destination.
for d in docs:
    seen = {}
    for i, line in enumerate(doc_lines(d), 1):
        m = HEADING.match(line)
        if not m:
            continue
        k = norm_title(m.group(2))
        if k in seen:
            seams.append(("duplicate-heading", f"{d}:{i}",
                          f"'{m.group(2)}' also at line {seen[k]} — did the "
                          "destination already cover this?"))
        else:
            seen[k] = i

# -- class 3b: provenance baked into a heading. Slugs are permanent; the run
#    that produced them is not interesting a month later.
prov = re.compile(r"(from\s+(AGENTS|CLAUDE)\.md|#\d{2,})", re.IGNORECASE)
for path in [policy_rel] + docs:
    for i, line in enumerate(doc_lines(path), 1):
        m = HEADING.match(line)
        if m and prov.search(m.group(2)):
            seams.append(("provenance-heading", f"{path}:{i}", m.group(2)[:100]))

# Acknowledged hits: judged legitimate on an earlier run and recorded in the
# ack file, one substring per line. Matched on content, not line numbers, so an
# entry survives unrelated edits and expires the moment its line changes —
# which is exactly when it should be re-judged. This is what makes a stable set
# of legitimate references a CLEAN exit instead of a permanent alarm: the
# alternative steady state is exit 3 every week, and a metric that can only be
# zeroed by deleting legitimate references invites exactly that deletion.
patterns = []
try:
    with open(ack_file, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.split("#", 1)[0].strip()
            if raw:
                patterns.append(raw)
except OSError:
    pass

new, acked = [], []
for cls, loc, detail in seams:
    hay = f"{cls} {loc.rsplit(':', 1)[0]} {detail}"
    (acked if any(p in hay for p in patterns) else new).append((cls, loc, detail))

if moved and not sweepable:
    print(f"note: {len(moved)} section(s) left the policy file but every title "
          "is under 8 characters — too generic to sweep for.")
if new:
    print(f"{len(new)} seam(s) to review — each needs a decision, not "
          "necessarily a fix:\n")
    width = max(len(c) for c, _, _ in new)
    for cls, loc, detail in new:
        print(f"  {cls:<{width}}  {loc}")
        print(f"  {'':<{width}}  {detail}")
    print("\nA back-reference hit is wrong only if the content it points at "
          "moved. Judge each:")
    print(f"fix what lies, add what is legitimate to {ack_file}, then re-run — "
          "the count")
    print("below goes on the ledger row via --seams.")
else:
    print("OK — no unacknowledged cross-reference seams.")
if acked:
    print(f"\n{len(acked)} acknowledged seam(s) skipped (judged legitimate in "
          f"{ack_file}):")
    for cls, loc, _ in acked:
        print(f"  {cls}  {loc}")

print(f"\nseams: {len(new)}")
sys.exit(3 if new else 0)
PY

exit "$RC"
