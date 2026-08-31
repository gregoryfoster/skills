# Telemetry and the Cohort Ledger

The ledger a curation run writes, the schema of a row, and the cross-repo
roll-up that reads them. Budgets and how the numbers are counted:
[budget-and-metrics.md](budget-and-metrics.md).

## Telemetry

An append-only JSONL ledger at `.skills/context-metrics.jsonl`, committed
alongside the file it measures. Committed, rather than kept in a central store,
for three reasons: the row travels with the repo through a transfer, it is
reviewable in the same PR as the edits it describes, and a run needs no write
access to any other repo.

A curation run writes **two** rows: a `baseline` row at Phase 1 for the surface
as found, and the curation row at Phase 7. See
[the pair, not the row](#the-pair-not-the-row) — a single row records a state,
and only a pair records a change.

### Row schema

| Field | Meaning |
|---|---|
| `ts` | UTC date, `YYYY-MM-DD`. Pinned to UTC so rows from different machines sort consistently. |
| `repo`, `file` | repo identity and policy-file path. `repo` is **the join key** the cohort roll-up and the validation gate match against the roster — not cosmetic. It comes from `--repo`, else the origin remote's basename, else the checkout directory name; the directory name alone recorded a *worktree* slug (`feat-161-curating-context`) as the repo in every member that mandates worktree-based feature work. |
| `tokens`, `lines`, `bytes` | policy-file size |
| `tokens_exact` | `true` when counted via `count_tokens`; gates delta comparability |
| `delta_unavailable` | present only when `delta_tokens` was suppressed; says why |
| `budget`, `over_budget` | the budget in force this run, and whether it was met |
| `tokens_live` | policy + reachable live reference docs |
| `docs_total`, `docs_orphaned` | live doc count, and how many nothing links |
| `links_dead` | broken relative links in the curated surface — the link's **file** does not exist |
| `links_dead_anchors` | the anchor half: the file resolves but the `#fragment` names no heading in it. `null` on a row predating the field, which is never the same as `0` — a run that never measured anchors has not shown there are none. Gated the same way as `links_dead`, because a doc split breaks anchors and no paths, so `links_dead` alone reports a clean surface ([#120](https://github.com/gregoryfoster/skills/issues/120), [#124](https://github.com/gregoryfoster/skills/issues/124)) |
| `no_loss` | `prove-no-loss.sh`'s verdict — `ok`, `failed`, `skipped`, or `null` when the check was not run. A safety field, not a score: [the validation gate](validation-gate.md) reads it to reject a change that reduced tokens by dropping content, which no token count can distinguish from a good run. `null` is unscorable, never a pass. |
| `no_loss_warrants` | how many of that verdict's unaccounted lines carried a judged entry in `.skills/context-loss-ok` — [`prove-no-loss.sh`](../scripts/prove-no-loss.sh)'s `loss_warranted:` line. `null` when the run did not report it, which is never the same as `0`: `0` says the run read the report and warranted nothing, `null` says it did not say. Without it `ok` cannot distinguish "nothing was unaccounted for" from "eight lines were judged and waved through", and two cohort adoptions recorded that same state in opposite ways — one leaving the ledger untouched, one recording a bare `ok` ([#111](https://github.com/gregoryfoster/skills/issues/111)). Recorded, surfaced as `ok+Nw`, and deliberately **not** gated; [the validation gate](validation-gate.md#the-safety-gates) says why. Watch the **delta**, as with `seams_acked` |
| `claims_dropped`, `claims_warranted` | [`prove-no-loss.sh --claims`](../scripts/prove-no-loss.sh)'s two trailer lines: atoms (backticked spans, issue refs, link targets, bare URLs) present at base and nowhere now, and how many of those carried a judged entry. Both `null` when the run did not report them, which is never the same as `0` — and that null is the whole point. A run that passed `--claims` and cleared it used to write **the same row** as one that never ran the check, so nothing in the ledger could tell a **verified** [class-C tightening](keep-cut-rubric.md#proving-a-class-c-tightening) from an unverified one. `no_loss_warrants` cannot answer it either: it aggregates all six warrant kinds, so a `tighten` is indistinguishable from a `retarget` in the count ([#253](https://github.com/gregoryfoster/skills/issues/253)). Both require a `no_loss` verdict, and a non-zero `claims_dropped` requires `failed` — an unwarranted dropped atom exits the check 3, so `ok` beside one is a verdict that run never reached. Recorded, surfaced beside `no_loss` as `/c`, `/c2w`, `/c3d`, and deliberately **not** gated, for the reason [the validation gate](validation-gate.md#the-safety-gates) gives for `no_loss_warrants` |
| `seams`, `seams_acked` | `check-seams.sh`'s counts after Phase 6.5's report was judged: **unacknowledged** hits, and hits judged legitimate and carried in `.skills/context-seams-ok`. Both `null` when the sweep was not run, which is never the same as `0`. Both recorded because `0 new / 0 acked` and `0 new / 50 acked` are different states — the second may be an acknowledged set quietly ballooning, which one number alone cannot show. Watch the **delta** on `seams`: a stable acknowledged set with `0` new hits is the healthy steady state, and a run that "improves" either number by deleting legitimate references has made the surface worse — the `tokens_live` mistake with a different metric. These fields are what make the cross-reference defect class visible to the gate at all; on the run that motivated the sweep, ten review findings were invisible to every other field on this row. |
| `skill_version`, `skill_commit` | which version of this skill produced the row; `null` on rows predating the field |
| `repo_commit` | short commit of **this** repo holding the state of the tree the rest of the row describes — on a curation row, the commit that **ships** it. The append cannot name that commit, because it runs before the commit exists; `record-telemetry.sh --repo-commit HEAD` backfills the row afterwards ([backfilling it](#backfilling-repo_commit), [#206](https://github.com/gregoryfoster/skills/issues/206)). Distinct from `skill_commit`, which names the *skill's* repo and can never stand in for it. The scheduled seam sweep reads it back off the previous row (`check-seams.sh --base-ledger`) to bound the interval `seams` covers, so a row without it sends the next sweep back to an empty interval. `null` outside a git repo with a commit, and on rows predating the field ([#169](https://github.com/gregoryfoster/skills/issues/169)). Two consecutive rows for one file bound an interval, and that is what the longitudinal covariates are **derived** from rather than recorded: `commits_since` — `git log <prev>..<this> -- <policy> <docs>`, which normalises regrowth by what causes it instead of by the calendar — and whether that run's seam sweep spanned anything at all, empty exactly when the previous row's `repo_commit` is `null`. A recorded field would be `null` on every row already written and could disagree with the commits; a derivation recomputes for history and cannot ([#118](https://github.com/gregoryfoster/skills/issues/118)) |
| `top_section`, `top_section_share` | largest section and its % of the file |
| `delta_tokens`, `delta_days` | change since the previous row for this file; `null` on the first |
| `actions` | action tags — see below |
| `note` | one-line free text |

### Action tags

The tags are the only mechanism connecting a token delta to its cause. Without
them the ledger records that a repo got smaller and nothing about how, which
makes the cohort roll-up unable to answer the question it exists to answer.

Use `verb:target`:

- `demote:<section>` — moved to a reference doc
- `prune:<section>` — tightened in place (class C)
- `delete:<section>` — removed with a warrant (class D)
- `split:<doc>` — an over-budget reference doc divided
- `fix:dead-link`, `fix:stale-command`, `fix:stale-issue-ref` — Phase 2 repairs
- `relink:<doc>` — an orphan given an index entry
- `self:curation` — the quarterly self-curation pass over the skill's own
  surface (`skills/curating-context/SKILL.md` as the policy file). Leads the
  curation row's tag list, so no reader has to infer the pass from the `file`
  path, and never travels with `delete:*` — the pass demotes and tightens only
  ([self-curation.md](self-curation.md)).
- `baseline:<kind>` — a measurement-only row, no edits. Written by
  `record-telemetry.sh --baseline[=KIND]`, which fixes the tag rather than taking
  `--actions`, so no reader has to guess whether a row describes a state or a
  change. Every reader — the gate, the roll-up — skips `baseline*` when looking
  for a curation.

  Two kinds, and the distinction is on the **tag** rather than in `--note`,
  because a longitudinal comparison has to be able to tell them apart without
  parsing freetext:

  - `baseline:pre-curation` (bare `--baseline`) — Phase 1: the state this run's
    edits will be measured against.
  - `baseline:scheduled` (`--baseline=scheduled`) — the weekly cadence: a
    reading of a surface nobody touched. See [cadence.md](cadence.md).

`"cleanup"` and `"misc"` are worse than no tag: they occupy the slot that would
otherwise have said something.

### The pair, not the row

A run's measurement is **two rows**: the Phase 1 `baseline` and the Phase 7
curation. One row alone records a state; the change lives in the difference, and
every consumer computes it that way — `delta_tokens` against the previous row for
the same file, and the validation gate's before-state the same.

That is why a first curation was unscorable before this rule existed. It is the
run that *creates* the ledger, so nothing precedes it, and the gate's scored run
was exactly the run it could never score: all twelve cohort repos came back
`unscorable` in experiment 1 ([#116](https://github.com/gregoryfoster/skills/issues/116)).
The `docs_orphaned` safety gate failed the same way and more quietly — it
compares against the previous row, so on a first curation it could not trip at
all.

Both rows ship in the same commit. Do **not** rewrite the baseline row when the
after-count changes; rewrite the curation row (next section). The baseline is the
thing being measured against, and a baseline edited to match its outcome measures
nothing.

### The baseline row is not optional either

`--baseline` appends a measurement-only row for the surface **as found**, before
any edit. It is what makes this run scorable at all.

The validation gate takes a run's before-state from the previous ledger row for
the same file, and a first curation is the run that *creates* the ledger — so
without this row the scored run is precisely the run that can never be scored,
and the `docs_orphaned` safety gate has nothing to compare against and cannot
trip. That is not hypothetical: it is what happened to all twelve cohort repos
in [experiment 1](experiment-log.md), which scored nothing
([#116](https://github.com/gregoryfoster/skills/issues/116)).

The row costs one command and lands in the same commit as the curation. Phase 7
appends the after-row; **never rewrite the baseline row to match it** — the pair
is the measurement.

**Be on a branch before you run this.** This is the first write of the run, and
it writes a tracked file. Phases 6 and 6.5 already presume a branch point exists
(`--base <branch-point>`) and Phase 7 commits there; the skill never says to
create it, so create it here. An aborted run otherwise leaves a modified ledger
on whatever branch you started from, which for an autonomous run is the one
place this skill forbids writing to.

### One row per phase: rewrite within, append across

The ledger is append-only **between** runs, and that is where the rule matters:
a later run that rewrites an old row destroys the trend it was keeping.
**Within** a run the instinct runs the other way and is correct — when a late
fix on the same branch shifts the count, rewrite this run's still-unmerged
*curation* row so it describes what actually ships, rather than appending a
third row for an intermediate state nobody can check out. The test is whether
the row's commit has merged: unmerged, it is a draft of this run's record;
merged, it is history. The baseline row is exempt in both directions — it
records a state that has already passed, so a late fix cannot change it.

The permission is about the row being a draft until it merges, not about the
count in particular. `repo_commit` is the other value that changes inside a
run, for a reason the count never has: it is unknowable until the commit exists.

### Backfilling `repo_commit`

Phase 7 measures, records, and only then commits the ledger alongside the edits.
So the hash the append can see is the **parent** of the commit that ships the
curation: everything else on the row describes the shipped tree, and
`repo_commit` alone points a commit behind. Observed on `CannObserv/archiver`,
where a row recording `bfff669` measured the tree that shipped as `5ce18a2`.

That is not cosmetic, because the field carries two meanings — *which state of
this tree the row describes*, and *where the next scheduled seam sweep starts* —
and a lagging value satisfies them with two different commits. A wired cadence
then bases its sweep before the curation, re-walks the run's own relocations,
and re-reports seams the run already judged and acknowledged: noise in exactly
the surface `.skills/context-seams-ok` exists to keep quiet.

So the row is backfilled after the commit, which is the rewrite-within-a-run the
section above sanctions:

```bash
bash "<SKILL_SCRIPTS>/record-telemetry.sh" --repo-commit HEAD
git commit -m "backfill repo_commit" .skills/context-metrics.jsonl
```

**Two commits, and the second one is why this works.** `git commit --amend`
would look tidier and has no fixed point: amending changes the hash the row was
just given. The follow-up commit touches the ledger line and nothing else, so
the tree the row describes is still the tree at the commit it names.

`--repo-commit` rewrites in place and never appends, so a re-run is a no-op and
an interrupted run leaves a row that still parses — one commit behind, and
recoverable by running the backfill later. It refuses a revision the repo does
not have (`null` already means "cannot name an interval"; a fabricated one sends
the next sweep to a tree nobody measured), refuses a `baseline` row, and
preserves any malformed line rather than dropping it in the rewrite.

Two alternatives were rejected, and the reasons still bind:

- **Record `git write-tree` instead**, which is knowable before the commit and
  identifies content exactly. Rejected: the field would stop being a commit, and
  `check-seams.sh --base-ledger` takes a *base revision* from it — the sweep-base
  meaning would have to be reworked to keep the attribution one.
- **Redefine the value as "the commit the run started from"** and define the
  sweep base as `repo_commit..HEAD`. Rejected: it satisfies the sweep
  requirement by weakening the attribution one, leaving no field that answers
  which tree the row's numbers describe.

Then get the branch a **fresh-eyes review pass** before it ships. Whoever just
moved three hundred lines has exactly the implementation blindness that misses
"and now this other file lies about it" — the seam sweep catches the mechanical
cases, a reviewer catches the rest. If a late fix changes the count, **rewrite
this run's row to match what ships; across runs, only ever append** — the
distinction this section opens with.

### Tagging the row — the Phase 7 text in full

`<N>` and `<M>` are the two numbers Phase 6.5 printed — new and acknowledged seams; `<W>` is Phase 6's `loss_warranted:`, omitted only if that phase was not run. Ran `--claims`? Add `--claims-dropped <D> --claims-warranted <C>` from its trailer — without them the row cannot say the tightening was checked ([#253](https://github.com/gregoryfoster/skills/issues/253)). Tag `--actions` honestly and specifically. The tags are the only thing that lets
a later run — or the cohort roll-up — attribute a token delta to what caused it.
`"cleanup"` teaches nothing; `"demote:Project Layout"` does. Schema and budget
rationale: [references/budget-and-metrics.md](budget-and-metrics.md).

Rows also carry `skill_version` and `skill_commit`, so an outcome can be
attributed to a *skill* change and not just a repo one, plus `repo_commit` —
which state of *this* tree the row describes, and where the next scheduled seam
sweep starts. Bump the frontmatter `version` whenever a change would plausibly
alter what a run does — an unbumped version makes the cohort look uniform when
it isn't, and the roll-up's `skill versions in play` footer is what surfaces
that.

### Reading the trend

`record-telemetry.sh --print-trend` prints the last eight **rows** with per-row
deltas and net change, and its header separates the two counts — a run writes a
`baseline` row and a curation row, so eight rows is four runs. Three shapes to
recognise:

- **Sawtooth** — reductions followed by regrowth. The file is not the problem;
  whatever keeps appending to it is. Look for a skill or hook that writes to
  `AGENTS.md`, and give it a reference doc to write to instead.
- **Step then flat** — one large demotion, then nothing. Healthy. Subsequent runs
  should show a curation row with a delta near zero: the surface is holding.
  (A `baseline` row is no longer the marker of a quiet week — every run writes
  one at Phase 1, so it says nothing about what the run found.)
- **Slow creep with no negative deltas** — nobody is running Phase 5, or every
  run is finding the budget already met and stopping. Check whether the budget is
  set high enough to never bind.

## Cohort roll-up

`cohort-report.sh` reads every member's ledger over `gh api` — no clone — and
prints current tokens, net change, run count, orphan and dead-link counts, and
**the action tags that accompanied each repo's largest single reduction**. That
last column is the cross-repo learning: after a few weeks it names which
optimisation actually pays, and the same one usually pays everywhere.

`net` obeys the same comparability rule as `delta_tokens`: it is anchored at the
oldest run contiguously matching the *latest* run's method, not at the first run
ever recorded. Anchoring at the first row instead reported **+2,743** for this
repo's own ledger, whose three rows record an identical 22,533-byte file — the
whole figure was the estimate→exact transition. When no comparable anchor exists
the cell reads `-` and a footer names the repo and says why, so a suppressed
comparison cannot be mistaken for "no change yet".

Roster in `.skills/cohort`, one `owner/repo` slug or local path per line; `#`
comments allowed. Repos with no ledger are reported rather than skipped.

An entry may also carry `wave:` and `pair:` annotations. The roll-up prints the
resulting split and how many members of each arm have adopted;
`score-cohort.sh` is what acts on it. Both scripts read the roster through one
parser in `_context-lib.sh`, so they cannot disagree about which repo is in which
arm — a second opinion about the experiment's own assignment would be worse than
no experiment. See [validation-gate.md](validation-gate.md).

Before a repo adopts the skill it has no ledger, and that is the expected state —
not a failure, and not something to fix by writing a ledger into it. Ledgers
appear as each repo adopts, driven by a per-repo adoption issue. After adoption,
a member with no recent row *is* the finding.

One caveat worth designing around: `gh api` prints nothing **and** exits non-zero
on a 404, so a naive empty-output test reads a missing ledger as an empty one.
The script greps the error body for `404` before deciding, and reports anything
else as `unreadable` rather than silently as absent.

### The cross-repo view, as Phase 7 carried it

For the cross-repo view:

```bash
bash "<SKILL_SCRIPTS>/cohort-report.sh" --cohort-file .skills/cohort
```

The `best reduction` column names which optimisation actually paid, per repo.
Repos with no ledger are reported rather than skipped — on a weekly cadence,
missing telemetry is itself the finding.

Phase 7 also carried the one-line form inline until v1.9:

  `cohort-report.sh --cohort-file .skills/cohort` gives the cross-repo view: which
  optimisation actually paid, per repo. Repos with no ledger are reported rather
  than skipped — on a weekly cadence, missing telemetry is itself the finding.
