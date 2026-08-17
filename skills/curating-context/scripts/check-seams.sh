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
  --base-ledger PATH
                   Take the base from the newest row in the telemetry ledger
                   PATH that carries a `repo_commit`, so the sweep spans the
                   interval since the last recorded measurement. This is what
                   the scheduled cadence passes, and it exists because `--base
                   HEAD` on a clean checkout compares the policy file against
                   itself: the diff is empty, so the moved-title class — the
                   only one that needs a base — was structurally zero in every
                   scheduled run, forever (#169).
                   Mutually exclusive with --base; naming a revision by hand is
                   how you override this deliberately.
                   NO PREDECESSOR is defined rather than fallen into: with no
                   ledger, no rows, or no row carrying a `repo_commit`, the base
                   is HEAD, the report SAYS the interval is empty, and the
                   base-dependent classes contribute nothing that run. A commit
                   that is not in this repo's history — a rewrite, a shallow
                   clone — falls back the same way with a WARN naming it.
  --file PATH      Policy file. Default: AGENTS.md, else CLAUDE.md.
  --docs-dir DIR   Reference-doc root. Default: CONTEXT_DOCS_DIR, then
                   .skills/context-docs-dir, then docs.
  --no-source      Skip the source classes below. For a repo whose tracked
                   source legitimately names the policy file everywhere — a
                   tooling repo, say — where the sweep is all noise. The report
                   says when the sweep ran with this on, so a clean exit never
                   silently means "not looked at".
  --ack-file PATH  Acknowledgement file. Default: .skills/context-seams-ok.
                   One entry per line, two forms:
                     CONTENT            substring of "<class> <path> <line>"
                     PATH :: CONTENT    both halves matched independently — use
                                        this to pin an entry to one file, since
                                        path-then-content as one substring only
                                        works when the content starts its line
                   A matched hit is reported under acknowledged, excluded from
                   the count, and does not trip exit 3. Lines STARTING with #
                   are comments;
                   a # anywhere else is part of the pattern, because
                   provenance-heading hits contain issue numbers and stripping
                   inline comments silently broadened exactly those entries.
                   Substrings match content rather than line numbers, so edits
                   elsewhere in a file do not invalidate an entry — and an
                   entry stops matching the moment the line it acknowledged
                   changes, which is exactly when it should be re-judged.
                   One entry per judged line: the report charges each hit to
                   the first pattern that matched and WARNs on any pattern
                   covering more than 3 hits or more than one file.
  -h, --help       Show this help and exit 0.

What it reports, in four classes:

  back-references  Every mention of THIS run's policy filename — whatever
                   --file named, or both AGENTS.md and CLAUDE.md when
                   autodetecting — inside a live reference doc. A doc that says
                   "see AGENTS.md for X" is wrong the moment X moves, and the run
                   that moved X is the run reading this report. Each hit needs a
                   human decision; a mention is not automatically wrong.

  moved-title refs Prose or link references, anywhere in the live surface, to
                   the title of a section that LEFT the policy file since
                   --base. These are the highest-confidence seams: something
                   still points at a home that no longer exists. A title of two
                   or more words (and 8+ characters) is matched anywhere; a
                   generic one — People, Organizations — only on a line that
                   points somewhere, meaning a §, a markdown link, or a .md
                   filename, because otherwise it matches every ordinary use of
                   the word. The report names the titles swept that way.

  heading defects  Within each live doc: duplicate normalised headings (the
                   destination already covered the topic and the demotion
                   appended a second copy), and headings carrying provenance —
                   "from AGENTS.md" or an issue number — which ages into noise
                   and bakes the run into permanent anchor slugs.

  source refs      The same two reference shapes — the policy filename, and a
                   moved title — in tracked source OUTSIDE the docs tree, as
                   their own classes (source-back-reference, source-moved-title)
                   so they do not drown the doc classes. Docstrings ship inside
                   wheels: a consumer reading one in site-packages is pointed at
                   a policy file they do not have. One adoption run left 16 such
                   references across 13 files and this sweep reported none of
                   them while fixing one it stumbled on — worse than missing all
                   of them, since the clean exit reads as "swept". Seven of the
                   sixteen named the section title and not the filename, so a
                   filename grep alone finds nine — which is why the moved-title
                   set is swept here too, and why it had to be tightened first.
                   Do NOT fix a hit by repointing it at a bare docs/ path:
                   that has no valid resolution from an installed wheel and can
                   silently resolve to a different repo's file in a sibling
                   checkout. Qualify it — `<distribution> docs/<FILE>.md`.

                   Swept only when a section actually LEFT the policy file since
                   --base, because that is what makes a source mention stale; a
                   script that reads the policy file names it legitimately, and
                   sweeping unconditionally buries the class in hundreds of
                   those. The report states its coverage either way. Tracked
                   files only (git ls-files, so the repo's ignore rules apply),
                   skipping *.md, the docs tree, .skills, archival subtrees, and
                   anything binary or over 500 KB.

Sections whose titles still exist in the policy file are not reported as moved.

WHAT THE BASE CHANGES, and what it does not: back-references and the heading
defects are read off the live surface and are a STANDING count, the same under
any base. moved-title, and the source classes it gates, are scoped to what left
the policy file since --base — an INTERVAL count. `seams` is the sum, so it is
never purely an accrual, and widening the base widens only half of it.

The report goes to stdout in full. The last three lines are machine-readable:

  seam_base: <REF>
  seams_acked: <M>
  seams: <N>

The two counts are what `record-telemetry.sh --seams N --seams-acked M` records
after the hits have been resolved or judged legitimate (re-run to confirm them).
`seam_base` is the revision they were measured from — not recorded, because the
row already carries `repo_commit` and the previous row's is where this one
started.

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
BASE_SET=0
BASE_LEDGER=""
POLICY=""
DOCS_DIR=""
ACK_FILE=".skills/context-seams-ok"
SWEEP_SOURCE=1

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a revision}"; BASE_SET=1; shift 2 ;;
    --base-ledger) BASE_LEDGER="${2:?--base-ledger needs a path}"; shift 2 ;;
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --no-source) SWEEP_SOURCE=0; shift ;;
    --ack-file) ACK_FILE="${2:?--ack-file needs a path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Refused rather than ranked. A precedence rule here would be invisible at the
