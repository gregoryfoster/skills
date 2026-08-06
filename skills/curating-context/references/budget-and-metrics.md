# Budget and Metrics

Why the budget is denominated in tokens, what the numbers mean, and the telemetry
schema that makes cross-cohort learning possible.

## Why tokens, not lines

A line cap is the intuitive budget and the wrong one. Measured exactly across the
cohort:

- `wslcb-licensing-tracker` — 205 lines, **5,331 tokens**
- `cannabis.observer-wordpress` — 332 lines, **49,103 tokens**

Both are in the same neighbourhood by lines. One costs **9.2×** the other on every
invocation. The difference is line length: the cohort's average bytes-per-line
ranges from 63 (`notifier`, `wslcb`) to 351 (`cannabis.observer-wordpress`).
Markdown does not care where you wrap, so a line cap is trivially satisfiable by
writing longer paragraphs — which is exactly the failure mode it was meant to
prevent. `watcher` and `usa-wa` settle it: 536 and 535 lines, 33,238 tokens apart.

Lines remain a useful *secondary* signal, because a file that is over budget on
tokens but short on lines is telling you the sections are dense prose (a class C
tighten), whereas one long on both is telling you there are too many sections (a
class B demotion). Read them together; gate on tokens.

## Budgets

| Surface | Default | Rationale |
|---|---:|---|
| Policy file | **6,000 tokens** | The initial cohort figure, chosen to be reachable — see below. Ratchets down. |
| Reference doc | **10,000 tokens** | The point of demotion is that loading the doc costs less than carrying it inline everywhere. Past ~10k that stops being true; split on top-level headings. |
| Live surface | reported, watched, never gated | `totals.tokens_live` is the ceiling on what one session can pull in. Gating it would penalise a repo for having thorough, well-routed docs — which is the goal. It *rises* on a successful demotion (this repo: 8,462 → 9,862 while the always-paid cost halved), so it is not the trend metric either — `policy.tokens` is. Watch `tokens_live` for a doc tree growing without being read. |

### Where 6,000 came from, and where it goes

An earlier version of this file justified a 4,000 budget by saying four of twelve
cohort repos already sat under it. **That was an artefact of a bad estimator** (see
the offline-estimate section below). Measured exactly, zero of twelve were under
4,000 — the leanest was `wslcb-licensing-tracker` at 5,331 and the heaviest
`usa-wa` at 52,953.

6,000 is the corrected starting figure, and it is chosen to be *reachable*:

- **Two repos are already under it** — `wslcb-licensing-tracker` (5,331) and
  `notifier` (5,468) — so the first green run is real rather than symbolic.
- **Two more are within 6%** — `cli` (6,013) and `address-validator` (6,322) — and
  both carry entirely unlinked `docs/` trees, so they get under by *routing what
  already exists*, not by writing anything new.
- ~200 lines of this cohort's prose lands at 5.3–6.0k tokens, so 6,000 is what the
  published "split at 150–200 lines" guidance actually means for this content.
- The remaining eight need structural work regardless of where the line sits.

**It ratchets.** 6,000 is the entry gate, not the destination. Once a repo is
comfortably under, lower that repo's `.skills/context-budget` — a budget that binds
is doing work, and one nobody can reach is just noise. The reason to start where
most repos can arrive is the same reason the budget must not become a CI fitness
function until the repo is under it: a permanently-red gate is one everybody learns
to ignore.

Against 6,000, the current standing is **10 of 12 over**:

| Over | Under |
|---|---|
| usa-wa 52,953 · wordpress 49,103 · observo 28,110 · cannobserv 25,949 · watcher 19,715 · replicator 14,633 · archiver 14,358 · power-map 13,298 · address-validator 6,322 · cli 6,013 | wslcb-licensing-tracker 5,331 · notifier 5,468 |

`gregoryfoster/skills` itself was at 8,462 and is now **4,273** — the first repo
under the budget by curation rather than by luck. The run is written up in
[cohort-patterns.md](cohort-patterns.md).

If a repo's file is genuinely irreducible, raise **that repo's** budget explicitly
and record why, rather than failing every week.

Override per repo with `--budget` / `--doc-budget`, or inline via the trigger
phrase (`context budget 6000`).

## Measuring tokens

`measure-context.sh --exact` calls `POST /v1/messages/count_tokens`. That endpoint
is the only accurate tokenizer for Claude models, and counts are model-specific —
`--model` defaults to `claude-opus-5`. Pin one model across the cohort; the
tokenizer introduced with Opus 4.7 produces ~30% more tokens for the same text
than earlier ones, so a mixed-model ledger is as incomparable as a mixed-method one.

