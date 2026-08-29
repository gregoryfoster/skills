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
  --claims         Also check the file's ATOMS — backticked spans, `#NNN` issue
                   references, link targets, bare URLs — base against now. Line
                   matching cannot see a class-C tightening (Phase 3 rewrites a
                   section in place, and a paragraph is one line, so a faithful
                   rewrite is 100% "lost"); atom matching can, because the atoms
                   are what a rewrite must carry across. REQUIRED by the
                   `tighten` warrant: see "Warranted losses".
  --claims-ack-file PATH
                   Warrant file for atoms a tightening legitimately dropped.
                   Default: .skills/context-claims-ok. Same grammar and warrants
                   as --ack-file minus `tighten`, and ATOM is matched WHOLE, not
                   as a substring.
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

  Optionally scoped to one target, since this file is per-repo while --file is
  per-target and an entry judged for one target otherwise reports "matched
  nothing" on a run against another:

    PATH :: WARRANT :: CONTENT
                              e.g.  docs/API.md :: retarget :: the shape lives in

  PATH is a substring of the run's --file, the way .skills/context-seams-ok
  pins an entry to one file. An entry scoped elsewhere is neither consulted nor
  called stale here — the report says how many sat this run out. The form is
  told apart by whether the first field names a warrant, so CONTENT may itself
  contain a `::`.

  WARRANT names WHY, from a closed set — an unrecognised one is refused rather
  than ignored, because a mute allowlist is not a judgement:

    retarget   the pointer's target moved in this same change
    rename     Phase 6.5 or check-seams required the new heading text
    duplicate  the content is verbatim elsewhere in the surface already
    disproven  a command refuted the claim (see verify-facts.sh)
    default    the tool now does this by default, so the instruction is noise
    tighten    Phase 3 class C rewrote the line in place — same claims, fewer
               words. REQUIRES --claims, and is refused without it (#250).

  `tighten` is the one warrant a run can always claim about its own edit, so
  alone it would be self-certifying — and the breadth guard below cannot
  restrain it, because class C's defining defect is a section written as ONE
  paragraph. One entry, one line, a whole section waved through: on the run that
  found this, five entries would have covered the entire body of a 9,826-token
  document. The other five warrants do not have this problem. Two are
  COMPULSORY, forced by the skill itself; three point at evidence outside the
  entry (a duplicate elsewhere, a command's verdict, a tool's default). So
  `tighten` is gated on a check the rewrite cannot perform on itself: --claims
  must pass, meaning every atom of the base line turns up somewhere or carries
  its own judged entry. Line matching proves the MOVES; atom matching proves
  the REWRITES.

  An entry that matched nothing is reported, and "re-judge and prune" is sound
  advice for only some of them (#251). Two facts settle whether this run is
  entitled to judge it, and either alone is enough: a PATH that matched says the
  entry IS about this target, and so does CONTENT appearing in this target at
  --base. With neither, the run cannot tell a re-worded line from an entry
  judged against another surface, and says so instead of guessing — an unscoped
  entry pinning an AGENTS.md line reported stale on every reference-doc run in
  one repo, and pruning on that advice would have discarded a live warrant.

  CONTENT is a substring of the reported line. Matched on content, never on
  line number, so an entry expires the moment its line changes — which is
  exactly when it needs re-judging. An entry can only ever reach a line that is
  ALREADY unaccounted for, so it can neither hide a relocation nor invent one.

  An acknowledgement covers ONE judged line. An entry matching more than one is
  REFUSED, as is CONTENT under 8 characters — one broad line that zeroes the
  count is the gaming vector this file introduces, and a warning about it is not
  enough: warnings ride in stdout, where the exit code, the ledger row and the
  cohort gate do not read them. Split a broad entry into one per line.

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

                    A demotion also re-aims in the opposite shape, by REMOVING
                    the docs root from a link that already pointed inside it:
                    `](docs/OTHER.md)` in AGENTS.md is `](OTHER.md)` in
                    docs/STYLE.md. That leading prefix — and only that one,
                    only at the start of the target — is erased too (#137).
                    `](lib/x.md)` -> `](x.md)` is a repoint and still reports.

  A leading YAML frontmatter block is not compared at all, on either side. Phase
  7 MANDATES bumping SKILL.md's `version`, so a line-based check reported the
  run that followed the skill's own instructions as losing `version: "1.6"` —
  and the warrant vocabulary is closed, with no warrant meaning "this field is
  required to change" (#136). Frontmatter is metadata, not the prose and
  pointers this check protects. The report says how many lines it skipped. A
  file opening with a `---` thematic rule is not frontmatter: the block counts
  only when it is closed and everything inside it reads as YAML.

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

  With --claims, two more:

    claims_dropped: <N>    atoms present at base and nowhere now, unwarranted
    claims_warranted: <M>  dropped atoms carrying a judged entry

The claim check (--claims):
  Whole-line matching is blind to a rewrite in place, and Phase 3 PRESCRIBES
  one. A `##` section holding a single 4,000-token paragraph is one line, so
  reflowing it into subsections reports 100% lost however faithful the rewrite
  is — the gate's strength is exactly what makes it blind here. `tighten`
  therefore needs a second check that a rewrite CANNOT satisfy by construction,
  and the atoms are it: the tokens a faithful rewrite has to carry across.

    backticked span   `uv sync --frozen`, `docs/API.md`, `POST /v1/ingest`
    issue reference   `#412`, `owner/repo#569`
    link target       the path inside `](...)`, normalised for depth and root
                      exactly as a whole line is
    bare URL          http(s), trailing punctuation trimmed

  Extracted from the base revision and from every destination, compared as
  SETS, and reported when an atom exists at base and nowhere now. Fenced code
  blocks are skipped on both sides: their content is protected line by line
  already, and extracting from them double-reports every deletion.

  This is not a formality. On the run that motivated it, the check surfaced 19
  dropped atoms of which 12 were real over-compression that would otherwise have
  shipped — including a `wp#569` that was the load-bearing justification for an
  entire API being write-only.

  An atom a tightening legitimately drops gets a judged entry in
  .skills/context-claims-ok, same grammar and same warrants MINUS `tighten`
  (warranting an atom with the warrant the atom check exists to gate would be
  circular). The differences from --ack-file follow from atoms being tokens
  rather than prose:

    ATOM is matched WHOLE, against the dropped set — never as a substring. So
    there is no minimum length (`#41` identifies itself exactly) and no
    over-broad refusal (a set element matches at most one thing).

  <D> is a NOTE, not a failure, and never changes the exit code. Presence
  anywhere satisfies this check, so a block COPIED rather than moved is
  invisible to it — six shipped that way on one cohort run, one line reaching
  three occurrences. Judge each: a lead-in that is load-bearing in both places
  is a real state, distinct from forgetting to delete the original. Only lines
  of 40+ characters are compared, or fences, rules and shared headings would
  bury the real hits.

Exit codes:
  0  every line accounted for, or warranted
  1  usage error, no policy file found, a malformed acknowledgement entry, or a
     `tighten` warrant without --claims
  2  infrastructure failure (base revision unreadable, python3 missing)
  3  one or more lines — or, under --claims, atoms — unaccounted for and
     unwarranted; the run must justify or restore them
USAGE
}

BASE="HEAD"
POLICY=""
DOCS_DIR=""
ACK_FILE=".skills/context-loss-ok"
CLAIMS_ACK_FILE=".skills/context-claims-ok"
CLAIMS=0
SHOW_RELOCATED=0
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a revision}"; shift 2 ;;
    --file) POLICY="${2:?--file needs a path}"; shift 2 ;;
    --docs-dir) DOCS_DIR="${2:?--docs-dir needs a path}"; shift 2 ;;
    --also) EXTRA+=("${2:?--also needs a path}"); shift 2 ;;
    --ack-file) ACK_FILE="${2:?--ack-file needs a path}"; shift 2 ;;
    --claims-ack-file)
      CLAIMS_ACK_FILE="${2:?--claims-ack-file needs a path}"; shift 2 ;;
    --claims) CLAIMS=1; shift ;;
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
python3 - "$TMP/before" "$POLICY" "$TMP/dests.u" "$SHOW_RELOCATED" "$ACK_FILE" \
  "$DOCS_DIR" "$CLAIMS" "$CLAIMS_ACK_FILE" <<'PY' || RC=$?
