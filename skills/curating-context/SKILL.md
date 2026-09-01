---
name: curating-context
description: Curates a repo's agent-context surface — AGENTS.md and the reference docs it links — against a token budget, verifying facts before removing them. Measures the policy file and its whole live doc tree, fans out to check falsifiable claims (paths, commands, links, issue refs), classifies each section keep/demote/tighten/delete against an evidence-based rubric, relocates rather than deletes, then records a before-and-after telemetry pair so the cohort can learn which optimisations actually pay. Use when the user says "curate context", "context budget", "hone AGENTS.md", "trim AGENTS.md", or "prune context", and for scheduled weekly maintenance.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git, bash, and python3. Optionally uses gh for issue verification and the cohort roll-up, and ANTHROPIC_API_KEY for exact token counts.
metadata:
  author: gregoryfoster
  version: "1.15"
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
else is a **move**, and the commit body says where it went — the third clause is
what makes this skill safe to run unattended
([the warrants](references/keep-cut-rubric.md#the-third-clause-and-the-three-warrants)).

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's under 200 lines, so it's fine" | Line count is not the budget. `watcher` and `usa-wa` differ by **one line** and 33,238 tokens. Gate on tokens. |
| "I'll move the bloat into `docs/`" | Only helps if the destination is smaller than what an agent would otherwise read. Demoting into an over-budget doc moves the cost; Phase 4 checks it. |
| "This section looks redundant, cutting it" | Redundant with *what*? Verbatim duplication is a warrant; "feels like boilerplate" is not. |
| "The path doesn't exist, so the claim is stale" | Policy files legitimately name paths that don't exist locally. Deleting on UNVERIFIABLE is how real guidance gets destroyed. |
| "I'll write the architecture overview more concisely" | Overviews measurably did not help agents reach files faster. Tightening a section that should not be inline is wasted work — classify first. |
| "More context is safer" | True of a **policy file**, loaded unconditionally: retrieval degrades as the window fills, and an unnecessary token dilutes attention. Not of a **skill library**, where selection ambiguity dominates and measured context overhead is ~zero. |
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
10,000-token per-doc budget and `SKILL.md` to a **7,600-token ratchet (estimate
and exact)** — not the 6,000 it enforces on `AGENTS.md`
([why](references/self-curation.md#the-ratchet-and-the-edit-budget-in-full)).
Both readings bind, so no measurement choice loosens it.

**Learnings carry an edit budget: +250 net tokens per round, or the headroom left
under the ratchet — whichever is smaller.** When either binds, **demote or
tighten first**.

Changes to the skill itself carry extra procedure — a refuted change recorded in
[references/rejected-changes.md](references/rejected-changes.md), a held-out
validation split ([references/validation-gate.md](references/validation-gate.md);
runs: [references/experiment-log.md](references/experiment-log.md)), and a
quarterly pass of Phases 1–7 over this file, demote/tighten only, never delete
([references/self-curation.md](references/self-curation.md#the-ratchet-and-the-edit-budget-in-full)).

## Parameterized invocation

Trigger phrases may carry scope inline — `curate context docs/`, `context budget
6000`, `hone AGENTS.md --autonomous`. A path scopes the surface to that subtree; a
bare number overrides the policy-file budget; `--autonomous` selects Phase 7's
unattended mode. Otherwise defaults apply.

## Script path resolution

The skill's `scripts/` directory is not at the project root — it ships inside the
skill. Resolve it once, then substitute the printed path wherever
`<SKILL_SCRIPTS>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63)):

<!-- skill:required -->
```bash
N=curating-context S=measure-context.sh SD=
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
```

A project-local `scripts/` copy wins if one exists. `<SKILL_SCRIPTS>` is a
**placeholder** for the printed path, not a shell variable — each Bash
invocation is a fresh shell.

Every script reads the ratio, the archival matcher, the docs-dir knob and **both
budgets** from `_context-lib.sh` — vendor the whole `scripts/` directory, never
individual files ([why](references/budget-and-metrics.md#the-library-the-chain-lives-in)).

## Phase 0 — Preflight the credential

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --check-credential
```

One command, before anything else. Exit 0 means `--exact` will work; exit 3 means
resolve a credential **now** — interactively, ask; autonomously, **abort the
run**. Found later, it costs eight phases of work toward a ledger row that
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
`tiktoken`: OpenAI's tokenizer, and it undercounts Claude badly.

**Be on a branch before you run this.** It is the run's first write, to a
tracked file; an aborted run otherwise leaves a modified ledger on the branch
you started from.

`--baseline` appends a measurement-only row for the surface **as found**, before
any edit. Without it the scored run is precisely the run that can never be scored,
and the `docs_orphaned` gate has nothing to compare against. Phase 7 appends the
after-row; **never rewrite the baseline row to match it**.

A credential is not optional even interactively, and a WARN means the row is an
estimate whatever credential was accepted
([both](references/budget-and-metrics.md#measuring-tokens),
[the baseline pair](references/telemetry.md#the-baseline-row-is-not-optional-either)).

Read the baseline before touching anything. Four numbers drive the whole run:

- `policy.tokens` vs `policy.budget` — is the file over budget, and by how much?
- `sections[0]` — the largest section and its `share`. A single section over ~30%
  of the file is the finding, not a symptom of one.
- `links.orphans` — live docs nothing points at. **The most common cohort defect.**
- `docs[].over_budget` — reference docs too large to be worth loading.

`totals.tokens_live` is watched, not optimised — a good demotion *raises* it — and
archival subtrees are excluded
([both](references/budget-and-metrics.md#tokens_live-is-watched-not-optimised)).

## Phase 2 — Verify facts

```bash
bash "<SKILL_SCRIPTS>/verify-facts.sh" --issues > /tmp/context-facts.tsv
```

Three verdicts, not interchangeable. **FALSE** — a command refuted the claim;
eligible for correction or removal, deliberately narrow. **TRUE** —
confirmed, though a *closed* issue reference is TRUE-the-reference while the
prose around it may be stale. **UNVERIFIABLE** — the script could not decide,
which is **never a licence to delete**.

Then verify what no script can
([references/fact-verification.md](references/fact-verification.md)): behavioural
rules, version pins, ports, deployment topology, "known issues". Prioritise by
decay rate — commands and issue state rot fastest, architecture prose slowest.

## Phase 3 — Classify every section

Assign each section from the Phase 1 census exactly one class, using
[references/keep-cut-rubric.md](references/keep-cut-rubric.md):

- **A — keep inline.** Only the author knows it and nearly every task needs it:
  build/test commands with their non-obvious flags, hard constraints and their
  reasons, project gotchas, the reference-doc index.
- **B — demote.** Correct and valuable, needed on *some* tasks. Moves to
  `docs/<TOPIC>.md` with an index entry.
- **C — tighten.** Class A content wrapped in prose an agent does not need,
  including narrative history of how a convention arose. Rewrite in place.
- **D — delete.** Restates a trained default, duplicates another part of the
  surface, or was disproven in Phase 2. Delete with the warrant named.

Classification is where the value is: compressing class B is wasted work,
deleting class A is damage. Classify before writing a single edit.

**Most large sections split A+B rather than taking one class.** Classify at `##`
level first, then check `subsections[]` for any child over ~5% of the file; a
parent's class does not descend to its children
([the measured example](references/keep-cut-rubric.md#the-measured-example)).

## Phase 4 — Plan to the budget

Sum the projected tokens. If the plan does not reach `policy.budget`, keep
demoting class-B sections in descending size order — never by reclassifying
class A as class D. If it still cannot be reached without touching
class A, **stop and report that**: an irreducible file is a real finding, and a
budget that cannot be met honestly is the wrong budget.

Check the destination: a demotion that pushes `docs/API.md` past its per-doc
budget has moved the problem — split it or pick another.

## Phase 5 — Apply

**Split before demoting, never after.** A doc split is free only while nothing
points at what moves; once relocated prose points *into* a section, splitting
forces a choice between a circular pointer and a
[no-loss failure](references/validation-gate.md#warranted-losses-are-not-the-same-claim-as-no-loss).
If a destination needs splitting, split it first.

Order matters — mechanical work first, so semantic edits land on a clean file:

1. **Fix FALSE facts.** Repair dead links, correct refuted commands.
2. **Relink orphans.** Every live doc gets a link from the policy file's index
   section, or an explicit decision to delete the doc.
3. **Normalize the index.** A `## Detail Docs` section listing every live
   reference doc with a one-line purpose. The cohort's converged shape,
   canonical section order and `docs/` filenames to align with:
   [references/cohort-patterns.md](references/cohort-patterns.md).
4. **Demote class B**, creating or extending `docs/<TOPIC>.md`. Move the text; do
   not paraphrase it in transit — a paraphrase during a move is an unreviewable
   content change wearing a refactor's clothes. Before extending an existing
   doc, read its `##` headings and merge into the canonical section rather
   than appending a near-duplicate beside it, and keep provenance out of
   headings. Phase 6.5 checks both.

   Two mechanical adjustments come with every move, and only these two:

   - **Relative links are re-aimed.** A block moving from the repo root into
     `docs/` turns `](tests/x.py)` into `](../tests/x.py)`, and `](docs/X.md)`
     into `](X.md)`. Skip this and Phase 6 reports dead links.
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
  distinctive-phrase grep is **not** sufficient. Carry the verdict to Phase 7
  (`--no-loss ok`); a missing one is unscorable, never a pass.

  A line the run had to **rewrite** rather than move — a pointer this change
  retargeted, a heading Phase 6.5 forced you to rename, a class-C tightening
  (which needs `--claims`) — is not a loss. Give each a judged entry in
  `.skills/context-loss-ok` (`WARRANT :: CONTENT`, or
  `PATH :: WARRANT :: CONTENT` to scope it to one target; warrant from the
  closed set in `--help`), re-run, and carry `loss_warranted:` to Phase 7 as
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

Then **once per doc you split**: `--file <that doc>`, as in Phase 6 — without it
a doc→doc split reports `seams: 0`. **Sum both** counts.


`prove-no-loss.sh` proves moved content arrived; this proves the surface still
**describes where it went**. Tracked **source** outside the docs tree is swept
once a section leaves the policy file. Never repoint one at a bare
`docs/X.md` — no installed wheel resolves it; qualify or inline it.

The count is a standing half plus an interval half
([references/seam-accounting.md](references/seam-accounting.md)). The report is
hits **to judge**, not defects to fix: a reference to the policy file is wrong
only if what it points at moved. Fix what lies, acknowledge what is
legitimate in `.skills/context-seams-ok`, re-run, and carry both counts to Phase 7
(`--seams N --seams-acked M`). Run this sweep *last*, and re-read any command
beside a block that moved.

Then the counts nothing else judges — `bash "<SKILL_SCRIPTS>/check-counts.sh"`.
A number earns its place by carrying the command that re-derives it, by dropping
the precision (the default), or by being gated — `--help` has the three. Warrant
the rest in `.skills/context-counts-ok`.

## Phase 7 — Record and ship

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" \
      --actions "demote:Project Layout,prune:Conventions,fix:dead-link" \
      --no-loss ok --no-loss-warrants <W> --seams <N> --seams-acked <M> \
      --counts <P> --counts-acked <Q> --print-trend
```

`<N>` and `<M>` are Phase 6.5's seam counts, `<P>` and `<Q>` its count
check's; `<W>` is Phase 6's `loss_warranted:`.
Ran `--claims`? Add `--claims-dropped <D> --claims-warranted <C>` from its
trailer — without them the row cannot say the tightening was checked (#253).
Tag `--actions` honestly and specifically — the tags are what lets a later run
or the cohort roll-up attribute a token delta to its cause. `"cleanup"` teaches
nothing;
`"demote:Project Layout"` does. Row schema and tag vocabulary:
[references/telemetry.md](references/telemetry.md).

Rows also carry `skill_version` and `skill_commit`, so an outcome can be
attributed to a *skill* change and not just a repo one, plus `repo_commit` —
which state of *this* tree the row describes, and where the next scheduled seam
sweep starts. Bump the frontmatter `version` whenever a change would plausibly
alter what a run does — an unbumped version makes the cohort look uniform when
it isn't. **What a run does, not what reads the rows afterwards**: changing
`score-cohort.sh` or `cohort-report.sh` alters no curation, and since #194 the
version *is* the arm — bumping for a gate change moves every future row into a
new arm for a change no row experienced.

Commit the ledger with the edits, on a branch, then `record-telemetry.sh
--repo-commit HEAD` and commit that: the append could not know the hash. Open a
PR whose body carries the before/after token count, the per-section disposition
table, **every relocated block with its destination**, and every deletion with
its warrant. In autonomous
mode this PR body is the entire audit trail — a reviewer must be able to
reconstruct and revert any single decision from it.

Then get the branch a **fresh-eyes review**. If a late fix changes the count,
**rewrite this run's row to match what ships; across runs, only ever append**
([telemetry.md](references/telemetry.md#one-row-per-phase-rewrite-within-append-across)).

Never push to the default branch. Never delete on an UNVERIFIABLE verdict, even
under budget pressure.

The cross-repo view is `cohort-report.sh`
([the roll-up](references/telemetry.md#cohort-roll-up)).

## Phase 8 — Wire the continuous surfaces

Three surfaces keep the ground this run won — `install-cadence.sh`,
`context-delta.sh` and `install-guard.sh`, the second seeing the shell-redirect
writes the third's matcher cannot. Offer all three **once per repo**, after the
first successful curation; on every later run this phase is a no-op. What each
is, the prompt to offer, the ratchet they form together and the hook-wiring
etiquette: [references/continuous-surfaces.md](references/continuous-surfaces.md)
(the cadence's credential requirement: [references/cadence.md](references/cadence.md);
the guard's: [references/write-guard-hook.md](references/write-guard-hook.md)).