# call site: whichever of the two lost, the sweep would still print a report and
# a count, and the reader would have no way to tell which interval it covered.
if [ -n "$BASE_LEDGER" ] && [ "$BASE_SET" -eq 1 ]; then
  echo "ERROR --base and --base-ledger are mutually exclusive: one names the" >&2
  echo "      interval start, the other reads it from the ledger. Pick one." >&2
  exit 1
fi

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
# C-runs-when-A-is-true is the intent: both tests must hold, and either one
# failing means the same thing — no library, no measurement, exit 2.
# shellcheck disable=SC2015
[ -n "$_libdir" ] && [ -f "$_libdir/_context-lib.sh" ] || {
  echo "ERROR _context-lib.sh not found next to $_self" >&2; exit 2; }
# shellcheck source=_context-lib.sh
. "$_libdir/_context-lib.sh"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR not inside a git repository" >&2; exit 2; }
cd "$ROOT" || { echo "ERROR cannot cd to $ROOT" >&2; exit 2; }

# --- the interval this sweep spans ----------------------------------------
# Paths are resolved from the repo root, like every other path option here.
#
# The ledger records one repo_commit per measurement, so the newest one is the
# state of the tree the last row described — the start of the interval this run
# closes. Read newest-wins over the whole file rather than matched to `file`:
# the commit is a property of the REPO, and "since this repo was last measured"
# is the interval, whichever policy file that measurement named.
if [ -n "$BASE_LEDGER" ]; then
  LAST_COMMIT=""
  if [ -f "$BASE_LEDGER" ]; then
    LAST_COMMIT="$(python3 - "$BASE_LEDGER" <<'PY'
import json
import sys

