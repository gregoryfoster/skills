---
name: curating-context
description: Curates a repo's agent-context surface — AGENTS.md and the reference docs it links — against a token budget, verifying facts before removing them. Measures the policy file and its whole live doc tree, fans out to check falsifiable claims (paths, commands, links, issue refs), classifies each section keep/demote/tighten/delete against an evidence-based rubric, relocates rather than deletes, then records a before-and-after telemetry pair so the cohort can learn which optimisations actually pay. Use when the user says "curate context", "context budget", "hone AGENTS.md", "trim AGENTS.md", or "prune context", and for scheduled weekly maintenance.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git, bash, and python3. Optionally uses gh for issue verification and the cohort roll-up, and ANTHROPIC_API_KEY for exact token counts.
metadata:
  author: gregoryfoster
  version: "1.6"
  triggers: curate context, context budget, hone AGENTS.md, trim AGENTS.md, prune context
---

# Curating Context

Keeps a repo's agent-context surface small, true, and navigable. The surface is
the **policy file** (`AGENTS.md`) plus the **live reference docs** it links —
everything a session can pull in from the repo's own guidance. Every token in
that surface is paid on every invocation, and every stale claim in it costs more
than its tokens: an agent that runs a command which no longer exists stops
trusting the file that told it to.

**Activation triggers:** "curate context", "context budget", "hone AGENTS.md",
"trim AGENTS.md", "prune context". Also the scheduled weekly run.

## The Iron Law

```
NO EDIT WITHOUT A MEASURED BASELINE
NO CLAIM REMOVED WITHOUT A VERIFICATION VERDICT
NO CONTENT DELETED THAT IS NOT RELOCATED, DUPLICATED, OR DISPROVEN
```

The third clause is what makes this skill safe to run unattended. Cutting a
section from `AGENTS.md` is a **move** to a `docs/` reference by default. Outright
deletion needs one of exactly three warrants: the content is verbatim-duplicated
elsewhere in the surface, a command proved it false, or it restates something the
model already knows (rubric class D — see below). Anything else gets relocated,
and the commit body names where it went.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's under 200 lines, so it's fine" | Line count is not the budget. Measured exactly, `wslcb-licensing-tracker` is 205 lines / **5,331 tokens** and `cannabis.observer-wordpress` is 332 lines / **49,103**. Both pass a line cap; one costs 9.2× the other. `watcher` and `usa-wa` differ by one line and 33,238 tokens. Gate on tokens. |
| "I'll move the bloat into `docs/`" | Only helps if the doc is *smaller than the thing an agent would otherwise read*. `cannabis.observer-wordpress` already carries 192k tokens of over-budget live docs; demoting its 44.8k `Constraints` section into one of them moves the cost, it doesn't remove it. Demotion is paired with a per-doc budget. |
| "This section looks redundant, cutting it" | Redundant with *what*? Verbatim duplication is a warrant; "feels like boilerplate" is not. Quote both copies or relocate instead. |
| "The path doesn't exist, so the claim is stale" | A policy file legitimately names paths that don't exist locally — illustrative templates, naming conventions, downstream consumer paths. `verify-facts.sh` marks those UNVERIFIABLE for exactly this reason. Deleting on UNVERIFIABLE is how real guidance gets destroyed. |
| "I'll write the architecture overview more concisely" | The ETH Zurich evaluation found codebase overviews did **not** help agents reach relevant files faster. Tightening a section that shouldn't be inline at all is wasted work — classify it first. |
| "More context is safer" | Context is a finite resource with diminishing returns. Retrieval accuracy degrades as the window fills, so an unnecessary token is not neutral — it dilutes attention on the necessary ones. |
| "Nothing changed this week, skip the run" | The run's cheapest output is the telemetry row. A flat week is a signal worth recording, and the fact checks still catch drift the repo caused elsewhere. |
| "I can get seams to 0 by deleting the references" | A legitimate back-reference is navigation, and deleting it zeroes the metric while making the surface worse — the `tokens_live` mistake again. Acknowledge it in `.skills/context-seams-ok` instead; the healthy steady state is a stable acknowledged set with zero *new* hits. |

