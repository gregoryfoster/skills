# Recovery — worker agent fell through to main checkout

Detailed procedure for the `orchestrating-issue-backlog` skill. Triggered when:

- Rule 6 detects uncommitted work in the main checkout between worker signals, **or**
- A worker self-reports via the pre-flight isolation check (Worker step 2) that `worktree create` failed and dropped it in the main checkout, **or**
- A worker's `worktree create` fell back to plain `git worktree add` and the orchestrator wants to confirm work landed on the right branch.

The procedure assumes you have already halted further completion signals for the affected batch (Rule 6).

## Salvage procedure

1. **Identify** the responsible agent and its intended feature branch (e.g. `feature/batch-a-<issue>`). The most recently signaled agent is the usual suspect; cross-check by reviewing the agent's recent tool calls and the modified files in `git status`.

2. **Capture state** in the main checkout:
   ```bash
   git -C <main> status                                        # confirm what's modified
   git -C <main> stash push -u -m "salvage from <agent-id>"
   ```
   The `-u` flag includes untracked files — critical, since the worker may have created new files.

3. **Switch to the agent's feature branch.** Do NOT use `git checkout -B` here — uppercase `-B` resets an existing branch to current HEAD and discards any commits already on it.

   ```bash
   # If the branch already exists (worker had managed to create it before fall-through):
   git -C <main> checkout <agent-branch>

   # If the branch does not yet exist:
   git -C <main> checkout -b <agent-branch> main
   ```

   Verify with `git log <agent-branch>` afterward: any commits present are the worker's prior work and must be preserved through the pop in step 4.

4. **Pop the stash** onto the feature branch:
   ```bash
   git -C <main> stash pop
   ```
   If the pop conflicts (because the worker had committed earlier work to the branch and the stashed changes overlap), resolve manually — the conflict is between the worker's two phases of work and only the worker's intent can disambiguate.

5. **Verify** modifications match what the agent intended. Review `git diff` against the issue scope; the agent's tool-call history and any partial commit messages help here. If the salvaged diff includes files outside the issue scope, the worker was misbehaving in a separate way — escalate before committing.

6. **Commit** with the proper `#N type: description` format the agent would have used (matches the host project's conventional-commits format).

7. **Re-run** the agent's verification (full test suite, linter) on the salvaged branch before signaling complete. **The agent's pre-salvage test pass is invalid** — those tests ran against the main checkout's working tree, which contained the modifications themselves plus whatever unrelated state the orchestrator or other agents had left in `main`. Trust only fresh post-salvage results.

8. **Return to main** in the orchestrator's working directory:
   ```bash
   git -C <main> checkout main
   ```
   Confirm `git -C <main> status --porcelain` is now clean (Rule 6 invariant). If it isn't, another worker has fallen through during salvage — repeat from step 1.

9. **Halt the affected wave** until the worktree ceiling root cause is resolved. Options:
   - Free a slot by destroying a completed worktree (`bash skills/using-git-worktrees/scripts/worktree-destroy.sh <branch>` — refuses unmerged work).
   - Widen the pool in the host project (out-of-band fix; file a follow-up issue).
   - Chunk the remainder of the batch into smaller sub-waves (Step 7 batch design rules).

   Do NOT relaunch the salvaged agent in the same wave that hit the ceiling — the ceiling is still saturated.

## Why this exists

`isolation: "worktree"` is an Agent tool parameter that creates and tears down a temporary worktree per agent. It does not control the host project's worktree-create tooling, which may fall through silently when its own resource pool (ports, docker slots, license seats) is exhausted. When that fall-through drops an agent into the main checkout, the agent has no way to know it isn't isolated — `git status`, `git branch`, and `pwd` all look normal because the main checkout *is* a real working tree.

The 2026-05-22 cannabis.observer-wordpress incident (Process Log entry of that date) is the canonical case. See Rules 5 and 6 in the main SKILL.md for prevention and detection; this file is the recovery path.