found = ""
# A malformed line is skipped, never fatal: the ledger is append-only and a
# half-written row from an interrupted run must not blind every future sweep.
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            commit = row.get("repo_commit")
            if isinstance(commit, str) and commit.strip():
                found = commit.strip()
print(found)
PY
)" || LAST_COMMIT=""
  fi
  if [ -z "$LAST_COMMIT" ]; then
    # Defined, not fallen into. HEAD is the same revision the working tree is
    # on, so the interval is EMPTY — which is the truth about a first run, and
    # the report has to say it rather than present a standing count as a week's
    # accrual. The row this sweep feeds carries its repo_commit, so the next
    # run has a real interval.
    BASE="HEAD"
    BASE_NOTE="note: no previous measurement in $BASE_LEDGER carries a repo_commit, so this run has no predecessor. The interval is EMPTY: moved-title and the source classes cannot contribute, and the count below is the standing surface only. The row this run feeds records its commit, so the next sweep spans a real interval."
  elif git rev-parse --verify --quiet "$LAST_COMMIT^{commit}" >/dev/null 2>&1; then
    BASE="$LAST_COMMIT"
    BASE_NOTE="note: sweeping the interval since the last recorded measurement ($LAST_COMMIT, from $BASE_LEDGER)."
  else
    # Loudly, because the silent version is permanent: a rewritten history
    # zeroes the base-dependent classes every week thereafter and the count
    # keeps looking healthy.
    BASE="HEAD"
    BASE_NOTE="WARN the last recorded measurement names commit $LAST_COMMIT, which is not in this repo's history — a rewrite, or a shallow clone. Falling back to HEAD, so the interval is EMPTY this run and moved-title cannot contribute."
  fi
  printf '%s\n' "$BASE_NOTE"
fi

if [ -z "$POLICY" ]; then
  for f in AGENTS.md CLAUDE.md; do
    [ -f "$f" ] && { POLICY="$f"; break; }
  done
fi
# C-runs-when-A-is-true is the intent: a named-but-absent policy file and no
# policy file at all are the same failure to this script.
# shellcheck disable=SC2015
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

# Tracked source outside the docs tree: the surface the sweep never looked at.
# git ls-files rather than find — it is limited to tracked files and inherits
# the repo's ignore rules for free, so a build tree or a vendored dependency
# cannot flood the report. Markdown is excluded everywhere: the docs classes
# already own the docs tree, and a README naming the policy file is navigation
# rather than a shipped docstring. .skills is excluded because it holds this
# sweep's own acknowledgement file and the telemetry ledger, both of which quote
# the policy filename by design.
: >"$TMP/src"
if [ "$SWEEP_SOURCE" -eq 1 ]; then
  LS_RC=0
  git ls-files -z -- ':!*.md' ':!*.markdown' ':!.skills' ":!$DOCS_DIR" \
    >"$TMP/src.all" 2>"$TMP/ls.err" || LS_RC=$?
  [ "$LS_RC" -eq 0 ] || {
    echo "ERROR git ls-files failed: $(tr -d '\n' <"$TMP/ls.err")" >&2; exit 2; }
  while IFS= read -r -d '' f; do
    [ -n "$f" ] || continue
    ctx_is_archival "$f" || printf '%s\n' "$f" >>"$TMP/src"
  done <"$TMP/src.all"
fi

RC=0
python3 - "$TMP/base_policy" "$REL" "$TMP/docs" "$ACK_FILE" "$TMP/src" \
  "$SWEEP_SOURCE" "$BASE" <<'PY' || RC=$?
import os
import re
import sys

(base_policy_path, policy_rel, docs_list, ack_file, src_list,
 sweep_source, base_ref) = sys.argv[1:8]

with open(base_policy_path, encoding="utf-8", errors="replace") as fh:
    base_lines = fh.read().splitlines()
with open(policy_rel, encoding="utf-8", errors="replace") as fh:
    now_text = fh.read()
now_lines = now_text.splitlines()

