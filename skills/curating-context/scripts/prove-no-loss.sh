#!/usr/bin/env bash
# prove-no-loss.sh — assert that nothing was silently dropped by a curation run.
#
# Every non-blank line of the file under --file as it was at <base> — the policy
# file by default, a reference doc when proving a split — must still be present
# verbatim, either inline or in a destination file. Lines that are not are
# reported, and each needs a named warrant in .skills/context-loss-ok before the
# run ships. Some of those warrants are for edits this skill MANDATES, which is
# why the file exists at all: see "Warranted losses" in --help.
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
  --file PATH      The file whose base-revision lines must still exist.
                   Default: AGENTS.md, else CLAUDE.md.

                   Not only the policy file. Point it at a REFERENCE DOC and it
                   is the right tool for a doc split: `--file docs/API.md`
                   proves every line of the doc as it was at --base still exists
                   somewhere under --docs-dir, which is the check a split needs
                   and the policy file cannot give (the split moves nothing out
                   of AGENTS.md, so a policy-file run passes while saying
                   nothing about the split). It must exist at --base as a
                   regular file, and need NOT still exist now: a split deletes
                   its source by construction, and with no file to read the
                   inline set is simply empty, so every line has to turn up in a
                   destination. Autodetection still requires a real file — a
                   repo with no policy file is a usage error.
  --docs-dir DIR   Reference-doc root searched for relocated content. Default:
                   CONTEXT_DOCS_DIR, then .skills/context-docs-dir, then docs.

                   Searched RECURSIVELY, so a destination nested below the root
                   counts: with the default root, `docs/api/conventions.md` is
                   found for content out of `docs/API.md`. That depth is also
                   normalised away on the link side — a split moves content one
                   level deeper than a demotion does, and before #119 every
                   link-carrying line in such a split reported LOST. --file and
                   --docs-dir are independent: --file names what must survive,
                   --docs-dir where it is allowed to have gone, and pointing
                   --file at a doc INSIDE --docs-dir is the normal case for a
                   split, not a conflict. Archival subtrees are never valid
                   destinations, whatever the root.
  --also PATH      Additional destination to search (repeatable) — use when a
                   block was demoted somewhere other than the docs tree, e.g.
                   a skill's references/ directory.
  --ack-file PATH  Warrant file for lines this run had to rewrite rather than
                   move. Default: .skills/context-loss-ok.
  --show-relocated Also list which destination each moved line landed in.
  -h, --help       Show this help and exit 0.

Warranted losses (.skills/context-loss-ok):
  Some edits legitimately leave a base line present nowhere, and whole-line
  matching — the thing that makes this check strong — cannot tell them from a
  drop. Two shapes came out of the cohort and both are compulsory rather than
  chosen:

    a pointer retargeted because THIS change moved what it points at. The split
    that invalidates it is the same run that fixes it, so the corrected line is
    a different line.
    a heading Phase 6.5 forces you to rename — `#\d{2,}` in a permanent anchor
    slug is a class 3b seam, and heading TEXT is not normalised here.

  Neither has an honest verdict without this file: `ok` contradicts exit 3,
  `failed` tells score-cohort.sh content was dropped when none was, and
  `skipped` is false. So each such line gets a judged entry:

    WARRANT :: CONTENT        e.g.  retarget :: Full rules live in docs/STYLE.md §32

  WARRANT names WHY, from a closed set — an unrecognised one is refused rather
  than ignored, because a mute allowlist is not a judgement:

    retarget   the pointer's target moved in this same change
    rename     Phase 6.5 or check-seams required the new heading text
    duplicate  the content is verbatim elsewhere in the surface already
    disproven  a command refuted the claim (see verify-facts.sh)
    default    the tool now does this by default, so the instruction is noise

  CONTENT is a substring of the reported line. Matched on content, never on
  line number, so an entry expires the moment its line changes — which is
  exactly when it needs re-judging. An entry can only ever reach a line that is
  ALREADY unaccounted for, so it can neither hide a relocation nor invent one,
  and every entry is charged with its hits in a per-entry report: one broad
  line that zeroes the count is the gaming vector this file introduces, and the
  report is what makes it visible.

  Comments are `#` at LINE START only. Stripping an inline one would silently
  broaden the entry — `Fixed in #412` becomes `Fixed in`.

