# Experiment log

What each run of the validation gate actually produced. The gate's *rules* live
in [validation-gate.md](validation-gate.md); this file is the record of what
happened when they were applied, kept separate so that reading the rule does not
mean reading every run that has ever exercised it.

One entry per experiment, appended, never rewritten — an experiment that is
re-described after its verdict is an experiment whose verdict moved. From
experiment 2 on, each entry has a committed pre-registration beside it in
`.skills/experiments/NN-<slug>.yml`, which is what makes the primary metric
checkable by someone who was not in the room
([#117](https://github.com/gregoryfoster/skills/issues/117)).

## Experiment 1 — v1.3, run 2026-08-10: no verdict

Both arms adopted as designed and the gate produced **no verdict**. Recorded here
because the design's one-shot property (previous bullet) means this cannot be
re-run: the cohort's first-curation capital is now spent.

What went right: the arms were clean. All six wave-B repos ran v1.3 (`c1e6273`),
all six wave-A first curations stand at v1.2 (`3fc7b71`), and every safety gate
passed in **both** arms — `no_loss=ok`, `links_dead=0`, `docs_orphaned=0` across
all twelve.

What went wrong, in two layers:

- **The gate scored nothing at all.** Every repo came back `unscorable` for the
  same reason: the before-state is defined as the previous ledger row, and a first
  curation is the run that *creates* the ledger. The scored run is precisely the
  run that can never be scored, and no phase of this skill ever records a
  baseline row ([#116](https://github.com/gregoryfoster/skills/issues/116)).
- **The metric could not have judged this proposal anyway.** Scored by hand
  against the pre-registered 2026-08-05 baseline, ten of twelve repos landed under
  budget, so `gap_after == 0` and closure pins at exactly 1.0 — four of six pairs
  uninformative, and the two that discriminate are the only two repos that
  *missed* budget, one falling to each arm. Closure measures shortfall, not
  quality, and it is structurally blind to what v1.3 changed
  ([#117](https://github.com/gregoryfoster/skills/issues/117)).

Per the rule above, this is INCONCLUSIVE and does **not** enter
`rejected-changes.md`. v1.3 stays shipped and unjudged, which is the accurate
state.

The evidence that does exist is qualitative and directional: all six v1.3 runs
recorded `seams: 0`, and `observo` — re-run at v1.3 over the surface its own v1.2
curation had declared finished — found **41** unacknowledged seams. One control
datapoint, and the comparison is asymmetric (detection on an unswept surface
versus resolution during a run), but it is the only measurement of that defect
class in existence. Wave B's runs also produced #111 and #113 as findings against
v1.3, so the held-out arm yielded qualitatively even where the gate did not.

The lesson for experiment 2 is that the unit of comparison and the primary metric
have to be settled — and pre-registered — *before* the treatment arm adopts.
Choosing either after the rows land is choosing the verdict.

**Fixed since, in v1.4:** Phase 1 records a `baseline` row, so a first curation
carries the before-state it is scored against and the `docs_orphaned` gate has
something to compare; a systematic unscorable is reported as a gate defect rather
than as an empty experiment; and a REJECT now needs three informative pairs
whatever `--min-pairs` says. None of that recovers experiment 1 — the cohort's
first-curation capital is spent either way, which is
[#118](https://github.com/gregoryfoster/skills/issues/118)'s subject. What it
does is make the *next* run of the gate measure something.