import os
import re
import sys

(before_path, policy, dests_path, show, ack_path, docs_dir, claims_on,
 claims_ack_path) = sys.argv[1:9]
claims_on = claims_on == "1"

# Why an unaccounted line was legitimate. A CLOSED set on purpose: the point of
# this file is to record a judgement, and free text would make it a mute
# allowlist — the same file minus the only part a reviewer can check. The first
# two are compulsory edits the skill itself forces (#111); the next three were
# already the warrants the LOST message names in prose, and had nowhere to live.
# `tighten` is the sixth and the only one that is not self-limiting, which is why
# it is the only one carrying a precondition: see REQUIRES_CLAIMS (#250).
WARRANTS = ("retarget", "rename", "duplicate", "disproven", "default", "tighten")

# Warrants that name an edit the run cannot certify for itself, and what each
# needs before it counts. `tighten` is claimed ABOUT the author's own rewrite —
# unlike `retarget`/`rename`, which the skill compels, and unlike
# `duplicate`/`disproven`/`default`, which point at evidence outside the entry.
# The atom check is that outside evidence, so the warrant is refused without it.
REQUIRES_CLAIMS = ("tighten",)

# The claim file's vocabulary is the loss file's minus `tighten`: warranting a
# dropped atom with the very warrant the atom check exists to gate would close
# the loop the gate is there to open.
CLAIM_WARRANTS = tuple(w for w in WARRANTS if w not in REQUIRES_CLAIMS)

