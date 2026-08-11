# The Validation Gate

Every learning folded into this skill so far was accepted because it seemed right
to whoever proposed it. Six went in from the first live run alone. That is exactly
the failure mode a held-out validation set exists to prevent, and
[Library Drift](https://arxiv.org/html/2605.19576v1) names the consequence:
persistent skill artifacts become the degradation substrate, "the frozen-weight
counterpart to catastrophic forgetting."

[Microsoft's SkillOpt](https://www.microsoft.com/en-us/research/blog/skillopt-agent-skills-as-trainable-parameters/)
treats the skill file as a trainable parameter against a frozen model, and its
central control is a binary gate: a revision "is adopted only if it scores
strictly higher than the current skill on the held-out validation split." Across
six benchmarks, seven models and three execution modes it was best or tied-best in
all 52 cells.

**The twelve cohort repos are the held-out split.** That is the thing most skills
cannot manufacture, and it is the only reason this gate is buildable here.

```bash
bash "<SKILL_SCRIPTS>/score-cohort.sh" --treatment b --control a
```

Exit 0 adopt, 3 reject, 5 inconclusive. The script reports; it never writes and
never adopts. [rejected-changes.md](rejected-changes.md) is where a rejection
goes.

## The unit of comparison is a repo's first curation

A repo's first curation and its fifth are not the same task. The first is where
the skill does the bulk of the work — the whole `docs/` tree gets created, the
largest section gets demoted, the index gets written — and it is where the
rubric's quality is most visible. The fifth is maintenance.

So the scored run is **the first ledger row carrying a `skill_version` whose
actions are not purely `baseline*`**, and the pairs exist so that first-against-
first is a fair comparison. This is also why the staging matters: if all twelve
repos adopt on the same day and the same version, every first curation is spent,
and the only comparisons left are between maintenance runs.

Three details decide whether that run is scored at all:

- **One policy file per repo — the one with the most rows**, ties broken by
  whichever was measured most recently. A ledger may track several, so "what did
  this repo do" is unanswerable until one is named.

  Most-recent alone was the first rule and it was too fragile: one incidental
  `docs/GUIDE.md` baseline re-defined a repo that had curated `AGENTS.md`
  50,000 → 6,800 over three runs, dropping it out of the experiment and
  collapsing the roll-up's headline to 4,000 tokens, one run and no net — a
  number that then fed the cohort total. Row count is what a stray append cannot
  flip.

  `score-cohort.sh` and `cohort-report.sh` use the **same rule**, and a test pins
  them to the same answer: when they disagreed, one ledger yielded two
  irreconcilable pictures of a single repo, the gate scoring a 100-token prune on
  `sub/AGENTS.md` (3.3% closure) while the roll-up reported the 43,000-token
  curation on `AGENTS.md`. If the primary file was never curated the repo is
  unscorable and the report names both the file and how many others were skipped;
  when any ledger held more than one file, the report names which was scored,
  because the table has no room for the column.
- **The before-state comes from that same file** — and it has to *exist*. Taking
  whichever row happens to precede the curation produced a fabricated closure: a
  repo that really went 50,000 → 9,000 scored **−2900%** against an unrelated
  file's 6,100, and handed the pair to the other arm.

  The deeper failure is that for a first curation there was no preceding row at
  all. It is the run that *creates* the ledger, so the scored run was exactly the
  run that could never be scored — which is why experiment 1 scored nothing
  ([#116](https://github.com/gregoryfoster/skills/issues/116)). Phase 1 now
  records a `baseline` row (`record-telemetry.sh --baseline`) and both rows ship
  in one commit, so a run carries the state it is compared against. Rows
  predating that rule stay unscorable; the gate says so as a **gate defect**
  when every repo in both arms is blocked by one and the same reason, instead of
  reporting an empty experiment.

  The same absence disarmed a safety gate. `docs_orphaned` trips on a *rise*
  against the previous row, so with no previous row it could not trip at all —
  on all twelve first curations. The recorded values were `0`, so nothing was
  missed in fact, but the check had not run.
- **An untagged run makes the repo unscorable.** `record-telemetry.sh` emits
  `actions: []` when `--actions` was omitted, and such a row cannot be told from
  a baseline. Scoring it as a curation would attribute its near-zero closure to
  the skill version; skipping past it would hide the tagging gap. The gate says
  "tag it and re-score" instead.

## Staging, and which arm is which

Wave A adopts now. Wave B is held. When a change to the skill is proposed, wave B
adopts *on the proposed version* while wave A keeps running the version before it.

**Wave A therefore holds the older version, and the first experiment runs
`--treatment b --control a`.** The script's defaults (`--treatment a`) suit later
rounds, once A is the arm carrying a proposal.

> **Superseded after experiment 1.** This describes how the first experiment was
> staged, and it worked — the arms came out version-clean. It does not describe
> how later ones can be. Every cohort repo is on skills-vendor auto-refresh and
> follow-up issues keep necessitating updates, so **a wave cannot hold a version**:
> `observo` moved itself to v1.3 within a day of that version existing. Going
> forward the arms are defined by each row's recorded `skill_version`, not by wave
> membership, and the `wave:`/`pair:` annotations keep only their staging value —
> rolling a proposal out to half the cohort first.
> [#118](https://github.com/gregoryfoster/skills/issues/118) carries the
> replacement design.

Getting the direction backwards turns a winning change into a losing one, so the
gate detects it: when the treatment arm's versions are all *older* than the
control's, it prints a `WARN` naming the inversion and the flags that fix it —
**and returns INCONCLUSIVE rather than a rejection.** Detection alone was not
enough. The first implementation warned at the top and then rejected the winning
change and told the reader to file it in `rejected-changes.md`, twenty lines
below the warning saying not to trust the result.

Comparison is by numeric component, not by string — `1.10` is newer than `1.9`
and sorts below it lexically. That ordering decides only whether to *stop*, never
who wins: a non-numeric component reads as zero, which is fine for refusing to
score and not fine for scoring.

The verdict also refuses when **either arm is split across versions**. "Adopt
only if strictly better" presumes one proposal; an arm running two names no
coherent change, and a sweep could be carried by whichever version drew the
easier pairs. That test runs *before* the inversion one — an arm that is not
internally coherent compares older than anything, so diagnosing inversion first
walked the reader through two problems to reach one.

Every "is this even an experiment?" test compares **canonical** versions, where
`1.2` and `1.2.0` are one release. Comparing the raw strings made them two, and
the gate returned ADOPT for a release scored against itself — the mirror of
adopting on zero evidence. Canonicalisation only strips trailing zero
components; it is deliberately *not* the numeric key used for the older/newer
test, which maps every non-numeric component to zero and would collapse
`2.0-alpha` and `2.0-beta` into one version.

## The pairs

Adjacent in the 2026-08-05 exact baseline, so both members of a pair started at a
comparable size. Within each pair, the wave assignment balances the secondary
axis — whether the repo already had a Detail Docs index — two indexed repos in
each arm.

| Pair | Wave A | | Wave B | | Apart |
|---:|---|---:|---|---:|---:|
| 1 | `usa-wa` | 52,953 | `cannabis.observer-wordpress` | 49,103 | 7% |
| 2 | `observo` | 28,110 | `cannobserv` | 25,949 | 8% |
| 3 | `replicator` | 14,633 | `watcher` | 19,715 | **29%** |
| 4 | `archiver` | 14,358 | `power-map` | 13,298 | 7% |
| 5 | `cli` | 6,013 | `address-validator` | 6,322 | 5% |
| 6 | `notifier` | 5,468 | `wslcb-licensing-tracker` | 5,331 | 3% |

Pair 3 is the weakest match in the roster. `watcher` has no size neighbour —
every other pair is within 8% — and a difference on pair 3 is partly a difference
in difficulty. Read it accordingly rather than dropping it. It is also the one
row where **wave A holds the smaller member**; every other row runs
larger-then-smaller, so the ordering looks like a transcription error and is
not.

Pairs 5 and 6 are expected to be **uninformative for effectiveness**, and it is
better to know that now than to discover it after the run. Pair 6 starts under
budget: there is no gap to close. Pair 5 starts within 6% of budget, so both arms
will close their gap completely and the metric saturates. Both pairs still carry
the safety gates.

**That leaves four informative pairs at best.** A clean sweep of four is p=0.062
under a one-sided sign test — suggestive, not significant. The gate says so in its
own output rather than letting a sweep read as proof. Twelve repos is the sample
that exists; the alternative is not a better experiment but no experiment.

## The metric

Effectiveness is **budget-gap closure**:

```
gap     = max(0, tokens - budget)
closure = (gap_before - gap_after) / gap_before
```

A fraction rather than a token count, because the cohort spans 5,331 to 52,953
and an absolute reduction would let `usa-wa` decide every verdict on its own.

Closure is **capped at 1.0**: a run that cuts far past the budget scores exactly
the same as one that lands on it. Over-cutting earns nothing, deliberately —
`tokens_live` rising while the always-paid cost halves was already recorded as a
[rejected metric](rejected-changes.md), and rewarding depth of cut here would
reintroduce the same pressure to delete rather than route.

The cap has a cost: when both arms reach budget, the metric has no room left to
express a difference. Such a pair is reported as **uninformative — saturated**,
not as a tie. Calling it a tie would make the adoption rule unsatisfiable for any
pair that starts close to budget, and "the metric cannot separate them" is a
different claim from "they are equal."

## The safety gates

Checked before any score, on the treatment arm's scored run:

| Gate | Trips when |
|---|---|
| `no_loss` | `prove-no-loss.sh` returned a **non-`ok`** verdict. An absent or `skipped` one does not trip the gate — it makes the run *unverified*, which the next section separates out |
| `links_dead` | the curated surface has broken links — the link's file does not exist |
| `links_dead_anchors` | a link's file resolves but its `#fragment` names no heading. The breakage a doc split makes: it moves headings out of a file while leaving the file in place, so `links_dead` stays `0`. `null` (a row predating the field) does not trip the gate |
| `docs_orphaned` | demotion left more orphans than it found |

`no_loss_warrants` is **not** a gate, deliberately. A warranted loss is a line
this run's own split — or a rename Phase 6.5 mandates — forced it to rewrite,
and rejecting a run for *reporting* that would recreate the choice the field
exists to remove: the rational response would be to stop recording it, and the
cohort would be back to two adopters resolving one state in opposite
directions. It rides the `no_loss` column as `ok+Nw` instead, so a run that
waved eight lines through and one that waved none stop reading identically. The
defences against a ballooning warrant file are the per-entry accountability in
`prove-no-loss.sh`'s own report and the **delta** across runs — the same two the
cohort settled on for `seams_acked`, and for the same reason: a count that can
only be zeroed by deleting legitimate entries invites exactly that deletion.

**Any tripped gate is an outright REJECT, whatever the token numbers say.** A
change that reduces tokens by losing content is the one failure this skill exists
to prevent, and no amount of closure buys it back. This is the composite the
issue asked for, expressed as a veto rather than a weighted sum: a weighted sum
lets a large enough token win pay for a small content loss, and there is no
exchange rate at which that trade is acceptable.

Three asymmetries are deliberate:

- **Missing data is never a pass.** A run with no `no_loss` field is unscorable,
  not ok. `record-telemetry.sh --no-loss` is what puts the verdict on the row, and
  a run that skipped Phase 6 should not be able to clear a Phase 6 gate by
  silence.
- **A missing verdict is not a failure.** Both block adoption, but only a
  *recorded* non-`ok` verdict is evidence that anything went wrong. An absent or
  `skipped` one yields **INCONCLUSIVE**, not REJECT: nothing was refuted, the
  experiment was run without its safety check, and filing that in
  `rejected-changes.md` would record the idea as tested and beaten when it was
  neither. Fix the run and re-score.
- **A control-arm failure is reported, not fatal.** That is the *current* version
  failing — a finding about today, and worth acting on, but not a reason to refuse
  tomorrow's proposal. A missing verdict there is reported separately again,
  because calling it a failure reads as the shipped skill having dropped content
  when in fact nobody ran the check.

### Why `no_loss` comes from a script and not a grep

Phase 6 originally said "grep a distinctive phrase from each moved block". On
this skill's first real run that check **passed over a genuine defect**: a line
had been moved *and* recombined into a longer sentence, so the phrase was present
and the line was not. One line out of 226, invisible in the diff, and exactly the
paraphrase-in-transit Phase 5 forbids. A dropped line is the one failure mode of
this skill that a token count cannot detect — the count looks *better* for it,
which is why the verdict is a gate rather than a metric.

### Warranted losses are not the same claim as no loss

Whole-line matching is what makes this check strong, and it is also what makes a
*justified* rewrite indistinguishable from a drop. `.skills/context-loss-ok`
carries one judged entry per such line — `WARRANT :: CONTENT`, the warrant from
a closed set — and `prove-no-loss.sh` then exits `0` with `loss_warranted: N`,
which Phase 7 records. Two of the warrants are for edits this skill *requires*:
a pointer whose target this same change moved, and a heading rename Phase 6.5
compels because an issue number must not survive into a permanent anchor slug.
Ordering avoids the first — "split before demoting, never after" — and nothing
avoids the second, which is why the answer had to be a warrant rather than a
discipline.

## The adoption rule

**Adopt only if the treatment wins every informative pair.** Ties, mixed results,
and "no measurable difference" are all rejections.

A majority rule would be a rule for adopting noise at this sample size. With four
informative pairs, three-of-four happens 31% of the time by chance alone. The
sweep requirement is the only threshold that carries any evidential weight here,
and even it lands at p=0.062.

`--min-pairs` (default 3, **minimum 1**) is the floor below which the verdict is
INCONCLUSIVE rather than a rejection. Read it against the four-informative-pair
ceiling above and it says something concrete about how much slack the roster
has: **the experiment tolerates exactly one pair dropping out.** A second repo
with no ledger, an untagged run, or a method change anywhere in pairs 1–4 takes
the round below the floor and there is no verdict to be had. That is the number
to weigh when deciding how tightly to sequence the adoption issues.

Zero is refused rather than clamped: a
verdict computed over no pairs is not a weaker verdict but no verdict, and the
sweep test reads `0 == 0` as a win — it adopted on no evidence whatever until
the branch was guarded on `informative` being non-empty as well.

### A rejection has its own floor

`--min-pairs` governs **adoption**. A failed sweep needs at least **three**
informative pairs to be recorded as a REJECT, and `--min-pairs` cannot lower
that; below it the verdict is INCONCLUSIVE, which still blocks adoption and
still leaves `rejected-changes.md` alone.

The two are not symmetric outputs. An adoption is a decision to ship that gets
revisited the next time the skill changes. A rejection is written into
`rejected-changes.md` permanently, by design, and shapes every later proposal —
which is the whole value of that file and exactly why filling it with artefacts
is expensive. Experiment 1 came within one flag of it: at `--min-pairs 2` the
gate would have reached a 1–1 split and written REJECT against v1.3 on the
strength of two repos, both of them the honest-shortfall cases and one of them
the pair the roster itself flags as its weakest match at 29% apart
([#117](https://github.com/gregoryfoster/skills/issues/117)).

The **safety veto is exempt.** A single repo that dropped content rejects on its
own, with no pairs at all — content lost under the proposed version is lost
whether or not that repo had a partner, which is also why the arm listing is
deliberately wider than the pairing.

INCONCLUSIVE is **not** a rejection and does not belong in
`rejected-changes.md`: nothing has been decided, and the proposal is still
pending evidence. Recording it as a rejection would poison the buffer with
non-results and teach a later reader that the idea was tested and failed.

## What this gate cannot do

- **It cannot measure quality of judgement.** Closure sees where the tokens went,
  not whether the right sections were classified A versus B. A change that
  demotes the wrong things but hits the number will pass. The gates catch loss,
  not misjudgement.
- **It sees only what the row carries.** The first field report (#101) proved the
  point: ten review findings, all created by an otherwise clean run, all
  invisible to `tokens`, `links_dead`, `docs_orphaned` and `no_loss`. The
  `seams` field exists so that class is measurable — but wave A's rows predate
  it, so the first experiment had no symmetric comparison available: its control
  datapoint is `observo` re-measured at v1.3 (41 seams on a surface v1.2 had
  declared finished), not a wave-A row. A proposal aimed at a defect class the row
  cannot see yet should add its measurement first, as v1.3 did — and note that
  doing so buys measurability for *later* rounds, not for its own experiment.
- **It cannot run more than once per proposal.** Each repo has one first
  curation. After both waves have adopted, the split still works for steady-state
  weekly runs, but the effect sizes are far smaller and the metric shifts from
  "how much of the gap did it close" to "did it stay under budget without loss."
- **It cannot gate itself.** The change that introduced this gate — v1.2 — is the
  last one that shipped unvalidated, because at the time it shipped no cohort
  repo had adopted anything. That is a genuine hole and not a rhetorical one; the
  honest mitigation is that that change added scripts and a reference rather than
  altering the keep/cut rubric that decides what gets moved. **v1.3 was the first
  proposal the gate judged** — see the record below.

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

## Not in scope

Automated adoption. The research is consistent that a human approves structural
changes. This produces the evidence; it does not act on it.
