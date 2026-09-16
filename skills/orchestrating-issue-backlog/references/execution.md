# Executing the plan

Loaded from [`SKILL.md`](../SKILL.md) at Step 8, whose design doc records the
batch→main merge strategy this file asks for, and before any batch launches.
Step and Q numbers refer to `SKILL.md`; Rule, Orchestrator-step and Worker-step
numbers refer to this file.

Demoted from the body in the #285 curation. A planning run cites Rules 1 and 6 at
Step 1–2 and Rule 5 at Step 7, and needs the whole protocol from Step 8; a batch
launch needs all of it.

## Agent Roles

### Branch strategy

Each **multi-agent batch** gets a shared integration branch (e.g. `batch/a`, `batch/f`), created **before any agent is spawned** (Orchestrator step 2, which also says when it may not be checked out). It is the merge *target* for every worker, **not the base their worktrees are cut from**, and worker output does not reliably auto-merge back (Rule 3) — the orchestrator reconciles and merges each worker explicitly (Orchestrator step 5).

**Single-agent batches** do not need a separate batch branch — the agent's feature branch serves directly.

The human review happens against the **batch branch**: run tests, inspect the combined diff, then merge to `main`. After merge, the orchestrator checks `main` back out, pulls to sync, and uses it as the base for the next batch branch.

**Intra-batch worker→batch integration must be fast-forward or regular-merge — not squash or rebase.** Orchestrator step 5's `worktree-destroy.sh --base batch/<X>` verifies the worker branch is an ancestor of `batch/<X>`; squash drops the parent link and rebase rewrites commits, so both break that check and force the orchestrator to descope the destroy, defeating the merge-safety gate. Separate from the batch→main strategy below, which the user picks.

Ask the user their preferred **batch→main** merge strategy (regular, squash, rebase) and record it in the design doc; a regular merge commit is the default, since it preserves per-agent commit history.

### Orchestrator agent