# Below this, a line shared by the policy file and a destination is structure,
# not duplicated content: fences, `---`, `## Detail Docs`, one-word bullets.
# Without a floor the copied-not-moved note is hundreds of lines of noise, and a
# note nobody reads finds nothing — which is how six real copies shipped.
DUP_MIN_CHARS = 40

# The same reasoning applied to an acknowledgement's CONTENT, which is matched as
# a substring. Kept low deliberately: the real breadth guard is the over-broad
# refusal further down, which counts what an entry ACTUALLY matched rather than
# guessing from its length. This floor only rules out the degenerate case a hit
# count cannot catch — an entry so short that matching one line today is luck.
WARRANT_MIN_CHARS = 8

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
# The mirror direction, and the one #119 could not see. A DEMOTION does not add
# `../`; it REMOVES a directory prefix, because the target it points at is
# already inside the directory the content moved into: `](docs/OTHER.md)` in a
# root policy file becomes `](OTHER.md)` once the bullet lives in docs/STYLE.md.
# That is the operation this skill recommends most often, and every link-carrying
# bullet it moved reported LOST — one run needed 12 `retarget` warrants for
# nothing else (#137).
#
# Erased for ONE prefix only: the reference-doc root this run was given. That is
# the directory content is relocated INTO, so it is the only prefix a sanctioned
# move can remove; `](lib/x.md)` -> `](x.md)` is a repoint and still reports. The
# residual cost is named rather than hidden — `](docs/X.md)` and `](X.md)` now
# compare equal, so a link repointed between those two exact paths is invisible
# here, and a demotion into a SUBdirectory of the root still reports, because
# only the root itself is erased. Every relaxation of whole-line matching is paid
# out of the strength of the only gate that can see content loss, and this is the
# smallest coin that buys the demotion case.
#
# The prefix a link actually carries is the docs root seen FROM THE FILE THE LINK
# IS WRITTEN IN, which is not the repo-relative --docs-dir string unless the
# policy file sits at the repo root. Built from the repo-relative string alone,
# this fix could not fire for any skill curating its own surface: the run passes
# `--docs-dir skills/x/references`, SKILL.md writes `](references/X.md)`, the
# pattern was `](skills/x/references/`, and the substitution was a no-op on the
# 21 links that needed it. So two prefixes are erasable, not one — the root as
# the policy file sees it, and as the repo root sees it, because content moves
# between exactly those two vantage points. They are the SAME string in the
# canonical shape (`AGENTS.md` + `docs`), so nothing widens there. Leading `../`
# is dropped from either because LINK_DEPTH has already erased it by then.
def _erasable_prefixes(docs, pol):
    seen = []
    for cand in (docs, os.path.relpath(docs, os.path.dirname(pol) or ".")):
        cand = os.path.normpath(cand).strip("/")
        while cand.startswith("../"):
            cand = cand[3:]
        if cand and cand != ".." and cand != "." and cand not in seen:
            seen.append(cand)
    return sorted(seen, key=len, reverse=True)


