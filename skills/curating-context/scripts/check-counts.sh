#!/usr/bin/env bash
# check-counts.sh — find the counts in a policy file that rot silently.
#
# A bare number in an agent-context file is a claim nothing checks. `AGENTS.md`
# on CannObserv/power-map carried "180 `hx-get` reveals mean the forms don't
# exist without JS anyway". Three parties measured that same claim in one week
# and got 180, 189 and 182 — and nobody was wrong: the sentence never said WHAT
# was counted (occurrences or lines, templates only or Python too), so three
# reasonable methods produced three answers and none could be checked against
# the sentence. A number that cannot be reproduced cannot be maintained, and it
# is worse than no number, because it reads as precise.
#
# Five sibling counts in the same file were correct only by luck of nothing
# having changed. One was not: "the three a11y test tiers" had been wrong since
# a fourth tier landed, and the doc that owns the subject said four the whole
# time.
#
# NOTHING ELSE SEES THIS CLASS. prove-no-loss.sh compares claims, not their
# arithmetic — "six audits" surviving a move is a preserved claim whether or not
# six is true. check-seams.sh sweeps cross-references, and a count is not a
# reference. The budget cadence reports the total and cannot say a number inside
# the file is stale. The rule, where it exists at all, is prose, followed by
# whoever remembers it.
#
# A curation run is exactly when it gets WORSE: an agent rewriting a section
# faithfully carries a number forward, and may re-measure it by a different
# method than the original author used, which is how the 189 above appeared.
#
# REPORTED, never auto-fixed — dropping a number changes prose, which is the
# author's call. The count goes onto the ledger row (--counts on
# record-telemetry.sh) so a skill change claiming to reduce this class is
# visible to the validation gate that judges it.
set -euo pipefail