What counts as "present":
  A line matches an entire line of the current policy file or of a destination —
  not a fragment of one — after normalising the two differences a move
  legitimately forces:

    heading level   `### Foo` in a policy file becomes `## Foo` at the top of its
                    own document.
    link depth      a block that changes directory re-aims its relative links,
                    so `](tests/x.py)`, `](../tests/x.py)` and
                    `](../../tests/x.py)` are one line at three depths. Erased
                    in BOTH directions and at ANY depth — a demotion into docs/
                    gains a level, a split into docs/api/ gains two, and a
                    promotion back to the root loses them. The target after the
                    `../` is not touched, so a REPOINTED link is still a
                    difference and still reports (#119).

  Nothing else is normalised. Reflowed prose, changed wording, appended clauses,
  and dropped lines all fail, which is the point. Whole-line matching is what
  makes that true: substring matching passed a dropped `1. Commit and push`
  because it appeared inside "Step 9: 1. Commit and push when ready." elsewhere.

  The report goes to stdout in full, including the LOST list, so it stays in
  order through a pipe. Its last three lines are machine-readable:

    duplicated: <D>       lines left in BOTH the policy file and a destination
    loss_warranted: <M>   unaccounted lines with a judged entry
    lost: <N>             unaccounted lines with none

  <M> goes on the ledger row via `record-telemetry.sh --no-loss-warrants M`,
  which is what keeps "nothing was unaccounted for" and "eight lines were
  judged and waved through" distinguishable in the cohort's data.

  <D> is a NOTE, not a failure, and never changes the exit code. Presence
  anywhere satisfies this check, so a block COPIED rather than moved is
  invisible to it — six shipped that way on one cohort run, one line reaching
  three occurrences. Judge each: a lead-in that is load-bearing in both places
  is a real state, distinct from forgetting to delete the original. Only lines
  of 40+ characters are compared, or fences, rules and shared headings would
  bury the real hits.

Exit codes:
  0  every line accounted for, or warranted
  1  usage error, no policy file found, or a malformed acknowledgement entry
  2  infrastructure failure (base revision unreadable, python3 missing)
  3  one or more lines unaccounted for and unwarranted — the run must justify
     or restore them
USAGE
}

BASE="HEAD"
POLICY=""
DOCS_DIR=""
ACK_FILE=".skills/context-loss-ok"
SHOW_RELOCATED=0
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a revision}"; shift 2 ;;
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --also) EXTRA+=("${2:?--also needs a path}"); shift 2 ;;
    --ack-file) ACK_FILE="${2:?--ack-file needs a path}"; shift 2 ;;
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

DOCS_DIR="$(ctx_docs_dir "$ROOT" "$DOCS_DIR")"

# A file named with --file need not still EXIST. Autodetection does — a repo
# with no policy file is a usage error — but a doc split deletes its source by
# construction (`docs/API.md` -> `docs/api/*.md`), and requiring the working-tree
# file made --file unusable for exactly the case it is the right tool for: the
# explicit argument fell through to the message below and reported "no policy
# file found (looked for AGENTS.md, CLAUDE.md)" for a path the caller had named.
# Nothing is weakened by allowing it: existence AT --base is still required, two
# checks down, and with no file now the inline set is empty, so every line has to
# turn up in a destination.
if [ -z "$POLICY" ]; then
  for cand in AGENTS.md CLAUDE.md; do
    [ -f "$cand" ] && { POLICY="$cand"; break; }
  done
  if [ -z "$POLICY" ]; then
    echo "ERROR no policy file found (looked for AGENTS.md, CLAUDE.md under $ROOT)" >&2
    exit 1
  fi
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
if [ -f "$POLICY" ]; then
  printf '%s\n' "$POLICY" >>"$TMP/dests"
else
  # Said out loud, because "0 still inline" out of 40 is indistinguishable in
  # the report from a file that was emptied in place, and the two want
  # different review.
  echo "note: $POLICY no longer exists — every line must be in a destination."
fi
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
python3 - "$TMP/before" "$POLICY" "$TMP/dests.u" "$SHOW_RELOCATED" "$ACK_FILE" <<'PY' || RC=$?
import re
import sys

