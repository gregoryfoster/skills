# Backlog orchestration — the silent-success class

Tracking issue: [#182](https://github.com/gregoryfoster/skills/issues/182)
Session: 2026-08-16 · Orchestrated with `orchestrating-issue-backlog`

## Goal

Clear the follow-up backlog accumulated between 2026-08-13 and 2026-08-16 — fifteen
open issues filed during the #155 batch cycle, the #163 cadence dogfood, the two
cohort pilots, and the four-round #178 review. Turn it into a merge-safe batch plan
that four worktree-isolated agents can execute in parallel without stepping on the
three genuinely contested surfaces: a policy file with 74 tokens of headroom, a
ratchet file that three agents are a paragraph away from being forced into, and a
validation-gate reference doc claimed by three different issues.

## Approved approach

- **Rubric**: `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Correctness
  weighted ×3 (Q1).
- **Deployment context**: active production (Q2). Twelve cohort repos consume this
  repo on a daily auto-refresh, so a defect propagates before anyone re-runs an
  installer. Favours narrow, well-tested fixes over restructuring.
- **Parallelism**: hybrid (Q4) — parallel within batches, a merge-and-test gate
  between them.
- **Concurrency ceiling: 4 per batch, host-bound** (Q5). There is **no provisioning
  ceiling**: no custom worktree-create script (plain `git worktree`), no shared
  database, no Redis, no port pool, no Docker, no `conftest.py`, and no test writing
  outside the repo. Verified by grep over `tests/`, `pyproject.toml` and
  `requirements-test.txt` for `docker|POSTGRES|DATABASE_URL|redis|PORT_POOL`. This is
  the second negative result for this repo (the first was 2026-08-12) — the cap is
  CPU/RAM for a 102-second suite × N. Four also keeps concurrent
  `SKILL_BUDGET_EXACT=1` API calls, which share one `ANTHROPIC_API_KEY`, well under
  any rate limit.
- **Merge strategy**: regular merge commit, batch → `main`. Intra-batch
  worker → batch is fixed at fast-forward or regular merge regardless, so
  `worktree-destroy.sh --base batch/<X>` keeps its ancestor check.
- **Suite baseline on `main` (`1bf970b`)**: **2250 passed, 127 skipped**, 102s, via
  `.venv/bin/python -m pytest tests/structural/`. Every worker brief carries this
  number with "stop and report if it does not match."

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** ×2 | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** ×3 | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** ×1 | Requires design discovery | Clear direction, minor decisions needed | Mechanical — obvious from the issue |

**Why Correctness ×3.** Seven of the fifteen issues are one failure shape: *a tool
asserting a change it did not make.* #181's success line after a failed write,
#176's exit-0 that consumes the day's lock without advancing a pointer, #177's
driver that exits 0 having printed nothing, #180's hook that cries wolf on every
worktree session, #162's always-in-context policy file naming gates that do not
exist, #156's worker reporting a green suite that collected 125 fewer tests, #157's
gate that dies before printing the JSON its own observability fix needs. Weighting
correctness sorts that class to the top, which is where it belongs in a repo twelve
others pull from daily.

## Scored backlog

Final scores, after the decide-then-rescore pass at the approval gate.

| # | Issue | F | C | S | **Score** | Blast | Batch |
|---|---|---|---|---|---|---|---|
| **#181** | temp-file write reports success when it failed — sweep + convention | 3 | 3 | 2 | **17** | Med-High | D |
| **#176** | `skills-submodule-update.sh` no-ops on uninitialized submodules | 2 | 3 | 3 | **16** | Low | A |
| **#162** | AGENTS.md claims two `references/` gates that do not exist | 2 | 3 | 3 | **16** | Low | B |
| **#177+179+180** | init-socraticode hook: silent no-op, copy-not-symlink, wrong path | 2 | 3 | 2 | **15** | Med | A |
| **#156** | harness worktrees have no `.venv`; green suite, rejected commit | 2 | 3 | 2 | **15** | Med | A |
| **#118+#168** | steady-state metric + longitudinal unit + wave A/B retirement | 3 | 2 | 1 | **13** | High | C |
| **#157** | unreadable `.md` kills the doc-inventory loop | 2 | 2 | 3 | **13** | Low | A |
| **#169** | `--base HEAD` makes the moved-title seam class unreachable | 2 | 2 | 2 | **12** | Med | B |
| **#159** | `ESTIMATE_BAND` pins only the 18 SKILL.md files | 1 | 2 | 2 | **10** | Low-Med | B |
| **#158** | demoted blocks drift by omission; three carry transit damage | 1 | 2 | 2 | **10** | Med | C |
| **#117** | pre-register a metric per experiment | 1 | 2 | 2 | **10** | Med | D |
| **#161** | orchestrating-issue-backlog execution addendum | 1 | 2 | 2 | **10** | Med | B |

### Dispositioned before scoring

**#164 — closed as done.** Not stale-looking; it had to be greped. Anchor resolution
shipped **2026-08-11** in `33c43cd` ("#120 #124 fix: resolve a link's `#fragment`
against the target's headings"), three days *before* #164 was filed on 2026-08-14.
It covers every item in the issue's "Suggested shape" plus both implementation notes
the issue said cost it a false-positive round: one-for-one space substitution with
the double-hyphen case (`measure-context.sh:767-769`), duplicate-heading `-N`
suffixes computed **per file** rather than per pre-split document
(`measure-context.sh:806-807`), the scope note's same-file fragments (`:911-915`),
the archival exclusion (`:100`), and the exact plumbing it proposed —
`links.dead_anchors` → Phase 6 assertion → `links_dead_anchors` telemetry →
`score-cohort.sh` gate — with `tests/structural/test_context_anchors.py` covering the
class.

The issue was filed from `CannObserv/cannabis.observer-wordpress`, **pinned at skill
v1.3**. The green pipeline the reporter observed was real; it was the consumer's
pinned version, not the skill's current state. *A defect report from a cohort repo
carries that repo's pin, not this repo's `main`.*

**#163 — deferred with a recorded reason.** Part 1 is complete and verified (#165
proved fresh-install and no-op, #166 proved the update path and cleared the
`checkout@v4` deprecation; the ledger carries real `baseline:scheduled` rows). Part 2
is gated on this issue's *own* stated condition — "#457 going green, with the four
coexistence answers" — and `CannObserv/observo#457` is **still open**. The blocker
sits outside this repo and outside the named set, so a batch slot allocated here
would have been dead work.