usage() {
  cat <<'USAGE'
check-counts.sh — Phase 6.5: find counts and index lines that rot silently

Usage:
  check-counts.sh [options]

A count earns its place in an agent-context file in exactly one of three forms.
The report is written against them, and so is the acknowledgement vocabulary:

  1. ATTACH THE COMMAND. ``the `hx-get` reveals (`grep -ro 'hx-get' src/ | wc -l`)``
     A stale number becomes a falsifiable claim. Detected automatically — a
     clause carrying a counting command in backticks is not reported at all.
  2. DROP THE PRECISION. "the admin's `hx-get` reveals mean the forms don't
     exist without JS anyway" is the same argument and cannot rot. THE RIGHT
     DEFAULT for a policy file: it is loaded on every invocation and
     budget-constrained, so a number that costs tokens AND rots pays rent twice.
     In all six sites that produced this check, the number was rhetorical and
     never load-bearing.
  3. MAKE IT A GATE. Where a count really is load-bearing, a test asserting it
     is the only form that stays true. If it is not worth a test, it is not
     worth stating precisely.

Options:
  --file PATH      File to read. Default: AGENTS.md, else CLAUDE.md.

                   Not only the policy file — point it at a reference doc to
                   sweep that instead, exactly as on check-seams.sh. The policy
                   file is the DEFAULT because it is the one loaded
                   unconditionally, where form 2 is nearly always right.
  --index-section TITLE
                   The `##` section holding the reference-doc index. Default:
                   "Detail Docs". Its lines are held to --index-max; the rest of
                   the file is not.
  --index-max N    Maximum characters in an index line. Default: 200. Pass 0 to
                   skip the class.

                   The stated rule for an index — "it cannot grow" — is
                   unenforceable, since adding a doc must be allowed. The
                   enforceable version is a PROPERTY: an index line is a
                   pointer, bounded in length; a new doc may add a line, an
                   existing line may not accrete clauses. One cohort policy file
                   went over budget because two commits widened EXISTING index
                   blurbs — each edit small, each locally reasonable, none of
                   them new policy. Rejected alternative: a delta-vs-HEAD check,
                   which goes quiet the moment the growth is committed and so
                   guards a diff rather than a property.
  --ack-file PATH  Acknowledgement file. Default: .skills/context-counts-ok.
                   One entry per judged line, two forms:
                     WARRANT :: CONTENT
                     PATH :: WARRANT :: CONTENT   (pins the entry to one file)
                   CONTENT is matched as a substring of the reported clause or
                   line, so an entry expires the moment the text it acknowledged
                   changes — which is exactly when it should be re-judged.
                   Lines STARTING with # are comments; a # anywhere else is part
                   of the pattern.

                   WARRANT is from a closed set, and an unrecognised one is
                   REFUSED rather than ignored — a warrant that merely failed to
                   match would report as an ordinary hit and send the reader to
                   re-judge a line they already judged:

                     gated       a test asserts this figure (form 3). Name it in
                                 a comment above the entry.
                     enumerated  the counted things are listed right there, so
                                 the number is checkable by reading the section.
                     stable      the count is structural and cannot change
                                 without the sentence being rewritten ("the two
                                 halves of the contract"). The one to be
                                 suspicious of: "nothing has changed yet" is not
                                 this warrant, it is the defect.
                     pointer     INDEX LINES ONLY. Long, but still a pointer
                                 rather than accreted clauses.

                   `pointer` on a count, or any other warrant on an index line,
                   is refused: the two classes have disjoint remedies and
                   crossing them silences the wrong thing.
  -h, --help       Show this help and exit 0.

What it reports, in two classes:

  rot-prone count  A CLAUSE — not a line — carrying a cardinal word (two …
                   twenty, dozen) or a digit qualifying a backticked term, with
                   no counting command beside it.

                   PER CLAUSE, not per line, because policy-file lines run long
                   and a per-line check let one properly re-derived count
                   shelter every bare one beside it. Clauses split on sentence
                   and clause punctuation and on an em dash, and are found in
                   the JOINED paragraph so a hard wrap between a number and its
                   command does not break the exemption that earns it. A list
                   item, a TABLE ROW and a BLOCKQUOTE line each start their
                   own unit: a row rarely ends in punctuation, so joining rows
                   put a whole table in one clause and let one cell's command
                   exempt all the others.

                   `one` is excluded: it reads as "a single", not a tally.

                   BARE DIGITS ARE DELIBERATELY LEFT ALONE. Only the shape
                   `<digits> \`term\`` is scanned. In a policy file a bare digit
                   is overwhelmingly a status code, a port, a standard or a
                   version, and a gate that cries wolf on `403` and `ISO 8601`
                   is a gate someone deletes. The gap is real: "182 hx-get
                   reveals" unbackticked passes. Naming it is the price of the
                   class being usable at all.

                   Fenced code blocks are skipped. A number inside one is
                   executable text that either works or does not; this class is
                   about prose claims.

  index line       A line inside --index-section longer than --index-max
                   characters.

The report goes to stdout in full. The last two lines are machine-readable,
and are emitted on exit 0 and exit 3 only — an exit 1 refuses the ack file
before anything is counted, so a caller reading the trailer gets nothing rather
than a zero it would mistake for a clean run:

  counts_acked: <M>
  counts: <N>

They are what `record-telemetry.sh --counts N --counts-acked M` records after
the hits have been resolved or judged (re-run to confirm them). Matched by
anchored PREFIX, like check-seams.sh's pair — adding a line above them is safe.

The number to watch across runs is the DELTA. A stable acknowledged set with 0
new hits is the healthy steady state; an acknowledged set that grows every run
is the file learning to state numbers it cannot keep.

Exit codes:
  0  no unacknowledged hits
  1  usage error, no file found, or an unrecognised warrant in the ack file
  2  infrastructure failure (python3 missing)
  3  one or more hits to judge — fix what rots, acknowledge what is warranted,
     re-run
USAGE
}

POLICY=""
INDEX_SECTION="Detail Docs"
INDEX_MAX="200"
ACK_FILE=".skills/context-counts-ok"

while [ $# -gt 0 ]; do
  case "$1" in
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --index-section) INDEX_SECTION="${2:?--index-section needs a title}"; shift 2 ;;
    --index-max) INDEX_MAX="${2:?--index-max needs a number}"; shift 2 ;;
    --ack-file) ACK_FILE="${2:?--ack-file needs a path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$INDEX_MAX" in
  "" | *[!0-9]* )
    echo "ERROR --index-max must be a whole number of characters: $INDEX_MAX" >&2
    exit 1 ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "ERROR python3 is required" >&2; exit 2; }