before_path, policy, dests_path, show, ack_path = sys.argv[1:6]

# Why an unaccounted line was legitimate. A CLOSED set on purpose: the point of
# this file is to record a judgement, and free text would make it a mute
# allowlist — the same file minus the only part a reviewer can check. The first
# two are compulsory edits the skill itself forces (#111); the last three were
# already the warrants the LOST message names in prose, and had nowhere to live.
WARRANTS = ("retarget", "rename", "duplicate", "disproven", "default")

# Below this, a line shared by the policy file and a destination is structure,
# not duplicated content: fences, `---`, `## Detail Docs`, one-word bullets.
# Without a floor the copied-not-moved note is hundreds of lines of noise, and a
# note nobody reads finds nothing — which is how six real copies shipped.
DUP_MIN_CHARS = 40

HEADING = re.compile(r"^#{1,6}\s+(.*)$")
# Every leading `../` on a link target, not just the first. `.replace("](../",
# "](")` erased exactly one level: str.replace scans the ORIGINAL string and
# resumes past each replacement, so `](../../plugins/x)` matched at index 0 and
# kept its second level. A doc split (`docs/API.md` -> `docs/api/part.md`) moves
# content one level deeper than a demotion does, and every link-carrying line
# then reported LOST — 172 of them on the run that found this, all false. A
# report that wrong is worse than no check, because a reader who learns to
# ignore it will ignore a real loss in it.
LINK_DEPTH = re.compile(r"\]\((?:\.\./)+")

def normalise(raw):
    """One line -> its comparable form, or "" when it carries no content.

    Exactly two differences a move legitimately forces are erased:

      link depth    a block moving between directories re-aims its relative
                    links, so `](tests/x.py)`, `](../tests/x.py)` and
                    `](../../tests/x.py)` are the same line at three depths.
                    Depth is erased in both directions and at any amount; the
                    target after it is not, so a repointed link is still a
                    difference.
      heading level a `###` subsection promoted to its own document's `##`.

    Heading text is tagged rather than merely stripped of its hashes. Stripping
    alone would let a `# comment` inside a fenced block collide with the prose
    line `comment`, which is a false match in the direction that hides loss.
    """
    line = raw.strip()
    if not line:
        return ""
    line = LINK_DEPTH.sub("](", line)
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