## Scope: one repo, and only this repo

This skill edits **the repo it is invoked in**. It never writes to a sibling
checkout, even one it just measured.

Cross-repo work is filed as **issues**, not commits — the same convention the
skill-family sweeps already follow. So a cohort pass is: measure each member
read-only, then open an adoption issue per repo carrying that repo's numbers and
findings. The repo's own maintainers (or an agent invoked inside it) run the
curation.

Two mechanics enforce this:

- `measure-context.sh --no-write` suppresses the one side effect an `--exact` run
  has — persisting the observed token ratio to `.skills/context-token-ratio`.
  **Always pass it when surveying a repo you are not curating.** Without it, a
  read-only-looking survey leaves an untracked file behind in every repo it
  touched.
- `cohort-report.sh` and `score-cohort.sh` read ledgers over `gh api` and never
  clone or write.

A cohort ledger therefore fills in as each repo adopts the skill, not from one
central sweep. `cohort-report.sh` reporting "no ledger" for a member is the
expected state before adoption, not a failure.

## Parameterized invocation

Trigger phrases may carry scope inline — `curate context docs/`, `context budget
6000`, `hone AGENTS.md --autonomous`. A path scopes the surface to that subtree; a
bare number overrides the policy-file budget; `--autonomous` selects the
unattended mode described in Phase 7. Otherwise defaults apply.

## Script path resolution

The skill's `scripts/` directory is not at the project root — it ships inside the
skill. Resolve it once, then substitute the printed path wherever
`<SKILL_SCRIPTS>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63)):

```bash
N=curating-context S=measure-context.sh SD=
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
```

A project-local `scripts/` copy wins if one exists. `<SKILL_SCRIPTS>` is a
**placeholder** for the literal path printed here, not an inherited shell
variable — each Bash invocation runs in a fresh shell.

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

## Phase 0 — Preflight the credential

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --check-credential
```

One command, before anything else. Exit 0 means `--exact` will work; exit 3
means resolve a credential **now** — interactively, ask while the human still
has context; autonomously, **abort the run**. Discovered any later, this failure
costs eight phases of work toward a ledger row that `record-telemetry.sh`
refuses at the very end.

## Phase 1 — Measure

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact \
  | tee /tmp/context-baseline.json \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" --baseline
