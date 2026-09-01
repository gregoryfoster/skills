# Seam accounting — what a scheduled `seams` count means

Split out of [cadence.md](cadence.md) in v1.15: the subject is what the
`seams` number on a row *is*, which is the sweep's semantics rather than the
schedule's, and cadence.md had reached its per-doc budget. Read this before
treating a scheduled `seams` count as pure accrual.

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

**Two classes, not one.** The source sweep is gated on the same set — `if src
and moved:` — so an empty `moved` skipped every tracked file outside the docs
tree, printing *"N tracked source file(s) not swept"*. The scheduled run had
never opened a source file in any repo, which takes `source-back-reference` with
it: the class [#113](https://github.com/gregoryfoster/skills/issues/113) added
after 16 stale docstrings shipped across 13 files under a clean exit.

The sweep now passes `--base-ledger`, which takes its base from the **newest
ledger row carrying a `repo_commit`** — the state of the tree at the last
recorded measurement. So each week's sweep spans the interval since the week
before.

**`seams` is a sum of two different quantities, and always was.** Widening the
base widens only half of it:

| Class | Scope |
|---|---|
| back-references — the policy file named in a live reference doc | **standing**: read off the live surface, identical under any base |
| duplicate headings, provenance baked into a heading | **standing**, likewise |
| moved-title — a reference to a title that left the policy file | **interval**: since the previous measurement |
| source refs in tracked source outside the docs tree | **interval**: gated on the same "something moved" set |

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