_roots = _erasable_prefixes(docs_dir, policy)
LINK_ROOT = (re.compile(r"\]\((?:"
                        + "|".join(re.escape(r) for r in _roots) + r")/")
             if _roots else None)

# A frontmatter key, loosely: `name:`, `  version: "1.7"`, or a `- ` list item.
# Loose on purpose — the point is not to validate YAML but to tell a metadata
# block from a document that opens with a thematic rule.
YAML_ISH = re.compile(r"^(?:\s+\S|-\s|[\w.$-]+\s*:)")

def strip_frontmatter(lines):
    """Drop a leading YAML frontmatter block. Returns (lines, how many dropped).

    Phase 7 REQUIRES bumping SKILL.md's frontmatter `version` whenever a change
    would alter what a run does, and Phase 6 then reported the old
    `version: "1.6"` as a line that existed at --base and exists nowhere now.
    The run that follows the skill's own instructions could not pass the skill's
    own gate, and the warrant file cannot absorb it: #111 shipped a CLOSED
    vocabulary and none of the five warrants means "this field is required to
    change" (#136).

    Frontmatter is metadata the run is TOLD to change, not the prose and
    pointers this check exists to protect, so it is not compared at all — on
    either side, or a body line could be "relocated" into a destination's
    metadata block and pass.

    A document may legitimately open with a `---` thematic rule, and swallowing
    everything up to the next one would hide real content. So a block counts
    only when it is closed AND everything in it reads as YAML.
    """
    if not lines or lines[0].strip() != "---":
        return lines, 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body = [x for x in lines[1:i] if x.strip()]
            if body and all(YAML_ISH.match(x) for x in body):
                return lines[i + 1:], i + 1
            return lines, 0
    return lines, 0

def delink(line):
    """Erase the link re-aiming a move forces, in both directions.

    Factored out because a link TARGET is one of the atoms --claims compares,
    and an atom normalised differently from the line it sits on would report a
    demoted link as a dropped claim on every run that moved one — the #119/#137
    false-LOST storm, reproduced one layer down.
    """
    line = LINK_DEPTH.sub("](", line)
    if LINK_ROOT is not None:
        line = LINK_ROOT.sub("](", line)
    return line


# --- atoms (--claims) -----------------------------------------------------
# The tokens a faithful rewrite must carry across. Deliberately narrow, for the
# reason verify-facts.sh gives about its own FALSE verdict: a claim list padded
# with prose teaches its reader to skim, and this one is the sole evidence
# behind the `tighten` warrant. Every atom here is checkable and its loss is
# real; nothing here is a judgement call about wording, which is exactly the
# thing whole-line matching already refuses to arbitrate.
FENCE = re.compile(r"^\s*(?:```|~~~)")
# Single-backtick spans only. A span cannot contain a backtick or span a line,
# so this leaves ``code with ` inside`` alone rather than mis-splitting it.
CODE_SPAN = re.compile(r"`([^`\n]+)`")
# `#412` and `owner/repo#569`. Two digits minimum, matching the seam
# convention, and the digits must abut the `#` — so `## Heading` and `# 2026
# plan` are not issue references.
ISSUE_REF = re.compile(r"(?<![\w#])((?:[\w.-]+/[\w.-]+)?#\d{2,})")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)")
BARE_URL = re.compile(r"(?<![(\w])(https?://[^\s)>\]]+)")
# Sentence punctuation a URL collects at the end of a prose line and does not own.
URL_TRAILING = ".,;:!?'\""


def atoms_of(lines):
    """Every atom in `lines`, as a set, with the line each first appeared on.

    Returns (set, {atom: line}) — the map is for the report, so a dropped atom
    can be shown in the context it was dropped from rather than alone.

    Fenced blocks are skipped. Their content is protected line by line already,
    so extracting from them would report every deleted code line twice: once as
    LOST and once as a dropped atom, with the second report adding nothing.
    """
    found, origin, fenced = set(), {}, False
    for raw in lines:
        if FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = delink(raw.strip())
        if not line:
            continue
        hits = [m.group(1).strip() for m in CODE_SPAN.finditer(line)]
        hits += [m.group(1) for m in ISSUE_REF.finditer(line)]
        hits += [m.group(1) for m in LINK_TARGET.finditer(line)]
        hits += [m.group(1).rstrip(URL_TRAILING) for m in BARE_URL.finditer(line)]
        for a in hits:
            if not a:
                continue
            found.add(a)
            origin.setdefault(a, raw.strip())
    return found, origin


