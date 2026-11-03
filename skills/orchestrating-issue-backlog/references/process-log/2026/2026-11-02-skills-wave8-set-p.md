## Session 2026-11-02 — gregoryfoster/skills (epic #516, Wave 8 set P: patching-hosts and maintaining-host-disk)

This is the first wave of #516 run as **local orchestrators, one per related set**, with sets running side by side and each one shipping itself. The operator decided that shape on 2026-11-02. The cloud-session waves (Waves 1–7) were ended by the same decision.
- **The brief was the plan.** It was a comment on #365, and the epic was the tracker, so Steps 1–9 were skipped: no scoring interview, no design doc, no tracking issue. The run started at Step 0 and went to `execution.md`.
- **Set S** (`shipping-work`, `using-git-worktrees`) ran beside this one, sharing no file with it.
- **Shipped:** `de245880..6de21bba`, one merge of 79 batch commits. 18 issues were closed, #551 was built and held, and two issues were filed (#554, #556). The wrap-up is on #516.

**Shape:** 21 issues in scope became 7 lanes.
- **Batch 1:** four workers at once.
  - W1: #365 → #458 → #388.
  - W2: #392, #370, #432.
  - W3: the #548 follow-up.
  - W4: #551, held apart.
- **Then:** a journal lane (J) in two phases, and #538.
- **Then:** three review rounds, and the operator's `CR --fix`.
- **Baseline:** 9,139 passed, 352 skipped at `4a2ec874`, measured in the orchestrator's fresh worktree. The shipped tree gave 9,305 passed with the skip set unchanged. Every intermediate gate reconciled with the workers' counts by arithmetic.

## Lessons

### 1. `rebase --rebase-merges` re-resolves a batch's own merges; re-make the batch merge instead

The first push was refused because the weekly measurement bot had moved `origin/main` by one commit. Rule 2's `git rebase --rebase-merges origin/main` then replayed every merge inside the batch, the per-worker merges included. It stopped on one whose `run.md` conflict a worker had already resolved by hand, and nothing re-applies a hand resolution (rerere is off).
- **What fixed it:** abort, fast-forward `orchestrate/<topic>` to the fresh `origin/main`, `merge --no-ff` the batch onto it, re-gate, and push. The push is still a fast-forward.
- **Side benefits:** it keeps every worker SHA the issue comments had already cited, and it is the shape Wave 7 shipped in.
- **Promoted** into Rule 2. Rebasing is right for a linear plan commit; a batch is not linear.

### 2. A journal lane must cite issues, not unpushed SHAs

The journal worker wrote "Since fixed" markers citing batch-merge SHAs. A rebase before the push would have left them pointing at nothing. Review caught it (CR 1664), and the markers now cite issue numbers. This is one sighting; a brief for a journal lane should say it.

### 3. A phased worker lets a late lane start early

The journal bundle had to come last, because its promotions edit `run.md`, which the code lanes were also editing. The entry files touch nothing the code lanes touch. So J started at once on phase 1, entries and index rows only, and reported its promotion candidates rather than writing them. Phase 2 got its go, and a fresh `batch/p1` to merge, once the code lanes had landed.
- **Merging into a moving batch:** J and W5 each re-merged `batch/p1` two or three times as review fixes landed. A one-line heads-up naming the files that would move was enough each time.

### 4. Review rounds converged at three, plus mutation

- Round 2 found a defect in a round-1 fix: CR 1646 caught CR 1641 refusing only packages named directly, not ones apt drags along, such as `apt:libpq5` taking `postgresql-16`.
- Round 3 found two in round 2's fixes.
- Round 3's findings were low or nit, so instead of a fourth round, each fix was verified by mutation: remove the fix, and see its new test go red.
- This is the existing "a fix round's commits are new code" rule, seen again, and the mutation step is what made it cheap to stop.

### 5. Two gates on one Mac: worker counts and timings

Two sets gating at once, plus each worker's commit hook running the full suite, made wall-clock time noisy. `gate-workers.sh` divided the cores by live gate slot (8, or 7 with one other gate), so no ceiling had to be set.
- **#538's timings:** the worker alternated before and after runs, and kept only pairs whose `gate-workers` line said `0 other gate(s)`.
- **An unexplained flake:** an in-suite ruff check once flagged a file that existed only in another worker's worktree. It never recurred in the orchestrator's gates, and its mechanism is unexplained.

### 6. Exact counts caught what the estimate gate didn't

The suite's offline estimate passed every reference doc. The exact count found the exe.dev profile at 9,808 of 10,000 tokens, after four lanes had each added to it. The operator's `CR --fix` moved the Tailscale material, verbatim, to its own page, with a no-loss proof. When several lanes append to one reference, measure it exactly before the push, not only at the weekly gate.