docs = [d for d in open(docs_list, encoding="utf-8").read().splitlines() if d]
src = [s for s in open(src_list, encoding="utf-8").read().splitlines() if s]

HEADING = re.compile(r"^(#{2,6})\s+(.*?)\s*$")


def headings(lines):
    return [(m.group(1), m.group(2)) for m in map(HEADING.match, lines) if m]


def norm_title(t):
    """Backticks and trailing punctuation are formatting, not identity."""
    return re.sub(r"[`*_]", "", t).strip().rstrip(".:").lower()


base_titles = {norm_title(t): t for _, t in headings(base_lines)}
now_titles = {norm_title(t) for _, t in headings(now_lines)}
# Titles that LEFT the policy file since base, in two tiers.
#
# A title is swept BARE — matched anywhere in the surface — only when it is
# specific enough to be a pointer rather than a noun: two or more words, and at
# least 8 characters. The character floor alone was the whole filter, and it
# shipped a flood: a doc split into per-resource docs titled People,
# Organizations, Jurisdictions produced 205 moved-title hits, every one a
# verified false positive (an admin breadcrumb, a scope-table row, prose using
# the plural noun), against 55 provenance-heading hits and zero real
# references. `Organizations` is thirteen characters, so raising the floor
# would have changed nothing. Descriptive titles on the same programme produced
# zero false positives, which is why bare matching survives for them — and why
# it must: a source docstring citing "WordPress conventions" and nothing else
# is a seam nothing else can see.
#
# Every OTHER moved title is still swept, but only on a line that POINTS
# somewhere — a §, a markdown link, or a .md filename. A title that moved
# matters where something refers readers to it, and "see docs/X.md § People" is
# exactly the reference this class exists to catch. The three measured false
# positives carry none of those markers.
WORDS = re.compile(r"[0-9a-z]+")
POINTER = re.compile(r"§|\]\(|\.md\b", re.IGNORECASE)

moved = {k: v for k, v in base_titles.items() if k not in now_titles}
sweepable = {k: v for k, v in moved.items()
             if len(k) >= 8 and len(WORDS.findall(k)) >= 2}
generic = {k: v for k, v in moved.items() if k not in sweepable}

# The name this run is sweeping FOR, taken from the target rather than assumed.
# The tuple used to be hardcoded, so `--file skills/x/SKILL.md` still hunted for
# the literal strings below: run against a skill *about* curating AGENTS.md it
# returned 296 hits, every one subject matter and not one a reference to the
# swept file. That is worse than an unswept class, because the only ack entry
# that silences noise at that scale is a blanket pattern in the repo's real seam
# ledger (#138).
#
# Both default names are kept when the target IS one of them, which is every
# autodetected run: the cohort norm is `CLAUDE.md -> ./AGENTS.md`, so a doc
# naming either name back-references the one policy file, and dropping the
# sibling would lose half the class it was written for.
#
# Scoped by WHERE the mention is, because a basename is only unambiguous inside
# the tree that owns it. This repo carries twenty SKILL.md files, so deriving
# the name and stopping there merely traded 296 AGENTS.md hits for 95 SKILL.md
# ones — in other skills' scripts and in tests, none of them about the swept
# file. A bare name resolves to the target from inside the target's own
# directory; from outside it takes a path. A policy file at the repo root owns
# the whole tree, which is every autodetected run, so nothing narrows there.
DEFAULT_POLICY_NAMES = ("AGENTS.md", "CLAUDE.md")
_policy_dir = os.path.dirname(policy_rel)
_policy_name = os.path.basename(policy_rel)
LOCAL_POLICY_NAMES = (DEFAULT_POLICY_NAMES
                      if _policy_name in DEFAULT_POLICY_NAMES
                      else (_policy_name,))
OUTER_POLICY_NAMES = (policy_rel,) if _policy_dir else LOCAL_POLICY_NAMES


def names_policy_file(path, line):
    """Does `line`, read in `path`, name the file this run is sweeping?"""
    local = (not _policy_dir or path == policy_rel
             or path.startswith(_policy_dir + "/"))
    names = LOCAL_POLICY_NAMES if local else OUTER_POLICY_NAMES
    return any(n in line for n in names)


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
        if names_policy_file(d, line):
            seams.append(("back-reference", f"{d}:{i}", line.strip()[:120],
                          line.strip()))

