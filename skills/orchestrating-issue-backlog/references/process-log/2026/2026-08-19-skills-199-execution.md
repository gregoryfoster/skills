# Session 2026-08-18/19 — gregoryfoster/skills (#199 execution)

Execution addendum to [2026-08-18-skills.md](2026-08-18-skills.md), which
covers the planning half. Four batches, thirteen workers, five CR rounds,
15 issues. Suite 2,625 → **2,790**.

| Batch | Issues | Merge |
|---|---|---|
| A | #190 #184 #185 #192 | `c37135a` |
| B | #193 #194 #183+#197 #188 | `2e9feaf` |
| C | #189 #191 #186 #196 | `ebd8f65` |
| D | #195 #187 | `458b1bd` |

## The repo did not gate the budget it enforces on twelve other repos

The finding of the run, and it survived three review rounds before anything
caught it. `AGENTS.md`'s 6,000-token budget was enforced by **nothing**:
`test_skill_self_budget.py` measures `--file skills/{skill}/SKILL.md`, so the
policy file is never the measured file, and `docs/` was unreachable for the
same reason. Proven by execution, not by reading — 12,000 tokens appended to
`AGENTS.md` passed the gate at `81 passed, 85 skipped`.

**Three surfaces had to fail at once for it to survive**, and that is the
transferable part:

1. the write guard is a `PostToolUse` hook, so it never fires for a change
   arriving by `git merge`;
2. `context-delta.sh` defaulted to `--base HEAD`, so a branch whose changes are
   committed diffs empty and the review-time block printed nothing;
3. neither structural gate looked at the file.

Each is individually defensible. **A budget with three advisory watchers and no
gate is ungated**, and the way to find that out is to break the file and see
what says so. Fixed with `test_policy_surface_budget.py` (offline always, exact
under the opt-in) and a merge-base in all four `reviewing-code*` variants.