def normalise(raw):
    """One line -> its comparable form, or "" when it carries no content.

    Exactly two differences a move legitimately forces are erased:

      link depth    a block moving between directories re-aims its relative
                    links, so `](tests/x.py)`, `](../tests/x.py)` and
                    `](../../tests/x.py)` are the same line at three depths, and
                    a link INTO the docs root loses that prefix when the block
                    lands inside it. Depth is erased in both directions and at
                    any amount; the target after it is not, so a repointed link
                    is still a difference.
      heading level a `###` subsection promoted to its own document's `##`.

    Heading text is tagged rather than merely stripped of its hashes. Stripping
    alone would let a `# comment` inside a fenced block collide with the prose
    line `comment`, which is a false match in the direction that hides loss.
    """
    line = raw.strip()
    if not line:
        return ""
    line = delink(line)
    m = HEADING.match(line)
    return "H:" + m.group(1).strip() if m else line

try:
    before = open(before_path, encoding="utf-8", errors="replace").read().splitlines()
    before, front_skipped = strip_frontmatter(before)
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
    # Atoms are pooled across ALL destinations rather than kept per file. An
    # atom is evidence that a claim survived the rewrite SOMEWHERE, which is the
    # same standard whole-line matching already applies; asking it to survive in
    # a particular file would fail every tightening that also demoted.
    dest_atoms = set()
    for path in dest_paths:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
        lines, _ = strip_frontmatter(lines)
        dests[path] = {n for n in (normalise(l) for l in lines) if n}
        if claims_on:
            dest_atoms |= atoms_of(lines)[0]
    base_atoms, atom_origin = atoms_of(before) if claims_on else (set(), {})
except OSError as exc:
    print(f"ERROR {exc}", file=sys.stderr)
    sys.exit(2)

# Acknowledgement entries, refused rather than ignored when malformed. A typo'd
# warrant that merely failed to match would report as an ordinary loss and send
# the run hunting for content that is fine; refusing also errs toward NOT
# passing, which is the only safe direction for a file that can turn exit 3
# into exit 0.
#
# Two forms, told apart by whether the FIRST field names a warrant — never by
# counting separators, which would truncate any entry whose judged line contains
# a `::`:
#
#   WARRANT :: CONTENT           every target
#   PATH :: WARRANT :: CONTENT   only runs whose --file contains PATH
#
# The scoped form exists because this file is per-repo while --file is
# per-target, so an entry judged against AGENTS.md reported "matched nothing" on
# the next run against a SKILL.md — the stale-entry warning, which is the thing
# that makes expiry trustworthy, firing on entries that were simply about
# another target (#139). PATH is matched as a substring of the target, the same
# way .skills/context-seams-ok pins an entry to one file. Scoping only ever
# NARROWS what an entry can reach.
def parse_ack(path, warrants, min_chars, unit):
    """Read an acknowledgement file. Returns (entries, malformed).

    Shared by the loss file and the claim file, because two files with the same
    grammar and two parsers is how they drift: the scoped form (#139) would have
    had to be found and fixed twice. What differs between them is passed in —
    the vocabulary, the length floor, and the noun for the error messages —
    and nothing else does.
    """
    entries, malformed = [], []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return entries, malformed
    with fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.rstrip("\n")
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            head, sep, tail = raw.partition("::")
            scope, warrant, content = None, head.strip(), tail.strip()
            if sep and warrant not in warrants and "::" in tail:
                second, _, rest = tail.partition("::")
                scope, warrant, content = warrant, second.strip(), rest.strip()
            if not sep:
                why = f"no `::` — an entry is `WARRANT :: {unit}`"
            elif scope is not None and not scope:
                why = ("empty PATH — an entry scoped to nothing matches every "
                       "target; drop the PATH half instead")
            elif warrant not in warrants:
                # Name the form it was read as. A three-field entry whose
                # warrant is typo'd is otherwise reported against a field the
                # author thought was a path.
                form = f" (read as `PATH :: WARRANT :: {unit}`)" if scope else ""
                why = (f"unknown warrant '{warrant}'{form} — one of: "
                       + ", ".join(warrants))
            elif not content:
                why = (f"empty {unit} — an entry with no {unit.lower()} matches "
                       "everything")
            elif len(content) < min_chars:
                # Checked here as well as by the over-broad refusal below, because
                # a two-character entry that happens to hit exactly one line
                # today is not identifying that line — it will silently move to
                # a different one the moment the surface changes, which is the
                # opposite of the expiry this file promises.
                why = (f"{unit} is {len(content)} characters — an entry must be "
                       f"at least {min_chars} to identify one line")
            else:
                entries.append((warrant, content, scope))
                continue
            malformed.append((lineno, raw.strip()[:100], why))
    return entries, malformed