# -- class 2: references to a title that left the policy file. Searched in the
#    docs AND in the policy file itself — "now lives in docs/X.md" pointing at
#    a section the same run renamed is a seam too. The moved title's own new
#    heading is not a seam, so heading lines matching the title exactly are
#    skipped.
for k, orig in moved.items():
    pat = re.compile(re.escape(orig), re.IGNORECASE)
    bare = k in sweepable
    for path in [policy_rel] + docs:
        for i, line in enumerate(doc_lines(path), 1):
            if not pat.search(line):
                continue
            if not bare and not POINTER.search(line):
                # A generic title on a line that points nowhere is the word,
                # not a reference to the section.
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
                          f"references '{orig}' — {line.strip()[:100]}",
                          line.strip()))

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
                          "destination already cover this?", line.strip()))
        else:
            seen[k] = i

# -- class 3b: provenance baked into a heading. Slugs are permanent; the run
#    that produced them is not interesting a month later.
prov = re.compile(r"(from\s+(AGENTS|CLAUDE)\.md|#\d{2,})", re.IGNORECASE)
for path in [policy_rel] + docs:
    for i, line in enumerate(doc_lines(path), 1):
        m = HEADING.match(line)
        if m and prov.search(m.group(2)):
            seams.append(("provenance-heading", f"{path}:{i}", m.group(2)[:100],
                          line.strip()))

# -- class 4: the same two shapes in tracked SOURCE, as their own classes and
#    reported last, so they cannot drown the doc classes.
#
#    Nothing outside the docs tree was ever read, so a curation could relocate a
#    contract and leave every production caller's docstring pointing at the old
#    home — 16 of them across 13 files on one adoption run, under a clean exit.
#    These ship inside wheels, where the reader has no policy file at all.
#
#    Only when something MOVED. A source file naming the policy file is usually
#    correct (a script that reads it must name it), and an unconditional sweep
#    buries the class: the skill's own repo would report ~180. What makes a
#    mention stale is content having LEFT, which is what `moved` measures.
#
#    One hit per line, filename first: a docstring citing both the file and the
#    section is one judgement, not two.
MAX_SOURCE_BYTES = 500 * 1024


def source_lines(path):
    """Text only. git ls-files lists every tracked blob, including images and
    fixtures; decoding those is noise at best and slow at worst."""
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            return []
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    if b"\0" in data:
        return []
    return data.decode("utf-8", "replace").splitlines()


if src and moved:
    title_pats = [(k, orig, re.compile(re.escape(orig), re.IGNORECASE))
                  for k, orig in moved.items()]
    for s in src:
        for i, line in enumerate(source_lines(s), 1):
            if names_policy_file(s, line):
                seams.append(("source-back-reference", f"{s}:{i}",
                              line.strip()[:120], line.strip()))
                continue
            for k, orig, pat in title_pats:
                if not pat.search(line):
                    continue
                if k not in sweepable and not POINTER.search(line):
                    continue
                seams.append(("source-moved-title", f"{s}:{i}",
                              f"references '{orig}' — {line.strip()[:100]}",
                              line.strip()))
                break