```

`--exact` counts via the Anthropic `count_tokens` endpoint — the only accurate
tokenizer for Claude models, and **free to call**. Run it always; without a
credential it degrades to a calibrated offline estimate with a WARN. Never
substitute `tiktoken` — it is OpenAI's tokenizer and undercounts Claude badly.

### The baseline row is not optional either

`--baseline` appends a measurement-only row for the surface **as found**, before
any edit. It is what makes this run scorable at all.

The validation gate takes a run's before-state from the previous ledger row for
the same file, and a first curation is the run that *creates* the ledger — so
without this row the scored run is precisely the run that can never be scored,
and the `docs_orphaned` safety gate has nothing to compare against and cannot
trip. That is not hypothetical: it is what happened to all twelve cohort repos
in [experiment 1](references/validation-gate.md), which scored nothing
([#116](https://github.com/gregoryfoster/skills/issues/116)).

The row costs one command and lands in the same commit as the curation. Phase 7
appends the after-row; **never rewrite the baseline row to match it** — the pair
is the measurement.

**Be on a branch before you run this.** This is the first write of the run, and
it writes a tracked file. Phases 6 and 6.5 already presume a branch point exists
(`--base <branch-point>`) and Phase 7 commits there; the skill never says to
create it, so create it here. An aborted run otherwise leaves a modified ledger
on whatever branch you started from, which for an autonomous run is the one
place this skill forbids writing to.

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

An exact run also writes the repo's observed bytes-per-token ratio to
`.skills/context-token-ratio`, which is what keeps the offline estimators (the
write guard, `context-delta.sh`) honest between runs. The conventional `bytes/4`
heuristic under-reports this cohort's markdown by 56–65%, so an uncalibrated
estimate would let a 6k budget pass a 15k file in silence.

Read the baseline before touching anything. Four numbers drive the whole run:

- `policy.tokens` vs `policy.budget` — is the file over budget, and by how much?
- `sections[0]` — the largest section and its `share`. A single section over ~30%
  of the file is the finding, not a symptom of one.
- `links.orphans` — live docs nothing points at. **The most common cohort defect.**
- `docs[].over_budget` — reference docs too large to be worth loading.

`totals.tokens_live` is the ceiling on what one session can pull in from this
repo's guidance — a number to **watch**, not the one to optimise. A successful
demotion *raises* it: this repo's first curation moved it 8,462 -> 9,862 while
halving the always-paid cost, because the index and the new documents' own headers
are real bytes. The trend follows **`policy.tokens`**, which is what every
invocation actually pays. Treating `tokens_live` as the success metric would make
every good run read as a regression, and would push an autonomous run toward
deleting content instead of routing it.

Archival subtrees (`docs/plans/`, `specs/`, `research/`, `audits/`, `archive/`, at
any depth) are excluded by default. Plans and audits are dated snapshots — a
since-moved path inside one is a correct historical record, and counting them
buries the live signal under hundreds of files. Do not widen `--archival` to
"measure everything" and then act on the result.

## Phase 2 — Verify facts

```bash
bash "<SKILL_SCRIPTS>/verify-facts.sh" --issues > /tmp/context-facts.tsv
```

Three verdicts, and they are not interchangeable:

- **FALSE** — a command refuted the claim. Eligible for correction or removal.
  Deliberately narrow: a broken markdown link, or a missing target in a runner
  manifest that does exist.
- **TRUE** — confirmed. Note that a *closed* issue reference is TRUE-the-reference
  yet may still make surrounding prose stale ("pending in #42" when #42 shipped).
- **UNVERIFIABLE** — the script could not decide. **Never a licence to delete.**

Then verify what no script can, using
[references/fact-verification.md](references/fact-verification.md): behavioural
rules, version pins, port numbers, deployment topology, and "known issues"
sections. That file gives the per-class verification command and the rule for
when absence of evidence counts as evidence. Prioritise by decay rate — commands
and issue state rot fastest, architecture prose slowest.

## Phase 3 — Classify every section

Assign each section from the Phase 1 census exactly one class, using
[references/keep-cut-rubric.md](references/keep-cut-rubric.md):

| Class | Meaning | Disposition |
|---|---|---|
| **A — Keep inline** | Only the author knows it, and it is needed on nearly every task: build/test commands, non-obvious constraints, project-specific gotchas | stays, possibly tightened |
| **B — Demote** | Correct and valuable, needed on *some* tasks | move to `docs/<TOPIC>.md`, link from the index |
| **C — Tighten** | Class A content carrying prose an agent doesn't need | rewrite in place |
| **D — Delete** | Restates a trained default, duplicates another part of the surface, or was disproven in Phase 2 | delete, with the warrant named |

Classification is where the value is. Compressing a class-B section is wasted
work; deleting a class-A section is damage. Do the classification before writing
a single edit.

**Most large sections split A+B rather than taking one class.** On this repo's
first run, three of four demotions were splits: the `##` section stayed and its
`###` subsections moved. So classify at `##` level first, then check
`subsections[]` for any child over ~5% of the file — that array exists because a
`##`-only census hides the unit the decision is actually made on. The measured
example:

| Section | Total | Kept inline | Demoted subsection |
|---|---:|---:|---|
| `Scripts` | 2,670 | 390 | `<SKILL_SCRIPTS>` 1,315 + gate-script discipline 1,215 |
| `Project-level superseding` | 1,351 | 384 | `Required override frontmatter` 789 |

Note the counter-example in the same run: `Self-discovery` (176) was a *child of a
demoted parent* and stayed inline, because the `../skills` vs `../../skills`
footgun is class A. A parent's class does not descend to its children.