def refuse_malformed(path, malformed):
    if not malformed:
        return
    print(f"ERROR {path} has {len(malformed)} malformed entry(ies):",
          file=sys.stderr)
    for lineno, text, why in malformed:
        print(f"  line {lineno}: {why}", file=sys.stderr)
        print(f"    {text}", file=sys.stderr)
    sys.exit(1)


entries, malformed = parse_ack(ack_path, WARRANTS, WARRANT_MIN_CHARS, "CONTENT")
refuse_malformed(ack_path, malformed)

# An atom is matched WHOLE against a set, so neither guard the loss file needs
# applies: a set element cannot be over-broad, and `#41` identifies itself at
# three characters. Passing the floor as 1 is the whole difference.
claim_entries, claim_malformed = parse_ack(
    claims_ack_path, CLAIM_WARRANTS, 1, "ATOM") if claims_on else ([], [])
refuse_malformed(claims_ack_path, claim_malformed)

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
#
# A scoped entry sits out a run against another target entirely: it cannot
# warrant a line here, and it is not accused of having gone stale here either,
# which is the whole point of the form.
in_scope, out_of_scope = [], []
for i, entry in enumerate(entries):
    if entry[2] is None or entry[2] in policy:
        in_scope.append(i)
    else:
        out_of_scope.append(entry)

# A warrant that cannot certify itself is refused when its evidence was not
# gathered, rather than downgraded to a warning — warnings ride in stdout, where
# the exit code and the ledger row do not read them, which is the lesson the
# over-broad refusal below already paid for. Checked against IN-SCOPE entries
# only: a `tighten` judged for another target is not this run's claim to make,
# and demanding --claims for it would make one target's file dictate another
# target's flags.
ungated = sorted({entries[i][0] for i in in_scope
                  if entries[i][0] in REQUIRES_CLAIMS}) if not claims_on else []
if ungated:
    print(f"ERROR {ack_path} uses {', '.join(ungated)} without --claims.",
          file=sys.stderr)
    print("  A rewrite in place is the one edit a run can always claim about "
          "itself, so\n  the warrant is gated on evidence the rewrite cannot "
          "produce: re-run with\n  --claims, which checks that every atom of "
          "the rewritten lines survived.", file=sys.stderr)
    sys.exit(1)

warranted, unwarranted = [], []
charged = [[] for _ in entries]
for line in lost:
    idx = next((i for i in in_scope if entries[i][1] in line), None)
    if idx is None:
        unwarranted.append(line)
    else:
        warranted.append((entries[idx][0], line))
        charged[idx].append(line)

# An entry that covers more than one line is REFUSED, not warned about. Breadth
# is the whole attack surface here: `retarget :: e` matched every dropped line
# in a repo and turned exit 3 into exit 0 with `lost: 0`, while the warning that
# said so rode along in stdout where no gate reads it. This file is the only
# thing that can convert a content-loss failure into a pass, so it gets the same
# treatment malformed syntax already gets — refusal, which errs toward NOT
# passing. An acknowledgement is ONE judged line; two lines are two judgements.
broad = [(w, c, len(h)) for (w, c, _), h in zip(entries, charged) if len(h) > 1]
if broad:
    print(f"ERROR {ack_path} has {len(broad)} over-broad entry(ies) — an "
          "acknowledgement covers ONE judged line:", file=sys.stderr)
    for warrant, content, n in broad:
        print(f"  {n} lines matched: {warrant} :: {content[:70]}", file=sys.stderr)
        print("    split it into one entry per line, or narrow the content so it "
              "identifies a single line", file=sys.stderr)
    sys.exit(1)

