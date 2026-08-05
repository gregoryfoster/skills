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

## Staging, and which arm is which

Wave A adopts now. Wave B is held. When a change to the skill is proposed, wave B
adopts *on the proposed version* while wave A keeps running the version before it.

**Wave A therefore holds the older version, and the first experiment runs
`--treatment b --control a`.** The script's defaults (`--treatment a`) suit later
rounds, once A is the arm carrying a proposal. Getting the direction backwards
turns a winning change into a losing one, which is why the flags are explicit
rather than inferred from version strings — `1.10` sorts below `1.9`.

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
in difficulty. Read it accordingly rather than dropping it.

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
| `no_loss` | `prove-no-loss.sh` did not return `ok` |
| `links_dead` | the curated surface has broken links |
| `docs_orphaned` | demotion left more orphans than it found |

**Any tripped gate is an outright REJECT, whatever the token numbers say.** A
change that reduces tokens by losing content is the one failure this skill exists
to prevent, and no amount of closure buys it back. This is the composite the
issue asked for, expressed as a veto rather than a weighted sum: a weighted sum
lets a large enough token win pay for a small content loss, and there is no
exchange rate at which that trade is acceptable.

Two asymmetries are deliberate:

- **Missing data is never a pass.** A run with no `no_loss` field is unscorable,
  not ok. `record-telemetry.sh --no-loss` is what puts the verdict on the row, and
  a run that skipped Phase 6 should not be able to clear a Phase 6 gate by
  silence.
- **A control-arm failure is reported, not fatal.** That is the *current* version
  failing — a finding about today, and worth acting on, but not a reason to refuse
  tomorrow's proposal.

## The adoption rule

**Adopt only if the treatment wins every informative pair.** Ties, mixed results,
and "no measurable difference" are all rejections.

A majority rule would be a rule for adopting noise at this sample size. With four
informative pairs, three-of-four happens 31% of the time by chance alone. The
sweep requirement is the only threshold that carries any evidential weight here,
and even it lands at p=0.062.

`--min-pairs` (default 3) is the floor below which the verdict is INCONCLUSIVE
rather than a rejection. INCONCLUSIVE is **not** a rejection and does not belong
in `rejected-changes.md`: nothing has been decided, and the proposal is still
pending evidence. Recording it as a rejection would poison the buffer with
non-results and teach a later reader that the idea was tested and failed.

## What this gate cannot do

- **It cannot measure quality of judgement.** Closure sees where the tokens went,
  not whether the right sections were classified A versus B. A change that
  demotes the wrong things but hits the number will pass. The gates catch loss,
  not misjudgement.
- **It cannot run more than once per proposal.** Each repo has one first
  curation. After both waves have adopted, the split still works for steady-state
  weekly runs, but the effect sizes are far smaller and the metric shifts from
  "how much of the gap did it close" to "did it stay under budget without loss."
- **It cannot gate itself.** The change that introduced this gate — v1.2 — is the
  last one that ships unvalidated, because at the time it shipped no cohort repo
  had adopted anything. That is a genuine hole and not a rhetorical one; the
  honest mitigation is that this change adds scripts and a reference rather than
  altering the keep/cut rubric that decides what gets moved.

## Not in scope

Automated adoption. The research is consistent that a human approves structural
changes. This produces the evidence; it does not act on it.
