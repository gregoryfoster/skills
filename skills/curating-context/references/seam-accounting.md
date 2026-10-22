# Seam accounting — what a scheduled `seams` count means

Split out of [cadence.md](cadence.md) in v1.15: the subject is what the
`seams` number on a row *is*, which is the sweep's semantics rather than the
schedule's, and cadence.md had reached its per-doc budget. Read this before
treating a scheduled `seams` count as pure accrual. The last section is Phase
6.5's other optional step: [the bare digits `check-counts.sh` passes
over](#bare-digits-the-count-gate-passes-over-optional-typesafe).

## What the scheduled `seams` count means

The cadence used to sweep with `--base HEAD`. `check-seams.sh` reads the base
policy file with `git show "$BASE:$REL"` and compares it against the policy file
in the **working tree**, so on a clean CI checkout those are the same content
and the diff is empty. *moved-title* — references to a title that left the
policy file — is computed from that diff and was therefore **zero in every
scheduled run, in every repo, forever, by construction**. A curation that
relocated a section and left danglers behind contributed nothing to any weekly
row, because by the next run the relocation was already in `HEAD`
([#169](https://github.com/gregoryfoster/skills/issues/169)).

Not a promise that the next scheduled row re-reports a curation's own
relocations: since [#206](https://github.com/gregoryfoster/skills/issues/206) a
curation row's `repo_commit` is backfilled to the commit that ships it, so the
next interval starts *after* that work — deliberately, because Phase 6.5 already
judged it. The class's live scope is relocations made outside a `curating-context` run.

**Two classes, not one.** The source sweep was gated on the same set — `if src
and moved:` — so an empty `moved` skipped every tracked file outside the docs
tree, printing *"N tracked source file(s) not swept"*. The scheduled run had
never opened a source file in any repo, which takes `source-back-reference` with
it: the class [#113](https://github.com/gregoryfoster/skills/issues/113) added
after 16 stale docstrings shipped across 13 files under a clean exit.

The sweep now passes `--base-ledger`, which takes its base from the **newest
ledger row carrying a `repo_commit`** — the state of the tree at the last
recorded measurement. So each week's sweep spans the interval since the week
before.

Since v1.18 the gate is `moved` **or** relocation — a body line of 24+
characters (8+ inside a fence) gone from the policy file and present under the
docs root — because a demotion out of a
section that *survives* moves no title at all, and the title-only gate skipped
157 source files while reporting that nothing had left
([#272](https://github.com/gregoryfoster/skills/issues/272)). That widens the
interval half of the class, not the standing half: on an EMPTY interval both
halves of the gate are empty, so a first scheduled run still opens no source
file, and the report now names which of the two turned the sweep on.

**`seams` is a sum of two different quantities, and always was.** Widening the
base widens only half of it:

| Class | Scope |
|---|---|
| back-references — the policy file named in a live reference doc | **standing**: read off the live surface, identical under any base |
| duplicate headings, provenance baked into a heading | **standing**, likewise |
| moved-title — a reference to a title that left the policy file | **interval**: since the previous measurement |
| source refs in tracked source outside the docs tree | **interval**: gated on what LEFT the policy file — a moved title, or a relocated body line |

So a scheduled row reads *"seams standing on the surface, plus seams accrued
since the last measurement"* — neither a pure accrual nor a pure state.
`check-seams.sh --help` says the same next to the exit codes, and the report's
`seam_base:` line names the revision each count started from.

**The interval half is a flow, not a stock — sum it, do not read the latest.**
A moved-title hit is a *pulse*. If week 2 reports one and nobody fixes it, week
3's base is week 2's commit, the title left the policy file before that, and the
hit is gone from week 3's count with the dangler still in the tree. The standing
half behaves the opposite way: a back-reference persists in every row until
somebody fixes or acknowledges it. So a reader comparing two rows is comparing a
stock plus a flow, and anything aggregating `seams` across a series should
**sum** the interval contribution rather than take the latest value.

**The first run has no predecessor, and says so.** With no ledger, no rows, or
no row carrying a `repo_commit` — every repo adopting the cadence, and every
ledger written before the field existed — the base is `HEAD`, the interval is
empty, the two interval classes contribute nothing, and the report prints a
`note:` saying so. That run's row records its own `repo_commit`, so the *second*
scheduled run is the first with a real interval. A recorded commit not in the
repo's history — a rewrite, a shallow clone — falls back the same way with a
`WARN` naming it, rather than failing the sweep and losing the classes that need
no base.

**The interval start is derivable, not stored twice.** The row records only
`repo_commit`; the base a given row's sweep used is the *previous* row's
`repo_commit`, and `null` there means that row's sweep had an empty interval.
The one case where that inference is wrong is the loud fallback above.

## A repo whose source is about policy files

The source classes open on any demotion, and in a repo whose own tooling is the
subject — a test suite built from synthetic policy files, scripts that read a
consumer's `AGENTS.md` — the filename is subject matter hundreds of times over.
Measured on this skill's own repo on 2026-09-24: one demotion out of `AGENTS.md`
took the sweep from 0 unacknowledged hits to ~700, ~690 of them under `tests/`
and `skills/`. A line-scoped entry for each expires whenever its line changes,
so the busiest test file turned the gate red on unrelated edits, and demotion —
the lever that makes real headroom — was priced out
([#321](https://github.com/gregoryfoster/skills/issues/321)).

So `.skills/context-seams-ok` takes a **group** entry:

```
@mentions AGENTS.md tests/ :: <why every mention under tests/ is subject matter>
```

It covers `source-back-reference` hits under the prefix, for that swept file
only, and never expires. It **declines** a line that also names content that
moved — a title that left the file, or a surviving section a body line left —
so `AGENTS.md's variant strategy` in a test is still reported when that section
moves. The report prints each group's count and reason, and its hits count
into `seams_acked` — so a demotion row in such a repo carries hundreds there,
which is the group working, not an acknowledged set ballooning. Doc
back-references and `source-moved-title` keep line-scoped entries, and those
still expire.

Chosen over three alternatives. A path **ignore-list** hides a real pointer with
no judgement attached. Sweeping only **pointer-shaped** hits is a heuristic that
fails silently. Declaring that the repo **curates by tightening only** leaves
the wall where it is. The group's limit is what a decline cannot see: a line
that describes moved content without naming its section. So group only where the
lines are about policy files in general, and judge a line that makes a claim
about the repo's own policy file line by line.

## Bare digits the count gate passes over (optional, TypeSafe)

`check-counts.sh` never reports a bare digit: in a policy file one is nearly
always a port, a status code, a version or a limit. So "182 hx-get reveals"
passes. `bare-digit-counts.sh` reads the clauses the gate passed over in a
**reference doc**, masks the digits code can rule out (code spans, links,
issue refs, dates, percentages, versions, SHAs, times, ports, list markers,
digits fused to letters), and asks one yes-or-no question about each clause
left: does a number in it state how many of something the repo holds now, so
it goes stale? It is advisory, and off until the repo opts in through
`.skills/typesafe` or `TYPESAFE_OPT_IN`. A request carries the `clause`, its
`numbers` and its `heading`. Nothing else leaves the machine, and a private
repo decides for itself. Resolve it on its own, since SKILL.md's block doesn't
list it:

<!-- skill:required id=skill-scripts -->
```bash
N=curating-context
for S in bare-digit-counts.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

```bash
bash "<check-counts.sh>" --file <reference doc> --candidates /tmp/context-count-candidates.jsonl
bash "<bare-digit-counts.sh>" /tmp/context-count-candidates.jsonl > /tmp/context-bare-digits.tsv
```

- **It never touches the gate.** `--candidates` is output only: the report,
  the trailer and the exit code are the same without it. A flagged clause
  needs no `.skills/context-counts-ok` entry, nothing is written for you, and
  the `counts` fields on the ledger row don't include it.
- **Never on a policy file.** A clause from an `AGENTS.md` or `CLAUDE.md` is
  not sent; its row says `policy-file`. The cohort's 12 policy files held 411
  passed-over digits and one tally, so a run there buys a call per port to
  find nothing. Run it on the docs a curation split, or any live doc. An
  archival doc (a dated plan or spec, by the `CTX_ARCHIVAL` names) is skipped
  the same way, as `archival`: its counts are records.
- **Read the flags, then the ranking.** Judged rows come most likely a tally
  first, and `tally?` marks those at or over 0.8. On 664 hand-labelled
  clauses from the live docs of 12 public cohort repos
  ([#441](https://github.com/gregoryfoster/skills/issues/441)), 0.8 flagged 5,
  all tallies, but caught only 5 of the 18. False positives start at 0.79, so
  read below the flag when the budget allows. On a random sample of docs
  clauses it flagged nothing. `p` orders the rows; it isn't a calibrated
  chance.
- **A dated count is a record, not a tally.** "Measured 2026-09-23: 132
  files" stays true as history, and the question says so. A count it ranks
  first still needs your judgment, and so does a dated one it misses.
- **It doesn't pick the remedy.** Which of the gate's forms fits a flagged
  count (the command, dropped precision, a gate, or a warrant) stays yours.
- **Exits 2 and 4 are a partial result, or none.** On 4 (a skip: not opted
  in, or no key) every row is printed unjudged. On 2 (a TypeSafe failure) rows
  judged before it keep their `p`, and the rest are `failed` or `not-asked`.