# --- the claim check ------------------------------------------------------
# Set difference, not line matching: an atom that exists at --base and in no
# destination is a claim the rewrite dropped. Sorted so the report is stable
# across runs — a gate whose output reorders is one nobody can diff.
dropped_atoms = sorted(base_atoms - dest_atoms) if claims_on else []

# Scoping and charging work exactly as they do for lines, so an entry judged
# against one target does not report stale on another (#139) and no entry can
# quietly become a blanket. The match is WHOLE rather than substring: `#41`
# must not warrant `#412`, and a dropped path must not be waved through by an
# entry naming its parent directory.
claim_in_scope = [i for i, e in enumerate(claim_entries)
                  if e[2] is None or e[2] in policy]
claim_out_of_scope = [e for e in claim_entries
                      if e[2] is not None and e[2] not in policy]
claims_warranted, claims_unwarranted = [], []
claim_charged = [[] for _ in claim_entries]
for atom in dropped_atoms:
    idx = next((i for i in claim_in_scope if claim_entries[i][1] == atom), None)
    if idx is None:
        claims_unwarranted.append(atom)
    else:
        claims_warranted.append((claim_entries[idx][0], atom))
        claim_charged[idx].append(atom)

# One stream for the whole report. Split across stdout and stderr it interleaved
# through a pipe, and the failure list printed above the counts explaining it.
out = sys.stdout
total = kept + sum(len(v) for v in relocated.values()) + len(lost)
# Named, not "policy file": --file takes a reference doc when proving a split,
# and a report headed "policy file" for docs/API.md reads as the wrong run.
print(f"{policy} at base: {total} non-blank lines", file=out)
# Named, because "not compared" is a claim a report owes its reader — this is
# the one place the check deliberately looks away.
if front_skipped:
    print(f"  frontmatter not compared:   {front_skipped} "
          "(metadata; Phase 7 mandates the version bump)", file=out)
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
    for (warrant, content, _), hits in zip(entries, charged):
        if not hits:
            continue
        print(f"    {len(hits)} hit(s): {warrant} :: {content[:70]}", file=out)

# An entry that matched nothing was called stale outright, and "prune it" is
# only sound advice for some of them (#251). Two facts decide which:
#
#   Is the entry ABOUT this target? A PATH that matched says yes outright.
#   Unscoped says nothing — the file is per-repo while --file is per-target.
#   Was its CONTENT in this target at --base? If so the entry is certainly about
#   this target, whatever its scope, and its line is now accounted for.
#
# Either fact alone settles it as STALE, which is the expiry this file promises
# and the case worth pruning. Neither holding leaves a question this run cannot
# answer, and the report must say so rather than pick:
#
#   the line was re-worded, so the entry no longer matches it — re-judge, OR
#   the entry was judged against another surface entirely and this run is no
#   evidence about it whatsoever.
#
# Pruning on the second reading discards a live warrant: an unscoped entry
# pinning an AGENTS.md line reported "matched nothing" on every reference-doc
# run in one cohort repo, and following that advice would have thrown away a
# warrant the next AGENTS.md curation still needs. #139 established that expiry
# is trustworthy only while every warning means something — so the honest move
# is to name the ambiguity, not to resolve it by guessing. A near-match test
# would resolve it, and is refused deliberately: "close enough to be the same
# line" is exactly the judgement whole-line matching exists to not make.
base_lines = [r.strip() for r in before if r.strip()]
stale, ambiguous = [], []
for i in in_scope:
    if charged[i]:
        continue
    warrant, content, scope = entries[i]
    settled = scope is not None or any(content in b for b in base_lines)
    (stale if settled else ambiguous).append(entries[i])

if stale:
    print(f"\n  {len(stale)} entry(ies) matched nothing — the line each "
          f"acknowledged is a line of\n  {policy}, and is accounted for now, "
          "which is when an entry needs\n  re-judging; re-judge and prune:",
          file=out)
    for warrant, content, _ in stale:
        print(f"    {warrant} :: {content[:70]}", file=out)

