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
commits `mine.py` names and labelled by one labeller. The pool they were drawn
from is every `tighten`-warranted line of 61 curations, 66 policy files. Each is a base sentence
on a line a `tighten` entry warranted, judged against the section the rewrite
left. `inputs.jsonl` holds 580 of `prove-no-loss.sh --candidates`' own records:
those on the lines of a labelled sentence, enough to rebuild every case and its
id. There are two slices:

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
