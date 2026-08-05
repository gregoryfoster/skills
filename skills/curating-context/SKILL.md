---
name: curating-context
description: Curates a repo's agent-context surface — AGENTS.md and the reference docs it links — against a token budget, verifying facts before removing them. Measures the policy file and its whole live doc tree, fans out to check falsifiable claims (paths, commands, links, issue refs), classifies each section keep/demote/tighten/delete against an evidence-based rubric, relocates rather than deletes, then records a telemetry row so the cohort can learn which optimisations actually pay. Use when the user says "curate context", "context budget", "hone AGENTS.md", "trim AGENTS.md", or "prune context", and for scheduled weekly maintenance.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git, bash, and python3. Optionally uses gh for issue verification and the cohort roll-up, and ANTHROPIC_API_KEY for exact token counts.
metadata:
  author: gregoryfoster
  version: "1.0"
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
| "It's under 200 lines, so it's fine" | Line count is not the budget. In this cohort `wslcb-licensing-tracker` is 205 lines / ~3.2k tokens and `cannabis.observer-wordpress` is 332 lines / ~29k. Both pass a line cap; one costs 9× the other. Gate on tokens. |
| "I'll move the bloat into `docs/`" | Only helps if the doc is *smaller than the thing an agent would otherwise read*. Demoting 26k tokens into one `docs/API.md` moves the cost, it doesn't remove it. Demotion is paired with a per-doc budget. |
| "This section looks redundant, cutting it" | Redundant with *what*? Verbatim duplication is a warrant; "feels like boilerplate" is not. Quote both copies or relocate instead. |
| "The path doesn't exist, so the claim is stale" | A policy file legitimately names paths that don't exist locally — illustrative templates, naming conventions, downstream consumer paths. `verify-facts.sh` marks those UNVERIFIABLE for exactly this reason. Deleting on UNVERIFIABLE is how real guidance gets destroyed. |
| "I'll write the architecture overview more concisely" | The ETH Zurich evaluation found codebase overviews did **not** help agents reach relevant files faster. Tightening a section that shouldn't be inline at all is wasted work — classify it first. |
| "More context is safer" | Context is a finite resource with diminishing returns. Retrieval accuracy degrades as the window fills, so an unnecessary token is not neutral — it dilutes attention on the necessary ones. |
| "Nothing changed this week, skip the run" | The run's cheapest output is the telemetry row. A flat week is a signal worth recording, and the fact checks still catch drift the repo caused elsewhere. |

## Parameterized invocation

Trigger phrases may carry scope inline — `curate context docs/`, `context budget
4000`, `hone AGENTS.md --autonomous`. A path scopes the surface to that subtree; a
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

## Phase 1 — Measure

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact > /tmp/context-baseline.json
```

`--exact` counts via the Anthropic `count_tokens` endpoint, the only accurate
tokenizer for Claude models; without a key it degrades to a `bytes/4` estimate
with a WARN. Never substitute `tiktoken` — it is OpenAI's tokenizer and
undercounts Claude by 15–20%, more on code.

Read the baseline before touching anything. Four numbers drive the whole run:

- `policy.tokens` vs `policy.budget` — is the file over budget, and by how much?
- `sections[0]` — the largest section and its `share`. A single section over ~30%
  of the file is the finding, not a symptom of one.
- `links.orphans` — live docs nothing points at. **The most common cohort defect.**
- `docs[].over_budget` — reference docs too large to be worth loading.

`totals.tokens_live` is the ceiling on what one session can pull in from this
repo's guidance. That is the number the telemetry trend follows.

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

## Phase 4 — Plan to the budget

Sum the projected tokens. If the plan does not reach `policy.budget`, keep
demoting class-B sections in descending size order — do not reach the budget by
reclassifying class A as class D. If it still cannot be reached without touching
class A, **stop and report that**: an irreducible file is a real finding, and a
budget that cannot be met honestly is the wrong budget.

Check the destination side too. A demotion that pushes `docs/API.md` past its
per-doc budget has moved the problem; split the destination or pick another.

## Phase 5 — Apply

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
   unreviewable content change wearing a refactor's clothes.
5. **Tighten class C**, then **delete class D**.

## Phase 6 — Prove no loss

Re-run Phase 1 and assert, before committing:

- Every demoted block is present at its destination. Grep a distinctive phrase
  from each moved block; a demotion that silently dropped content is the one
  failure mode of this skill that a token count cannot detect.
- `links.dead` is empty, and no new orphan appeared.
- `policy.tokens` is at or under budget, or the Phase 4 report explains why not.
- The repo's own test suite still passes, if it asserts on policy-file content.
  Several cohort repos have structural tests that read `AGENTS.md`.

## Phase 7 — Record and ship

```bash
bash "<SKILL_SCRIPTS>/measure-context.sh" --exact \
  | bash "<SKILL_SCRIPTS>/record-telemetry.sh" \
      --actions "demote:Project Layout,prune:Conventions,fix:dead-link" \
      --print-trend
```

Tag `--actions` honestly and specifically. The tags are the only thing that lets
a later run — or the cohort roll-up — attribute a token delta to what caused it.
`"cleanup"` teaches nothing; `"demote:Project Layout"` does. Schema and budget
rationale: [references/budget-and-metrics.md](references/budget-and-metrics.md).

Commit the ledger with the edits, on a branch, and open a PR whose body carries:
the before/after token count, the per-section disposition table, **every relocated
block with its destination**, and every deletion with its warrant. In autonomous
mode this PR body is the entire audit trail — a reviewer must be able to
reconstruct and revert any single decision from it without re-deriving the run.

Never push to the default branch. Never delete on an UNVERIFIABLE verdict, even
under budget pressure.

For the cross-repo view:

```bash
bash "<SKILL_SCRIPTS>/cohort-report.sh" --cohort-file .skills/cohort
```

The `best reduction` column names which optimisation actually paid, per repo.
Repos with no ledger are reported rather than skipped — on a weekly cadence,
missing telemetry is itself the finding.

## Phase 8 — Install the write guard

Offer this once per repo, after the first successful curation:

> Install the context-budget write guard? It is a `PostToolUse` hook that flags an
> edit which pushes `AGENTS.md` or a live reference doc further over budget. It
> never blocks, and it stays silent when an edit *reduces* the count.

On yes:

```bash
bash "<SKILL_SCRIPTS>/install-guard.sh" --budget 4000 --doc-budget 10000
```

The guard and the weekly run are two halves of one ratchet: the guard stops
regrowth, the run recovers ground. A repo with the run but no guard sawtooths —
reduce, regrow, reduce — and no amount of curation fixes a file something else
keeps appending to. Semantics, the reasoning behind the speak-only-on-both-
conditions rule, and the uninstall path:
[references/write-guard-hook.md](references/write-guard-hook.md).

The installer prints its `git add` line rather than committing. Hook wiring lands
through the project's normal gate — a hook that starts running because something
committed it unannounced is a bad surprise.