### Decide-then-rescore at the approval gate

Four issues scored low on Scope Clarity *because the issue itself named an
unresolved decision*. Each was settled at the gate and written back to GitHub, not
left for a worker to resolve as if it were an implementation detail.

| Issue | Decision | Effect |
|---|---|---|
| **#162** | Option 2 — make the text true; no new structural test | Scope 2→**3**, score 15→**16**, blast Med→**Low** |
| **#161** | Promote **net-neutral**; do not raise the 23,110 ratchet | Scope 1→**2**; keeps #161 file-disjoint from #159 |
| **#169** | Option 2 — give the cadence a real base | Scope 1→**2**; makes seam accrual registrable by #118 |
| **#118 / #168** | Bundle; decide the arm predicate **once** | Two items → **one**; resolves a live contradiction |

The #118/#168 bundle is the one worth restating. The two issues contradict:
#168 argues the wave split is unrecoverable, while #118's own last comment shows CI
resolves the *committed gitlink*, so for scheduled runs a pin **does** hold a version
and the paired design survives if #100's selective pin is installed. Deciding that
twice, in two branches, across the **106** `wave:`/`pair:` references in
`score-cohort.sh`, is how the roster and the scorer end up disagreeing.

## Conflict zones

### Footprint corrections from the bidirectional grep

The grep ran in both directions, and moved two issues in opposite directions.

**#181 overstates — the sweep is 7 files, and 3 are read-only for it.** Enumerated
with `grep -rln '\.tmp' skills/*/scripts/ scripts/ .claude/hooks/`:

| File | Disposition |
|---|---|
| `curating-context/scripts/install-guard.sh:179-180` | **FIX** — the confirmed instance |
| `managing-skills/scripts/install-doctor.sh` | **AUDIT** — the only genuinely new territory |
| `curating-context/scripts/context-budget-guard.sh:126` | **LEAVE** — the deliberate `|| true` |
| `managing-skills/scripts/install-refresh.sh` | **REFERENCE** — fixed in #178 |
| `curating-context/scripts/install-cadence.sh` | **REFERENCE** — fixed in #178 |
| `managing-skills/scripts/skills-submodule-update.sh:107` | **READ-ONLY** — named as already correct |
| `init-socraticode/scripts/socraticode-health.sh:102` | **READ-ONLY** — named as already correct |

