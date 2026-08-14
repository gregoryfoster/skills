## Session 2026-08-13/14 (CannObserv/usa-wa) — execution addendum

Execution of the #218 plan (planning entry above). Batch A (3 parallel) + Batch B (solo) + an ops
tail, all merged; #208/#211/#212/#213/#216 closed. Two CR rounds, 8 findings, zero bugs found in
either — the findings were documentation surface, one graceful-degradation gap, and stamp-authority
drift.

### The ops tail is where a backlog's claims get falsified, and it belongs in the plan

The plan's third row — "delete the kill switch, restart, observe ≥2 passes" — was the only step that
could distinguish a merged fix from a working one. It paid immediately: the first production pass
reported **`healed=0`**, the exact number #212 argued was structurally unreachable (it had read 3,290
every hour, forever). No test could have produced that evidence; it required the real converged
cohort. Conversely, the worker's own confident prediction — that re-enabling would show
`budget_exhausted=true` for hours while a hold-period backlog drained — **was wrong**: the pass
enumerated 913 items against a 2,000 budget and caught up in one go. A plan that ended at "merged"
would have shipped both the unverified win and the wrong prediction as if settled.

### An operationally-mitigated issue keeps its scope and loses its urgency (planning entry) — and its
### *evidence* moves to the ops tail

The corollary discovered in execution: because #211's symptom was already suppressed by a kill
switch, nothing in the merge could show the fix worked. The observation window is not optional
polish on such an issue — it is the only test that runs against the failure the issue described.

### Reading a log line without checking its timestamp against the restart

I reported the new summary fields "missing from the live log" and started diagnosing a deploy
failure. The line was stamped 22 seconds *before* the restart I was verifying — the old process's
output. The tell was available in the same JSON blob I was already parsing. **When verifying that a
restart picked up new code, filter the journal by the restart timestamp before reading anything**
(`--since "$(systemctl show -p ExecMainStartTimestamp --value <unit>)"`), rather than reading
`tail -1` of a window that spans the restart. Same failure shape as reading a stale checkout (Rule 1):
the artifact looked current and was not.

### Second, independent hit on the batch-checkout guard — and why the rule did not reach me

Orchestrator step 2's caution about repos that deploy from the main checkout **already existed
upstream** when this ran (added by the #146/#151/#153/#154 session, citing this same repo). It did
not help, and the reason is worth more than the incident: **the skill text in an agent's context is
a snapshot taken at session start.** Mine was cut at submodule SHA `3b374bb`, where step 2 read only
"Check out the batch branch before spawning agents — `git checkout -b batch/<X>`". The guarded
version arrived in the working tree when I pulled the submodule mid-session to append this log —
by which point both batch branches had already been checked out for hours. The file on disk was
right; the file in context was not.

The incident is therefore a clean *independent* corroboration of the rule rather than a discovery:
`batch/a` and `batch/b` sat checked out in the prod checkout across the orchestration, and this
repo's `ExecStartPre=assert-main-checkout.sh` (usa-wa#87) failed **nine** timer-fired one-shots —
WSL refresh, SOS archive+rebuild, PDC archive+rebuild, both corroborations, succession invariants,
committee lineage invariants — each logging `refusing to start — checkout on 'batch/b', expected
'main'`. Recovery was `reset-failed` + `start` per unit once main was restored; all nine returned
`outcome=ok`, so the cost was delay, not data.

Two things to carry:

1. **When a session opens by pulling or updating a vendored skill, re-read the skill body before
   acting on it.** A mid-session `git pull` of the skills submodule silently desynchronizes the
   instructions being followed from the instructions on disk, and nothing surfaces the gap.
2. **`systemctl list-units --failed` (or the project's equivalent) belongs in the ops tail.** Here it
   ran only because a post-deploy health check happened to include it; the batch merged green and
   the test gate was clean while nine scheduled jobs had been wedged for hours. Two rounds were
   needed — four more units surfaced after the first five were cleared, because their timers had
   fired later in the window.

### Also captured

- **A "0 requests since T" measurement taken 18 seconds after T is not a quiet period.** I nearly
  reported traffic had gone quiet using a window that had barely opened. Bounding the *claim* by a
  window that actually elapsed (a background waiter to a wall-clock time) is the cheap fix; the
  instinct to publish the first favorable number is the expensive habit.
- **The duty-cycle win is a ratio, not an absence of traffic.** During its pass the sidecar still ran
  at the ~2 req/s pacing ceiling — identical instantaneous rate to the incident. What changed is that
  the pass *ends*: 465s of work per 3,600s cadence ≈ 11% duty vs >100%. Reporting "still at the rate
  limit" or "quiet now" would both have been true-but-misleading; the honest unit is duty cycle.
- **Every worker again corrected its brief, including mine.** The #212/#213 worker found the issue's
  central cost claim stale (the no-op *write* it described had already been eliminated by #109's
  parity skip; only the misreported outcome was real) and rejected the issue's suggested mechanism
  (`is_modified` after a function that flushes is always False). The #211 worker found the issue's
  "refuse overlapping passes" presumed a concurrency that does not exist — passes are sequential in
  one event loop; the defect was *start*-stamping the cadence. Four for four across two batches.
- **A batch that fixes the concurrency ceiling still runs under the old ceiling.** Batch A shipped
  #208's advisory lock, but its own three workers ran under the pre-#208 contract (one DB-capable
  worker, siblings unit-tier only, orchestrator's gate run authoritative). "We're fixing it in this
  batch" is not a licence to rely on the fix mid-batch.
- **`worktree-destroy.sh` cannot address harness worktree paths** (`.claude/worktrees/agent-*`;
  gregoryfoster/skills#149), and `git worktree remove` refuses any worktree whose submodules a worker
  initialized — `--force` is required, with `git branch -d` (not `-D`) left as the real merge guard.
- Fresh harness worktrees have **uninitialized submodules**, failing a skills-symlink test in the
  unit tier until `git submodule update --init`. Two workers hit it independently; brief it up front.
