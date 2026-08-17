## Session 2026-08-17 — CannObserv/watcher, #268 execution addendum

Execution half of [2026-08-17-watcher.md](2026-08-17-watcher.md). Three batches,
seven worker agents, three CR rounds, three production deploys. Eight issues
closed (one as already-done), three new filed (#269, #270, #271). The plan
survived contact; the *briefs* did not.

---

### 7 of 7 workers corrected their brief or issue body. Two would have shipped defects.

The skill already says the issue body is a proposal. This run says the same of
the **orchestrator's brief**, and the two failures were mine as much as the
issues':

- **#262's central premise was false.** It claimed `bus_client_from_env()` was
  "the single funnel both `get_shared_bus_client()` and every direct caller pass
  through". Two producers read the env var themselves and then
  `assert client is not None  # guarded by the env check above`. Gating only at
  the claimed funnel leaves that check passing and the client `None` — an
  `AssertionError`, or a publish on `None` under `python -O`. The agent found it
  by verifying the claim instead of implementing it.
- **My brief asked a question about a field that does not exist.** I told the
  #249 worker to decide whether a `not_modified` check "reuses the item's
  existing `content_fingerprint`". `WatchedItem` has no such column. The agent
  located the field before answering and reported the framing as incoherent.

Both were caught because the brief carried the *"I want the corrections, not a
report that matches the prediction"* clause. Worth keeping literally that
phrasing.

---

### The orchestrator's own CR finding was wrong, and a guard test caught it

CR round 1 finding: the dashboard's archive/restore/toggle-active routes don't
defer a fetch-policy republish, so a suspension travels on the 5-minute tick.
The gap was real. The *framing* — an oversight — was not: `src/dashboard/routes/
domains.py:47` carries a #245 NOTE stating dashboard mutations deliberately do
not defer, because the dashboard is decoupled from the task queue, **and names
the guard test that enforces it**. My fix failed that test.

I had briefed four agents on "read the artifact, not your model of it" and then
skipped it myself on my own finding. Generalizes to: **before writing a fix for
a review finding, grep the target file for a comment explaining the current
behaviour.** A finding that something is missing is much weaker evidence than it
feels, in a repo that documents its deliberate omissions.

Resolution: kept the API half, reverted the dashboard half, extended the NOTE to
record what the new issue costs there and which existing seam would close it.

---

### Deploy order belongs in the CR, not the deploy

Batch B dropped three columns. The code was correct and every test passed. But
the *previous* release still mapped those columns, and SQLAlchemy names every
mapped column in its SELECTs — so **AGENTS.md's documented default** ("After DB
model changes: `alembic upgrade head` then restart") would have dropped them out
from under the running process and failed every query against two tables.

Nothing in the diff was wrong. The defect was that the migration required
restart-before-migrate and *nothing said so* — while the repo's default said the
opposite, and `docs/DEPLOYMENT.md` already had two precedent sections for exactly
this shape (#251, #252) that this batch did not extend.

Promote to the review dimension: **when a migration drops or tightens something
the previous release still references, ask whether its required deploy order
contradicts the repo default, and whether that is written down.** A migration
can be correct and still be a production incident.

Verification that actually proved it afterwards, worth reusing: load the deployed
`Base.metadata` **offline** and diff each table's mapped columns against
`information_schema.columns`. No production DB connection from the app, no
guard-bypass, and it answers the only question that matters — "does the running
ORM still match the live schema". Came back clean across 12 tables.

---

### Scoping the riskiest agent *away* from production produced better work

Batch C (#259, PostgreSQL role split) was scoped to code, tests, docs and a
reviewed SQL script, and forbidden from `CREATE ROLE`/`GRANT` against the live
database or editing `/etc/watcher/.env`.

The constraint did not degrade the work — it *caused* the best work of the run.
Unable to just do it, the agent rehearsed: it booted the whole application on the
DML-only role against a scratch database, watched every periodic task reach
`succeeded`, and ran the exact committed bytes of its script twice for
idempotency plus once with the password unset. Two of its own drafting bugs fell
out of the rehearsal and would never have fallen out of review:

- `\warn` + `\quit` on a missing password exits **0** — indistinguishable from
  success to anything checking `$?`.
- `psql` does not interpolate variables inside single quotes, so `\echo 'x :var'`
  prints the literal.

It also inverted the issue's proposed design with a better argument: #259 wanted
a new `watcher_migrate` owning the schema; on a live database that means
reassigning 17 tables, 4 sequences, 18 routines and 41 indexes for **no extra
guarantee**, because the role being constrained is the application's. Keeping the
incumbent as the migration role makes the script purely additive and rollback an
env-file edit.

Rule of thumb: **for an issue whose risk is in the operator step, scope the agent
to everything but that step.** The deliverable becomes a rehearsed, reviewable
script instead of an accomplished fact.

---

### Environment discovery is orchestrator work, not worker work

Three of four Batch A agents independently lost time on the same three things,
none of which are in any doc:

1. The auto-provisioned worktree ships an **empty `.wheelhouse/`** (gitignored,
   so `git worktree add` cannot populate it) and **no `.env`** — so the first
   `uv` command fails to resolve `co-core`, and `scripts/load-env.sh` resolves
   `$(git rev-parse --show-toplevel)/.env` to a path that does not exist.
2. The harness **refuses `source scripts/load-env.sh`** outright — it will not run
   a string through `source` it cannot verify stays inside the worktree. The
   repo's own documented idiom is unusable in an isolated worktree.
3. **`grep` is shadowed by a shell function** that shells out to the Claude binary
   and dies with "Claude Code cannot be launched inside another Claude Code
   session". Every `grep` fails, intermittently enough to look like something
   else — I spent several tool calls this session diagnosing a phantom token
   permission problem and a phantom env-file guard before a worker found it.
   `command grep` and `rg` work.

Put the recipe in the brief for batch 2 onward. And **fix the recipe when it
draws blood**: my `rm -rf .wheelhouse && ln -s …` deleted a *tracked* `.gitkeep`,
which then made `worktree-destroy.sh` refuse. `cp` the wheels in instead.

---

### Two mechanical traps in the orchestrator loop itself

- **`git branch -d` from the main checkout always refuses** a worker branch that
  is merged into `batch/<X>`, because `-d` tests against **HEAD** — which is
  `main` here, since this repo deploys from the main checkout and its branch must
  never move. It is *not* the merge-safety signal SKILL.md treats it as in that
  position. Verify with `git merge-base --is-ancestor`, then delete from the
  integration worktree whose HEAD *is* the batch branch.
- **GitHub needs the closing keyword before every number.** `Closes #262, #256,
  #250, #260` closed exactly one issue. The rest needed explicit `gh issue close`.
- **And the parser has no notion of negation.** A merge message reading
  *"CR round 3 applied. Does NOT close #259 — the operator step remains."*
  **closed #259**, because `close #259` appears in it. The issue sat wrongly
  closed for two hours on the strength of a sentence saying the opposite. Never
  write a closing keyword adjacent to an issue number you do not mean to close —
  say "#259 stays open" instead. Cheap to hit, silent, and it desynchronises the
  tracking issue from reality precisely when a long run is hardest to audit.

Also: `gh` returned HTTP 503 on roughly a third of calls for a stretch. Every
`gh` invocation in a long orchestration wants a retry loop; a single failure
silently skips a write-back you will believe happened.

---

### A sibling repo moved underneath two settled decisions

`archiver#158` landed **during this run** (14:12 UTC) and retired Archiver's
outbound provisioning call to Watcher. `watcher_provisioning.py` — which I had
cited as evidence for the #260 decision at the scoring gate, and which a worker
cited again — no longer exists.

The decision survived (the *announcement* path still refuses spec-less sources,
and that was the load-bearing half), but two consequences did not:

- A cross-repo issue a worker recommended filing was moot: the code path it named
  was gone. **Re-verify a cross-repo finding against the sibling's current tree
  before filing**, not against the tree you read at planning time.
- `POST /api/v1/watched-items` now has no caller at all, which reframes the gate
  #260 shipped as guarding a door nobody walks through.

The planning entry's rule was "read the dependency's checked-in contract". The
execution corollary: **on a multi-hour run, that reading has a shelf life.** The
sibling checkout was also dirty mid-cutover the whole time — a signal worth
checking for, since it means someone is actively moving the ground.
