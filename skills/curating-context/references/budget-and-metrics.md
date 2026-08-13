# Budget and Metrics

Why the budget is denominated in tokens, what the numbers mean, and how they are
counted. The ledger those numbers land in, and the cross-cohort roll-up that
reads it: [telemetry.md](telemetry.md).

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

### `tokens_live` is watched, not optimised

`totals.tokens_live` is the ceiling on what one session can pull in from this
repo's guidance — a number to **watch**, not the one to optimise. A successful
demotion *raises* it: this repo's first curation moved it 8,462 -> 9,862 while
halving the always-paid cost, because the index and the new documents' own headers
are real bytes. The trend follows **`policy.tokens`**, which is what every
invocation actually pays. Treating `tokens_live` as the success metric would make
every good run read as a regression, and would push an autonomous run toward
deleting content instead of routing it.

Phase 1 carried this and the archival exclusion inline until v1.9, in these words:

  `totals.tokens_live` is a ceiling to **watch**, not to optimise: a successful
  demotion *raises* it. The trend follows `policy.tokens`. Archival subtrees
  (`docs/plans/`, `specs/`, `research/`, `audits/`, `archive/`, at any depth) are
  excluded by default — a since-moved path inside a dated snapshot is a correct
  historical record.

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

**One chain, four scripts.** Every reader resolves the budget the same way —
the flag, then `CONTEXT_BUDGET`, then `.skills/context-budget`, then 6,000 — and
the per-doc budget likewise via `CONTEXT_DOC_BUDGET` and
`.skills/context-doc-budget`. `install-guard.sh --budget N` writes the knob file,
which is what makes a repo's choice stick across the weekly measurement, the
write guard and the review delta. `measure-context.sh` was the exception and
recorded every row against 6,000 regardless
([#126](https://github.com/gregoryfoster/skills/issues/126)); a test now pins all
three surfaces to one answer for one knob file.

### The library the chain lives in

`scripts/` also holds **`_context-lib.sh`**, which is sourced rather than run.
`measure-context.sh`, `context-budget-guard.sh`, and `context-delta.sh` all read
the bytes-per-token ratio, the archival matcher, the docs-dir knob, **the two
budgets**, and the symlink/git comparison from it, so the weekly run and both
continuous surfaces cannot disagree about a number. The budgets were the
exception until [#126](https://github.com/gregoryfoster/skills/issues/126):
`measure-context.sh` hardcoded 6,000 and read only its flag, so a repo that set
`.skills/context-budget` got warnings at its own number from both continuous
surfaces and **ledger rows recorded against 6,000** — the denominator
`score-cohort.sh` divides by. It must travel with them: vendor the whole
`scripts/` directory, never individual files. `install-guard.sh` refuses to
install a guard whose library is missing, because that combination wires up
cleanly and then does nothing, silently.

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

### The Phase 0 preflight, in full

One command, before anything else. Exit 0 means `--exact` will work; exit 3
means resolve a credential **now** — interactively, ask while the human still
has context; autonomously, **abort the run**. Discovered any later, this failure
costs eight phases of work toward a ledger row that `record-telemetry.sh`
refuses at the very end.

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

### Run-wide on `policy`, per row on `docs`

`policy.tokens_exact` answers "is this whole measurement comparable with an exact
ledger row?" — `true` only when every count in the run succeeded. That is the right
question for the ledger and the wrong one for a per-doc consumer. Observo's CI gate
reports per-doc overages as `::warning file=…` annotations, and on a run-wide
`false` its only defensible move is to suppress **all** of them, because an
annotation naming a precise count is a claim the same run has disowned. One
transient failure on one file therefore dropped budget reporting for all 29 docs,
including the 28 counted exactly
([#123](https://github.com/gregoryfoster/skills/issues/123)).

So each `docs` row carries its own `tokens_exact` as well:

```jsonc
"docs": [
  {"path": "docs/API.md",   "tokens": 6930, "tokens_exact": true,  "over_budget": false},
  {"path": "docs/FLEET.md", "tokens": 9701, "tokens_exact": false, "over_budget": false}
]
```

A consumer can then report on the exact rows and stay silent on the estimated ones,
rather than choosing between reporting nothing and reporting numbers that may be
fiction. Nothing about the existing contract changed: a consumer reading only
`policy.tokens_exact` sees exactly what it saw before.

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

An exact run also writes the repo's observed bytes-per-token ratio to
`.skills/context-token-ratio`, which is what keeps the offline estimators (the
write guard, `context-delta.sh`) honest between runs. The conventional `bytes/4`
heuristic under-reports this cohort's markdown by 56–65%, so an uncalibrated
estimate would let a 6k budget pass a 15k file in silence.

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

### A credential is not optional, even interactively

The measurement is the same either way, but the *ledger row* is not: an estimate
records `tokens_exact: false`, and a row recorded by one method cannot be compared
against a row recorded by the other. One credential-less run appended to a ledger
of exact rows nulls its own delta and resets the trend baseline — so
`record-telemetry.sh` **refuses** that append and exits 4, telling you to fix the
cause rather than record the row. `--allow-method-change` overrides it and
deliberately starts a new baseline.

This matters most in an interactive session, which is the case least likely to
have a key: a Claude Code session exports no `ANTHROPIC_API_KEY`. Phase 0
exists so the gap is found *before* any work starts — if you are reading this
mid-run with no credential, that is the check that was skipped. Three sources
are tried in order — the environment, then `ANTHROPIC_API_KEY` **parsed** out of a
repo-root secrets file (`.env`, then bare `env`), then an `ant auth login`
profile. Parsed, never sourced: a measurement script must not execute a secrets
file to obtain a token count. `--no-env-file` refuses that source when the key
must come only from the environment.

The `ant auth` profile is last on purpose — `count_tokens` currently rejects JWT
auth, so it authenticates and then 401s. Don't rely on it.

And `tokens_exact` reports whether the **numbers** are exact, not whether a
credential was found: if any count falls back, the run says `false` and the
observed ratio is not persisted. So a warning from `--exact` means the row is an
estimate no matter what credential was accepted — prefer stopping to recording an
incomparable row.

So an interactive run in a repo whose `.env` holds the key needs nothing extra.
Elsewhere, export the key first.

### The Phase 1 credential note, in full

Phase 1 restated the rule above inline until v1.9, when it was demoted here and
replaced by a pointer. The words it carried:

  A credential is not optional even interactively: an estimate records
  `tokens_exact: false`, and `record-telemetry.sh` refuses that append against a
  ledger of exact rows rather than nulling its own delta. A WARN from `--exact`
  means the row is an estimate whatever credential was accepted — prefer stopping
  to recording an incomparable row. An exact run also writes the observed
  bytes-per-token ratio to `.skills/context-token-ratio`, which is what keeps the
  offline estimators honest between runs
  ([both](budget-and-metrics.md#measuring-tokens),
  [the baseline pair](telemetry.md#the-baseline-row-is-not-optional-either)).

## The link graph

`measure-context.sh` reports two classes of broken link, and they are separate on
purpose.

| Field | Meaning |
|---|---|
| `links.dead` | the link's **file** does not exist |
| `links.dead_anchors` | the file exists and the link's `#fragment` names no heading in it — `"AGENTS.md -> docs/CONSUMERS.md#adding-a-new-analysis-stage"` |

The anchor half was invisible until
[#124](https://github.com/gregoryfoster/skills/issues/124): the extractor stripped
the fragment before resolving, so `[l](docs/FOO.md#some-heading)` was a check that
`docs/FOO.md` exists and nothing more. That is blind exactly where this skill's own
advice points — **splitting an over-budget doc moves headings out of a file while
leaving the file in place**, the one edit shaped to break anchors and no plain
paths. Observo split a 13,871-token `docs/CONSUMERS.md` into three files and
`measure-context.sh` reported `"dead": []` before, during and after; the orphaned
anchor was caught by hand. Five more were measured on
`cannabis.observer-wordpress` immediately after a curation shipped a clean run
([#120](https://github.com/gregoryfoster/skills/issues/120)).

Keeping them as separate fields is what lets an existing consumer's `dead`
semantics stay put, and lets a repo adopting the check stage the cleanup instead of
turning the gate red on day one.

### What Phase 6 asserts about links

- `links.dead` **and** `links.dead_anchors` are empty, and no new orphan appeared. `dead_anchors` is the anchor half — a link whose file resolves and whose `#fragment` names no heading, which is the breakage a split makes and the one `dead` alone cannot see ([the link graph](budget-and-metrics.md#the-link-graph)).

### How a fragment is resolved

GitHub's slug rules: lowercase, drop everything outside `[a-z0-9 _-]`, each space
becomes a hyphen, and a repeat of an earlier slug gets `-1`, `-2`, … Four details
decide whether the checker is usable:

- **Spaces are substituted one for one, not collapsed.** A dropped character leaves
  its spaces behind, so `## Segments tranche 5h3 — 2026-06-15` slugs to
  `segments-tranche-5h3--2026-06-15`, double hyphen and all. Collapsing runs
  validates against slugs GitHub never mints.
- **Headings inside fenced code blocks do not count.** A `# comment` in a bash
  fence otherwise manufactures an anchor that masks a real miss, and this cohort's
  docs are dense with bash fences.
- **Duplicate numbering is per file.** A split that moves the third
  `### PHP layers` into a file of its own makes it `php-layers` again — a suffix
  computed over the pre-split document validates against slugs that do not exist.
- **A prose fragment is dropped, not reported.** Fragments containing `<`, `>`, `*`
  or a comma-space are dropped for the same reason those are dropped from paths:
  reporting prose in link clothing trains the reader to ignore the list. The path
  around such a fragment is still resolved.

Same-file anchors (`[jump](#setup)`) are checked too — a heading rename inside one
long file breaks them exactly as a cross-file rename does. Explicit
`<a id="…">` anchors are **not** modelled; a repo using them gets a
`dead_anchors` entry to judge rather than a silent pass.

**Archival subtrees are scanned as sources.** `docs/plans/` and friends are excluded
from the doc inventory and never traversed, because a stale *path* inside a dated
snapshot is a correct historical record. Their **anchors** are still reported: a
dated plan pointing into a live doc is navigation, and it goes stale the same way.
Whether to fix it is the maintainer's call.