So #181's **write** set is disjoint from every other issue. Its **verification** is
not: the last two rows are edited by #176 and the socraticode bundle. That
asymmetry, not file contention, is what puts #181 last.

**#162 names one file and needs two read.** `docs/CONVENTIONS.md:60-66` states the
*same four* `references/` rules — and is **already honest**, citing
`test_references.py` for the linked-from-SKILL.md rule and
`TestConditionalBlockMarkers` for delimiters while stating "No frontmatter" and
"`lowercase-kebab.md`" as bare bullets with no enforcement claim. `AGENTS.md` is the
only wrong file, but the fix is *mirror the discipline the convention doc already
uses*, not invent a phrasing. `CONVENTIONS.md` is read-only.

### Contested files and their resolution

| File | Claimants | Windows | Merge order |
|---|---|---|---|
| `AGENTS.md` — **5,926 / 6,000 tokens** | #162, #156, #181 | References L175–196 · Dev setup L237–269 · Scripts L108–144 | **One writer per batch**: #156 (A) → #162 (B) → #181 (D) |
| `skills/curating-context/references/validation-gate.md` (446 L) | #118+#168, #158, #117 | L28–192 · L302–308 · L309–391 | #118+#168 (C) → #158 (C) → #117 (D) |
| `skills/curating-context/references/telemetry.md` (220 L) | #118+#168, #158 | Row schema L20–42 · L138–149 | #118+#168 first within C |
| `skills/curating-context/scripts/record-telemetry.sh` | #169, #118+#168 | measured-commit field · `commits_since` field | #169 (B) → #118+#168 (C) |
| `skills/curating-context/scripts/score-cohort.sh` | #118+#168, #117 | verdict ladder + roster reads · adoption rule | #118+#168 (C) → #117 (D) |
| `tests/structural/test_context_surface.py` (1,745 L) | #157, #181, #118+#168 | measure regions · `TestSharedLibrary` 331–415 · `TestRosterAnnotations` 1424 + `TestValidationGate*` | separated class windows |
| `tests/structural/test_content_invariants.py` | #156, #161, #176 | 347–458 · 547–575 · 1208+ | separated class windows |
| `tests/structural/test_skill_self_budget.py` | #159 owns | — | **read-only for all others** |

**The file-level pass returned "everything touches everything"** — `test_context_surface.py`
and `test_content_invariants.py` are hub files that every issue's grep hits, because
they scan the whole surface. Escalating to class/region granularity resolved both
into cleanly separated windows. A hub file is a set of independent regions; the
governing property is whether the *windows* overlap, not whether the file is shared.

**Non-test shared files carry one extra clause**: additions within the window only,
**no restructuring**. A reorder merges cleanly and silently reshuffles another
agent's window. This applies to `AGENTS.md`, `validation-gate.md` and `telemetry.md`.

### The ratchet headroom is the hidden constraint

`tests/structural/test_skill_self_budget.py` is not contested by file overlap — it is
contested by *consequence*. Measured against current sizes:

| Skill | Ratchet | Current (est.) | Headroom | Claimed by |
|---|---|---:|---:|---|
| `orchestrating-issue-backlog` | 23,110 | 23,097 | **13** | #161 |
| `init-socraticode` | 10,050 | 9,797 | **253** | #177+179+180 |
| `curating-context` | 7,600 | 7,294 | 306 | #169, #118+#168, #158 |
| `managing-skills` | 8,750 | 8,189 | 561 | #176, #179 |

Three agents are one paragraph away from being forced to edit #159's file. Hence the
read-only declaration below.

## Dependency graph

```
Batch A — no inbound edges
   #176        managing-skills --init
   #177+179+180  socraticode hook trio
   #157        measure-context redirect
   #156        worktree .venv          ─┐ front-loaded: every later batch's
                                        │ workers hit this defect at commit time
                                        │
Batch B ────────────────────────────────┘  (gate: AGENTS.md single-writer)
   #162        AGENTS.md honesty
   #159        ESTIMATE_BAND
   #161        orchestrating addendum
   #169        cadence real base  ──────────┐
                                            │  no file overlap shows this edge:
Batch C ────────────────────────────────────┤  #118 registers seam accrual as
   #118+#168   arm predicate + roster  ◄─────┘  primary; #169 decides whether
                                        ─┐     that metric can accrue at all
   #158        demoted-block repair      │
                                         │
Batch D ─────────────────────────────────┘  (gate: arm predicate defined)
   #117        pre-registration          ◄──  needs #118's arm predicate
   #181        temp-file sweep           ◄──  needs a SETTLED tree, not a free slot
```

