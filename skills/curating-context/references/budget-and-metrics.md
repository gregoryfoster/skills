# Budget and Metrics

Why the budget is denominated in tokens, what the numbers mean, and the telemetry
schema that makes cross-cohort learning possible.

## Why tokens, not lines

A line cap is the intuitive budget and the wrong one. Measured across the cohort:

- `wslcb-licensing-tracker` — 205 lines, **3,245 tokens**
- `cannabis.observer-wordpress` — 332 lines, **29,183 tokens**

Both are in the same neighbourhood by lines. One costs 9× the other on every
invocation. The difference is line length: the cohort's average bytes-per-line
ranges from 63 (`notifier`, `wslcb`) to 351 (`cannabis.observer-wordpress`).
Markdown does not care where you wrap, so a line cap is trivially satisfiable by
writing longer paragraphs — which is exactly the failure mode it was meant to
prevent.

Lines remain a useful *secondary* signal, because a file that is over budget on
tokens but short on lines is telling you the sections are dense prose (a class C
tighten), whereas one long on both is telling you there are too many sections (a
class B demotion). Read them together; gate on tokens.

## Budgets

| Surface | Default | Rationale |
|---|---:|---|
| Policy file | **4,000 tokens** | Four of twelve cohort repos already sit under it with genuinely useful files, which makes it demonstrably achievable rather than aspirational. Published guidance converges on splitting a monolithic context file at roughly 150–200 lines of ordinary prose — the same order of magnitude. |
| Reference doc | **10,000 tokens** | The point of demotion is that loading the doc costs less than carrying it inline everywhere. Past ~10k that stops being true; split on top-level headings. |
| Live surface | reported, not gated | `totals.tokens_live` is the ceiling on what one session can pull in. Gating it would penalise a repo for having thorough, well-routed docs — which is the goal. Track the trend instead. |

Override per repo with `--budget` / `--doc-budget`, or inline via the trigger
phrase (`context budget 6000`). A repo with a genuinely irreducible policy file
should raise its budget explicitly and record why, rather than failing the gate
every week — a permanently-red gate is a gate everyone learns to ignore.

## Measuring tokens

`measure-context.sh --exact` calls `POST /v1/messages/count_tokens`. That endpoint
is the only accurate tokenizer for Claude models, and counts are model-specific —
`--model` defaults to `claude-opus-5`. Pin one model across the cohort; the
tokenizer introduced with Opus 4.7 produces ~30% more tokens for the same text
than earlier ones, so a mixed-model ledger is as incomparable as a mixed-method one.

**Counting is free.** The endpoint consumes no tokens and is billed nothing; it is
rate-limited per usage tier (2,000–8,000 RPM), with limits independent of message
creation. So `--exact` has no cost argument against it — run it always. What it
does need is a credential, and an unset `ANTHROPIC_API_KEY` does not mean there
isn't one: the script falls back to an `ant auth login` profile, sending the
short-lived token as `Authorization: Bearer` with the `oauth-2025-04-20` beta
header (OAuth tokens are rejected on `x-api-key`). A zero credit balance blocks
the whole API including free endpoints, which surfaces as a 400 whose body names
the reason — the script prints that body rather than just the status line.

**Never use `tiktoken`.** It is OpenAI's tokenizer; it undercounts Claude text by
15–20% and by considerably more on code and non-English input. There is no
accurate offline tokenizer for current Claude models, which is why `bytes/4`
remains the documented fallback rather than a local library.

Without any credential the script falls back to `bytes/4` and sets
`policy.tokens_exact: false`. The estimate is fine for ranking sections against
each other within one run — the error is roughly uniform across a single file —
but it is **not** comparable to an exact count. `record-telemetry.sh` warns when a
`delta_tokens` spans a change in `tokens_exact`, because a 15% tokenizer artefact
reads exactly like a real 15% reduction. Keep a repo's ledger on one method.

## Telemetry

One append-only JSONL row per run at `.skills/context-metrics.jsonl`, committed
alongside the file it measures. Committed, rather than kept in a central store,
for three reasons: the row travels with the repo through a transfer, it is
reviewable in the same PR as the edits it describes, and a run needs no write
access to any other repo.

### Row schema

| Field | Meaning |
|---|---|
| `ts` | UTC date, `YYYY-MM-DD`. Pinned to UTC so rows from different machines sort consistently. |
| `repo`, `file` | repo basename and policy-file path |
| `tokens`, `lines`, `bytes` | policy-file size |
| `tokens_exact` | `true` when counted via `count_tokens`; gates delta comparability |
| `budget`, `over_budget` | the budget in force this run, and whether it was met |
| `tokens_live` | policy + reachable live reference docs |
| `docs_total`, `docs_orphaned` | live doc count, and how many nothing links |
| `links_dead` | broken relative links in the curated surface |
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
- `baseline` — a measurement-only run with no edits

`"cleanup"` and `"misc"` are worse than no tag: they occupy the slot that would
otherwise have said something.

### Reading the trend

`record-telemetry.sh --print-trend` prints the last eight runs with per-run
deltas and net change. Three shapes to recognise:

- **Sawtooth** — reductions followed by regrowth. The file is not the problem;
  whatever keeps appending to it is. Look for a skill or hook that writes to
  `AGENTS.md`, and give it a reference doc to write to instead.
- **Step then flat** — one large demotion, then nothing. Healthy. Subsequent runs
  should be cheap `baseline` rows.
- **Slow creep with no negative deltas** — nobody is running Phase 5, or every
  run is finding the budget already met and stopping. Check whether the budget is
  set high enough to never bind.

## Cohort roll-up

`cohort-report.sh` reads every member's ledger over `gh api` — no clone — and
prints current tokens, net change, run count, orphan and dead-link counts, and
**the action tags that accompanied each repo's largest single reduction**. That
last column is the cross-repo learning: after a few weeks it names which
optimisation actually pays, and the same one usually pays everywhere.

Roster in `.skills/cohort`, one `owner/repo` slug or local path per line; `#`
comments allowed. Repos with no ledger are reported rather than skipped — on a
weekly cadence, missing telemetry is the finding.

One caveat worth designing around: `gh api` prints nothing **and** exits non-zero
on a 404, so a naive empty-output test reads a missing ledger as an empty one.
The script greps the error body for `404` before deciding, and reports anything
else as `unreadable` rather than silently as absent.
