---
name: auditing-ci-cost
description: Audits a repository's GitHub Actions spend by measuring its cost shape before prescribing anything — a per-job billed-minute census computed from job timestamps, platform-incident days separated from the structural baseline, then a prescription that branches on whether the spend is job COUNT or job DURATION, since the levers for one are actively wrong for the other. Produces numbered severity-tiered findings each carrying a measured-or-estimated confidence label, a path-filter replay gated on zero false skips, and a required non-levers section, then hands the accepted filter to enforcing-architecture. Use when the user says "audit CI", "CI cost", "Actions spend", "optimize CI", or "why is CI so expensive".
compatibility: Designed for Claude. Requires gh (authenticated) and jq. Stack-agnostic — the billing model and every trap are GitHub behaviours, not language ones.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: audit CI, CI cost, Actions spend, optimize CI, why is CI so expensive, CI billing
---

# Auditing CI Cost — measure the shape, then prescribe

Two audits three weeks apart, in different stacks, reached **opposite**
conclusions from the same procedure. Re-measured with this skill's own script
over the same 30 days:

| | WordPress repo | Python repo |
|---|---|---|
| mean billed/job | **1.85** | **1.01** |
| jobs under 60s | 40% | 99% |
| biggest line item | a job running **128s** | a job running **7s** |
| cost shape | **duration** | **job-count** |

The second repo's largest expense was a job doing seven seconds of work,
billing a full minute, 146 times. No amount of speeding it up recovers
anything. The first repo's largest expense genuinely *ran* for over two
minutes, where caching and narrowing are real money.

**Either repo's playbook applied to the other would have been wrong.** That is
why this is a skill and not a checklist: Phase 1 measures the shape and Phase 2
forks the prescription on it.

## The Iron Law

```
NO PRESCRIPTION WITHOUT A MEASURED COST SHAPE
NO BASELINE QUOTED BEFORE ANOMALY DAYS ARE SEPARATED
```

## The billing model

```
cost = Σ over jobs of max(1, ceil(job_seconds / 60))
```

Per **job**, rounded **up**, with a **one-minute floor**. The floor is the
whole game: it makes a 3-second job and a 55-second job cost the same, and it
makes an extra job strictly more expensive than a slower one.

