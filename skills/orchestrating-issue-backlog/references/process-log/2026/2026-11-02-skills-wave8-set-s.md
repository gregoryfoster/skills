## Session 2026-11-02 — gregoryfoster/skills (epic #516, Wave 8 set S: shipping-work and using-git-worktrees)

The second of Wave 8's local orchestrators, run beside set P ([its entry](2026-11-02-skills-wave8-set-p.md)) with no file shared between them.
- **The brief was the plan.** It was a comment on #342; Steps 1–9 were skipped, and the run went from Step 0 to `execution.md`.
- **Shipped:** `e6bbc786..074bd9cd`, one fast-forward push of 29 commits: four `--no-ff` worker merges (#552, #533, #342, #397), then the operator's `CR --fix` round. All four issues were closed; #559 was filed. The wrap-up is on #516.

**Shape:** four issues, four local workers.
- **Parallel:** #533 and #552, which share no file. #552's review came back first, so it merged first.
- **Then, in the brief's order:** #342, then #397.
- **Baseline:** 9,310 passed, 352 skipped at `e6bbc786`, not the brief's `4a2ec874`, because set P shipped first. Final: 9,497 passed, the skip-set hash unchanged at every merge. +11 +27 +141 +8 = +187, closing exactly.

## Lessons

### 1. Two bodies were corrected before any build: one by the operator, one by a measurement

- **#342:** the operator's launch message said the default is `direct`, not the body's `pr`. The body was edited before the worker was briefed, so the worker read the real boundary.
- **#552:** the body's trigger was "the root declares no dependencies". One read of cannobserv's virtual root showed it declares its own workspace members as dependencies, so the trigger would never have fired there. The option question went to the operator with that measurement attached, and they chose to key on `[tool.uv.workspace]` instead.

Both are existing rules seen again: measure an empirical decision at the gate, and write the scope change back to GitHub.

### 2. A decided fix passed its own tests and missed the issue's headline case

#533's decision was "match the root as configured or as resolved". The worker built and tested exactly that. But the default root is built with `pwd -P`, so it is already resolved, and the issue's own `/tmp` → `/private/tmp` example still missed. The orchestrator's review of the diff found it (CR 1738); the worker added the caller's spelling (`pwd -L`), guarded so it counts only when it resolves back to the root.
- **The gap:** the tests encoded the decision, and none reproduced the issue's example literally.
- **For a brief:** ask for one red test that is the issue's own reproduction, verbatim, beside the tests of the decided mechanism. One sighting.

### 3. Decisions survived; prescriptions were corrected three more times

#342's worker corrected three things the body prescribed:
- `gh pr view` also finds merged and closed PRs;
- a branch-name match is not merge evidence, so a PR counts only if its head equals or descends from the tip;
- `Closes #n` contradicts shipping-work's HARD-GATE item 4 when `deploy_command` is set, so those repos get `Refs #n`.

That is the 2026-08-21 pattern again: the decisions held, and the implementations named in the body did not.

### 4. The whole-range review looked at consumers; the per-issue reviews looked at diffs

The operator held the first push and ran `CR --fix` over the whole range. It found no correctness defects, but three places that read what the set had changed and still said the old thing: `docs/KNOBS.md`'s `default_branch` row, and coordinating-epics' kickoff prompt and implementer contract, which consume #397's new Step 5 leads.
- **Why per-issue review missed them:** each review read its worker's diff. #397 changed a producer's contract, and its consumers sat in another skill.
- **For an orchestrator's per-merge review:** when an issue changes what a skill emits, grep for who reads it. One sighting.

### 5. A budget-tight file stayed single-writer by order, not by rule

Both #533 and #342 edit `using-git-worktrees` SKILL.md, which had 284 tokens of headroom exact at the start (the brief estimated about 257). The brief's order put #342 after #533's merge, so the file never had two writers at once. It ended at 5,974 of 6,000, so its next edit needs a trim first. This is the existing budget-tight-file rule holding, and the exact count was taken before the push.
