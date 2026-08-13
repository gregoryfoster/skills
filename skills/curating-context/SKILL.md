---
name: curating-context
description: Curates a repo's agent-context surface — AGENTS.md and the reference docs it links — against a token budget, verifying facts before removing them. Measures the policy file and its whole live doc tree, fans out to check falsifiable claims (paths, commands, links, issue refs), classifies each section keep/demote/tighten/delete against an evidence-based rubric, relocates rather than deletes, then records a before-and-after telemetry pair so the cohort can learn which optimisations actually pay. Use when the user says "curate context", "context budget", "hone AGENTS.md", "trim AGENTS.md", or "prune context", and for scheduled weekly maintenance.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git, bash, and python3. Optionally uses gh for issue verification and the cohort roll-up, and ANTHROPIC_API_KEY for exact token counts.
metadata:
  author: gregoryfoster
  version: "1.7"
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

Deletion needs one of exactly three warrants: verbatim duplication elsewhere in
the surface, a command that proved the claim false, or rubric class D. Everything
else is a **move**, and the commit body names where it went — the third clause is
what makes this skill safe to run unattended
([the warrants](references/keep-cut-rubric.md#the-third-clause-and-the-three-warrants)).

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's under 200 lines, so it's fine" | Line count is not the budget. `watcher` and `usa-wa` differ by **one line** and 33,238 tokens. Gate on tokens. |
| "I'll move the bloat into `docs/`" | Only helps if the destination is smaller than what an agent would otherwise read. Demoting into an over-budget doc moves the cost; Phase 4 checks the destination. |
| "This section looks redundant, cutting it" | Redundant with *what*? Verbatim duplication is a warrant; "feels like boilerplate" is not. |
| "The path doesn't exist, so the claim is stale" | Policy files legitimately name paths that don't exist locally. Deleting on UNVERIFIABLE is how real guidance gets destroyed. |
| "I'll write the architecture overview more concisely" | Overviews measurably did not help agents reach files faster. Tightening a section that shouldn't be inline is wasted work — classify first. |
| "More context is safer" | Retrieval accuracy degrades as the window fills. An unnecessary token dilutes attention on the necessary ones. |
| "Nothing changed this week, skip the run" | The run's cheapest output is the telemetry row, and a flat week is a signal worth recording. |
| "I can get seams to 0 by deleting the references" | That zeroes the metric while making the surface worse. Acknowledge in `.skills/context-seams-ok` instead. |

The measurements behind these rows:
[references/keep-cut-rubric.md](references/keep-cut-rubric.md#rationalization-prevention).

## Scope: one repo, and only this repo

This skill edits **the repo it is invoked in**. It never writes to a sibling
checkout, even one it just measured. Cross-repo work is filed as **issues**, not
commits: measure each member read-only, then open an adoption issue per repo
carrying that repo's numbers. Always pass `--no-write` when surveying a repo you
are not curating — without it an `--exact` run leaves an untracked ratio file
behind. A member reporting "no ledger" is the expected pre-adoption state
([references/cohort-patterns.md](references/cohort-patterns.md#cross-repo-surveys-stay-read-only)).

## This skill's own surface

`tests/structural/test_skill_self_budget.py` holds each `references/*.md` to the
10,000-token per-doc budget and `SKILL.md` to a **7,600-token ratchet** — not the
6,000 it enforces on `AGENTS.md`, because this file was 10,902 and the last 1,600
cannot go without deleting procedure. That is Phase 4's escape clause, not a
licence: the ratchet only ever comes down.

**Learnings carry an edit budget: +250 net tokens per round, or the headroom left
under the ratchet — whichever is smaller.** The ratchet is the ceiling, the budget
a rate limit, and the ceiling usually binds first, so measure before writing.
Without a cap a skill walks up to its ceiling one plausible addition at a time,
which is how this file reached 82% over. When either binds, **demote or tighten
first**.

Changes to the skill itself carry extra procedure: an abandoned change is
recorded in [references/rejected-changes.md](references/rejected-changes.md) with
what refuted it, and nothing is adopted on judgement — the cohort is a held-out
validation split ([references/validation-gate.md](references/validation-gate.md)).

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

Every script reads the ratio, the archival matcher, the docs-dir knob and **both
budgets** from `_context-lib.sh`, so vendor the whole `scripts/` directory, never
individual files ([why](references/budget-and-metrics.md#the-library-the-chain-lives-in)).

## Phase 0 — Preflight the credential

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --check-credential
```

One command, before anything else. Exit 0 means `--exact` will work; exit 3 means
resolve a credential **now** — interactively, ask; autonomously, **abort the
run**. Found any later, it costs eight phases of work toward a ledger row that
`record-telemetry.sh` refuses at the very end.

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

**Be on a branch before you run this.** It is the run's first write and it writes
a tracked file; an aborted run otherwise leaves a modified ledger on the branch
you started from.

`--baseline` appends a measurement-only row for the surface **as found**, before
any edit. Without it the scored run is precisely the run that can never be scored
and the `docs_orphaned` gate has nothing to compare against. Phase 7 appends the
after-row; **never rewrite the baseline row to match it**.

A credential is not optional even interactively: an estimate records
`tokens_exact: false`, and `record-telemetry.sh` refuses that append against a
ledger of exact rows rather than nulling its own delta. A WARN from `--exact`
means the row is an estimate whatever credential was accepted — prefer stopping
to recording an incomparable row. An exact run also writes the observed
bytes-per-token ratio to `.skills/context-token-ratio`, which is what keeps the
offline estimators honest between runs
([both](references/budget-and-metrics.md#measuring-tokens),
[the baseline pair](references/telemetry.md#the-baseline-row-is-not-optional-either)).

Read the baseline before touching anything. Four numbers drive the whole run:

- `policy.tokens` vs `policy.budget` — is the file over budget, and by how much?
- `sections[0]` — the largest section and its `share`. A single section over ~30%
  of the file is the finding, not a symptom of one.
- `links.orphans` — live docs nothing points at. **The most common cohort defect.**
- `docs[].over_budget` — reference docs too large to be worth loading.

`totals.tokens_live` is a ceiling to **watch**, not to optimise: a successful
demotion *raises* it. The trend follows `policy.tokens`. Archival subtrees
(`docs/plans/`, `specs/`, `research/`, `audits/`, `archive/`, at any depth) are
excluded by default — a since-moved path inside a dated snapshot is a correct
historical record.

## Phase 2 — Verify facts

```bash
bash "<SKILL_SCRIPTS>/verify-facts.sh" --issues > /tmp/context-facts.tsv
```

Three verdicts, not interchangeable. **FALSE** — a command refuted the claim;
eligible for correction or removal, and deliberately narrow. **TRUE** —
confirmed, though a *closed* issue reference is TRUE-the-reference while the
prose around it may be stale. **UNVERIFIABLE** — the script could not decide,
which is **never a licence to delete**.

Then verify what no script can, using
[references/fact-verification.md](references/fact-verification.md): behavioural
rules, version pins, ports, deployment topology, "known issues". Prioritise by
decay rate — commands and issue state rot fastest, architecture prose slowest.

## Phase 3 — Classify every section

Assign each section from the Phase 1 census exactly one class, using
[references/keep-cut-rubric.md](references/keep-cut-rubric.md):

- **A — keep inline.** Only the author knows it and nearly every task needs it:
  build/test commands with their non-obvious flags, hard constraints and their
  reasons, project-specific gotchas, the reference-doc index. Stays, possibly
  tightened.
- **B — demote.** Correct and valuable, needed on *some* tasks. Moves to
  `docs/<TOPIC>.md` and gets an index entry.
- **C — tighten.** Class A content wrapped in prose an agent does not need,
  including narrative history of how a convention arose. Rewrite in place.
- **D — delete.** Restates a trained default, duplicates another part of the
  surface, or was disproven in Phase 2. Delete with the warrant named.

Classification is where the value is. Compressing a class-B section is wasted
work; deleting a class-A section is damage. Classify before writing a single edit.

**Most large sections split A+B rather than taking one class.** Classify at `##`
level first, then check `subsections[]` for any child over ~5% of the file; a
parent's class does not descend to its children
([the measured example](references/keep-cut-rubric.md#the-measured-example)).

## Phase 4 — Plan to the budget

Sum the projected tokens. If the plan does not reach `policy.budget`, keep
demoting class-B sections in descending size order — do not reach the budget by
reclassifying class A as class D. If it still cannot be reached without touching
class A, **stop and report that**: an irreducible file is a real finding, and a
budget that cannot be met honestly is the wrong budget.

Check the destination side too. A demotion that pushes `docs/API.md` past its
per-doc budget has moved the problem; split the destination or pick another.

## Phase 5 — Apply

**Split before demoting, never after.** A doc split is free only while nothing
points at what moves; once relocated prose points *into* a section, splitting it
forces a choice between a circular pointer and a
[no-loss failure](references/validation-gate.md#warranted-losses-are-not-the-same-claim-as-no-loss).
If a destination needs splitting, split it first.

Order matters — do the mechanical work first so the semantic edits land on a
clean file:

1. **Fix FALSE facts.** Repair dead links, correct refuted commands.
2. **Relink orphans.** Every live doc gets a link from the policy file's index
   section, or an explicit decision to delete the doc.
3. **Normalize the index.** A `## Detail Docs` section listing every live
   reference doc with a one-line purpose. The shape the cohort converged on, the
   canonical section order and the `docs/` filenames to align with:
   [references/cohort-patterns.md](references/cohort-patterns.md).
4. **Demote class B**, creating or extending `docs/<TOPIC>.md`. Move the text; do
   not paraphrase it in transit — a paraphrase during a move is an unreviewable
   content change wearing a refactor's clothes, and the one thing a reader
   skimming the diff will not notice. Before extending an existing doc, read its
   `##` headings and merge into the canonical section rather than appending a
   near-duplicate beside it, and keep provenance out of headings. Phase 6.5
   checks both.

   Two mechanical adjustments come with every move, and only these two:

   - **Relative links gain a level.** A block moving from the repo root into
     `docs/` turns every `](tests/x.py)` into `](../tests/x.py)`. Skip this and
     Phase 6 reports a wave of dead links.
   - **A `###` subsection becomes `##`** at the top of its own document.

   `prove-no-loss.sh` normalises exactly these two, and skips frontmatter; any
   other difference is reported as content loss.
5. **Tighten class C**, then **delete class D**.

## Phase 6 — Prove no loss

Re-run Phase 1 and assert, before committing:

- **Nothing was dropped.** Run the check; do not eyeball it:

  ```bash
  bash "<SKILL_SCRIPTS>/prove-no-loss.sh" --base <branch-point>
  ```

  Every non-blank line of the policy file as it was at `--base` must still be
  present verbatim, inline or in a destination. Exit 3 lists what is not; a
  distinctive-phrase grep is **not** sufficient, which is why this is a script.
  Carry the verdict to Phase 7 (`--no-loss ok`); a missing one is unscorable,
  never a pass.

  A line the run had to **rewrite** rather than move — a pointer this change
  retargeted, a heading Phase 6.5 forced you to rename — is not a loss. Give each
  a judged entry in `.skills/context-loss-ok` (`WARRANT :: CONTENT`, warrant from
  the closed set in `--help`), re-run, and carry `loss_warranted:` to Phase 7 as
  `--no-loss-warrants M`. **Never** warrant a line you have not read against its
  replacement.
- **No block was copied instead of moved.** Presence *anywhere* satisfies the
  check, so a bullet left inline *and* in a destination is invisible to it, to
  Phase 6.5 and to `links.dead`. `duplicated: N` lists them; judge each.
- **Every demoted block sits at the right heading depth.** A `###` inserted
  directly under an existing `##` silently reparents everything below it, and no
  gate sees depth.
- `links.dead` **and** `links.dead_anchors` are empty, and no new orphan
  appeared. `dead_anchors` is the breakage a split makes and the one `dead` alone
  cannot see ([the link graph](references/budget-and-metrics.md#the-link-graph)).
- `policy.tokens` is at or under budget, or the Phase 4 report explains why not.
- The repo's own test suite still passes — several cohort repos have structural
  tests that read `AGENTS.md`.

## Phase 6.5 — Sweep the seams

```bash
bash "<SKILL_SCRIPTS>/check-seams.sh" --base <branch-point>
```

`prove-no-loss.sh` proves moved content arrived; this proves the rest of the
surface still **describes where it went**. Tracked **source** outside the docs
tree is swept too once a section leaves the policy file. Never repoint one of
those at a bare `docs/X.md` — no installed wheel resolves it, and it can hit a
*different* repo's file in a sibling checkout. Qualify or inline it.

The report is hits **to judge**, not defects to fix: a reference to the policy
file is wrong only if what it points at moved. Fix what lies, acknowledge what is
legitimate in `.skills/context-seams-ok`, re-run, and carry both counts to Phase 7
(`--seams N --seams-acked M`). Run this sweep *last*, and re-read any command
beside a block that moved.

## Phase 7 — Record and ship

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" \
      --actions "demote:Project Layout,prune:Conventions,fix:dead-link" \
      --no-loss ok --no-loss-warrants <W> --seams <N> --seams-acked <M> --print-trend
```

`<N>` and `<M>` are Phase 6.5's two counts; `<W>` is Phase 6's `loss_warranted:`.
Tag `--actions` honestly and specifically — the tags are the only thing that lets
a later run, or the cohort roll-up, attribute a token delta to what caused it.
`"cleanup"` teaches nothing; `"demote:Project Layout"` does. Row schema and tag
vocabulary: [references/telemetry.md](references/telemetry.md).

Rows also carry `skill_version` and `skill_commit`, so an outcome can be
attributed to a *skill* change and not just a repo one. Bump the frontmatter
`version` whenever a change would plausibly alter what a run does — an unbumped
version makes the cohort look uniform when it isn't.

Commit the ledger with the edits, on a branch, and open a PR whose body carries:
the before/after token count, the per-section disposition table, **every relocated
block with its destination**, and every deletion with its warrant. In autonomous
mode this PR body is the entire audit trail — a reviewer must be able to
reconstruct and revert any single decision from it without re-deriving the run.

Then get the branch a **fresh-eyes review pass**. If a late fix changes the count,
**rewrite this run's row to match what ships; across runs, only ever append**
([telemetry.md](references/telemetry.md#one-row-per-phase-rewrite-within-append-across)).

Never push to the default branch. Never delete on an UNVERIFIABLE verdict, even
under budget pressure.

`cohort-report.sh --cohort-file .skills/cohort` gives the cross-repo view: which
optimisation actually paid, per repo. Repos with no ledger are reported rather
than skipped — on a weekly cadence, missing telemetry is itself the finding.

## Phase 8 — Wire the continuous surfaces

Three surfaces keep the ground this run won. Offer all three once per repo, after
the first successful curation:

- **The cadence** — `install-cadence.sh`. What goes on the clock is a
  **measurement, not a curation**. It needs the `ANTHROPIC_API_KEY` repository
  secret, or the job records *nothing*, silently, every week
  ([references/cadence.md](references/cadence.md)).
- **Review-time delta** — `context-delta.sh`, already called from the four
  `reviewing-code*` variants' `gather-context.sh`, so it needs no wiring. It sees
  what the guard cannot: the guard matches `Edit|Write|MultiEdit`, so a shell
  redirect (`cat >> AGENTS.md <<'EOF'`) or a `NotebookEdit` never reaches it.
- **Write guard** — `install-guard.sh --budget 6000 --doc-budget 10000`, a
  `PostToolUse` hook that flags an edit pushing a file further over budget. It
  never blocks and stays silent when an edit reduces the count
  ([references/write-guard-hook.md](references/write-guard-hook.md)).

The prompt to offer, the ratchet the three form together, and the hook-wiring
etiquette: [references/continuous-surfaces.md](references/continuous-surfaces.md).
