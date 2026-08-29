# The Self-Curation Pass

Every learning folded into this skill has been **additive** — six from the first
live run, five review rounds' worth before that, and nothing removed. That is
the documented failure mode of accumulating skill knowledge:
[Library Drift](https://arxiv.org/html/2605.19576v1) calls it "the frozen-weight
counterpart to catastrophic forgetting", and
[SkillOps](https://arxiv.org/html/2605.13716v1) frames the answer as
library-time maintenance. Per-run learnings are additive by nature;
[SkillOpt](https://arxiv.org/abs/2605.23904) — a third system, not a typo for
SkillOps — supplies the counterweight: "an epoch-wise slow/meta update
consolidates longer-horizon lessons that single batches cannot reveal." This
document is that slower clock for this skill
([#96](https://github.com/gregoryfoster/skills/issues/96)).

## What the pass is

Phases 1–7 of [SKILL.md](../SKILL.md), unchanged, with one substitution: the
policy file is `skills/curating-context/SKILL.md` and the docs tree is
`skills/curating-context/references/`. The tooling takes this without
modification — `tests/structural/test_skill_self_budget.py` already measures
every skill surface with the same flags, so the measurement dependency #96
recorded as open is satisfied in fact:

```bash
# Phase 1 — measure. The budget is the 7,600 ratchet, not the repo's 6,000 knob.
# --no-write is load-bearing: without it an --exact run refits
# .skills/context-token-ratio to the surface it measured — here this skill's
# files, not the repo's policy surface — re-baselining every skill's estimate
# (the #230 incident). Calibration writes belong to the weekly cadence alone.
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact --no-write --budget 7600 \
  --file skills/curating-context/SKILL.md \
  --docs-dir skills/curating-context/references \
  | tee /tmp/self-baseline.json \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" --baseline

# Phase 2 — verify facts. --also each live reference doc.
bash "<SKILL_SCRIPTS>/verify-facts.sh" --issues \
  --file skills/curating-context/SKILL.md \
  --also skills/curating-context/references/telemetry.md   # ... and the rest

# Phase 6 — prove no loss, the same flags the self-budget gate already uses.
# --claims is not optional here: this pass is demote/tighten only, so every
# round produces class-C rewrites, and `tighten` is refused without it.
bash "<SKILL_SCRIPTS>/prove-no-loss.sh" --base <branch-point> --claims \
  --file skills/curating-context/SKILL.md \
  --docs-dir skills/curating-context/references
```

Phase 4 plans to the ratchet, and its escape clause applies unchanged: an
irreducible file is reported, never forced. Phase 3's classes read as #96
sharpened them — prose written to justify a decision that has since become
uncontroversial is class C; a worked example a newer worked example supersedes
is class-D-shaped — but see the eviction rule below for what class D becomes
here.

Two Phase 2 specifics, learned by running it on this surface:

- **Known FALSE rows to adjudicate, not fix.** SKILL.md's Phase 5 explains link
  re-aiming with literal examples — `](tests/x.py)`, `](../tests/x.py)`,
  `](docs/X.md)`, `](X.md)` — and `verify-facts.sh` extracts them and reports
  FALSE. They are illustrations: the rationalization table's "the path doesn't
  exist, so the claim is stale" row, live on the skill's own file.
- **The script cannot see stale numbers in prose.** #96 credits
  `verify-facts.sh` with catching the two reference docs that kept claiming a
  measured 8,376 tokens after the curation landed. It would not have: a token
  figure matches none of its claim classes (path, link, command, unit, issue).
  That catch is Phase 2's manual half
  ([fact-verification.md](fact-verification.md)) — re-check every count and
  token figure the surface quotes against the fresh Phase 1 measurement. This
  surface quotes many, and they rot fastest.

## Cadence: quarterly

Quarterly, not every-Nth-run. Runs in this repo are event-driven — review
rounds, orchestration batches — so "every Nth run" has no stable clock, and the
drift the pass counters is time-shaped: claims rot whether or not runs happen.

The pass is **due when the newest curation row for
`skills/curating-context/SKILL.md`** in `.skills/context-metrics.jsonl` (actions
not purely `baseline*` — any real curation of this surface resets the clock)
**is more than 92 days old**; before the first such row, 92 days from the
mechanism's adoption (2026-08-27). `tests/structural/test_self_curation.py`
carries that epoch and **warns, never fails**, when the pass is overdue — the
budget blind-spot's shape (#217): time passing must not redden an unrelated
commit.

## The eviction rule: demote and tighten only

**Self-curation never deletes.** Decided on #96 (2026-08-27), taking the body's
own lean:

- A class D finding becomes a **demotion**: a superseded rationale, a worked
  example replaced by a newer one, prose defending a now-uncontroversial
  decision — each moves into `references/` (a refuted proposal to
  [rejected-changes.md](rejected-changes.md)) rather than vanishing.
- The Iron Law and the three warrants stay **unchanged**. No fourth warrant:
  "this learning no longer earns its tokens" is a judgement the pass makes
  about its own instructions, unfalsifiable from inside the pass — and a
  demotion is reversible and visible to `prove-no-loss.sh`, where a deletion is
  neither.
- Pinned executably: `test_self_curation.py` refuses a `self:curation` ledger
  row that carries any `delete:*` tag.

## Recording the pass

Two rows, like any run ([telemetry.md](telemetry.md)): Phase 1's `--baseline`,
then the Phase 7 curation row whose `--actions` list **leads with
`self:curation`**, followed by the normal `verb:target` tags. The `file` field
already separates the pass from a repo curation, but pass-kind is contract, not
inference from a path.

No cohort reader sees these rows: this repo is not in `.skills/cohort` (the
roster is the twelve CannObserv members), so `score-cohort.sh` and
`cohort-report.sh` never read this ledger, and the "one policy file per repo,
most rows" rule cannot be tipped by them. Within this repo, trend readers group
by file.

## What "gated by #94" means now

#96's body closes with "should be gated by #94 like any other change to the
skill." Verified against the tree on 2026-08-27, that sentence is stale as
written:

- **What shipped**: #94/#98 built the pairwise validation gate —
  `score-cohort.sh`, pre-registration under `.skills/experiments/`,
  adopt-only-if-strictly-better ([validation-gate.md](validation-gate.md)).
- **What retired**: #168 ended the wave A/B assignment the sentence assumed.
  The `.skills/cohort` header records it — `wave:`/`pair:` are rollout order,
  never an assignment in force, and the arm a run belongs to is the
  `skill_version` on its own row. There is no held-back wave for a
  self-curation pass to be staged against.

What gating means for this pass, wired to what exists:

- A pass that edits SKILL.md plausibly alters what a run does, so it **bumps
  the frontmatter `version`** (Phase 7's rule). The bump is what makes the
  pass's effect observable as an arm.
- An edit refuted mid-pass goes to [rejected-changes.md](rejected-changes.md) —
  unchanged.
- When a verdict on the pass's effect is wanted, **pre-register**
  (`.skills/experiments/NN-<slug>.yml`) and score with
  `score-cohort.sh --experiment NN`, like any skill change since #194.
- What the gate cannot do: score the pass's **own** token delta. It scores
  cohort curations, and the rows this pass writes are for a file no scorer
  reads. The before/after pair in this repo's ledger is the pass's own
  evidence, and the safety half — `no_loss`, `seams` — travels on the row like
  any other.