The orchestrator reads the batch plan and manages progression. It:
1. **Sync local main before every batch launch** — `git checkout main && git pull --ff-only`. The pull advances `origin/main` too, which is the ref agents' worktrees are actually cut from (Rule 3).
2. **Create the batch branch before spawning agents** — `git checkout -b batch/<X>`. This makes it the merge target only — workers still branch from `origin/main` and must merge it in themselves (Rule 3). **But where the host repo deploys from the main checkout, that checkout's branch must never move.** Grep the deploy units for a checkout guard (`ExecStartPre=.*assert.*main`) before Batch A; where one exists, `git branch batch/<X> main` *without* checking out and integrate in a worktree, and give a single-agent batch no local branch at all — push the worker's own branch as the feature branch. Same caution at wrap-up: run `systemctl is-enabled` and `systemctl cat` before any repo-documented restart, because a unit that is inactive *and* disabled while its preset is enabled is a deliberate hold, not a fault (process-log 2026-08-13 usa-wa: this step stopped production across three separate batches; a documented restart then resurrected a held daemon 94 seconds into an incident).
3. **Verify worktree slot availability** — before launching, check that consumed slots + planned agents ≤ project ceiling (Rule 5). Prefer the host project's own slot-status command (e.g. `dev.sh worktree status`, or listing the port-pool directory) — it reports **actual** resource consumption. Otherwise use `bash skills/using-git-worktrees/scripts/worktree-list.sh --porcelain | grep -c '^worktree '` (minus 1 for the main checkout) as a **lower-bound** proxy, with a safety margin of `ceiling - 1` to absorb port leaks from destroys whose project-side cleanup didn't run.
4. Launches all worker agents whose batch gate is currently satisfied simultaneously
5. **On each worker signal — a `failed` one takes the same path as a `completed` one** (reconcile, then merge — do not assume auto-merge; Rule 3). A killed agent is not an empty worktree, and from outside it "died" and "fell through" are indistinguishable, so run this procedure before concluding anything; then **resume that agent rather than spawning a fresh one**, or you discard both a coherent phase and the context that produced it (2026-08-14 observo: a mid-TDD kill left four modified test files at 6 failed / 15 passed, every failure describing intended behaviour):
   - Run `git -C <main> status --porcelain` (Rule 6). Any output — **or a non-zero exit** → halt the batch and salvage.
   - Locate the worker's work: run `git branch --no-merged batch/<X>` to surface every local branch carrying commits not yet on the batch branch — this catches both `worktree-agent-*` and custom-named branches regardless of the orchestrator's current checkout (don't rely on `git log batch/<X>..HEAD`, which only sees a branch if the workspace shifted onto it). Also check `git branch --show-current` (the workspace may have shifted off `batch/<X>`) and the worktree directory (e.g. `.claude/worktrees/agent-<id>/`) for uncommitted changes; if work was left uncommitted, commit it on the worker's branch with the prescribed message format first.
   - Merge the worker's branch into `batch/<X>` if it isn't already an ancestor (`git merge --no-ff <agent-branch>`), respecting any intra-batch ordering; merge conflicts return to the responsible worker agent to resolve.
   - Destroy the merged worker's worktree: `bash skills/using-git-worktrees/scripts/worktree-destroy.sh <agent-branch> --base batch/<X>`. `--base` verifies the merge against the batch branch rather than `main`, since the human batch→main merge hasn't happened yet (it would otherwise refuse). Frees the slot for a chunked sub-wave.
   - Drop the now-unused ref: `git branch -d <agent-branch>`. The lowercase `-d` refuses if the branch isn't merged into HEAD, providing a second guard against the same merge-safety class as the destroy script's Iron Law. If `-d` refuses, the worker's commits are not actually on `batch/<X>` — escalate before forcing.
6. When all workers are merged, runs the full test suite against `batch/<X>`
7. **Between sub-waves of a chunked batch** — after destroying completed workers' worktrees in sub-wave Aₙ, re-verify slot availability (step 3) before launching Aₙ₊₁
8. Notifies the user: "Batch X ready for review: `batch/<X>`, N issues, tests passing"
9. Waits for merge confirmation before proceeding
10. **On confirmation**, checks out `main`, merges `batch/<X>`, pushes, then syncs local main before launching the next batch

Never writes implementation code itself.

### Worker agents

Each worker agent follows this protocol before signaling completion:

1. **Confirm your auto-provisioned worktree** — you are launched inside one created by `isolation: "worktree"` (typically on a `worktree-agent-<id>` branch); do NOT create your own. Work on the branch you are on — the orchestrator discovers and merges it by content, not name (Orchestrator step 5). Mechanics: [`using-git-worktrees`](../../using-git-worktrees/).
2. **Pre-flight: verify isolation** — confirm cwd is an isolated worktree, not the main checkout. Use either:
   - `[ -f "$(git rev-parse --show-toplevel)/.git" ]` — in a linked worktree, `.git` is a *file* pointing to the worktree's git-dir; in the main checkout it's a *directory*. Cheapest reliable check.
   - Or compare resolved paths: `[ "$(realpath "$(git rev-parse --git-dir)")" != "$(realpath "$(git rev-parse --git-common-dir)")" ]`. Do not compare the raw `git rev-parse` outputs without `realpath` — git may return one as absolute and the other as relative depending on cwd, producing false-unequal results that mask a fall-through.

   If the check fails, abort and signal the orchestrator that worktree provisioning fell through (Rule 5/6) — do NOT modify files in the main checkout.
3. **Merge the batch branch** — `git merge batch/<X>`; expect a fast-forward, stop and report anything else. Your worktree is cut from `origin/main`, not the orchestrator's checkout (Rule 3), so after sub-wave 1 it is missing work already on `batch/<X>`. After step 2, never before — a merge writes files.
4. **Verify your brief's baseline** — the expected test count on `batch/<X>` and the interpreter that produces it. If the suite disagrees, STOP and report; do not reconcile to it. If the brief names none, ask before implementing. Catches what step 3 cannot: a brief written against the wrong tree still merges cleanly.
5. **Treat the issue body as a proposal, not a specification.** Verify every file:line, every claimed call site, and every prescribed implementation against the current tree before acting. Where the body is wrong, **report the correction** — do not implement around it silently. Across one 13-issue backlog the implementing agent found a material error in the body **every single time**; three would have shipped a defect as written, and staleness rose with batch depth because earlier batches moved the code the later bodies describe (process-log 2026-08-09). The direction is reliable; the specifics are not. Name those prior failures concretely in each worker prompt.
6. **Implement with TDD** — red → green → refactor, and **commit the red phase separately** rather than squashing. It is the only way a reviewer can check the ordering afterwards instead of assuming it, and it leaves an interrupted agent's salvage already coherent. The red commit lands cleanly *only where the pre-commit hook does not run the suite* — check which yours is, and where it does, use `--no-verify` and say so in the commit body
7. **Run full test suite** — all tests must pass
8. **Run linter** — no violations
9. **Self-review diff** — check: correctness, test coverage, project conventions, no unintended side effects outside issue scope
10. **Address findings** — fix before signaling; do not signal with known issues
11. **Signal completion** — notify orchestrator the branch is ready to merge into the batch branch. The orchestrator destroys the worktree after merge (see Orchestrator step 5); the worker does NOT destroy it itself (premature destruction can race with the merge).

**Required report-back slot: the suite's collected count (`N passed, M skipped` — never a bare "green"), and everything in the issue body that turned out to be wrong or stale.** The count is Rule 3's number seen from the worker's end: N verdicts cannot be reconciled against each other, N counts can (2026-08-16 skills: baseline + 4 + 6 + 15 + 17 matched the merged gate exactly), and a stale briefed baseline then surfaces as arithmetic instead of being silently adopted — three of four workers diagnosed one that way. Phrase the corrections half with its second clause — *"I want the corrections, not a report that matches the prediction"* — because without it agents reliably produce a report shaped like agreement. This is what surfaces the body-decay corrections above; it is also how the orchestrator learns its own briefs were wrong, which happens (process-log 2026-08-10: two workers corrected the orchestrator's brief and were right both times). Escalations are evidence, not findings — verify one before acting on it.

