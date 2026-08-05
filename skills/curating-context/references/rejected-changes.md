# Rejected Changes

Things this skill tried and gave up, with what refuted them.

A rejected change is **negative feedback, not garbage**. Without a record of it,
the same plausible idea gets re-proposed every few runs and re-litigated from
scratch — and the second proposer has no way to know it was already tested. This
file is the skill's own version of the discipline it imposes on `AGENTS.md`: a
claim removed needs a named warrant, and the warrant is worth keeping.

## What belongs here

An entry needs three things, and an entry missing any of them is not yet a
rejection — it is an opinion:

1. **The change as it was actually proposed**, specifically enough to recognise if
   someone proposes it again.
2. **What refuted it** — a measurement, a command and its output, or a
   demonstration. "It felt wrong" is not a refutation and does not belong here.
3. **What replaced it**, so the entry reads as a decision rather than a dead end.

Entries are not deleted when they age. A rejection that turns out to have been
wrong gets a **Reopened** note appended with the new evidence; the original stays,
because the fact that it was once refuted is itself information.

---

## A 4,000-token policy-file budget

**Proposed:** 4,000 tokens, justified in `budget-and-metrics.md` on the grounds
that "four of twelve cohort repos already sit under it" — a budget most of the
cohort could reach.

**Refuted by:** measuring all twelve with `count_tokens` instead of the offline
estimate. **Zero** of twelve were under 4,000. The leanest was
`wslcb-licensing-tracker` at 5,331 and the heaviest `usa-wa` at 52,953. The whole
justification was an artefact of the `bytes/4` heuristic, which under-reports this
cohort's markdown by 56–65%.

**Replaced by:** 6,000, chosen against exact counts and against a stated
reachability criterion — two repos already under it, two more within 6% by routing
`docs/` trees that already exist. Recorded as *retracted* in
`budget-and-metrics.md` rather than quietly overwritten, because the reasoning
error is more instructive than the number.

**Generalisable lesson:** a budget derived from an estimator is a claim about the
estimator. Calibrate first, then set the threshold.

## "Grep a distinctive phrase" as the no-loss check

**Proposed:** Phase 6 originally verified relocation by grepping a distinctive
phrase from each moved block, on the theory that a phrase present at the
destination proves the block arrived.

**Refuted by:** running it against a real defect from the skill's first live run.
A line had been moved *and* recombined into a longer sentence, so the phrase was
present and the line was not:

```
Phase 6 as written — grep a distinctive phrase:   PASS  <- the defect survives
Full-line check:                                  FAIL  <- the defect is caught
```

One line out of 226, invisible in the diff, and exactly the paraphrase-in-transit
Phase 5 forbids.

**Replaced by:** `prove-no-loss.sh`, which asserts every non-blank line survives
verbatim. The test that pins this is deliberately written to fail if a phrase grep
ever becomes sufficient — at which point Phase 6 should be simplified rather than
carrying dead complexity.

**Generalisable lesson:** a check that can pass for the wrong reason will
eventually be relied on for the wrong reason. Test the check against a known
defect before trusting it.

## Substring matching inside the no-loss check

**Proposed:** the first implementation of `prove-no-loss.sh` tested
`line in destination_text` — substring containment against the whole file.

**Refuted by:** a five-line deletion where the dropped lines appeared only as
fragments of unrelated prose elsewhere. **Four of five** were reported as
"relocated verbatim": `1. Commit and push` matched inside "Step 9: 1. Commit and
push when ready.", and a bare ``` matched almost anything. Short and common lines
were effectively unchecked, and a policy file is mostly those.

**Replaced by:** a set of whole normalised lines per destination. The real curation
still passes at 226 lines and 0 unaccounted, so the stricter rule cost nothing in
false positives.

**Generalisable lesson:** the replacement for a check that was too weak can also
be too weak. The second version needed its own adversarial test, not just a
passing run on known-good input.

## `tokens_live` as the telemetry trend metric

**Proposed:** SKILL.md instructed that `totals.tokens_live` — the policy file plus
every reachable live doc — "is the number the telemetry trend follows."

**Refuted by:** the first real curation. `tokens_live` rose 8,462 → 9,862 while
the always-paid cost halved, because the Detail Docs index and three new file
headers are real bytes. Followed literally, every successful run in the cohort
would read as a regression, and a run optimising it would be pushed toward
*deleting* content rather than routing it — the opposite of the Iron Law.

**Replaced by:** the trend follows `policy.tokens`. `tokens_live` is watched as a
ceiling, for a doc tree growing without being read.

**Generalisable lesson:** check that the metric moves the right way on a known-good
outcome before making it the target.

## `ant auth` as the second credential source

**Proposed:** when `ANTHROPIC_API_KEY` is unset, fall back to an `ant auth login`
profile before looking anywhere else — on the reasonable theory that an
authenticated CLI means an authenticated user.

**Refuted by:** `count_tokens` rejecting the token outright:

```
HTTP 401: {"type":"error","error":{"type":"authentication_error",
"message":"jwt auth is not yet supported on count_tokens"}}
```

Worse than useless: the credential was *accepted* locally, so `EXACT_OK` was set,
every per-file count silently fell back to the estimate, and the run still reported
`tokens_exact: true`. On a machine with the `ant` CLI installed the broken
credential also won ahead of a perfectly good key in `.env`.

**Replaced by:** the secrets-file source moved ahead of it, `tokens_exact` computed
from whether counts *succeeded* rather than whether a credential was *found*, and
the OAuth path kept last with its limitation announced.

**Generalisable lesson:** obtaining a credential is not the same as it working.
Gate on the operation succeeding, not on the precondition being satisfied.