## Phase 4 — Plan to the budget

Sum the projected tokens. If the plan does not reach `policy.budget`, keep
demoting class-B sections in descending size order — do not reach the budget by
reclassifying class A as class D. If it still cannot be reached without touching
class A, **stop and report that**: an irreducible file is a real finding, and a
budget that cannot be met honestly is the wrong budget.

Check the destination side too. A demotion that pushes `docs/API.md` past its
per-doc budget has moved the problem; split the destination or pick another.

## Phase 5 — Apply

**Split before demoting, never after.** A doc split is free only while nothing in the surface points at what moves; once relocated prose points *into* a section, splitting it forces a choice between a circular pointer and a [no-loss failure](references/validation-gate.md#warranted-losses-are-not-the-same-claim-as-no-loss). One cohort run reverted a split because moving `## DB` into `docs/SCHEMA.md` routed 14 relocated bullets back to their own page. If a destination needs splitting, split it first.

Order matters — do the mechanical work first so the semantic edits land on a
clean file:

1. **Fix FALSE facts.** Repair dead links, correct refuted commands.
2. **Relink orphans.** Every live doc gets a link from the policy file's index
   section, or an explicit decision to delete the doc.
3. **Normalize the index.** A `## Detail Docs` section listing every live
   reference doc with a one-line purpose. See
   [references/cohort-patterns.md](references/cohort-patterns.md) for the shape
   the cohort has converged on, and the canonical section order and `docs/`
   filenames to align with.
4. **Demote class B**, creating or extending `docs/<TOPIC>.md`. Move the text;
   do not paraphrase it in transit. A paraphrase during a move is an
   unreviewable content change wearing a refactor's clothes — and it is the one
   thing a reader skimming the diff will not notice, because the words are all
   still there.

   Before **extending** an existing doc, read its `##` headings first: if the
   destination already covers the incoming topic, merge into the canonical
   section rather than appending a near-duplicate beside it — the cohort's
   defect #5 created at the destination by the run itself. And keep provenance
   out of headings: "Demoted from AGENTS.md (#412)" belongs in the commit, not
   baked into a permanent anchor slug. Phase 6.5 checks both.

   Two mechanical adjustments come with every move, and only these two:

   - **Relative links gain a level.** A block moving from the repo root into
     `docs/` turns every `](tests/x.py)` into `](../tests/x.py)`. Skip this and
     Phase 6 reports a wave of dead links — the check catches it, but the run
     fails rather than succeeding.
   - **A `###` subsection becomes `##`** at the top of its own document.

   `prove-no-loss.sh` normalises exactly these two and nothing else, so any other
   difference is reported as content loss.

   When the repo has **no `docs/` tree at all** — as this one did — the run is
   creating it. Take filenames from the frequency table in
   [references/cohort-patterns.md](references/cohort-patterns.md) rather than
   inventing them; a thirteenth distinct name for the same concept is how the
   cohort loses its shared shape. This is a different starting state from the six
   members that have `docs/` but no index: there, step 2 is the whole job.
5. **Tighten class C**, then **delete class D**.

## Phase 6 — Prove no loss

Re-run Phase 1 and assert, before committing:

- **Nothing was dropped.** Run the check; do not eyeball it:

  ```bash
  bash "<SKILL_SCRIPTS>/prove-no-loss.sh" --base <branch-point>
  ```

  Every non-blank line of the policy file as it was at `--base` must still be
  present verbatim, inline or in a destination. Exit 3 lists what is not. A
  distinctive-phrase grep is **not** sufficient, which is why this is a script —
  [the gate](references/validation-gate.md#why-no_loss-comes-from-a-script-and-not-a-grep)
  carries the defect that proved it. Carry the verdict to Phase 7 (`--no-loss
  ok`); a missing one is unscorable, never a pass.

  A line the run had to **rewrite** rather than move — a pointer whose target this same change relocated, a heading Phase 6.5 forces you to rename — is not a loss and must not be recorded as one. Give each a judged entry in `.skills/context-loss-ok` (`WARRANT :: CONTENT`, warrant from the closed set in `--help`), re-run, and carry `loss_warranted:` to Phase 7 as `--no-loss-warrants M`. Entries expire when their line changes and each is charged with its hits, so one blanket line is visible. **Never** warrant a line you have not read against its replacement.
- **No block was copied instead of moved.** The check is satisfied by presence *anywhere*, so a bullet left inline *and* in a destination is invisible to it, to Phase 6.5, and to `links.dead` — six shipped that way on one run. `duplicated: N` lists them; judge each, because a lead-in that is load-bearing in both places is a real state.
- **Every demoted block sits at the right heading depth.** Compare each against its neighbours in the destination: a `###` inserted directly under an existing `##` silently reparents everything below it — 24 pre-existing bullets, on the run that found this — and no gate sees depth.
- `links.dead` **and** `links.dead_anchors` are empty, and no new orphan appeared. `dead_anchors` is the anchor half — a link whose file resolves and whose `#fragment` names no heading, which is the breakage a split makes and the one `dead` alone cannot see ([the link graph](references/budget-and-metrics.md#the-link-graph)).
- `policy.tokens` is at or under budget, or the Phase 4 report explains why not.
- The repo's own test suite still passes — several cohort repos have structural tests that read `AGENTS.md`.

## Phase 6.5 — Sweep the seams

```bash
bash "<SKILL_SCRIPTS>/check-seams.sh" --base <branch-point>
```

`prove-no-loss.sh` proves moved content arrived; this proves the rest of the
surface still **describes where it went** — the *prose* half. `links.dead_anchors`
now decides the *link* half mechanically. One cohort adoption shipped a
clean run carrying ten such findings; a later one left 16 stale docstring
references across 13 shipped packages, which is why tracked **source** outside
the docs tree is swept too once a section leaves the policy file. Never repoint
one of those at a bare `docs/X.md` — no installed wheel resolves it, and it can
hit a *different* repo's file in a sibling checkout. Qualify or inline it.

The report is hits **to judge**, not defects to fix — a reference to the policy
file is wrong only if what it points at moved. Judge each: fix what lies, add
what is legitimate to `.skills/context-seams-ok` (entries match line *content*
and expire when the line changes, which is when they need re-judging; the
report warns on blanket patterns). Re-run, carry both counts to Phase 7
(`--seams N --seams-acked M`), and run this sweep *last*. No class sees a
command split from its claim: re-read any command beside a block that moved.

## Phase 7 — Record and ship

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" \
      --actions "demote:Project Layout,prune:Conventions,fix:dead-link" \
      --no-loss ok --no-loss-warrants <W> --seams <N> --seams-acked <M> --print-trend
```

`<N>` and `<M>` are the two numbers Phase 6.5 printed — new and acknowledged seams; `<W>` is Phase 6's `loss_warranted:`, omitted only if that phase was not run. Tag `--actions` honestly and specifically. The tags are the only thing that lets
a later run — or the cohort roll-up — attribute a token delta to what caused it.
`"cleanup"` teaches nothing; `"demote:Project Layout"` does. Schema and budget
rationale: [references/budget-and-metrics.md](references/budget-and-metrics.md).

Rows also carry `skill_version` and `skill_commit`, so an outcome can be
attributed to a *skill* change and not just a repo one. Bump the frontmatter
`version` whenever a change would plausibly alter what a run does — an unbumped
version makes the cohort look uniform when it isn't, and the roll-up's
`skill versions in play` footer is what surfaces that.

When a change to this skill is tried and abandoned, record it in
[references/rejected-changes.md](references/rejected-changes.md) with what refuted
it. A rejection is negative feedback: without the record the same plausible idea
returns every few runs and is re-litigated from scratch.

**A change to this skill is not adopted on judgement.** The cohort is a held-out
validation split, and `score-cohort.sh` scores the arm running a proposal against
the arm running the version before it. Adoption needs a win on every informative
pair and a clean sweep of the safety gates; anything else, "no measurable
difference" included, blocks adoption. The split, the metric, and what the gate
cannot see: [references/validation-gate.md](references/validation-gate.md).

Commit the ledger with the edits, on a branch, and open a PR whose body carries:
the before/after token count, the per-section disposition table, **every relocated
block with its destination**, and every deletion with its warrant. In autonomous
mode this PR body is the entire audit trail — a reviewer must be able to
reconstruct and revert any single decision from it without re-deriving the run.

Then get the branch a **fresh-eyes review pass** before it ships. Whoever just
moved three hundred lines has exactly the implementation blindness that misses
"and now this other file lies about it" — the seam sweep catches the mechanical
cases, a reviewer catches the rest. If a late fix changes the count, **rewrite
this run's row to match what ships; across runs, only ever append** — the same
distinction in [references/budget-and-metrics.md](references/budget-and-metrics.md).

Never push to the default branch. Never delete on an UNVERIFIABLE verdict, even
under budget pressure.

For the cross-repo view:

```bash
bash "<SKILL_SCRIPTS>/cohort-report.sh" --cohort-file .skills/cohort
```

The `best reduction` column names which optimisation actually paid, per repo.
Repos with no ledger are reported rather than skipped — on a weekly cadence,
missing telemetry is itself the finding.

## Phase 8 — Wire the continuous surfaces

Three surfaces keep the ground this run won. Offer all three once per repo, after
the first successful curation.

### The cadence

```bash
bash "<SKILL_SCRIPTS>/install-cadence.sh"
```

What goes on the clock is a **measurement, not a curation** — regrowth, budget
adherence and seam accrual all come from measuring, and judgement on a timer is
what this skill avoids everywhere else. The weekly job records a `baseline` row
and warns when the surface drifts; a human or an agent curates on that evidence.
It never runs on `pull_request`.

**It needs the `ANTHROPIC_API_KEY` repository secret.** Without it the job
records *nothing*, silently, every week — `record-telemetry.sh` refuses an
estimate against exact rows. Set the secret first, then run it once by hand.

Design, the annotated template, and what it deliberately does not do:
[references/cadence.md](references/cadence.md) ([#118](https://github.com/gregoryfoster/skills/issues/118)).

The next two catch regrowth *between* those weekly measurements.

### Review-time delta

`context-delta.sh` reports the branch's effect on the surface — token delta and
budget position per changed file, nothing at all when the diff touches no
context-surface file. The four `reviewing-code*` variants already call it from
their `gather-context.sh` when this skill is vendored alongside them, so it needs
no wiring there. It is informational by construction and exits 0 on every path.

It sees what the write guard cannot, twice over: the guard evaluates one edit at a
time, so a 400-token addition that replaced 600 elsewhere reads the same as a
straight gain; and it matches `Edit|Write|MultiEdit`, so a shell redirect
(`cat >> AGENTS.md <<'EOF'`) or a `NotebookEdit` never reaches it
([#103](https://github.com/gregoryfoster/skills/issues/103)). Review sees the
whole branch however the bytes arrived, while the tradeoff is still cheap.

### Write guard

> Install the context-budget write guard? It is a `PostToolUse` hook that flags an
> edit which pushes `AGENTS.md` or a live reference doc further over budget. It
> never blocks, and it stays silent when an edit *reduces* the count.

On yes:

```bash
bash "<SKILL_SCRIPTS>/install-guard.sh" --budget 6000 --doc-budget 10000
```

The guard and the weekly run are two halves of one ratchet: the guard stops
regrowth cheaply, in the turn that caused it, on the common path; the run and the
review-time delta recover ground and catch what the matcher never saw. A repo with
the run but no guard sawtooths, and no curation fixes a file something else keeps
appending to. Semantics, the speak-only-on-both-conditions rule, the uncovered
write paths, and uninstall:
[references/write-guard-hook.md](references/write-guard-hook.md).

The installer prints its `git add` line rather than committing, and names the log
path to tail. Hook wiring lands through the project's normal gate — a hook that
starts running because something committed it unannounced is a bad surprise.
