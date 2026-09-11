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

How a count is obtained and how far to trust the one you have — the
`count_tokens` endpoint and why never `tiktoken`, the credential chain and the
order that is not the obvious one, what `tokens_exact` describes, why `docs`
rows carry their own, the calibrated offline estimate and why it is not
`bytes/4`, per-repo and per-file calibration, and the single-method rule the
ledger enforces: [budget-and-metrics/measuring-tokens.md](budget-and-metrics/measuring-tokens.md).

Two things belong here rather than there, because they are what the budgets
above are measured *in*: a count is **exact** only when every `count_tokens`
call in the run succeeded, and an estimate and an exact count are **never
differenced** — `record-telemetry.sh` refuses the append rather than compare
them.

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
