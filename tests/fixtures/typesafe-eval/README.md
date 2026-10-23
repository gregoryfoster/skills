# Labelled sets for `scripts/typesafe-eval.py`

One directory per epic #451 child, each holding the labelled set a judgment
was measured on and the cache of the replies it got:

```
<child>/
  set.jsonl     the cases, in typesafe-eval.py's SET format
  cache.jsonl   the replies, in its CACHE format (holds no case text)
```

A set mined after #463 also keeps what built it beside it (#463's note), so
the set can be rebuilt without the source repos:

```
  mine.py       the mining, selection and build steps
  inputs.jsonl  each case's input, as the child's script reads it
  labels.tsv    the labels, by case id
```

`tests/structural/test_typesafe_eval_sets.py` replays each one with
`typesafe-eval.py <set> --cache <cache> --offline --public` and holds it to its
headline numbers. It needs no network and no key.

## Only public material lands here

**Decided 2026-10-21 by the operator** (epic #451): a set built from public
material only is committed, with its cache. **A set drawn from a private repo
never lands**, and neither does its cache or report: keep those outside every
git work tree, where the evaluator's own guard puts them.

## Adding a set

1. **Check every source repo is public at commit time,** not when the set was
   mined. List the repos the set's `source` fields name, then:

   ```bash
   for r in <owner>/<repo> ...; do printf '%s %s\n' "$r" "$(gh api "repos/$r" -q .private)"; done
   ```

   Every line must end in `false`. Anything else (`true`, or an error because
   the repo can't be seen) keeps the set out.
2. Copy the set and its cache into `<child>/` under the names above.
3. Replay it: `python3 scripts/typesafe-eval.py <child>/set.jsonl --cache
   <child>/cache.jsonl --offline --public`. It must be valid with zero misses.
4. Add a row to `SETS` in the test: the set's sha256, its case count, and the
   sweep rows the child chose its threshold on.
5. If the child's case builder takes only what is in `state`, rebuild every
   case through it and assert byte equality, as the stale-issue-prose test
   does. That pins what is sent at no cost.

## What a replay pins, and what it doesn't

It pins the set, the cache and the evaluator's metrics, and step 5 pins the
case builder itself. It does **not** pin what feeds the builder: rebuilding a
case's input needs the source file it came from, which lives in another repo,
often at an old commit. A change there shows up only when someone re-measures.

## Sets

| Directory | Child | Set sha256 | Measured |
|---|---|---|---|
| `stale-issue-prose/` | #438 | `cc3ee5d181b2` | [report](https://github.com/gregoryfoster/skills/issues/438#issuecomment-6302036571), [re-measure](https://github.com/gregoryfoster/skills/issues/438#issuecomment-6303164875) |
| `bare-digit-counts/` | #441 | `31f064bca50a` | [report](https://github.com/gregoryfoster/skills/issues/441) |
| `tightened-rules/` | #442 | `551c3c7c10ac` | [report](https://github.com/gregoryfoster/skills/issues/442) |
| `index-lines/` | #447 | `c5a99b92ba64` | [report](https://github.com/gregoryfoster/skills/issues/447#issuecomment-6370273852) |
| `section-class/` | #435 | `a24ecb5ef667` | [report](https://github.com/gregoryfoster/skills/issues/435#issuecomment-6372110302) |

`stale-issue-prose/` is 130 cases from gregoryfoster/skills and 11 public
CannObserv repos (`still_open` 15 positive, `already_done` 3), labelled by one
labeller. Its cache holds 133 replies: the 3 extra are the pre-CR 428 cases,
which the set no longer asks (A14, A30, F40, before CR 428 took their
blockquote markers out).

`bare-digit-counts/` is 664 cases from gregoryfoster/skills and the same 11
public CannObserv repos, mined 2026-10-21 at the commits `mine.py` names,
labelled by one labeller. `inputs.jsonl` holds 1,082 of `check-counts.sh
--candidates`' own records in three slices:

- `P`: every candidate in the 12 policy files (411, 295 of them prefiltered).
  The pass sends no policy-file clause, so `P` is in no case; it is kept so
  the prefilters' recall is measured, and as the reason for that rule;
- `S`: every docs candidate that survives the prefilters and looks like a
  tally, a number before a plural that isn't a unit (571, 6 of them
  prefiltered since CR 459 added the `time` mask);
- `R`: a seeded sample of the other docs survivors (100, 1 since
  prefiltered).

`R` is the rate a run sees, and `S` is where the positives are: 18 tallies,
all in `S` (the 19th labelled tally is `P`'s). The cache holds exactly the
set's 646 distinct requests: 18 cases repeat another's text, vendored docs in
several repos.

The rubric: a **tally** is an undated count of what the repo or project holds
now (files, tests, tables, seeded values), so the sentence rots when that
changes. Not a tally: a dated measurement or a past run's, audit's or
incident's result (a record, true as history), a limit or a config value, a
code, a port, a version, an ordinal or step, a duration, an external
standard's figure.

`tightened-rules/` is 421 sentences from 49 curations in 9 public repos
(gregoryfoster/skills and 8 CannObserv repos), mined 2026-10-22 at the clone
commits `mine.py` names and labelled by one labeller. Each is a base sentence
on a line a `tighten` entry warranted, judged against the section the rewrite
left. They were drawn from every `tighten`-warranted line of 61 curations, in
66 policy files. `inputs.jsonl` holds 580 of `prove-no-loss.sh --candidates`'
own records: those on the lines of a labelled sentence, enough to rebuild every
case and its id. There are two slices:

- `H`: every sentence the pass would send that has history evidence, 271 of
  them. Either a word 4-gram it had and its successor lacked came back later,
  or a review fix edited its successor. This slice is where the positives are:
  35, 14 of them a later review restored.
- `R`: a seeded 150 of the other 580. This is the rate a run sees: 26
  positives.

The rubric: a sentence is a **yes** when it states a rule and the successor no
longer states it, or states it more weakly or more broadly. A rule is a
requirement, a prohibition, a condition or scope, an exception, a boundary, or
the stated reason for one. A rule that survives only as a link to another doc
is a yes, and so is one moved to another section (`delegated`, `moved` in the
notes), because the pass sees only the successor. A **no** is a rule kept in
other words, or a sentence that states no rule: an index line or other
pointer, a description of how something works, a dated measurement,
history, an incident's story. `restored` marks a sentence a later review put
back. It is evidence, not the label: a review restored a pointer's anchor or
a descriptive word too.

The set and its inputs are the largest here, 1.7 MB and 3.7 MB: each record
repeats its block and its successor, as `--candidates` writes them.

`held.tsv` is a second label on the same set, added for
[#470](https://github.com/gregoryfoster/skills/issues/470) beside `labels.tsv`
and drawn from nothing new. It covers all 61 positives, and only them. A
positive is **held** when a doc its successor points to states the same rule
at the curation commit, in any words. `where` names that doc, and `how` says
`verbatim` or `reworded`. A pointer is a Markdown link or a backticked `*.md`
path. A rule moved within its own file, with no pointer to it, is not held.
Nor is a routing condition ("read it before …"), which only the pointer can
carry. **46 of the 61 are held:** 26 of the 28 delegated or moved positives, and
20 that `labels.tsv` calls drops, 8 of which a later review restored.
The suite pins the ceiling this implies from the committed cache. The step-1
figures read docs at each curation commit, so `mine.py delegated` re-derives
them from the clones.

`index-lines/` is 198 cases from the same 12 public repos, mined 2026-10-23 at
the commits `mine.py` names and labelled by one labeller. #447 shipped no pass,
so there is no `inputs.jsonl`: each case's `state` is all it was asked, and
`mine.py build` rebuilds the set from the clones. Each case is one index line
against its doc's `#`–`###` headings and opening paragraph. There are two
slices:

- `H`: the 17 accuracy fixes in the policy files' history, each as a pair.
  `HP` is the line before the fix, a yes. `HN` is the fixed line, a no. Both
  are judged against the doc at the fix's parent, so the pair differs only in
  the line. They come from 249 rewrites that kept a line's target: 120 landed
  with a change to their doc, and the 17 are among the other 129.
- `R`: every HEAD index line whose first target is a Markdown doc, 164 of
  them. All are no. 7 are an `HN` line unchanged since, and share its request.

The rubric: a line is **inaccurate** when it claims a topic its doc doesn't
cover, or leaves out a major topic the doc covers, so a task about that topic
wouldn't open the doc. Not inaccurate: a line naming the doc's purpose rather
than its contents, an abbreviation of its headings, a routing condition ("read
it before …") or a link to another doc, which only the line can carry, and a
heading whose section only says its content moved. `borderline` marks 18 HEAD
lines whose doc has grown a topic the line doesn't name. They are labelled no,
because power-map's `docs/CONTEXT.md` Rule 1 keeps an index line a pointer on
purpose (#667).

The suite pins the labels and the pairs result #447 closed on: the line before
a fix scored above its own fix in 8 of the 17 pairs. A variant whose state held
each section's first sentence came out the same, 8 of 17. Its 34 cases aren't
committed, so that figure isn't pinned.

`section-class/` is 1,178 cases from the 10 public repos that keep a ledger
(processor and status don't), mined 2026-10-23 at the commits `mine.py`
names. Each case is one `##` section of a policy file at the base of a
curation, alone in the state (V1). Its label comes from that curation's ledger
row: `demote:` is B, `prune:` and `tighten:` are C, `delete:` is D, and a
section the curation left unchanged is A. That last label is the weakest: a
run stops once it is under budget, so it means "not acted on", and 32
byte-identical sections carry A in one curation and C or B in another. No
`delete:` in these ledgers removes a trained default, so the `default` Noul
has no positives, and every case expects no. A label follows the tag even when
the edit landed after the commit the row was stamped with: 10 C sections are
unchanged there (power-map 2026-08-17 and 2026-09-19, replicator 2026-09-18,
watcher 2026-08-19), so they stay out of the pairs.

`pairs.jsonl` holds the 178 sections each curation edited, before and after,
and the cache answers both. The suite pins the result #435 closed on: Jev
never answers C, and past its own repeat noise (186 requests sent more than
once; the probabilities' 90th-percentile spread is 0.07), a tightened
section's P(A) rose in 14 pairs and fell in 11. The cache keeps every repeated
reply, in the order the replies came back, and the pinned numbers are read by
the evaluator's rule: the last reply for a request wins. The issue's own design, the whole file in the state with a question
per section (V2), did no better: 41% agreement, and P(B) fell in 21
part-demoted pairs and rose in 20. `mine.py v2` rebuilds its requests, but
they aren't committed, so its figures aren't pinned.

`harvest-candidates/` comes from harvests that actually happened. It holds
156 cases from 4 public epics: wslcb-licensing-tracker#205, archiver#300,
broker#80 and this repo's #451. A "Changed since filed" comment on child T
that harvests child S's thread is one event. Its time is that comment's. The
candidates are the epic's children open at that time, with their bodies as
they read then, rebuilt from GitHub's edit history. The thread is S's
comments before the harvest, read the way `_harvest.select` reads them.

`labels.tsv` accounts for all 58 public harvests:
- **18 come from no child's thread:** the coordinator's own measurements,
  another tracker, #348's adoption findings, and an epic split.
- **2 target an issue outside the epic.**
- **The other 38 were aligned** to the source paragraphs sharing the most
  words with them (Jaccard ≥ 0.2, `mine.py align`). Each alignment to a
  paragraph that doesn't name its target was checked by hand: 13 were
  spurious, mostly a heading matched to a heading. A hand-check of the Noul's
  top-ranked "negatives" found 3 more real harvests.
- **What's left:** 68 pairs whose paragraph names the target (a `For #N`
  scope or a linked `#N`), 22 that don't, and 10 harvests rewritten past
  word overlap, which have no paragraph.

The set is the 22 unnamed paragraphs, each against every child open at its
event. The suite pins three results #436 built on:
- **The target's rank among those children.** The Noul put it first for 14
  of 22 and in the top 3 for 16. Plain matching (shared backticked spans,
  then shared words) did 3 and 12; random order expects 3.8 and 11.4.
  Paired, the Noul did better on 15, worse on 2 and the same on 5.
- **Repeat noise.** The cache answers every request twice, and the last
  reply wins. The two replies differ by at most 0.11, p90 0.04.
- **The whole-thread table.** `scores.tsv` holds the Noul for every residue
  row of six events, 1,732 rows with no text. A row is in the residue when
  its paragraph doesn't name its child. The top 20 rows of each event hold
  10 of their 16 unnamed positives; plain matching's hold 5.

Labels mined from these comments undercount positives: a harvest also lands
in the next child's brief. Of the strongest "negatives" checked by hand, 7 of
11 had been delivered that way.
