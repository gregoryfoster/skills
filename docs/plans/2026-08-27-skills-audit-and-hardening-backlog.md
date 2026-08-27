# 2026-08-27 — Skills audit-and-hardening backlog orchestration

## Goal

Clear the user-named set — #88, #96, #97, #163, #231–#238 — as a parallel-safe
batch plan. An audit pass ran first because some issues were suspected stale:
none was closed-in-fact, one (#163) rescoped to a residual, two pairs resolved
at Q0 (#234+#236 bundled; #97 split into investigation + doc fix), and three
embedded decisions were settled at the scoring gate (#237 driver shape, #231
resolution, #96 eviction rule). Twelve work items across two batches.

## Approved approach

- Rubric weights equal: **(Foundation ×2) + (Correctness ×2) + Scope, max 15**.
- Deployment context: **early production** — the repo is the vendor source for a
  12-repo cohort; changes propagate passively via daily submodule refresh.
- Nothing deferred.
- Parallelism: **hybrid** — parallel within batches, gates between,
  `isolation: "worktree"` per worker, `batch/<x>` integration branches.
- Concurrency ceiling: **none** (plain `git worktree`, hermetic pytest suite;
  host CPU/RAM only — reconfirmed, consistent with 2026-08-12/2026-08-18).
- Batch→main merge strategy: **regular merge commit** (per-agent history
  preserved). Intra-batch: FF/regular merge only — never squash/rebase.

## Audit pass results (2026-08-27)

Every issue's claims verified against the tree before scoring:

| Issue | Verdict | Evidence |
|---|---|---|
| #88 | open, unblocked | no `--gate` in `measure-context.sh`; no fitness-functions row; blocker #132 CLOSED |
| #96 | open | no self-curation pass exists; #94 shipped but #168 retired the wave split it scored over |
| #97 | open | `test_trigger_routing.py` exists; rationalization-table qualification never applied |
| #163 | rescoped | Part 1 + both pilots done; gate (observo#457) closed green with all four coexistence answers |
| #231 | open | `doctor.sh:249` — warn-only by design; `--check-only` exists, doesn't gate |
| #232 | open | `measure-context.sh:860-861` unchanged; correct tracker exists in-file at :757-774 |
| #233 | open | `is_linked()` at `install-hook.sh:480` unchanged (script is in **managing-skills**, not init-socraticode) |
| #234 | open | template still transcribes the ~680-byte prefetch string (`socraticode-doc.md:83-91`) |
| #235 | open | `mcp-driver.mjs:473` prunes only `node_modules`/`.git` |
| #236 | open | unqualified `.socraticodeignore` claim at `socraticode-doc.md:182-183` |
| #237 | open, sharpened | #192's fix made the driver live in clones → silent revert now reproducible everywhere; `c7be4eb` is the incident record |
| #238 | open | `SKILL.md:209` still "complete replacement"; scan still one level deep (`doctor.sh:433`) |

Cohort sweep for #233 (read-only, all 12 repos): **zero absolute hook
symlinks**; every `install-hook.sh`-managed link is relative into
`skills-vendor/`. Option 3 ("simply become correct") is therefore free.

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| Foundation Leverage | standalone | 1–2 issues benefit | multiple issues depend on it |
| Correctness Risk | cosmetic | edge-case/runtime failure | data loss, silent failures |
| Scope Clarity | needs design discovery | clear direction | mechanical |

Score = (F×2) + (C×2) + S. Blast drives sequencing, not score.

## Scored backlog

| Rank | Item | F | C | S | Score | Blast |
|---|---|---|---|---|---|---|
| 1 | #237 newest-wins calibration merge driver | 2 | 3 | 2 | 12 | Med |
| 2 | #232 fence-length fix in `slugs_of` | 1 | 3 | 3 | 11 | Med |
| 3 | #163-res ten per-repo cadence filings | 3 | 1 | 3 | 11 | None |
| 4 | #97-inv skill-shadowing investigation | 3 | 2 | 1 | 11 | Low |
| 5 | #88 budget fitness gate | 2 | 2 | 2 | 10 | High |
| 6 | #238 override-drift detection + re-sync doc | 2 | 2 | 2 | 10 | Med |
| 7 | #234+#236 template-block bundle | 1 | 2 | 3 | 9 | Low |
| 8 | #233 shape check on resolving branch | 1 | 2 | 3 | 9 | Low |
| 9 | #235 freshness-walk dot-dir prune | 1 | 2 | 3 | 9 | Low |
| 10 | #231 `--check-only` gate + documented loop | 1 | 2 | 3 | 9 | Low-Med |
| 11 | #96 self-curation pass (demote/tighten only) | 2 | 1 | 2 | 8 | Med |
| 12 | #97-doc rationalization-table qualification | 1 | 1 | 3 | 7 | Low |

Decisions taken at the gate (each recorded as a comment on its issue):
#237 → per-line newest-wins driver (worker decides the ratio file's treatment,
documented either way); #231 → both the `--check-only` non-zero exit and the
documented per-hook loop; #96 → demote/tighten only, never delete; #233 →
gate shape on the resolving branch (sweep proved the compatibility set empty).

## Conflict zones

| File | Issues | Resolution |
|---|---|---|
| `curating-context/scripts/measure-context.sh` | #232 (:856 awk), #88 (args/exit) | Shape B: #232 in A, #88 in B |
| `managing-skills/scripts/doctor.sh` + `SKILL.md` | #231, #238 | Shape A bundle, #231 commits first |
| `init-socraticode/references/socraticode-doc.md` + `SKILL.md` | #234, #236 | Shape A bundle (Q0) |
| `curating-context/SKILL.md` | #96, #97-doc | Shape A bundle, #97-doc commits first |

Test-file ownership (each exclusive to one agent; read-only for all others):

- `test_doctor_hook_registration.py` → A4 (its `test_the_exit_code_stays_advisory`
  pins the exact contract #231 amends — default mode stays advisory; only
  `--check-only` changes)
- `test_hook_installer_generic.py` → A5 (#227's shape/resolution tests, :470–520)
- `test_context_artifact_parity.py` → A7 (its :738 asserts `.socraticodeignore`
  appears in the doc's notes — A6's clause edit must keep that string present)
- `test_cadence_ours_driver.py` (+ cadence rendered-shell/context-surface tests
  as needed) → A1, the only agent permitted to modify the merge-driver pins
- `test_skill_self_budget.py` → read-only for **everyone**; a ratchet breach is
  reported, never raised (Phase-4 rule). `curating-context` sits ~7,58x/7,600.

## Dependency graph

```
Batch A (8 parallel, disjoint)                Batch B (after A → main)
  A1 #237 cadence merge-driver ────────────────→ B2 #163-res (design coherence)
  A2 #232 fence fix ────────(same file)────────→ B1 #88 budget gate
  A3 #97-inv investigation (read-only)
  A4 #231+#238 managing-skills hardening
  A5 #233 install-hook shape gate
  A6 #234+#236 template-block fixes
  A7 #235 freshness-walk prune
  A8 #97-doc+#96 curating-context self-curation
```

Two edges. #232→#88 is same-file sequencing. #237→#163-res is a
design-coherence gate with zero file overlap: the ten per-repo issues instruct
installing the cadence, and filing them after the driver redesign means
consumers install the corrected design instead of `merge=ours` plus a later
re-run sweep.

## Batch execution plan

| Batch | Agent | Issues | Files | Gate |
|---|---|---|---|---|
| A | A1 | #237 | `install-cadence.sh`, `.gitattributes`, `references/cadence.md`, cadence tests | start now |
| A | A2 | #232 | `measure-context.sh` (slugs_of only), anchor/fence tests | start now |
| A | A3 | #97-inv | none (report as comment on #97; follow-up issues allowed) | start now |
| A | A4 | #231→#238 | `doctor.sh`, `managing-skills/SKILL.md`+`references/`, doctor tests | start now |
| A | A5 | #233 | `install-hook.sh`, `test_hook_installer_generic.py` | start now |
| A | A6 | #234→#236 | `init-socraticode/SKILL.md`, `references/socraticode-doc.md` | start now |
| A | A7 | #235 | `mcp-driver.mjs`, `test_context_artifact_parity.py` | start now |
| A | A8 | #97-doc→#96 | `curating-context/SKILL.md` (≤7,600), new `references/` doc | start now |
| B | B1 | #88 | `measure-context.sh` (args/exit), `fitness-functions.md`, `AGENTS.md` (1 line), check surface | A merged |
| B | B2 | #163-res | none — ten `gh issue create` across the cohort + closing comment | A merged |

## Key decisions

- **Calibration files are untouchable.** No agent writes
  `.skills/context-token-counts` / `.skills/context-token-ratio`; no worker runs
  `measure-context.sh --exact` in a worktree — its side effect re-baselines
  every skill's estimate (the #230 mid-run 2.68→2.63 incident).
- **`AGENTS.md` has a single writer**: B1, one line.
- **A1 is the only writer of `.gitattributes`** and of the cadence-driver test
  family.
- **A6 keeps the literal `.socraticodeignore` present** in the template block
  (A7's parity test asserts it) and does not touch parity tests.
- **#233's shape rule stays scoped to hooks `install-hook.sh` manages** —
  `context-budget-guard.sh` legitimately links through `skills/` indirection
  and belongs to `curating-context`'s installer.
- **#96's #94-gate reference is stale**: #168 retired the wave split the
  validation gate scored over; the A8 worker verifies the current
  `validation-gate.md` semantics before wiring anything to it.
- No chain-appending artifacts in this backlog. The ledger
  (`context-metrics.jsonl`, merge=union) is written by no agent.
- No verification-mode asymmetry: no agent changes the test runner's config.
- The weekly cadence workflow pushes to `main` Mondays 18:12 UTC; Rule 1's
  sync-before-every-launch absorbs it. Until A1 merges, any batch→main merge
  performed from a stale side risks the #237 clobber — check the counts file's
  AGENTS.md row after each merge to main (the `c7be4eb` failure mode).

## Runtime note on issue-body decay

The backlog is N sequential mutations of what the bodies describe; re-verify
the specifics of any issue whose files an earlier batch touched (Worker
step 5). B1's body predates A2's edit of the same script; #163's body is
historical — the 2026-08-27 rescope comment is its contract. The later the
batch, the staler the body.

## Deferred items

None. (Q3: nothing deferred.)

## Out of scope

- #207 (SocratiCode upstream advisory) and #68 (structlog research) — open in
  the repo, not in the user-named set.
- Implementing #97's option 3 (collapsing the four variants) — the deliverable
  is an investigation report; any restructure goes through
  `reviewing-architecture` as its own cycle.
- Re-syncing the cohort's stale overrides (#238's cohort audit) — B-side
  per-repo work; #238 here ships the detector and the documented procedure.