# --- shared library -------------------------------------------------------
# Before the cd, deliberately: a relative invocation from a subdirectory leaves
# ${BASH_SOURCE[0]} relative to the ORIGINAL cwd, and resolving it after the cd
# looks for the library in the wrong tree and blames the library for it.
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

if [ -z "$POLICY" ]; then
  for f in AGENTS.md CLAUDE.md; do
    [ -f "$f" ] && { POLICY="$f"; break; }
  done
  [ -n "$POLICY" ] || {
    echo "ERROR no policy file found (looked for AGENTS.md, CLAUDE.md)" >&2; exit 1; }
fi
[ -f "$POLICY" ] || { echo "ERROR no such file: $POLICY" >&2; exit 1; }

# The tracked path, so a symlinked policy file (the cohort norm is
# `CLAUDE.md -> ./AGENTS.md`) is reported and acknowledged under one name
# whichever of the two the caller happened to open.
REL="$(ctx_resolve_rel "$ROOT" "$POLICY")"
[ -n "$REL" ] || REL="$POLICY"

RC=0
python3 - "$REL" "$ACK_FILE" "$INDEX_SECTION" "$INDEX_MAX" <<'PY' || RC=$?
import re
import sys

policy_rel, ack_file, index_section, index_max = sys.argv[1:5]
index_max = int(index_max)

with open(policy_rel, encoding="utf-8", errors="replace") as fh:
    lines = fh.read().splitlines()

# Cardinal words that read as a TALLY. `one` is excluded on purpose: in prose it
# almost always means "a single" rather than a count, and including it made the
# class unreadable without catching anything that could rot.
CARDINALS = (
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "dozen",
)
CARDINAL_RE = re.compile(r"\b(" + "|".join(CARDINALS) + r")\b", re.IGNORECASE)

# A digit QUALIFYING a backticked term — the "180 `hx-get`" shape. Bold markers
# are stepped over on both sides, because the number that produced this check
# was written `**180** \`hx-get\``.
#
# Bare digits are not scanned. See --help: in a policy file they are
# overwhelmingly status codes, ports, standards and versions.
DIGIT_RE = re.compile(r"\b\d{1,5}\*{0,2}\s+\*{0,2}`")

# Form 1, detected rather than declared. A clause carrying a counting command in
# backticks re-derives its own number, which is the whole remedy — so it is not
# reported and needs no acknowledgement.
COMMAND_RE = re.compile(r"`[^`]*(?:wc\s+-[lcwm]|grep\s+-c)[^`]*`")

# Clause, not line. Policy-file lines run long, and a per-line check let one
# properly re-derived count shelter every bare one beside it.
CLAUSE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|\s+[—–]\s+")

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def norm(title):
    return re.sub(r"[`*_]", "", title).strip().rstrip(".:").lower()


# The index section's line range, so the two classes never overlap: an index
# line is judged as a pointer, not as prose that happens to carry a number.
index_start = index_end = None
if index_max > 0:
    want = norm(index_section)
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        if index_start is None and norm(m.group(2)) == want:
            index_start, index_level = i + 1, len(m.group(1))
        elif index_start is not None and len(m.group(1)) <= index_level:
            index_end = i
            break
    if index_start is not None and index_end is None:
        index_end = len(lines)

ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
# A table ROW too, and for the same reason a list item is one. A row rarely ends
# in clause punctuation, so consecutive rows joined into one block collapsed into
# a single clause — and a `wc -l` in one cell then exempted every bare count in
# the rows below it. That is the defect per-clause scanning exists to prevent,
# reappearing at table scope, and tables are where a policy file puts exactly
# this kind of claim: this repo's own "Rationalization prevention" is one.
ROW = re.compile(r"^\s*\|")
# And a blockquote line, the same shape one construct over: a `wc -l` inside a
# quotation would otherwise exempt a bare count in the paragraph beneath it.
QUOTE = re.compile(r"^\s*>")


