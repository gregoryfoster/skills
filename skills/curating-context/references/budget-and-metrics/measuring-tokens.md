<!-- Split out of budget-and-metrics.md (#276): 6,031 tokens, 60% of that
document, and a single subject — how a token count is obtained, and how far to
trust the one you have. What the budgets ARE stayed behind. -->

# Measuring tokens

`measure-context.sh --exact` calls `POST /v1/messages/count_tokens`. That endpoint
is the only accurate tokenizer for Claude models, and counts are model-specific —
`--model` defaults to `claude-opus-5`. Pin one model across the cohort; the
tokenizer introduced with Opus 4.7 produces ~30% more tokens for the same text
than earlier ones, so a mixed-model ledger is as incomparable as a mixed-method one.

**Counting is free.** The endpoint consumes no tokens and is billed nothing; it is
rate-limited per usage tier (2,000–8,000 RPM), with limits independent of message
creation. So `--exact` has no cost argument against it — run it always. A zero
credit balance blocks the whole API including free endpoints, which surfaces as a
400 whose body names the reason — the script prints the API's own
`error.message` from that body rather than just the status line, falling back to
the raw body when the shape is unfamiliar.

### Pointing the count somewhere else

`ANTHROPIC_BASE_URL` — the SDK's own knob — replaces `https://api.anthropic.com`
for every `count_tokens` call, so a repo behind a gateway counts against the
endpoint it has. Environment only: the secrets file is parsed for
`ANTHROPIC_API_KEY` and nothing else. Treat it as part of the credential, since
it decides where the credential is **sent** — a stale value returns `invalid
x-api-key` from a proxy that never saw your account, which reads exactly like an
expired key. So both surfaces name the host when it is set (`--check-credential`
in every answer, `--exact` in the WARN of a failed count), both print scheme,
host and port only, so a token in it never reaches a log, and a value that
cannot be parsed is exit 2 rather than a credential verdict.

### The Phase 0 preflight, in full

One command, before anything else. Exit 0 means `--exact` will work — it asks
the endpoint, not just the environment: the credential still comes from the
three sources below, and only the verdict moved. One free `count_tokens` call
on a one-character body, the same request `--exact` will make, for the same
model.
Presence was the old test: it passed a key that authenticated and could not
spend, and the run lost the week's row to exit 4 over a remediation line naming
the preflight that had just gone green (#271). Exit 3 means resolve a credential
**now** — interactively, ask while the human still has context; autonomously,
**abort the run**. The endpoint's own words are quoted, because "Your credit
balance is too low" is more actionable than a 400 alone. Exit 2 is an
unreachable endpoint, not a bad key: an offline or sandboxed runner reaches it
with a perfectly good credential, and a billing verdict sends it the wrong way.
Discovered
any later, this failure costs eight phases of work toward a ledger row that
`record-telemetry.sh` refuses at the very end.

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

Three mechanisms fix it:

- **Default 2.7 bytes/token**, from the measurement above.
- **Per-repo calibration.** Every whole-surface `--exact` run writes the
  observed ratio to
  `.skills/context-token-ratio`, and the offline estimators (the write guard,
  `context-delta.sh`, and `measure-context.sh` without `--exact`) read it. An
  estimate-only run never writes the file — deriving a calibration from an
  estimate would just re-record the default and freeze whatever error it carries.

  The persisted figure is fitted over the **whole measured surface**, not the
  policy file alone ([#172](https://github.com/gregoryfoster/skills/issues/172)).
  It used to be `P_BYTES / P_TOKENS`, and since the policy file is the most
  prose-heavy thing on the surface, the fallback over-reported every doc priced
  by it — worst on the class densest in tables, inline code and links, which is
  also the class most likely to sit near budget. Measured on `usa-wa`'s 24-file
  surface, the change takes mean absolute error from **8.2% to 3.1%** and files
  over-reported by more than 5% from **19 of 24 down to 2**. The bias moves, not
  just the spread. What the run *reports* as `policy.bytes_per_token` is still
  the policy file's own ratio, and the section figures still divide by it so the
  parts sum to the whole; only the persisted value is surface-wide.

- **Per-file calibration** ([#145](https://github.com/gregoryfoster/skills/issues/145)).
  The repo ratio still describes a whole surface rather than any one file in it,
  so a whole-surface `--exact` run also
  writes `<bytes> <tokens> <path>` per measured file to
  `.skills/context-token-counts`, and the estimators prefer a file's own last
  exact measurement, falling back to the repo ratio for a file never counted or
  since drifted more than 25% from the size recorded there. Two integers rather
  than a stored ratio: `tokens × bytes_now / bytes_then` is the exact count when
  the file has not changed, with no rounding step at all.

The estimate is still an estimate: use it to rank sections against each other and
to decide whether the guard should speak, and use `--exact` for anything that lands
in the ledger or a budget decision.

**One ratio is not enough, and it is not enough in both directions.** Measured
across this repo's own 56-file surface, the per-file ratio runs **2.041** (a
scaffolding doc that is mostly TOML and Python) to **3.029** (a review-dimensions
doc that is mostly prose and tables) against a global of 2.65 — so a single
divisor is wrong by **-23.0% to +14.3%**, under-reporting 37 of the 56 files and
over-reporting 19. Both errors cost something, and not the same thing:
over-reporting flags files that are under budget, which trains the reader to
ignore the guard; under-reporting is silence on a file that is genuinely over,
which is the decay the guard exists to catch.

Do not reach for a code-fraction heuristic. #145 was filed from a repo whose
code-block-heavy docs measured 2.485 and 2.549 against a 2.32 global — *over*-
reported — while here the code-heaviest files are the *densest* and are
*under*-reported. Both readings are correct about their own repo. What varies is
how well the content compresses, which a fenced-code fraction does not measure,
so any such heuristic would have to predict opposite signs in two repos of one
cohort. Measure the file instead.

Every row of the measurement JSON carries `tokens_source` — `exact`, `file` or
`repo` — so a number can be weighed by whoever quotes it. #145's cost was not an
estimate being wrong but an unattributed one being copied into a plan document,
an issue comment and several status reports before anyone re-derived it.

### A scoped run does not calibrate

A run that passed `--file` or `--docs-dir` reads both calibration files and
writes neither ([#263](https://github.com/gregoryfoster/skills/issues/263)).
Curating one skill ran `--exact --file skills/X/SKILL.md` and the ratio went
2.68 → 2.63 — that one file's rate, applied by every offline estimate in the
repo, which put two untouched skills over their budgets — and the file gained
an anchor row, which changed what the self-budget gate measures for it. Phase
7's `git add -A` then shipped both inside a commit about one file. Neither write
is wrong; both were made by accident. So the scoped run says what it measured
and what it left standing, and `--calibrate` is how the decision is made when
it is one: it persists both files from the scoped run, merged as before. The
docs-dir *knob* configures the surface rather than scoping a run, so the
flagless weekly cadence still calibrates.

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
  ([both](#measuring-tokens),
  [the baseline pair](../telemetry.md#the-baseline-row-is-not-optional-either)).