Three edges. Two of them are invisible to any contested-file grep:

1. **`#169 → #118`.** #118's review recommends **seam accrual** as the default
   primary metric, on the grounds that of the five candidates it is the only one
   measuring something the skill uniquely controls. #169 shows that under
   `--base HEAD` one of its four classes — moved-title — is structurally zero in
   every scheduled run, forever. Registering the metric before that decision
   registers a metric that partly cannot move: the same category error #117 exists
   to document.
2. **`everything → #181`.** #181 scores **17/18**, the highest in the backlog, and
   goes last. Its deliverable is a *measurement of the final state*; run early it
   certifies a tree that no longer exists at merge time. Score determines what gets
   done; ordering constraints determine when.

## Batch execution plan

| Batch | Issues | Agents | Gate | Branch |
|---|---|---|---|---|
| **A** | #176 · #177+179+180 · #157 · #156 | 4 (parallel) | Start immediately | `batch/a` |
| **B** | #162 · #159 · #161 · #169 | 4 (parallel) | After A merged to `main` | `batch/b` |
| **C** | #118+#168 · #158 | 2 (parallel) | After B merged to `main` | `batch/c` |
| **D** | #117 · #181 | 2 (parallel) | After C merged to `main` | `batch/d` |

Max concurrency 4 = the ceiling. No chunking required in any batch.

### Batch A — four independent surfaces

| Agent | Issue | Owned files |
|---|---|---|
| A1 | #176 | `skills/managing-skills/scripts/skills-submodule-update.sh`, `tests/structural/test_skills_update_hook.py`, `test_content_invariants.py` L1208+ |
| A2 | #177 + #179 + #180 | `skills/init-socraticode/scripts/mcp-driver.mjs`, `scripts/socraticode-health.sh`, `skills/init-socraticode/SKILL.md`, `tests/structural/test_socraticode_graph_yield.py`, optional new `scripts/install-health.sh` |
| A3 | #157 | `skills/curating-context/scripts/measure-context.sh`, `tests/structural/test_context_surface.py` (measure regions), `test_context_anchors.py` |
| A4 | #156 | `skills/using-git-worktrees/scripts/worktree-create.sh`, `.pre-commit-config.yaml`, **`AGENTS.md` L237–269**, `test_content_invariants.py` L347–458 |

**A2 is the Shape A bundle.** #177's own "two follow-ons once fixed" are literally
#179 (install mechanism) and half of #180 (resolution order). Three defects in one
hook's install-and-resolve path, reviewed once. Sequential commits: fix the driver's
realpath guard, then the hook's project path, then the install mechanism.

**A4 is front-loaded despite scoring below A1.** `.pre-commit-config.yaml:5` is
`bash -c 'source .venv/bin/activate && pytest tests/structural/ -v'` — the exact line
that rejects a finished commit in a harness worktree after a green suite. Fixing it
first partially retires a brief line Batches B–D would otherwise carry. Only
partially: harness worktrees do not run `worktree-create.sh`, so the `ln -s` remedy
stays in every worker brief regardless. A4 does **not** remove that instruction.

### Batch B — the ratchet batch

| Agent | Issue | Owned files |
|---|---|---|
| B1 | #162 | **`AGENTS.md` L175–196 only**; reads `docs/CONVENTIONS.md` |
| B2 | #159 | `tests/structural/test_skill_self_budget.py` |
| B3 | #161 | `skills/orchestrating-issue-backlog/SKILL.md`, `references/process-log/2026/`, one row in `references/process-log.md`, `test_content_invariants.py` L547–575 |
| B4 | #169 | `skills/curating-context/scripts/install-cadence.sh`, `references/cadence.md`, `.github/workflows/context-cadence.yml`, `scripts/check-seams.sh`, `scripts/record-telemetry.sh`, `tests/structural/test_cadence_rendered_shell.py` |

**B3 is the batch's only chain-appending agent** — `references/process-log.md` takes
one row per session. The orchestrator adds this backlog's own Step 10 row after
Batch D, not concurrently.