**No PR is opened by the worker.** The orchestrator merges into the batch branch; the user reviews the batch branch as a whole.

## Branch Hygiene Rules

These rules prevent the class of failures that produced the Batch B→C conflict:

### Rule 1 — Sync local main before conflict analysis AND before every agent launch

`git push origin HEAD:main` from a feature branch advances `origin/main` but does **not** move local `main`. The orchestrator then analyses, plans, and merges against a tree that is behind. (Agents branch from `origin/main`, not local `main` — Rule 3.)

The same staleness corrupts the *plan*, one step earlier and less visibly: a stale checkout produces a conflict map of a repo layout that no longer exists, and every downstream instruction inherits the fiction (process-log 2026-08-10: three workers were assigned an ownership boundary in a file that two merged PRs had already split apart; it surfaced only because a worker said so in its report). **So sync at Step 1–2 as well** — by launch time the plan is written and the tracking issue is filed.

**Before analysing the backlog, and before launching any batch:**
```bash
git checkout main
git pull --ff-only   # or: git fetch origin && git merge --ff-only origin/main
```

If `--ff-only` fails, the branches have diverged — stop and investigate before proceeding.

### Rule 2 — Never use `git push origin HEAD:main` to advance main

This is the root cause of Rule 1 violations. Always push from local `main`:
```bash
git checkout main
git merge --ff-only batch/x   # or rebase; whatever the agreed strategy is
git push origin main
```

Where local `main` already carries the merged batch (the human merged `batch/<X>` → `main` per Rule 3), the push alone is the whole sequence.

### Rule 3 — Do not assume `isolation: "worktree"` auto-merges; verify and merge per worker

The `isolation: "worktree"` parameter runs the agent in a temporary worktree. Its post-completion behavior is **inconsistent** — parallel volleys have produced all four of: an un-merged `worktree-agent-<id>` branch (most common), a commit straight onto the orchestrator's current branch, a custom-named branch the agent picked, and work left **uncommitted** despite a "completed" signal (process-log 2026-05-09, 2026-05-11).

**The base, by contrast, does not vary: worktrees are cut from `origin/main`, independent of the orchestrator's checked-out branch.** Sub-wave 1 hides this — `batch/<X>` still equals `main` — and by sub-wave 2 the batch branch carries everything merged since, so the gap widens with batch depth. Rule 1 does not cover it: local `main` can be current and the agent's tree still wrong. Two obligations follow, both the orchestrator's:
- **Brief every worker to `git merge batch/<X>`** — worker protocol step 3, immediately after the isolation pre-flight. Expect a fast-forward.
- **Give every worker prompt the expected test count on `batch/<X>`**, plus "stop if it does not match" — the only detector that has caught this. In #144 Batch A two of four agents found it because a briefed `1740 passed` read `1644` in their tree; one had been told to trim a file to a target measured on a version it lacked, and the other two would have edited a tree missing eight merged issues. Give a number, not an exhortation to "verify your assumptions" — that gets confirmation.

**Operating rule: the orchestrator owns the merge** — reconcile, then merge explicitly, on every completion signal. The runtime checklist is **Orchestrator step 5**, the single authoritative copy; follow it there rather than duplicating it here — Rule 1 carries the sync, Orchestrator step 2 the branch creation and the never-move-a-deploying-checkout caveat.