# Acknowledgement entries, refused rather than ignored when malformed. A typo'd
# warrant that merely failed to match would report as an ordinary loss and send
# the run hunting for content that is fine; refusing also errs toward NOT
# passing, which is the only safe direction for a file that can turn exit 3
# into exit 0.
entries, malformed = [], []
try:
    with open(ack_path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.rstrip("\n")
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            head, sep, tail = raw.partition("::")
            warrant, content = head.strip(), tail.strip()
            if not sep:
                why = "no `::` — an entry is `WARRANT :: CONTENT`"
            elif warrant not in WARRANTS:
                why = (f"unknown warrant '{warrant}' — one of: "
                       + ", ".join(WARRANTS))
            elif not content:
                why = "empty CONTENT — an entry with no content matches every line"
            else:
                entries.append((warrant, content))
                continue
            malformed.append((lineno, raw.strip()[:100], why))
except OSError:
    pass

if malformed:
    print(f"ERROR {ack_path} has {len(malformed)} malformed entry(ies):",
          file=sys.stderr)
    for lineno, text, why in malformed:
        print(f"  line {lineno}: {why}", file=sys.stderr)
        print(f"    {text}", file=sys.stderr)
    sys.exit(1)

inline = dests.get(policy, set())
others = [p for p in dest_paths if p != policy]
kept, relocated, lost, duplicated = 0, {}, [], []

for raw in before:
    line = normalise(raw)
    if not line:
        continue
    if line in inline:
        kept += 1
        # Still inline AND in a destination: copied rather than moved. This
        # check is satisfied by presence ANYWHERE, so without this it sees
        # nothing — and check-seams and links.dead do not look at all.
        if len(line) >= DUP_MIN_CHARS:
            also = [p for p in others if line in dests[p]]
            if also:
                duplicated.append((raw.strip(), also))
        continue
    where = next((p for p in others if line in dests[p]), None)
    if where:
        relocated.setdefault(where, []).append(raw.strip())
    else:
        lost.append(raw.strip())

# A warrant only ever reaches a line that is ALREADY unaccounted for, so it can
# neither mask a relocation nor manufacture one. First matching entry is charged
# with the hit, which is what makes an entry's blast radius visible below.
warranted, unwarranted = [], []
charged = [[] for _ in entries]
for line in lost:
    idx = next((i for i, (_, c) in enumerate(entries) if c in line), None)
    if idx is None:
        unwarranted.append(line)
    else:
        warranted.append((entries[idx][0], line))
        charged[idx].append(line)

# One stream for the whole report. Split across stdout and stderr it interleaved
# through a pipe, and the failure list printed above the counts explaining it.
out = sys.stdout
total = kept + sum(len(v) for v in relocated.values()) + len(lost)
# Named, not "policy file": --file takes a reference doc when proving a split,
# and a report headed "policy file" for docs/API.md reads as the wrong run.
print(f"{policy} at base: {total} non-blank lines", file=out)
print(f"  still inline:               {kept}", file=out)
for path in sorted(relocated):
    print(f"  relocated verbatim -> {path}: {len(relocated[path])}", file=out)
    if show == "1":
        for line in relocated[path]:
            print(f"      {line[:120]}", file=out)
print(f"  UNACCOUNTED FOR:            {len(lost)}", file=out)
if entries or warranted:
    print(f"    warranted:                {len(warranted)}", file=out)
    print(f"    unwarranted:              {len(unwarranted)}", file=out)

if duplicated:
    print(f"\n{len(duplicated)} line(s) left in BOTH the policy file and a "
          "destination — copied, not moved.\nJudge each: a lead-in that is "
          "load-bearing in both places is a real state, but\nnothing else "
          "requires the second copy. Not a failure, and not checked by any "
          "gate.", file=out)
    for line, where in duplicated:
        print(f"  ALSO IN {', '.join(where)}", file=out)
        print(f"          {line[:120]}", file=out)

if warranted:
    print(f"\n{len(warranted)} warranted loss(es) (judged in {ack_path}):",
          file=out)
    width = max(len(w) for w, _ in warranted)
    for warrant, line in warranted:
        print(f"  WARRANTED {warrant:<{width}}  {line[:120]}", file=out)
    # Per-entry accountability, the part of check-seams.sh's ack report the
    # cohort named as what proved no entry had quietly become a blanket. An
    # acknowledgement is ONE judged line, so anything above one hit is an
    # entry doing the job of judgement without the judging.
    print("\n  by entry:", file=out)
    for (warrant, content), hits in zip(entries, charged):
        if not hits:
            continue
        print(f"    {len(hits)} hit(s): {warrant} :: {content[:70]}", file=out)
        if len(hits) > 1:
            print(f"    WARN this entry is broad ({len(hits)} hits) — an "
                  "acknowledgement should cover ONE judged line; split it or "
                  "re-judge", file=out)

unused = [e for e, hits in zip(entries, charged) if not hits]
if unused:
    print(f"\n  {len(unused)} entry(ies) matched nothing — the line each "
          "acknowledged has changed\n  or gone, which is when it needs "
          "re-judging; re-judge and prune:", file=out)
    for warrant, content in unused:
        print(f"    {warrant} :: {content[:70]}", file=out)

if unwarranted:
    print(
        f"\nEach line below is missing from {policy} AND from every "
        "destination.\nA curation may only drop a line with a named warrant — "
        f"add a judged entry to\n{ack_path} (see --help) or restore the line "
        "verbatim.\n",
        file=out,
    )
    for line in unwarranted:
        print(f"  LOST  {line[:160]}", file=out)
elif warranted:
    print(f"\nOK — {len(warranted)} line(s) warranted, none unexplained.",
          file=out)
else:
    print("\nOK — every line is either still inline or relocated verbatim.",
          file=out)

print(f"\nduplicated: {len(duplicated)}", file=out)
print(f"loss_warranted: {len(warranted)}", file=out)
print(f"lost: {len(unwarranted)}", file=out)
out.flush()
if unwarranted:
    sys.exit(3)

PY

exit "$RC"