def joined(block):
    """A hard-wrapped block as one string, plus where each line starts in it.

    Clauses are found in the JOINED text, not per line. A policy file is
    hard-wrapped at some column nobody chose for semantic reasons, so a
    per-line scan cuts clauses at that column: the count and the command that
    re-derives it land in different "clauses" whenever the wrap falls between
    them, and the form-1 exemption then fails on exactly the sentences that
    earned it. The offsets exist so a hit still reports the line it is on
    rather than the top of its paragraph.
    """
    parts, starts, off = [], [], 0
    for lineno, line in block:
        text = line.strip()
        if parts:
            off += 1
        starts.append((off, lineno))
        parts.append(text)
        off += len(text)
    return " ".join(parts), starts


def clauses(text):
    """(offset, clause) pairs — split with positions kept, unlike re.split."""
    pos = 0
    for m in CLAUSE_SPLIT.finditer(text):
        yield pos, text[pos:m.start()]
        pos = m.end()
    yield pos, text[pos:]


def line_at(starts, offset):
    lineno = starts[0][1]
    for off, n in starts:
        if off > offset:
            break
        lineno = n
    return lineno


hits = []
blocks = []
block = []
in_fence = False
for i, line in enumerate(lines):
    if FENCE.match(line):
        in_fence = not in_fence
        if block:
            blocks.append(block)
            block = []
        continue
    if in_fence:
        continue
    if index_start is not None and index_start <= i < index_end:
        # Held to the length bound instead. A blurb that states a count AND runs
        # long is one finding about one line, and reporting it twice would make
        # the acknowledgement grammar ambiguous about which class it silenced.
        stripped = line.strip()
        if stripped and len(stripped) > index_max:
            hits.append((
                "index-line", f"{policy_rel}:{i + 1}",
                f"{len(stripped)} chars (max {index_max}) — "
                f"{stripped[:90]}", stripped,
            ))
        continue
    # A block break, not merely a skip: a heading, a blank line and the start of
    # a new list item each end the prose unit. Joining consecutive bullets would
    # run one item's clause into the next and report a count against a sentence
    # that never contained it.
    if (not line.strip() or HEADING.match(line) or ITEM.match(line)
            or ROW.match(line) or QUOTE.match(line)):
        if block:
            blocks.append(block)
            block = []
        if not line.strip() or HEADING.match(line):
            continue
    block.append((i + 1, line))
if block:
    blocks.append(block)

for block in blocks:
    text, starts = joined(block)
    for offset, clause in clauses(text):
        clause = clause.strip()
        if not clause or COMMAND_RE.search(clause):
            continue
        found = CARDINAL_RE.search(clause) or DIGIT_RE.search(clause)
        if found:
            hits.append((
                "rot-prone-count",
                f"{policy_rel}:{line_at(starts, offset + found.start())}",
                f"'{found.group(0).strip()}' — {clause[:100]}", clause,
            ))

# Reported in file order. The two classes are collected in separate passes, so
# without this an index-line hit at the bottom of the file lands above a count
# from line 12 and the report reads as unordered.
hits.sort(key=lambda h: (int(h[1].rsplit(":", 1)[1]), h[0]))

# Acknowledgements. WARRANT :: CONTENT, or PATH :: WARRANT :: CONTENT, told
# apart by whether the FIRST field names a warrant — so CONTENT may itself
# contain " :: " without the entry being misread. Same grammar as
# .skills/context-loss-ok, and the vocabulary is closed for the same reason: no
# warrant means "this line is fine", because that is what a bare substring
# already meant and it taught the next reader nothing.
COUNT_WARRANTS = ("gated", "enumerated", "stable")
INDEX_WARRANTS = ("pointer",)
WARRANTS = COUNT_WARRANTS + INDEX_WARRANTS
CLASS_WARRANTS = {"rot-prone-count": COUNT_WARRANTS, "index-line": INDEX_WARRANTS}

