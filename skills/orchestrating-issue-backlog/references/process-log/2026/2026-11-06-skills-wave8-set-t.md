## Session 2026-11-06 — gregoryfoster/skills (epic #516, Wave 8 set T: shipping-work and using-git-worktrees)

The fourth of Wave 8's local orchestrators, after set B ([its entry](2026-11-03-skills-wave8-set-b.md)). Set T committed no entry of its own; this one was written by set R's orchestrator ([its entry](2026-11-06-skills-wave8-set-r.md)) from set T's wrap-up on #516, so it records what that wrap-up says and nothing more.

- **The brief was the plan.** Steps 1–9 were skipped.
- **Shipped:** one fast-forward push of 74 commits, closing #559, #567, #553, #561, #563, #565, #557 and #564, then two operator-requested `CR --fix` rounds (CR 1838–1873, 1851 held).
- **Shape:** four chains, one local worktree worker each, merged into `batch/t` with `--no-ff`. Each review round used three area reviewers and three fix workers, one commit per finding, with a mutation check on each.
- **Counts:** the base matched the brief exactly (9,443 passed, 327 skipped). Each merge's count was predicted by arithmetic and matched: 9,607, 9,671, then 9,737. The skip hash didn't move.

## Lessons

### 1. "Chains share no file" was a claim, and it was wrong
Two files were shared across chains: `docs/KNOBS.md` and `shipping-work/SKILL.md`. Planned row placement and a per-chain token split kept the merges clean. A brief's disjointness claim needs the same footprint grep as an issue body.

### 2. One idiom, copied, is one defect, copied
The brief said every knob found the primary checkout one way. There were two idioms, and neither handled a bare primary or a submodule. The review found it in the scripts it read (CR 1839, 1858, 1860), and #584 was filed for two more readers outside the set's window. After a fix to a copied idiom, grep for every other copy.

### 3. Shared scratch space and parallel full suites are hazards of the host, not of the work
Workers sharing the session scratchpad clobbered each other's `base.xml`, and a reviewer ran `rm -rf` over every `tmp.*` in the user's temp folder (the repo was untouched). Three workers' commit hooks running the full suite at once, beside other repos' gates, drove host load to about 980; the operator halted the run and restarted it one worker at a time. Set R's brief carried both: a per-worker scratch directory with no globbed deletes outside it, and a load check before each full gate.

### 4. A held finding was a contract change
CR 1851's fix forced Python ≥3.11, which turned a documented detection limit into exit 2 or an automatic Python download. It was reverted and held, and the limit stays on #553. A review fix can change a contract as well as close a defect.
