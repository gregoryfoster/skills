# Backlog orchestration — the #182 followups and the budget-gate trap

Tracking issue: [#199](https://github.com/gregoryfoster/skills/issues/199)
Session: 2026-08-18 · Orchestrated with `orchestrating-issue-backlog`

## Goal

Clear the fifteen issues filed between 2026-08-17 16:49 and 23:44 — eleven surfaced by
the agents executing the #182 backlog, two by downstream cohort repos adopting
`curating-context` (power-map#444, observo#457), and two journaling the
CannObserv/replicator orchestration. Turn them into a merge-safe batch plan for four
worktree-isolated agents per batch, without letting any of the six files that sit
within one edit of a token gate acquire a second concurrent writer.

## Approved approach

- **Rubric**: `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Inherited
  from #182 (Q1), and the same justification holds: seven of the fourteen work items
  are one failure shape — *a tool asserting a guarantee it does not hold.*
- **Deployment context**: active production (Q2). Twelve cohort repos consume this
  repo on a daily auto-refresh.
- **Parallelism**: hybrid (Q4) — parallel within batches, a merge-and-test gate
  between them.
- **Concurrency ceiling: 4 per batch, host-bound** (Q5). **Third consecutive negative
  result for this repo** (after 2026-08-12 and 2026-08-16). Re-verified this session,
  both sub-questions:
  - *Worktree tooling*: `worktree-create.sh:90,92` is plain `git worktree add`.
  - *Shared backing services*: no `conftest.py` anywhere in `tests/`;
    `addopts = -m 'not integration and not benchmark'`; no test writes outside
    `tmp_path`. The Step 5 escape grep
    (`DROP SCHEMA|TRUNCATE|create_engine|create_async_engine`) returns hits **only
    inside `init-project-fastapi`'s scaffolding template for other repos** —
    `references/tests-scaffolding.md`, `assets/alembic-env.py` — never this repo's
    own suite. A grep that reads a skill's *output* as its *behaviour* is the false
    positive to expect in a repo whose product is templates.

  The cap is CPU/RAM for a 123-second suite × N.
- **Merge strategy**: regular merge commit, batch → `main`. Intra-batch
  worker → batch is fixed at fast-forward or regular merge regardless, so
  `worktree-destroy.sh --base batch/<X>` keeps its ancestor check.
- **Suite baseline on `main` (`b9c1eef`)**: **2562 passed, 151 skipped**, 123s, via
  `.venv/bin/python -m pytest tests/structural/`. Every worker brief carries this
  number with "stop and report if it does not match."

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** ×2 | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** ×3 | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** ×1 | Requires design discovery | Clear direction, minor decisions needed | Mechanical — obvious from the issue |

## Scored backlog

Final scores, after the decide-then-rescore pass at the approval gate.

| # | Issue | F | C | S | **Score** | Blast | Batch |
|---|---|---|---|---|---|---|---|
| **#190** | `init-project-fastapi` 43 exact tokens from breach; the exact gate is invisible | 3 | 3 | 2 | **17** | Med-High | A |
| **#184** | three unchecked reads in `measure-context.sh` + an awk that leaks its own error | 2 | 3 | 3 | **16** | Med | A |
| **#185** | `SKILL.md` teaches the command #176 fixed; the doctor is blind to the state it repairs | 1 | 3 | 3 | **14** | Med | A |
| **#192** | `install-cadence --check` reports a `merge=ours` guarantee that is inert | 1 | 3 | 3 | **14** | Med | A |
| **#193** | `skills-submodule-update.sh:237` lock write unchecked | 1 | 3 | 3 | **14** | Med | B |
| **#183+#197** | replicator planning + execution entries, **and** the index-by-year split | 2 | 2 | 2 | **12** | Med | B |
| **#194** | `score-cohort.sh` groups arms by the roster wave (5 sites) | 2 | 2 | 2 | **12** | Med | B |
| **#188** | `worktree-create` leaks git's stdout; `resolve-worktree-root` nests | 1 | 2 | 3 | **11** | Low | B |
| **#189** *(residual)* | evaluate `extensions.worktreeConfig`; attribution | 1 | 2 | 2 | **11** | Low | C |
| **#191** | Phase 6.5 never sweeps a doc→doc split; `--file` is ~69% noise | 1 | 2 | 2 | **10** | Med | C |
| **#186** *(narrowed)* | vendor `socraticode-reminder.sh` + install it as a symlink | 1 | 2 | 2 | **10** | Low-Med | C |
| **#195** | a tie scored as a loss is wrong for a bounded metric | 1 | 2 | 2 | **10** | Med | D |
| **#196** | two demotion self-links remain; `write-guard-hook.md` has no owner | 1 | 1 | 3 | **8** | Low | C |
| **#187** *(residual)* | `HEALTH_TIMEOUT_MS` help contradiction (60000 vs 120000) | 1 | 1 | 3 | **8** | Low | D |

### Q0 dispositions

- **#183 + #197 → bundled into one agent (B2), plus the index-by-year split.** They are
  *not* duplicates: #183 is the planning entry and #197 the execution addendum for the
  same CannObserv/replicator session, and the index already carries six `-execution`
  rows as separate entries. They are a matched pair landing in one file, and that file
  cannot hold them — see "The constraint neither issue states" below.
- **#187 → rescoped to residual.** Part 1 (the unchecked lock write) shipped in Batch D
  of #182; `socraticode-health.sh:168-171` now carries the checked `if !` form. Only the
  help contradiction remains.
- **#189 → rescoped to residual.** Directions 1, 2 and 4 shipped via #161's promotion
  into `SKILL.md:383,387`. Only direction 3 remains, and its stated risk is real:
  `extensions.worktreeConfig` is unset and this repo's `core.hooksPath` *is* an
  absolute path.
- **#186 → narrowed.** Half (a), vendoring `socraticode-reminder.sh` and installing it
  as a symlink, is in scope. Half (b), generalizing `install-refresh.sh` (435 lines)
  into a parameterized shared installer, is descoped to its own issue — it is a
  cross-skill refactor, not a fix.
- **#194 / #195 → scored independently and sequenced**, not bundled. Their windows in
  `score-cohort.sh` interleave, and #194 redefines what an arm *is*, which is the input
  #195's tie rule reads.

### Decisions taken at the approval gate

Three issues scored Scope Clarity 1 because the issue itself named an unresolved
decision. Each was decided here rather than handed to a worker, and re-scored.

1. **#190 — how the exact gate stops being invisible.** Chosen: print the margin in
   the *offline* failure message. **The obvious implementation does not exist**:
   `.skills/context-token-counts` holds four anchored paths, `AGENTS.md` and `docs/`
   only, with zero coverage of any `skills/*/SKILL.md` — which is precisely why the
   estimator runs 13% low on this file with no correction available. The deliverable
   is therefore the **band-derived worst case**: `POLICY_ESTIMATE_BAND = (-0.15, 0.15)`
   already exists at `test_skill_self_budget.py:319` and `:567` already uses it for
   stale-ratchet detection. The message should read the shape *"estimate 14,773 →
   worst case ~17,380 against a 17,100 ratchet; this file may already be over."*
   Rejected, and why it is worth keeping as a pointer rather than deleting: extending
   the per-file anchors to every SKILL.md (the issue's option 2) would make the
   estimate honest rather than the gate louder, but it is a larger change that touches
   the two calibration files #192 is simultaneously changing the merge driver for.
   S: 1 → 2.
2. **#195 — the saturation mechanism.** A registered metric that names its bound gets
   the saturated-not-tied treatment automatically; one that does not keeps today's
   behaviour, leaving closure and every unbounded metric unaffected. The
   pre-registration file (#117) is where the declaration lives, and it already refuses
   `wave` by name. Rejected: a blanket "ties are uninformative" rule, which would make
   the adoption rule easier to satisfy by discarding the pairs that disagree — the
   failure `rejected-changes.md` exists to record. S: 1 → 2.
3. **#189 — `extensions.worktreeConfig`.** The deliverable is a *verdict backed by
   evidence*, not an adoption: does setting it move where the absolute `core.hooksPath`
   resolves from inside a linked worktree? Pin whichever way it lands with a structural
   test, and record the decision. This is the only direction that would end the
   corruption class outright rather than detect it. S: 1 → 2.

## Conflict zones

| File | Issues | Windows | Required order |
|---|---|---|---|
| `curating-context/scripts/score-cohort.sh` | #194, #195 | #194 `:758-767, :878-879, :894-904, :916, :1019`; #195 `:771, :792, :814, :827` — **interleaved** | **#194 → #195** (B → D). A real dependency, not a convenience split |
| `curating-context/references/cadence.md` | #192, #196 | #192 § *"The ledger needs a union merge"* (`:63-101`); #196 `:395`, tail of § *"The workflow"* | Separated sections; split A → C anyway |
| `tests/structural/test_skill_self_budget.py` | #190, #183+#197 | #190 `:200` + `:388-400`; #183/197 `:260-290` | Separated, additions-only; split A → B |
| `tests/structural/test_context_surface.py` (3,798 ln) | #184, #192, #191, #194 | `TestEmptyPolicyFile:242` / `TestUnreadableDocInTheInventory:691` · `TestCadence*:3154-3630` · `TestCheckSeams:2219` / `TestSeam*:2401-2660` · `TestValidationGate*:1301-2218` | Separated class windows; **new tests route to new per-agent files** |
| managing-skills test trio | #185, #193 | `TestManagingSkillsHookCommand:286` vs `TestDoctorHealsHookSymlinks:403` | Separated; split A → B |
| `init-socraticode` | #186, #187 | #186 new script + `SKILL.md:174,344` + policy doc; #187 `socraticode-health.sh:62,80` + `mcp-driver.mjs:1067,1123` | Disjoint files; split C → D |

**Line ranges above were measured on `b9c1eef` and are stale by the batch that consumes
them.** Re-derive every window at launch. In Markdown, own the **named section**, not
the range.

### The constraint neither #183 nor #197 states, and it binds both

`references/process-log.md` measures **9,611 estimated against the 10,000 per-doc
budget — 389 tokens of margin.** #183's index row alone is ~573 estimated tokens;
#197's is ~120. #183's row breaches on its own; together they breach by ~300.

Neither issue mentions it, and `test_skill_self_budget.py:279-283` already anticipated
it and named the resolution: *"When it crosses, splitting it by year is the move — not
an exception."* B2 therefore delivers both entries **and** the split.

The split's blast is **Medium, not High**, and the difference is worth recording
because the raw grep said otherwise. `grep -rn process-log` returns hits in
`test_relative_links.py:242,252,367`, `test_content_invariants.py:1668`,
`test_references.py:18-25` — but the first three are **`tmp_path` fixtures** and the
rest are **docstrings**. Not one is an assertion about the real file. The only real
constraint is that `references/**/*.md` is globbed **recursively** (`#152`), so any new
year-index file is gated on reachability and must be linked from `process-log.md`,
which stays at its current path.

### Budget-constrained files — a conflict class no file grep shows

Six files sit within one edit of a gate. **Each has exactly one writer**, which
satisfies the "foundation shared files are read-only" rule by construction rather than
by declaration:

| File | Binding margin | Sole writer |
|---|---|---|
| `AGENTS.md` | **28 exact** / 6,000 | #189 (C1) |
| `init-project-fastapi/SKILL.md` | **43 exact** / 17,100 | #190 (A1) — whose job is to buy margin |
| `orchestrating-issue-backlog/SKILL.md` | **149 estimate** / 23,110 | **nobody — read-only for all fourteen workers** |
| `curating-context/SKILL.md` | **177 exact** / 7,600 | #191 (C2) |
| `references/process-log.md` | **389 estimate** / 10,000 | #183+#197 (B2) — whose job is the split |
| `init-socraticode/SKILL.md` | **412 exact** / 10,050 | #186 (C3) |

`AGENTS.md`'s 28 tokens is roughly one clause. C1's brief must say so: recording the
`extensions.worktreeConfig` verdict there means finding an offsetting trim, or putting
the record somewhere else and leaving a pointer.

## Dependency graph

```
#194 ─────────────▶ #195            the only true edge: the arm definition
 (arm = version)    (tie rule)      is the input the saturation rule reads
   B3                  D1

#190, #184 ───────▶ everything      not file overlap — these two ARE the
 (budget gate,      downstream      instrument every later batch's budget
  measurement)                      evidence is read from
   A1    A2

all others: independent
```

**#190 and #184 are the guards on this orchestration's own verification path.** Four
later items spend against token budgets, and #184 is the script those numbers come
from — it currently exits **1** with empty stdout on an unreadable file while its own
header promises *"Exit 2 on infrastructure failure so a caller can never mistake a
broken measurement for a clean one."* They score 17 and 16, so no priority inversion is
needed; this is why they lead rather than fill a slot. Same shape #183's own replicator
entry records ("the backlog contained the guards for its own deploy/CI path"), here on
the measurement tier.

### Provenance

**Followup-derived, dispersing CR-like rather than clustering.** The #182 cycle's
defects landed **one-per-skill-family** rather than in one partial, so eleven of the
fourteen work items have a sole owning file. #191 and #192 are **adoption-feedback**
from downstream cohort repos (power-map#444, observo#457) and land in the one family
that does cluster — `curating-context`, five items — which decomposes cleanly on the
owning-script axis: `measure-context.sh` / `install-cadence.sh` / `check-seams.sh` /
`score-cohort.sh` / `references/`. Confirmed by the contested-file grep, not inferred
from the provenance.

## Batch execution plan

| Batch | Agent | Issue | Owned surface | Gate |
|---|---|---|---|---|
| **A** | A1 | **#190** | `init-project-fastapi/SKILL.md` (trim) · `test_skill_self_budget.py` `:200`, `:388-400` | Start immediately |
| | A2 | **#184** | `curating-context/scripts/measure-context.sh` `:402`, `:475-476`, `slugs_of` awk | |
| | A3 | **#185** | `managing-skills/SKILL.md:136` · `scripts/doctor.sh` precondition | |
| | A4 | **#192** | `scripts/install-cadence.sh` `:265`, `:489` · `cadence.md` § *"The ledger needs a union merge"* | |
| **B** | B1 | **#193** | `scripts/skills-submodule-update.sh:237` · `test_checked_temp_writes.py` | After A merged |
| | B2 | **#183+#197** | two entry files · **index-by-year split** · `test_skill_self_budget.py:260-290` | |
| | B3 | **#194** | `scripts/score-cohort.sh` — the 5 arm sites | |
| | B4 | **#188** | `worktree-create.sh`, `resolve-worktree-root.sh`, `.gitignore:1-4` | |
| **C** | C1 | **#189** | repo git config · `AGENTS.md` (**28 tokens**) · new structural test | After B merged |
| | C2 | **#191** | `scripts/check-seams.sh:505` · `curating-context/SKILL.md` § Phase 6.5 | |
| | C3 | **#186** | new `init-socraticode/scripts/socraticode-reminder.sh` · `SKILL.md:174,344` · policy doc | |
| | C4 | **#196** | `cadence.md:395` · `write-guard-hook.md:259` · `test_self_links.py` | |
| **D** | D1 | **#195** | `score-cohort.sh` saturation · `validation-gate.md` · registration schema | After C merged |
| | D2 | **#187** | `socraticode-health.sh:62,80` · `mcp-driver.mjs:1067,1123` | |

**No intra-batch merge ordering is required** — every within-batch pair is
file-disjoint. The three same-file pairs are separated across batch boundaries instead.

## Key decisions

**`.skills/context-token-*` is read-only for every Batch A worker; brief `--no-write`.**
A1 and A2 will each plausibly run `measure-context.sh --exact` to check their work, and
`--exact` **recalibrates and rewrites** `.skills/context-token-ratio` and
`.skills/context-token-counts`. Two workers doing that concurrently race on committed
artifacts — and A4 (#192) is simultaneously changing those same two files' merge
driver, so a collision would land in exactly the file whose collision handling is
under repair. This is the manifest-read-only resolution from #183's own replicator
entry ("any repo with a committed index over its own docs has a shared backing
service"), arriving in a second repo by a different route.

**Verification-mode asymmetry in Batch A.** A2 changes `measure-context.sh`'s exit
codes; every budget test in the repo calls that script. A1 changes the failure message
those tests print. Each verifies in a worktree carrying only its own change, so **the
orchestrator's post-merge run on `batch/a` is the first execution where the new exit-2
paths meet the new message.** A red there is an interaction, not one agent's defect.

**`orchestrating-issue-backlog/SKILL.md` is read-only for all fourteen workers.** 149
estimated tokens against its ratchet, and the ratchet binds the estimate for this file.
Two things want it and both are orchestrator work after Batch D:

- #183's deliberately-deferred correction. `SKILL.md:82` reads *"Nine sessions across
  four projects"*; with the replicator session and this one it is **eleven across
  five**, and the shared service was the ceiling in eight of eleven.
- Whatever Step 10 promotes from this session.

Both need an offsetting trim, which is a deliberate edit and not a drive-by at the end
of an orchestration. #183 was right to flag rather than do it.

**This session's own Step 10 entry must land after B2's split**, or it appends to a
layout that no longer exists. B2 is also the sole appender to the index during the
batches — the one chain-appending agent, in the sense the skill's migration/ADR rule
means.

**A grep that reads a skill's output as its behaviour.** The Q5 escape grep returned
`DROP SCHEMA`, `create_async_engine` and `drop_all` hits in this repo — all inside
`init-project-fastapi`'s *template for other projects*. In a repo whose product is
templates, every hazard grep will hit its own documentation of that hazard. Read the
path before reading the match.

## Deferred items

- **#186's installer generalization** — refactoring `install-refresh.sh` (435 lines, of
  which ~400 are the generic two-artifact contract) into a shared installer taking a
  hook name, so refresh, health and reminder all call one mechanism. Deferred to its
  own issue: it is a cross-skill refactor landing in `managing-skills/scripts/` while
  the hooks live in `init-socraticode/`, and #179's implementing agent already declined
  to build it for the right reason — copy-pasting the contract guarantees the drift
  #179 is *about*.
- **#190's redesign of `init-project-fastapi`** — the file's own ratchet comment says
  what it would take (`DEPLOY_TARGET`, `DB_BACKED`, `ADMIN_UI`, `PRIVATE_WHEELHOUSE`
  each fork the procedure and every run loads all four to walk one). That is #96's kind
  of work. A1 delivers an interim demotion pass; 43 tokens cannot wait for a redesign.
- **#191's item 4** — a checker for prose `FILE § "Title"` references whose named file
  lacks that heading. The issue flags it as "possibly its own issue" and it is the one
  class no diff-based sweep would ever raise, since both offending refs were stale
  *before* the run that surfaced them. In scope for C2 only if it comes for free.
- **The `co-core` version disagreement** noted in #183's entry (replicator's
  `pyproject.toml` pinning `>=0.10,<0.11` against its AGENTS.md documenting
  `>=0.9.4,<0.10`) is a CannObserv/replicator issue, not one for this repo.

## Out of scope

- **Raising any ratchet.** Every tight file in the table is tight because a previous
  session argued the number in a diff. #190 buys margin by trimming, not by raising.
- **Adopting `extensions.worktreeConfig` without measuring it.** C1's deliverable is
  the verdict and the test, either way it lands.
- **Attributing the `core.bare = true` corruption to a specific agent.** Four
  occurrences across #182's Batches A and B, never reproduced outside subagent
  activity. #189's residual carries it as an open note, not as a deliverable.

## Runtime note on issue-body decay

This backlog is four sequential mutations of the tree the bodies describe. **Re-verify
the specifics of any issue whose files an earlier batch touched** (Worker step 5); the
later the batch, the staler the body. Concretely, already true at planning time:

- #187's body describes an unchecked lock write that **no longer exists** — it shipped
  in #182's Batch D between filing and now.
- #189's body asks for a Rule 6 hardening that **already shipped** via #161.
- #190's margin table is measured at `batch/b` tip of a *different* backlog;
  `curating-context` has since moved from 248 to **177** exact margin.
- #194's body enumerates four sites; its own comment adds a fifth
  (`attributed()` at `:1019`) introduced by #117 in the same batch. The body's
  enumeration was made against the pre-#117 file.

Every load-bearing number in a worker brief — a test count, a line window, a token
margin — is measured **at the revision the worker will branch from**, not carried from
the orchestrator's reading. A stale number in a brief is worse than an absent one: the
worker spends its first cycle reconciling it.