**Do not implement that line as written.** Taken literally it bills a phantom
minute for three classes of row the formula was never meant to see — skipped
jobs, non-positive durations, and jobs still in flight. That is the form
[#212](https://github.com/gregoryfoster/skills/issues/212) carried, and it
survived two completed audits before anyone checked. Phase 1 names all three.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "The Actions usage page will tell me" | Account-level totals only — no per-job, per-workflow or per-day breakdown. It says the bill is 600 minutes and nothing about which job to delete. |
| "`/timing` gives billable ms" | Its `total_ms` reads **0** on every repo probed here, public and private, against runs of 35–99s. The per-job `job_runs[]` array exists and is zeroed too. Building on it reports zero spend and no error. |
| "The docs say the glob won't match" | Both audits were burned this way. Where the docs and a **probe** disagree, the probe wins — and its result gets recorded next to the rule, or the next reviewer "corrects" it back. |
| "I'll split this workflow to skip work" | Only in a `duration` repo. In a `job-count` repo a split **adds** a billed minute per new job and saves nothing. |
| "I'll merge these jobs to cut the count" | Only in a `job-count` repo. Elsewhere it serialises parallel work for at most one floor-minute. |
| "550 minutes last month" | Not until anomaly days are out. One platform incident was 33% of a real repo's raw total — and worse, it moved the p99 to 902s and made a count problem look like a duration one. |
| "The filter obviously only matches docs" | Replay it. A README can be a build input; so can the root `.gitignore`. Zero false skips or it does not ship. |

## Script path resolution

Resolve once, then substitute the printed path wherever `<SKILL_SCRIPTS>` appears:

```bash
N=auditing-ci-cost S=measure-ci-cost.sh SD=

for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done

echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
```

## Procedure

### Phase 1 — Measure the cost shape

```bash
bash "<SKILL_SCRIPTS>/measure-ci-cost.sh" --repo <owner/name> --days 30 --cache /tmp/ci-cost.ndjson
```

One API call per run (200+ on a busy repo, a couple of minutes); `--cache`
makes every re-classification free. The census computes billed minutes from
`started_at`/`completed_at`, because no endpoint returns them.

Three corrections it embeds, each verified by probe and each wrong or missing
in the originating issue — re-derive a census by hand and you reintroduce them,
silently, because every one of them still produces a plausible number:

- **`filter=all` on the jobs endpoint.** The default `filter=latest` hides
  every re-run attempt but the last, and each attempt was billed in full.
- **`conclusion: skipped` is excluded.** A skipped job carries a zero or
  **negative** duration, so `max(1, ceil(...))` bills it a phantom minute that
  is indistinguishable from a real one.
- **`created=>=DATE` on the runs listing**, or `--paginate` walks the entire
  retention window.

Full evidence, and the two repos' worked numbers:
[references/measurement.md](references/measurement.md).

**The anomaly gate.** The script flags a day only when it is *both* unusually
large *and* structurally unlike the others (billed total **and** billed
min/job above the median by the factor). Total alone flags a merely busy day —
measured: 3.1× the median day at an entirely normal 1.05 min/job — and
subtracting that understates the very spend you are hunting. Confirm each
flagged day against the GitHub status history. **Quote the structural baseline;
report the raw total beside it, never instead of it.**

Percentiles obey the same rule. One incident day moved a real repo's p99 from
47s to 902s; a p99 of 902 printed under the word "structural" is the same
error as the raw total, one level down, and harder to notice.

### Phase 2 — Classify: job-count or duration

Read `mean billed/job` from the census.

| mean billed/job | shape | prescribe | never |
|---|---|---|---|
| ≤ 1.10 | **job-count** | delete jobs, merge jobs, cut trigger frequency | **never split** a workflow — every new job pays the floor |
| ≥ 1.40 | **duration** | cache, narrow, split; hunt jobs just over a minute boundary | don't merge — it buys one floor-minute and costs parallelism |
| between | **mixed** | classify row by row in `by_job`: rows with `median_seconds < 60` are job-count, the rest duration | — |

State the shape and the number **before** writing a single finding. Every
saving downstream is computed against this branch.

### Phase 3 — Attribute

From the census: `by_job`, `by_workflow`, `by_event`. Then ask what each run
*validated* — re-push frequency, duplicate coverage across workflows, jobs
whose only output is a status check nothing reads.

### Phase 4 — Findings

Numbered, severity-tiered, and each carrying:

- the **measured saving** in billed min/mo, computed on the Phase 2 branch;
- a **confidence label — `measured` or `estimated`.** Both audits' biggest wins
  came from converting an estimate into a measurement, and a report that does
  not distinguish them loses exactly that.

Then the `reviewing-code` loop: present findings, wait for terse directives
(`fix` / `stet` / `GH`), implement only what was accepted.

### Phase 5 — Probe

Anything the docs do not settle gets a probe, from a branch that carries the
change. Two mandatory ones:

- **Replay every path filter against history.** Report skips and **false
  skips**; **zero false skips** is a hard gate. Enumerate build inputs by
  *building and inspecting the artifact*, not by intuition — a `readme =` entry
  makes a README a build input, and the root `.gitignore` was proved to drop a
  module from an sdist. [references/path-filter-replay.md](references/path-filter-replay.md).
- **Probe any behaviour a finding depends on.** The eight that already bit —
  `paths-ignore` seeing the whole PR diff, `workflow_call` inheriting the
  caller's context and silently disabling a release gate, `**/` matching zero
  directories, `>-` embedding a newline inside `${{ }}` —
  [references/traps.md](references/traps.md). Record each probe's result
  **inline next to the rule**, not only in the PR that produced it.

### Phase 6 — Non-levers

**Required output.** Everything considered and rejected, each with its reason,
its evidence, and the cost shape it was rejected under — the same lever is
often live in the other shape. Without this section the next audit re-derives
the same dead ends. Catalogue and row format:
[references/non-levers.md](references/non-levers.md).

### Phase 7 — Graduate

Hand every accepted filter or invariant to
[`enforcing-architecture`](../enforcing-architecture/SKILL.md), which turns it
into an executable contract. A path filter that nothing tests drifts the first
time a build input moves; the reference implementation asserts that duplicated
`paths-ignore` blocks stay identical and that no build input matches any
pattern, with the inputs discovered from disk.

## Report

```
Repo · window · raw total · anomaly days (attributed) · structural baseline
Cost shape: <shape> at <mean> billed min/job (p50/p90 <s>/<s>)
Findings:   N numbered, each with severity, saving, and measured|estimated
Non-levers: M rejected, each with reason
Graduated:  <contract> via enforcing-architecture
```

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it. The skill's own invariants are pinned
by `tests/structural/test_ci_cost_shape.py`.