entries, refused = [], []
try:
    with open(ack_file, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            fields = raw.split(" :: ")
            path = ""
            if fields and fields[0] in WARRANTS:
                warrant, content = fields[0], " :: ".join(fields[1:])
            elif len(fields) >= 3 and fields[1] in WARRANTS:
                path, warrant, content = fields[0], fields[1], " :: ".join(fields[2:])
            else:
                refused.append((lineno, raw))
                continue
            if not content.strip():
                refused.append((lineno, raw))
                continue
            entries.append((raw, path, warrant, content))
except OSError:
    pass

if refused:
    # stderr, not stdout: AGENTS.md's script rules put structured output on
    # stdout and diagnostics on stderr, and prove-no-loss.sh — the sibling with
    # this same warrant grammar — already does. On stdout a caller grepping
    # stderr for ERROR saw nothing at all.
    print(f"ERROR {len(refused)} entry(ies) in {ack_file} name no recognised "
          f"warrant. The vocabulary is closed — {', '.join(WARRANTS)} — because "
          "an entry that merely failed to match would report as an ordinary hit "
          "and send you to re-judge a line you already judged:", file=sys.stderr)
    for lineno, raw in refused:
        print(f"  {ack_file}:{lineno}  {raw[:80]}", file=sys.stderr)
    sys.exit(1)

new, acked = [], []
matched_by = {raw: [] for raw, _, _, _ in entries}
for cls, loc, detail, full in hits:
    path = loc.rsplit(":", 1)[0]
    hit = None
    for raw, p_path, warrant, content in entries:
        if p_path and p_path not in path:
            continue
        # A warrant belongs to one class. `pointer` on a count would silence the
        # wrong remedy: "still a pointer" says nothing about whether a number is
        # reproducible.
        if warrant not in CLASS_WARRANTS[cls]:
            continue
        if content in full:
            hit = raw
            break
    if hit is None:
        new.append((cls, loc, detail))
    else:
        acked.append((cls, loc))
        matched_by[hit].append(loc)

if index_max <= 0:
    print("note: index lines not checked (--index-max 0).")
elif index_start is None:
    # Said out loud. A heuristic that finds no section to check is
    # indistinguishable, from the report, from one that checked and found
    # nothing — and the index is the class that grows without anyone deciding to.
    print(f"note: no '{index_section}' section in {policy_rel}, so no index "
          "line was checked. Name the right one with --index-section.")
else:
    print(f"note: checked {index_end - index_start} line(s) under "
          f"'{index_section}' against a {index_max}-character bound.")

if new:
    print(f"\n{len(new)} count(s) to judge — each needs a decision, not "
          "necessarily a fix:\n")
    width = max(len(c) for c, _, _ in new)
    for cls, loc, detail in new:
        print(f"  {cls:<{width}}  {loc}")
        print(f"  {'':<{width}}  {detail}")
    print("\nFor each: attach the command that re-derives it, drop the "
          "precision (the right")
    print("default in a policy file), or make it a gate and record `gated` in "
          f"{ack_file}.")
    print("An index line over the bound has accreted clauses — tighten it back "
          "to a pointer.")
else:
    print("\nOK — no unacknowledged rot-prone counts.")

if acked:
    print(f"\n{len(acked)} acknowledged hit(s) skipped (judged in {ack_file}):")
    for cls, loc in acked:
        print(f"  {cls}  {loc}")
    # Per-pattern accountability, as on check-seams.sh. An acknowledgement is
    # ONE judged line, so a pattern matching many is doing the job of judgement
    # without the judging — the one way to zero this metric with no edit to the
    # file it measures.
    print("\n  by entry:")
    for raw, locs in matched_by.items():
        if not locs:
            continue
        print(f"    {len(locs)} hit(s): {raw[:70]}")
        if len(locs) > 1:
            print(f"    WARN this entry covers {len(locs)} hits — an "
                  "acknowledgement should warrant ONE judged line; split it")
unused = [raw for raw, _, _, _ in entries if not matched_by[raw]]
if unused:
    print(f"\n{len(unused)} entry(ies) in {ack_file} matched nothing — the text "
          "each warranted has changed or gone; re-judge and prune:")
    for raw in unused:
        print(f"  {raw[:70]}")

# ABOVE the two counts, which stay the last two lines and are matched by
# anchored prefix rather than by offset from the end.
print(f"\ncounts_acked: {len(acked)}")
print(f"counts: {len(new)}")
sys.exit(3 if new else 0)
PY

exit "$RC"
