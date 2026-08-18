## Session 2026-08-17 — CannObserv/replicator

Five user-named issues (#17, #20, #25, #37, #44) → three batches (2+2+1), tracking issue #47,
design doc `docs/plans/2026-08-17-worker-hardening-backlog.md`.

### Interview answers

| Q | Answer |
|---|---|
| Q0 | #17/#25 candidate pair (both edit `_raise_for_status` + `errors.py`) → **score independently** |
| Q1 | Correctness-leaning → **(Foundation × 2) + (Correctness × 3) + Scope**, max 18 |
| Q2 | Early production — worker `enabled`+`active`, Watcher live as issuer since 2026-08-06 |
| Q3 | All five in scope; **#17 stops short of removing the conditional-GET doc warning** |
| Q4 | Hybrid |
| Q5 | **Ceiling 2** — set by host CPU/RAM/disk; neither worktree tooling nor a shared service |

Batch shape: **A = #37 + #44 → B = #17 + #20 → C = #25.** Batch→main: regular merge commit.

Scores: #17 = 17, #20/#37/#44 = 14, #25 = 9 → 10 after two gate decisions.

### Q5 — 10th recurrence, and the **second** true negative (across a 5th project)

At session time `SKILL.md` carried a hand-maintained tally — "Nine sessions across four
projects have found the real ceiling in sub-question 2" at `SKILL.md:82`, duplicated in the
Process Logs pointer as "nine recurrences across four projects … in all nine". After this
session it was **ten across five**, with the shared service the ceiling in **eight of ten**.
Not bumped here: the file is held at a 23,110-token ratchet, so the correction needed a
token-neutral trim elsewhere and that is a deliberate edit, not a drive-by. Flagged to the
user rather than done.

> **Resolved 2026-08-18 (#199, commit `8b116c4`).** Both copies of the tally were *removed*
> rather than bumped — "far more often in sub-question 2 than in 1" — which freed 10 tokens
> instead of spending any. A counter a runbook maintains by hand is a maintenance liability
> disguised as evidence; the dates on the Q5 provenance line already carry the evidence. See
> `2026-08-18-skills.md`. (The issue that filed this entry cited "SKILL.md line 451"; the
> file was 429 lines and the claim lived at `:82` and `:419`.)

Both sub-questions came back negative, and both were *checked* rather than assumed:

- **Worktree tooling:** `worktree-create.sh` is plain `git worktree add` + the Iron Law check.
- **Shared backing services:** `addopts = -m 'not integration'`, default suite hermetic on
  fakeredis, `tmp_path` blobs, no Postgres (`ci.yml:151` says so). **The integration suite
  answered sub-question 2 in prose** — `tests/worker/conftest.py:242` mints
  `replicator.itest.<uuid4>` per test and its docstring explains why: *"The uuid keeps
  concurrent runs … from colliding on a group whose PEL would otherwise leak."* First session
  where a repo's own conftest pre-answered the ceiling question; **read the integration
  conftest's docstrings before running the escape-helper grep.**

**5th distinct ceiling driver, and the first that is a *compound*:** 2 cores + ~1 GB available
RAM + 2.7 GB free disk at 85% + a 181 MB `.venv` per worktree. cli (2026-08-13) found disk
alone; here no single resource forbids 3 agents but the combination does, and the failure mode
is an OOM kill mid-`pytest` — which presents as an unrelated mysterious red, the same
signature as the shared-fixture-escape hazard. Also worth capturing: `[tool.uv] find-links =
["./.wheelhouse"]` is **repo-relative**, so each worktree needs its own wheelhouse mirror
(ADC round-trip) or a symlink — a per-worker setup cost that belongs in the brief, not in the
ceiling.

### A DB-free repo still had a shared backing service — the semantic-search index

**New instance of Step 5's shared-fixture-*escape* hazard in a repo the prescribed grep cannot
find it in.** The grep the skill specifies (`DROP SCHEMA|TRUNCATE|create_engine|
create_async_engine`) returns nothing here — Replicator is DB-free by charter.

The shared service is SocratiCode: a local Qdrant store plus an on-disk graph, with
`.socraticodecontextartifacts.json` as its committed manifest. Three of the five issues
(#17, #37, #44) edit manifest-described artifacts — AGENTS.md, `docs/ARCHITECTURE.md`, both
contract docs, `docs/DEPLOYMENT.md`, `deploy/replicator.service`,
`.github/workflows/ci.yml`. Two compounding hazards:

1. The manifest is **one JSON file** three agents have reason to edit.
2. AGENTS.md's own policy says nothing re-embeds it, so the prescribed fix is a
   `codebase_context_index` re-run — **and that writes to the shared Qdrant store**, so two
   workers doing it concurrently race on a genuinely shared service.

Resolution: **manifest read-only for every worker; the orchestrator re-indexes once,
post-merge, per batch.** Avoided rather than provisioned around, so the ceiling is unaffected.

Generalization worth one clause if it recurs: **any repo with a committed index over its own
docs has a shared backing service, whatever its database situation.** The Q5 grep is
database-shaped; the property is "a store outside the worktree that a worker writes to".

### Same-function overlap is **not** always a Shape-A bundle signal

2026-08-13 cannobserv logged *"same-function overlap is the sharpest Shape-A signal yet"* (two
issues editing `test_write_bodies.py:22-23`). Four days later the same geometry took the
opposite verdict, and the discriminator is clean:

#17 and #25 both edit `_raise_for_status` (`src/worker/handler.py:638-657`, 20 lines). Verdict
was **Shape B / sequence**, because #25's edit is *structural*: the function takes
`(result, command)` with no pacer, and `TransientFetchError(detail)` at `:653` carries no
status code, so reaching the pacer — and reaching `result.headers` for `Retry-After` — means
changing the signature or that construction. Step 5's own line-window rule already forbids
restructuring inside a shared window; the same prohibition decides Shape A vs B.

**Refinement: same-function overlap is a bundle signal when both edits are additions, and a
sequencing signal when either must restructure the function.** They also differed in kind
(a new terminal outcome vs a stateful pacing mechanism), which the 2026-05-11 "differ in kind"
clause already covers — but "differ in kind" is a judgment call and "one of them changes the
signature" is not. One sighting; logged, not promoted.

### The hedge-grep trap fired again — caught before publishing this time

2026-08-12's lesson verbatim: *an orchestrator's own quick grep is exactly as falsifiable as
the issue body it audits, and it carries more authority because it arrives as a correction.*

#25 says its decay should mirror Watcher's `_maybe_decay_backoff`. My first instrument —
`grep` over the retired `rate_limiter.py` at one commit — found nothing, and I was one step
from reporting "the method never existed". It exists. `git log --all --oneline -S` found it in
three commits; it lived in `src/workers/pipeline.py:74`, not the rate limiter, and is
**DB-backed** (SELECTs a `Domain` row, reads `decay_window`/`min_interval`/`last_request_at`,
writes back).

What made the difference was **widening the instrument rather than trusting the first
negative**: `git log --all -S<symbol>` plus `git grep <symbol> $(git rev-list --all)`. Stated
as a rule: **an absence claim about a *deleted* artifact needs a history-scoped instrument,
not a tree-scoped one.** A tree grep can only ever say "not here now".

The correction mattered: the truth is *worse* for #25 than either reading. There is nothing to
mirror — Replicator is DB-free, so the decay has to be re-derived as in-memory state, which
is most of why the issue scored Scope Clarity 1.

### New body-decay class: an issue that exists *because* of a migration cites pre-migration paths

#25's entire Refs block points at `watcher/src/core/rate_limiter.py`. That file was deleted by
`2b98989` — watcher#241 step 5, *"retire the local fetch path and the rate limiter"* — which is
**the very cutover #25 exists to compensate for**. The issue is a correct reaction to a
migration, filed against paths the migration removed.

Recoverable only as `git show <commit>^:<path>`. Two of the four constants #25 depends on were
not in it anyway: a hard floor of `2.0` on the first escalation
(`max(current * BACKOFF_MULTIPLIER, 2.0)`), and `DEFAULT_DECAY_WINDOW = 1800.0`, which lives in
`src/core/models/domain.py:14`. Both recovered and written into the design doc so the worker
does not re-derive them.

**Heuristic: when an issue's rationale is "sibling X is losing capability Y", its references to
X are dated by construction — check them against X's HEAD first, and expect deletion rather
than drift.** Distinct from ordinary staleness: nothing edited these paths, they ceased to
exist as the intended outcome.

### The backlog contained the guards for its own process — 2nd recurrence

2026-08-13 usa-wa: *"the backlog contained the fix for its own ceiling"* (a shared-test-DB issue
inside the named set). Same shape here on the **deploy/CI** surface rather than the test tier:

- **#37** is the guard that `replicator.service` refuse a non-`main` checkout — i.e. the
  enforcement of the invariant Orchestrator step 2 requires of *this* orchestration, on the
  exact checkout it runs from (`WorkingDirectory=/home/exedev/replicator`, unit `enabled` and
  `active`).
- **#44** is what makes each batch's merge commit actually receive a CI run.

Consequence: **#17 at 17/18 waited behind two 14s.** Justified as sequencing, not inverted
priority — the existing "a trivial issue can be a hard gate" and "a zero-conflict issue is a
slot-filler" variants both apply, and #37/#44 had zero contested files with anything. But the
sharper framing is worth a clause: **when the backlog contains guards on the orchestration's
own deploy or verification path, they go in Batch A regardless of score, because every later
batch's evidence depends on them.** Two sightings now (test ceiling, then deploy/CI) →
promotion candidate; both currently reachable from Key Principles by inference rather than
statement.

Also from #37: its guard needs a **post-merge operator step no worker can take** — AGENTS.md
says the installed unit is a `cp`, not a symlink, so `sudo cp deploy/replicator.service
/etc/systemd/system/ && sudo systemctl daemon-reload`. A guard living only in the repo's copy
is not a guard. Recorded in the plan's Key Decisions along with usa-wa's
`systemctl is-enabled` / `systemctl cat` precaution.

### Smaller things

- **Verifying an issue's own version claim audited the policy file for free.** #17 argued
  shape A ships against `co-core >=0.7.7,<0.8`. Checking that turned up `pyproject.toml:32`
  pinning `>=0.10,<0.11` *and* **AGENTS.md documenting `>=0.9.4,<0.10`** — a live disagreement
  between the policy file and the manifest of record, unrelated to all five issues. Filed into
  the plan's Deferred as deserving its own issue. The issue's *reasoning* survived: I confirmed
  `FetchFailedEvent.model_fields["reason"].annotation` is still plain `str` on the installed
  0.10.0, so A still needs no bump.
- **A withdrawn requirement in a comment thread is still load-bearing.** #17's 2026-08-10
  comment asserted an Archiver dependency; the 2026-08-10 follow-up withdrew it — *and*
  recorded why, which is a design fact worth keeping (`blob_available` reports that bytes
  arrived, not that the item was observed). Read retractions for what they explain, not just
  for what they cancel.
- **`origin/main` was one commit behind local `main`** at Step 1–2 (`04ba17a chore: update
  skills submodules`). Rule 1's `git pull --ff-only` reports "Already up to date" and says
  nothing about it, because the divergence runs the other way. Workers' worktrees are cut from
  `origin/main`, so this must be pushed before Batch A or every worker gets a tree missing it.
  **Rule 1's check is one-directional — also compare `git log origin/main..main`.**
- **Bash `grep` against the skill's own `SKILL.md` path was blocked by a hook** ("Claude Code
  cannot be launched inside another Claude Code session"), while `ls` on the same directory
  succeeded. Used the Read tool instead. Worth knowing at Step 10 in any repo that vendors
  these skills as a submodule.
- **Five issues at ceiling 2 is three batches under every grouping** (2+2+1), so the grouping
  choice was about *which* pairing, not batch count. Two candidate shapes were offered with
  ASCII previews: guards-first (one documented line-window split in `loop.py`) vs.
  zero-intra-batch-overlap (guards later, one idle slot). The user took guards-first. Offering
  both with the cost named made a genuine tradeoff decidable in one question.