# Acknowledged hits: judged legitimate on an earlier run and recorded in the
# ack file, one substring per line. Matched on content, not line numbers, so an
# entry survives unrelated edits and expires the moment its line changes —
# which is exactly when it should be re-judged. This is what makes a stable set
# of legitimate references a CLEAN exit instead of a permanent alarm: the
# alternative steady state is exit 3 every week, and a metric that can only be
# zeroed by deleting legitimate references invites exactly that deletion.
# Comments only at LINE START. Stripping an inline `#` silently turned an
# entry containing one — exactly what acknowledging a provenance-heading hit
# requires, since that class matches on #\d{2,} — into a BROADER pattern than
# the author wrote. "Fixed in #412" became "Fixed in", which still matched the
# judged hit and every future "Fixed in ..." hit nobody judged.
patterns = []
try:
    with open(ack_file, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw and not raw.startswith("#"):
                patterns.append(raw)
except OSError:
    pass

# Matching is against the FULL source line, not the truncated display — a
# pattern pasted from the actual doc line must work, not only one copied from
# the report. First matching pattern is charged with the hit, so a pattern's
# blast radius is visible below.
#
# Two forms. "PATH :: CONTENT" matches the two halves independently — needed
# because path-then-content as ONE substring only works when the content starts
# its line, and a heading hit's line starts with "## ". A plain entry is a
# substring of "<class> <path> <full line>".
def matches(p, cls, path, full):
    if " :: " in p:
        p_path, p_content = p.split(" :: ", 1)
        return p_path in path and p_content in full
    return p in f"{cls} {path} {full}"


new, acked = [], []
matched_by = {p: [] for p in patterns}
for cls, loc, detail, full in seams:
    path = loc.rsplit(":", 1)[0]
    hit_pattern = next((p for p in patterns if matches(p, cls, path, full)), None)
    if hit_pattern is None:
        new.append((cls, loc, detail))
    else:
        acked.append((cls, loc))
        matched_by[hit_pattern].append(loc)

if generic:
    # Say which titles got the weaker sweep. A heuristic that silently narrows
    # itself to stop a flood is indistinguishable, from the report, from one
    # that found nothing.
    named = ", ".join(sorted(generic.values()))
    print(f"note: {len(generic)} moved title(s) are too generic to sweep bare "
          f"({named[:120]}) — one word, or under 8 characters. They were "
          "matched only on lines that point somewhere: a §, a markdown link, "
          "or a .md filename.")
# What was and was not looked at outside the docs tree. Without this the exit
# code is the only signal, and a clean one reads as "swept" — which is how 16
# stale docstrings shipped under a report that had never opened a .py file.
if sweep_source != "1":
    print("note: source not swept (--no-source) — mentions of the policy file "
          "in tracked source outside the docs tree were not looked at.")
elif not moved:
    print(f"note: {len(src)} tracked source file(s) not swept — nothing left "
          "the policy file since --base, so a mention there is not fallout "
          "from this run.")
else:
    print(f"note: swept {len(src)} tracked source file(s) outside the docs "
          f"tree for the policy filename and {len(moved)} moved title(s).")
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
    for cls, loc in acked:
        print(f"  {cls}  {loc}")
    # Per-pattern accountability. An acknowledgement is one judged line, so a
    # pattern matching many hits — or hits across files — is doing the job of
    # judgement without the judging. That is the metric-gaming vector moved
    # into this file: one blanket line zeroes the count with no diff in the
    # docs, and without this report it would be indistinguishable from careful
    # entries.
    print("\n  by pattern:")
    for p, locs in matched_by.items():
        if not locs:
            continue
        print(f"    {len(locs)} hit(s): {p[:70]}")
        files = {l.rsplit(":", 1)[0] for l in locs}
        if len(locs) > 3 or len(files) > 1:
            print(f"    WARN this pattern is broad ({len(locs)} hits across "
                  f"{len(files)} file(s)) — an acknowledgement should cover ONE "
                  "judged line; split it or re-judge")
    unused = [p for p in patterns if not matched_by[p]]
    if unused:
        print(f"\n  {len(unused)} entry(ies) matched nothing — the line each "
              "acknowledged has changed or gone; re-judge and prune:")
        for p in unused:
            print(f"    {p[:70]}")

# ABOVE the two counts, which stay the last two lines — three readers parse the
# tail by position. The interval a count covers is not recoverable from the
# count, and `seams` mixes a standing half with an interval half, so a row of
# them is uninterpretable without knowing where each one started.
print(f"\nseam_base: {base_ref}")
print(f"seams_acked: {len(acked)}")
print(f"seams: {len(new)}")
sys.exit(3 if new else 0)
PY

exit "$RC"