**Counting is free.** The endpoint consumes no tokens and is billed nothing; it is
rate-limited per usage tier (2,000–8,000 RPM), with limits independent of message
creation. So `--exact` has no cost argument against it — run it always. A zero
credit balance blocks the whole API including free endpoints, which surfaces as a
400 whose body names the reason — the script prints that body rather than just the
status line.

### Credential order, and why it is not the obvious one

1. `ANTHROPIC_API_KEY` from the environment.
2. `ANTHROPIC_API_KEY` **parsed** out of a repo-root `.env` (then bare `env`, the
   cohort's pre-2026-08-05 name). Parsed rather than sourced: sourcing a secrets
   file executes whatever it contains, which is not a thing a measurement script
   should do to obtain a token count. `--no-env-file` declines this source;
   `--env-file NAMES` changes which files are searched.
3. An `ant auth login` profile, sent as `Authorization: Bearer` with the
   `oauth-2025-04-20` beta header (OAuth tokens are rejected on `x-api-key`).

**The OAuth path is last because it does not currently work here.** It
authenticates, and then `count_tokens` answers `401 "jwt auth is not yet supported
on count_tokens"`. It was originally tried second, which meant that on a machine
with the `ant` CLI installed the broken credential won and a perfectly good key in
`.env` was never reached. It is kept, last, in case the endpoint gains JWT support,
and it announces the limitation rather than looking like a working choice.

### `tokens_exact` describes the numbers, not the credential

A credential that is accepted and then rejected by the endpoint is the reason
`tokens_exact` is computed from whether counts *succeeded*, not from whether a
credential was *found*. Getting this wrong was worse than having no credential at
all: every per-file count fell back to the estimate, and the run reported
`tokens_exact: true` over numbers that were entirely estimates — so the ledger
accepted them as comparable with real counts and the whole single-method
discipline below became decorative.

Any fallback now marks the run, `tokens_exact` reports `false`, and a WARN says
so. The observed ratio is not persisted either: derived from an estimate it simply
re-derives the divisor it was computed with, producing exactly `2.70` — a
self-confirming fake measurement, comfortably inside the plausibility band, which
every later offline estimate in the repo would then trust.

**Never use `tiktoken`.** It is OpenAI's tokenizer; it undercounts Claude text by
15–20% and by considerably more on code and non-English input. There is no
accurate offline tokenizer for current Claude models, which is why a
bytes-per-token ratio remains the fallback rather than a local library.

### The offline estimate, and why it is not `bytes/4`

Without a credential the script estimates, sets `policy.tokens_exact: false`, and
divides bytes by a **calibrated ratio, not 4**.

`bytes/4` is the conventional heuristic and it is badly wrong for this content.
Measured against `count_tokens` across all twelve cohort policy files it
under-reported by **56% to 65%**; across a mixed sample of sixteen markdown files
(policy files, reference docs, READMEs) the real ratio sat between **2.40 and
2.69 bytes per token**. The heuristic is calibrated for flowing prose, and a policy
file is not that — it is dense with paths, flags, code fences, tables, and
identifiers, all of which tokenize far worse than English.

This mattered concretely rather than academically: with `bytes/4` and a 6,000
budget, the write guard would enforce an effective ceiling near 15,000 real tokens
and stay silent the whole way there.

Two mechanisms fix it:

- **Default 2.7 bytes/token**, from the measurement above.
- **Per-repo calibration.** Every `--exact` run writes the observed ratio to
  `.skills/context-token-ratio`, and the offline estimators (the write guard,
  `context-delta.sh`, and `measure-context.sh` without `--exact`) read it. On this
  repo the calibrated estimate reproduces the exact count to the token. An
  estimate-only run never writes the file — deriving a calibration from an
  estimate would just re-record the default and freeze whatever error it carries.

The estimate is still an estimate: use it to rank sections against each other and
to decide whether the guard should speak, and use `--exact` for anything that lands
in the ledger or a budget decision.

### Keeping a ledger single-method

`record-telemetry.sh` **refuses** to append a row whose method differs from the
ledger's latest row for that file, exiting 4 and naming the fix. Warning and
writing anyway was the earlier behaviour and it put the burden on every future
reader: `delta_tokens` null, `delta_unavailable` set, the trend's net re-anchored,
`net` blank in the cohort roll-up — all correct, all downstream of a problem that
was cheap to fix at the source. The usual cause is a missing credential, and the
usual fix is to supply one. `--allow-method-change` records it anyway and starts a
new baseline, which is the honest thing to do when the method genuinely changed.

This is mostly a guard on **interactive** runs, the case least likely to hold a
key: a Claude Code session exports no `ANTHROPIC_API_KEY` and often has no `ant`
CLI, so the OAuth fallback may not exist either. `measure-context.sh` therefore
tries a third source — `ANTHROPIC_API_KEY` **parsed** out of a repo-root `.env`
(then bare `env`, the cohort's pre-2026-08-05 name). Parsed rather than sourced:
sourcing a secrets file executes whatever it contains, which is not a thing a
measurement script should do to obtain a token count. `--no-env-file` declines
that source; `--env-file NAMES` changes which files are searched.

With all three sources, an interactive run and a scheduled run produce the same
`tokens_exact: true` rows, which is the whole point — a weekly cadence and an
ad-hoc `curate context` must land in one comparable series.

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
| `repo`, `file` | repo identity and policy-file path. `repo` is **the join key** the cohort roll-up and the validation gate match against the roster — not cosmetic. It comes from `--repo`, else the origin remote's basename, else the checkout directory name; the directory name alone recorded a *worktree* slug (`feat-161-curating-context`) as the repo in every member that mandates worktree-based feature work. |
| `tokens`, `lines`, `bytes` | policy-file size |
| `tokens_exact` | `true` when counted via `count_tokens`; gates delta comparability |
| `delta_unavailable` | present only when `delta_tokens` was suppressed; says why |
| `budget`, `over_budget` | the budget in force this run, and whether it was met |
| `tokens_live` | policy + reachable live reference docs |
| `docs_total`, `docs_orphaned` | live doc count, and how many nothing links |
| `links_dead` | broken relative links in the curated surface |
| `no_loss` | `prove-no-loss.sh`'s verdict — `ok`, `failed`, `skipped`, or `null` when the check was not run. A safety field, not a score: [the validation gate](validation-gate.md) reads it to reject a change that reduced tokens by dropping content, which no token count can distinguish from a good run. `null` is unscorable, never a pass. |
| `seams` | `check-seams.sh`'s final count after Phase 6.5's hits were judged and the wrong ones fixed; `null` when the sweep was not run, which is never the same as `0`. This is what makes the cross-reference defect class visible to the gate at all — on the run that motivated the sweep, ten review findings were invisible to every other field on this row. |
| `skill_version`, `skill_commit` | which version of this skill produced the row; `null` on rows predating the field |
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

### One row per run: rewrite within, append across

The ledger is append-only **between** runs, and that is where the rule matters:
a later run that rewrites an old row destroys the trend it was keeping.
**Within** a run the instinct runs the other way and is correct — when a late
fix on the same branch shifts the count, rewrite this run's still-unmerged row
so it describes what actually ships, rather than appending a second row for an
intermediate state nobody can check out. The test is whether the row's commit
has merged: unmerged, it is a draft of this run's record; merged, it is history.

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

`net` obeys the same comparability rule as `delta_tokens`: it is anchored at the
oldest run contiguously matching the *latest* run's method, not at the first run
ever recorded. Anchoring at the first row instead reported **+2,743** for this
repo's own ledger, whose three rows record an identical 22,533-byte file — the
whole figure was the estimate→exact transition. When no comparable anchor exists
the cell reads `-` and a footer names the repo and says why, so a suppressed
comparison cannot be mistaken for "no change yet".

Roster in `.skills/cohort`, one `owner/repo` slug or local path per line; `#`
comments allowed. Repos with no ledger are reported rather than skipped.

An entry may also carry `wave:` and `pair:` annotations. The roll-up prints the
resulting split and how many members of each arm have adopted;
`score-cohort.sh` is what acts on it. Both scripts read the roster through one
parser in `_context-lib.sh`, so they cannot disagree about which repo is in which
arm — a second opinion about the experiment's own assignment would be worse than
no experiment. See [validation-gate.md](validation-gate.md).

Before a repo adopts the skill it has no ledger, and that is the expected state —
not a failure, and not something to fix by writing a ledger into it. Ledgers
appear as each repo adopts, driven by a per-repo adoption issue. After adoption,
a member with no recent row *is* the finding.

One caveat worth designing around: `gh api` prints nothing **and** exits non-zero
on a 404, so a naive empty-output test reads a missing ledger as an empty one.
The script greps the error body for `404` before deciding, and reports anything
else as `unreadable` rather than silently as absent.
