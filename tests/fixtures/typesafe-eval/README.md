# Labelled sets for `scripts/typesafe-eval.py`

One directory per epic #451 child, each holding the labelled set a judgment
was measured on and the cache of the replies it got:

```
<child>/
  set.jsonl     the cases, in typesafe-eval.py's SET format
  cache.jsonl   the replies, in its CACHE format (holds no case text)
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

`stale-issue-prose/` is 130 cases from gregoryfoster/skills and 11 public
CannObserv repos (`still_open` 15 positive, `already_done` 3), labelled by one
labeller. Its cache holds 133 replies: the 3 extra are the pre-CR 428 cases,
which the set no longer asks (A14, A30, F40, before CR 428 took their
blockquote markers out).