*Batch work* moves `main` only when the human merges the batch branch, via Rule 2's push sequence. The one thing the orchestrator pushes on its own authority is the Step 8 design doc, before any batch branch exists — and it must, since worktrees are cut from `origin/main` and an unpushed plan reaches no worker.

### Rule 4 — Fix commit messages before continuing after a rebase conflict

When `git rebase --continue` auto-generates a commit message from the conflict resolution, it replaces the original `#N type: description` format with a verbose blob. Fix it immediately with `git commit --amend` on that commit **before** continuing the rebase or adding more commits — amending the wrong commit requires a `reset --soft` recovery.

```bash
git rebase --continue          # resolves conflict, creates commit with bad message
git commit --amend -m "..."    # fix message before doing anything else
# only then: git rebase --continue for the next patch (if any)
```

### Rule 5 — Cap per-batch parallelism at the host project's worktree provisioning ceiling

`isolation: "worktree"` is an Agent tool parameter; it does not control the host project's worktree-create tooling. If that tooling has a finite resource ceiling (port pool, docker port range, license slot), exceeding it produces **silent fall-through**, not a graceful error: the agent's worktree-create script may print a warning and fall back to plain `git worktree add` (losing project-specific provisioning), or — worse — drop the agent into the main checkout where it modifies tracked files in place.

**Before launching any batch**, verify `len(agents) ≤ project ceiling` established in Q5; past it, chunk into sub-waves (Step 7) rather than narrowing.

**Slot-reclaim semantics**: a well-behaved host-project `worktree destroy` synchronously frees its slot (port, vhost, DB clone) and the next `worktree create` reclaims the lowest-available number. The ceiling check therefore counts *concurrently-live* worktrees, not lifetime-allocated — a stale-slot leak is only possible when `destroy` fails partway, not under normal operation. This is what makes chunking work: destroying a sub-wave's completed worktrees before launching the next is sufficient; you don't need a wider pool.

**Recording the ceiling**: capture it in the design doc's "Approved approach" section so subsequent sessions inherit it without re-interviewing. To cheaply *re-verify* an established ceiling in a follow-up session, just read the port number off any in-session `worktree create` output (e.g. the plan-doc worktree) — the pool's bounds don't change between sessions, so one assignment confirms it without re-interviewing or re-grepping the host script.

### Rule 6 — Detect worktree fall-through at runtime

A ceiling check is a precondition, not a guarantee — Q5 answers can be wrong, port pools can shrink mid-run, scripts can fail in new ways. The orchestrator MUST detect when an agent fell through into the main checkout.

**Between worker signals**, the orchestrator runs:
```bash
git -C <main checkout> rev-parse --is-inside-work-tree   # must print true
git -C <main checkout> status --porcelain
```

**Read the exit code, not only stdout.** A linked worktree *shares* `.git/config` with the main checkout, so a worker's stray `git config` — or a bare `git init --bare` whose path mis-resolves — can set `core.bare = true` there, and that makes `git status` **fail** with empty stdout. To a caller reading output alone, that is indistinguishable from "clean": the corruption **disables** this detector rather than tripping it, and keeps answering "clean" forever (#189, twice in one four-agent batch). Hence the canary above, and hence a non-zero exit is as much a halt as any output. Brief workers to give every repo-creating git command an explicit path (`git -C <tmpdir> init`).

Any output indicates a worker fell through and is modifying files in the main checkout. Stop processing further completion signals from this batch until the salvage completes and `git -C <main> status --porcelain` is clean again. Identify the responsible agent (most recently signaled, or — if commits ended up on the wrong branch — via `git log main..HEAD` on the main checkout), and salvage per the Recovery procedure in [`references/recovery.md`](recovery.md).

This check is cheap and runs on the orchestrator's host, not in any agent's worktree. Do it on every signal, not just on suspicion.

## Recovery

When Rule 6 fires — or a worker's pre-flight isolation check (Worker step 2) does — halt the batch's signals and follow [`references/recovery.md`](recovery.md). It preserves the worker's intended commits, replays uncommitted modifications onto the correct feature branch, and re-runs verification (the agent's pre-salvage test pass is invalid — it ran against the main checkout's working tree, not an isolated copy).

Do not relaunch a salvaged agent in the same wave that hit the ceiling. Resolve the ceiling first (destroy a completed worktree, widen the host-project pool, or chunk the remaining work into smaller sub-waves per Step 7).