**Corollary worth carrying: (2) is why (3) was invisible.** The advisory that
should have flagged the growth was structurally silent on exactly the shape
being reviewed — a merged batch branch. Third sighting of the `--base HEAD`
default reading as "nothing changed" (#169 was the cadence's).

## I briefed the looser of two bound readings — again

`validation-gate.md` was briefed to D1 as **1,122 tokens of margin**. That was
the *exact* count; the gate binds on **both** readings and the offline estimate
had **512**. D1's first draft cleared exact comfortably and failed on the
estimate, forcing a rewrite mid-task.

This is verbatim the lesson in
[2026-08-17-skills-182-execution.md](2026-08-17-skills-182-execution.md) —
*"the cause is quoting the looser of two bound readings"* — repeated one
backlog later, in the same briefs that told every agent to run the gate rather
than trust my numbers. **Writing the rule down did not stop me; the rule needs
to be that the brief carries no number at all**, only the invocation. Batch A–D
briefs did carry the invocation, which is why this cost a rewrite rather than a
shipped breach.

Second-order: the gate can report **green having verified nothing**.
`SKILL_BUDGET_EXACT=1` prints `81 passed, 85 skipped` with a warning when
count_tokens is unreachable; the verified shape is `159 passed, 13 skipped`.
**The skip count is the tell**, and it bit two agents and me.

## Every worker corrected its brief or its issue; the two that corrected *me* mattered most

13 of 13 workers reported at least one correction. Two classes:

**The issue's own suggested fix was wrong.** #188 proposed `-q` to stop
`git worktree add` leaking stdout; `-q` also silences `Preparing worktree` on
*stderr*, so it passes a naive stdout test while destroying the operator's
record. B4 shipped `>&2` and a test that fails if anyone simplifies it back.

**The issue's premise was false, and so was the repo's own documentation.**
#189 direction 3 proposed `extensions.worktreeConfig` "so a worktree's
`--local` writes stay local". It does not do that — it *adds* a `--worktree`
scope. Verified independently on git 2.39.3. `docs/STYLE.md` carried the same
false claim, written by me in Batch A's CR. **A refusal backed by measurement
is a good outcome**; C1 was briefed that adopting was not required.

## Pre-registered answers are hypotheses, not conclusions

`test_skill_self_budget.py` carried, in a comment, *"when it crosses, splitting
it by year is the move — not an exception."* B2 executed it and produced a
**negative result**: `process-log/2026/index.md` came out at 9,760 exact / 240
margin. Thirty-seven sessions in under six months fill one year-document, so
the split bought about one row. The next crossing is a **row-length** problem,
not a split problem, and the index's own footer already demands headlines.

The repo had written a plan into a test comment as settled. **Executing it was
the only way to find out it did not work**, and the comment is now the
measurement rather than the prediction.

## Stale numbers, four of them, all confidently stated

- #196: "eleven self-links … four real ones" — the tree held **9 and 2** before
  the batch opened.
- `docs/STYLE.md`: "five occurrences" of the #189 corruption; the issue and
  `SKILL.md` both say **twice**, and nothing substantiated five. Mine.
- #195: `score-cohort.sh:814`; the file had grown to **1,724 lines** and the
  site was `:1041`.
- #187: `socraticode-health.sh:161`; actually `:168`.

**A census recorded as a fact decays exactly like a line number.** The
`test_demoted_blocks.py:34` precedent — *"writing the totals into this
docstring would put a number here that the next demotion falsifies"* — is the
right treatment, and C4 applied it by deleting the totals rather than
refreshing them.

One line-number correction was itself wrong: D2 reported my `:168` had "gone
stale by 4 lines" to `:172`. It reads `:172` **on D2's own branch, because D2's
edit added four lines above it**. The conclusion survives and lands harder —
a range went stale *inside one agent's own session*.

## Closed-in-fact has a third axis: shipped under another issue's CR

Two of fifteen issues were already fixed, and neither was fixed by the work
that closed them:

- **#187 part 1** (the unchecked lock write) shipped in `3d7267b`, a CR round
  on *batch/a of the previous backlog*, and is now gated by the rule #193
  shipped. Zero hits from the gate's matcher is ambiguous on its own — the
  disambiguation was reading the file.
- **#189 directions 1, 2 and 4** shipped with #161's promotion pass;
  `SKILL.md:387` cites #189 by number. The issue never closed because nothing
  in the fixing commit referenced it.

**Grep the fix, not the issue state — and grep CR commits, not just feature
commits.** A defect fixed as a review finding leaves no trace on its own issue.

Also: #190 and #192 shipped in batch A and were never closed at that gate. A
batch's wrap-up needs an explicit close step; four issues in this run were
closed late or by a merge-message reference rather than deliberately.

## Two agents cannot share a scratchpad, and a worktree has no `.venv`

Three environment findings, all reported independently by more than one worker:

- **`.venv` and `.env` live in the main checkout**, so `.venv/bin/python` and
  `. ./.env` both fail from a linked worktree. Every brief carried them anyway
  until Batch D. Put the symlink instruction in the brief.
- **`measure-context.sh --exact` without `--no-write` recalibrates the whole
  library.** C2 pushed an untouched skill 31 tokens over its ratchet from a
  verification run meant to be read-only. The pytest gate is hermetic; the
  ad-hoc invocation is not.
- **The scratchpad is shared between concurrent agents.** C1 overwrote C2's
  runner script mid-task. Prefix per-agent helpers.

## Orchestrator self-inflicted

- **`git checkout -- <file>` after a mutation probe reverted an entire round of
  uncommitted CR work.** Mutation-test on a *copy*, restore from the copy.
- A probe that appended 12,000 tokens to `AGENTS.md` had its restore killed by
  a command timeout, leaving the real policy file bloated. The probe is now a
  test that builds its fixture in `tmp_path`.
- **Backticks inside a double-quoted `-m` are command-substituted.** A merge
  message lost `` `-q` `` — the very flag the paragraph was about. Same family
  as the apostrophe-in-heredoc rule already in the skill; use `-F`.
- The pre-commit hook runs the full structural suite and exceeds a 2-minute
  tool timeout. Budget 400s for `git commit` in this repo.

## Where the ratchets stand

| Surface | Margin (est) |
|---|---|
| `orchestrating-issue-backlog/SKILL.md` | **55** |
| `validation-gate.md` | **56** |
| `process-log/2026/index.md` | **150** |
| `curating-context/SKILL.md` | **151** |

Four surfaces within one edit of a gate. **Budget margin is a conflict class no
file grep shows** — established in the planning half, and it held: the plan
gave each tight file exactly one writer per batch and no breach shipped.

The trim pass this backlog kept deferring is now due on
`orchestrating-issue-backlog/SKILL.md`, whose Step 10 pointer at `:244` was
itself found stale by CR round 3.