**B4 must move three files together.** The cadence workflow template exists in three
copies by design — the renderer in `install-cadence.sh`, the annotated block in
`references/cadence.md`, and this repo's rendered
`.github/workflows/context-cadence.yml`. `TestCadenceTemplateMatchesTheRenderer`
pins them and has already caught one attempt where only a comment's wording differed.

### Batch C — one decision, one repair

| Agent | Issue | Owned files |
|---|---|---|
| C1 | #118 + #168 | `.skills/cohort`, `scripts/score-cohort.sh`, `scripts/record-telemetry.sh`, **`validation-gate.md` L28–192**, **`telemetry.md` L20–42**, `test_context_surface.py` (`TestRosterAnnotations`, `TestValidationGate*`) |
| C2 | #158 | `references/cohort-patterns.md`, **`validation-gate.md` L302–308**, **`telemetry.md` L138–149**, `tests/structural/test_demoted_blocks.py` |

**Intra-batch ordering: C1 merges into `batch/c` first**, C2 second. The windows are
separated (110 lines apart in `validation-gate.md`), so either order merges
textually — but C1 owns the earlier windows and is the larger change, so reviewing
it as the base is cheaper.

**C1's twelve per-repo adoption issues are explicitly out of scope.** They belong to
#163, whose gate is still closed. Cross-repo work is filed as issues, never
committed across repos.

### Batch D — the closing sweep

| Agent | Issue | Owned files |
|---|---|---|
| D1 | #117 | `scripts/score-cohort.sh`, **`validation-gate.md` L309–391**, new `.skills/experiments/NN-<slug>.yml` |
| D2 | #181 | `scripts/install-guard.sh`, `scripts/install-doctor.sh`, **`AGENTS.md` L108–144**, optional new structural test |

**D2's structural-test checkbox has a sanctioned negative outcome.** The issue's own
framing: `TestShellcheck` cannot catch this, a grep-based rule is the honest ceiling,
and *if it proves too noisy to be useful, say so in the issue and settle for the
convention.* Reporting "too noisy, here is why" completes that checkbox. Any rule
that does ship needs an exemption mechanism, not a flat ban —
`context-budget-guard.sh:126` is a legitimate `&& mv … || true`.

## Key decisions

**1. `tests/structural/test_skill_self_budget.py` is read-only for every agent except
B2 (#159).** The governing property is "one file every agent's verification depends
on." Four agents across three batches edit a `SKILL.md` whose ratchet lives there,
and the thinnest headroom is **13 tokens**. Any agent whose edit would exceed its
ratchet **trims to fit** — it does not edit the ratchet. Route a genuine raise as a
small post-merge PR after Batch D, with the argument written into the file's comment
per the precedent it already documents.

**2. `AGENTS.md` gets one writer per batch, and the constraint is tokens, not lines.**
The three claimants occupy separated line windows, so git would merge them cleanly —
and the file would still bust its 6,000-token budget with three concurrent additions
against 74 tokens of headroom. Sequencing them across batches lets the orchestrator
re-measure at each gate. #162's edit is a **reword** and must be token-neutral or
net-negative; #156 and #181 get roughly one sentence each.

**3. #118 and #168 are bundled because they contradict.** Not merely because they
share files. #168's premise (the wave split is unrecoverable) is challenged by
#118's own last comment (CI resolves the committed gitlink, so a pin holds a version
for scheduled runs). One agent decides whether arms are **assigned** (staged by pin,
prospective, needs #100 installed) or **observed** (per-row `skill_version`,
observational). Everything else follows: what `.skills/cohort`'s header says, what
`score-cohort.sh` does with 106 `wave:`/`pair:` references, and whether #118's
honest-accounting downgrade can be softened. Neither branch removes #100's pin
mechanism.

**4. #181 is last despite the highest score.** A sweep's deliverable is a measurement
of the final state. Its write set is disjoint and it could run in Batch A; but two of
the seven files its sweep certifies are edited by A1 and A2, and a new unchecked
write introduced there would land after the sweep declared the library clean. Blast
radius did not put it last — epistemics did.

**5. #156 runs before the batches that depend on it, not where it scored.** A
zero-conflict issue is the most schedulable thing in a backlog, so it fills whichever
slot would otherwise idle. Here it does better than idle-filling: it repairs the
commit-time failure every subsequent worker would hit.