if ambiguous:
    print(f"\n  {len(ambiguous)} entry(ies) matched nothing AND pin content "
          f"that is not in\n  {policy} at --base, so this run cannot tell which "
          "of two things happened:\n  the line was re-worded (re-judge and "
          "prune), or the entry was judged for\n  another surface (add a PATH "
          "scope). Do not prune on this run alone:", file=out)
    for warrant, content, _ in ambiguous:
        print(f"    {warrant} :: {content[:70]}", file=out)

# Said out loud rather than silently skipped. An entry this run never consulted
# is not evidence of anything about this run, but a file whose entries quietly
# stop applying is one nobody can audit.
if out_of_scope:
    print(f"\n  {len(out_of_scope)} entry(ies) scoped to another target — not "
          f"consulted for {policy}:", file=out)
    for warrant, content, scope in out_of_scope:
        print(f"    {scope} :: {warrant} :: {content[:60]}", file=out)

if claims_on:
    print("\nclaims — backticked spans, issue refs, link targets, URLs:",
          file=out)
    print(f"  atoms at base:              {len(base_atoms)}", file=out)
    print(f"  DROPPED:                    {len(dropped_atoms)}", file=out)
    if claim_entries or claims_warranted:
        print(f"    warranted:                {len(claims_warranted)}", file=out)
        print(f"    unwarranted:              {len(claims_unwarranted)}",
              file=out)
    if claims_warranted:
        width = max(len(w) for w, _ in claims_warranted)
        for warrant, atom in claims_warranted:
            # With the line it came from. An atom alone is unreviewable — `#569`
            # says nothing about whether dropping it was right, and the sentence
            # it sat in is the whole of the evidence.
            print(f"  WARRANTED {warrant:<{width}}  {atom}", file=out)
            print(f"            {'':<{width}}  in: "
                  f"{atom_origin.get(atom, '')[:100]}", file=out)
    claim_unused = [claim_entries[i] for i in claim_in_scope
                    if not claim_charged[i]]
    if claim_unused:
        print(f"\n  {len(claim_unused)} claim entry(ies) matched nothing — the "
              "atom each acknowledged is\n  present again or gone from the base; "
              "re-judge and prune:", file=out)
        for warrant, content, _ in claim_unused:
            print(f"    {warrant} :: {content[:70]}", file=out)
    if claim_out_of_scope:
        print(f"\n  {len(claim_out_of_scope)} claim entry(ies) scoped to another "
              f"target — not consulted for {policy}:", file=out)
        for warrant, content, scope in claim_out_of_scope:
            print(f"    {scope} :: {warrant} :: {content[:60]}", file=out)

if claims_unwarranted:
    print(
        f"\nEach atom below is in {policy} at --base and in no destination.\n"
        "A tightening must carry its claims across — restore each, or add a "
        f"judged\nentry to {claims_ack_path} saying why the claim is gone.\n",
        file=out,
    )
    for atom in claims_unwarranted:
        print(f"  DROPPED  {atom}", file=out)
        print(f"           in: {atom_origin.get(atom, '')[:120]}", file=out)

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
elif claims_unwarranted:
    # Deliberately no OK line. Every line being accounted for is TRUE here and
    # printing it would still read as a pass twenty lines above exit 3 — the
    # shape the validation gate had to fix in itself, where a WARN at the top
    # and a rejection below left the reader believing the top.
    pass
elif warranted:
    print(f"\nOK — {len(warranted)} line(s) warranted, none unexplained.",
          file=out)
else:
    print("\nOK — every line is either still inline or relocated verbatim.",
          file=out)

print(f"\nduplicated: {len(duplicated)}", file=out)
print(f"loss_warranted: {len(warranted)}", file=out)
print(f"lost: {len(unwarranted)}", file=out)
# Emitted only under --claims. A `claims_dropped: 0` from a run that never
# looked would read as a clean bill of health, and this trailer is what the
# ledger row is copied from.
if claims_on:
    print(f"claims_warranted: {len(claims_warranted)}", file=out)
    print(f"claims_dropped: {len(claims_unwarranted)}", file=out)
out.flush()
if unwarranted or claims_unwarranted:
    sys.exit(3)

PY

exit "$RC"