**6. Verification-mode asymmetry in Batch B.** B2 (#159) changes `ESTIMATE_BAND`.
B1, B3 and B4 verify in their own worktrees under the **old** band; the orchestrator's
post-merge run at the B gate is the first under the new one. B3 additionally changes
the *size* of a file that band assesses. **If an estimator-band failure appears at the
B gate, it is an interaction, not one agent's defect** — do not attribute it to
whoever signalled last.

**7. Worker self-verification is narrower than the orchestrator's, and #156 does not
fully fix that.** Per #156's own comment from the `observo` #447 session: worker
worktrees ran green while collecting ~125 fewer tests than the orchestrator on the
same commit. Every worker prompt in this backlog therefore requires the **collected
count**, not just pass/fail, in the completion report — so the gap shows up at signal
time rather than at merge, or never.

## Runtime note on issue-body decay

Issue bodies are a snapshot of filing time; this backlog is twelve sequential
mutations of what they describe. Two data points from this session alone, both found
before any agent launched:

- **#164's entire premise was retired three days before it was filed.** A defect
  report arriving from a cohort repo carries *that repo's pin*, not this repo's
  `main`.
- **#157's own line numbers are already stale.** The body cites
  `measure-context.sh:874`, its comment cites `:908`; the bare redirect is at
  **`:956-957`** today. The defect is real and unchanged — the coordinates are not.

Across one 13-issue backlog in a sibling repo, the implementing agent found a
material error in the body **every single time**, and staleness rose with batch
depth because earlier batches moved the code the later bodies describe. Treat every
issue body as a **proposal, not a specification**. Verify each file:line, each claimed
call site, and each prescribed implementation against the current tree before acting;
where the body is wrong, **report the correction rather than implementing around it
silently**. Batches C and D are the ones to distrust most — B4 rewrites
`record-telemetry.sh`, which C1's body describes as it stands today.

## Deferred items

- **#163** — `curating-context`: dogfood the weekly cadence, then file it across the
  cohort. Part 1 complete and verified; **Part 2's own gate,
  `CannObserv/observo#457`, is still open**. The blocker is outside this repo and
  outside the named set, so a batch slot here would be dead work. Deferral reason and
  the carried-forward constraints are recorded on the issue.
- **The twelve per-repo cadence adoption issues** — belong to #163, not to C1's #118
  scope, and are gated identically. Cross-repo work is filed as issues per repo;
  this session commits to no other repository.
- **The `test_naming.py` `^[a-z]` conflict** — surfaced by #162: the regex would
  reject every date-first journal filename (`2026-08-13-usa-wa.md`) if applied to
  `references/`. Real, but it is a convention change rather than a documentation
  fix, and #162 is resolved as option 2. File separately if wanted.

## Out of scope

- **#164** — closed as done during this session, not deferred. See "Dispositioned
  before scoring."
- **Retightening the 6,000-token budget** to un-saturate the closure metric. Named
  and refused on #117: changing the budget after seeing where the cohort landed is
  the same integrity failure as choosing the metric late, and `rejected-changes.md`
  already carries the precedent (the 4,000 budget was rejected for being derived from
  where repos happened to sit). The temptation is now stronger, not weaker — every
  cohort policy file measures just under budget.
- **Removing #100's selective-pin mechanism.** #168 retiring the wave split is not a
  reason to lose the ability to hold one repo at a known-good commit, and under the
  *assign* branch #100 becomes load-bearing rather than optional.
- **Asymmetric scoring in `score-cohort.sh`** (#117 proposal 2). It is an n=1 shape
  the script cannot validate is being used honestly. Ships instead as a named
  INCONCLUSIVE outcome: "this proposal added its own instrument and cannot be judged
  by it."
- **A `--metric` flag on `score-cohort.sh`.** Explicitly forbidden. The metric comes
  from the committed experiment file or the gate refuses to score; a free flag lets a
  proposer re-run until the answer is agreeable.
- **`tokens_live` as a primary metric.** A recorded rejection in
  `rejected-changes.md` — it rose 8,462 → 9,862 while the always-paid cost halved, so
  every successful run reads as a regression and a run optimising it is pushed toward
  deleting rather than routing. C1 drops it from #118's candidate table.
- **`docs/CONVENTIONS.md`** — read-only. It is already correct about which
  `references/` rules are enforced; it is the model #162 mirrors, not a target.
