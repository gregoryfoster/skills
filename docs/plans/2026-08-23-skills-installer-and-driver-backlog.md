# Backlog orchestration — the installer/driver adoption backlog (#220, #222–#229)

Tracking issue: [#230](https://github.com/gregoryfoster/skills/issues/230)
Session: 2026-08-23 · Orchestrated with `orchestrating-issue-backlog`

## Goal

Clear nine issues — #220 and #222 through #229 — filed over 48 hours by four
consuming repos (watcher#276, observo#483, archiver#184, notifier#21) plus one
CR finding and one residual from the #219 batch. Six of the nine are the same
shape and it is the shape this library keeps producing: **a failure that is
silent, and in three cases silent *upward*** — a counter goes up, a check
reports green, and the capability is gone. #222 deletes a working hook's
registration and reports success. #224 is why nothing downstream notices. #225
counts an artifact present and never fresh. #229 embeds compiled bytecode into
an embedding while the chunk count rises. #223 is the meta-instance: the gate
that would catch a whole defect class is disclaimed by one test and picked up by
no other.

## Approved approach

- **Rubric**: `(Foundation × 2) + (Correctness × 3) + Scope`, max 18. Fifth
  consecutive Correctness-×3 session; the justification has strengthened rather
  than merely repeated — twelve cohort repos vendor this library and pull
  daily, and this backlog *is* the record of that shipping wide before anyone
  read it.
- **Deployment context**: active production (Q2).
- **Deferrals** (Q3): **#207 stays deferred.** #220's body argues the two are
  "worth deciding together", but #207 is gated on upstream
  giancarloerra/SocratiCode#112, which is outside anything schedulable here —
  so #220 settles the `findings` contract now and #207 adapts to it when
  upstream ships. #163, #97, #96, #88 and #68 are out as outside the named
  range.
- **Parallelism**: hybrid (Q4) — parallel within the batch, merge-and-test gate
  before `main`, all workers in `isolation: "worktree"`.
- **Concurrency ceiling: 4 per batch, host-bound** (Q5). **Sixth consecutive
  negative result** (2026-08-12, -16, -18, -20, -21, now -23). Re-verified
  rather than inherited: `worktree-create.sh` is plain `git worktree add` with
  no port pool, docker or vhost provisioning; no `conftest.py` under `tests/`;
  `addopts` is `-m 'not integration and not benchmark'`. The escape grep
  (`docker|POSTGRES|DATABASE_URL|PORT_POOL|redis|localhost:`) returned nine
  hits and **all nine were read before being dismissed** — seven are string
  literals inside test fixtures (`HEALTH_OK = "Docker: ✓ running…"`), one is a
  filename in a budget comment, one is example CLI output. This repo's product
  is templates, so it documents the hazards it does not have; a grep hit is not
  a ceiling until you read the path. Binding here for the first time in six
  sessions: five work items against a ceiling of four.
- **Shared credential**: `ANTHROPIC_API_KEY` in the gitignored `.env` is a
  single shared resource. No agent in this backlog needs an exact-token run, so
  no contention and no serialization.
- **Merge strategy**: regular merge commit, `batch/a` → `main`. Intra-batch
  worker → batch fixed at FF/regular merge so
  `worktree-destroy.sh --base batch/a` can verify ancestry.
- **Suite baseline on `main` (`8ee142a`)**: **3038 passed, 159 skipped**, 145s,
  via `.venv/bin/python -m pytest tests/structural/`. Every worker brief carries
  this number with "stop and report if it does not match."

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| **Foundation Leverage** ×2 | Standalone improvement | 1–2 other issues benefit | Multiple issues depend on or are simplified by this |
| **Correctness Risk** ×3 | Cosmetic / organizational | Edge-case incorrect behavior, runtime failure risk | Data loss, race conditions, silent failures |
| **Scope Clarity** ×1 | Requires design discovery | Clear direction, minor decisions needed | Mechanical — obvious from the issue |

## Scored backlog

Final scores, after the decide-then-rescore gate. Three issues scored Scope 1 or
2 on arrival because each named an unresolved decision **in its own body**;
those decisions were answered at the gate (see Key decisions) and the issues
re-scored.

| # | Headline | F | C | S | **Score** | Blast | Agent |
|---|---|---|---|---|---|---|---|
| **222** | Group-scoped strip evicts a hook's group-mates — silently | 3 | 3 | 3 | **18** | High | A1 |
| **224** | Doctor checks one hook's registration; the other two are undetectable | 2 | 3 | 3 | **16** | Med | A3 |
| **220** | A neutral finding still sets `exitCode` 1 | 3 | 2 | 2 | **14** | Med | A2 |
| **229** | Binary guard can never fire — bytecode embedded, every counter up | 1 | 3 | 3 | **14** | Low | B1 |
| **225** | Artifacts counted present, never fresh | 1 | 3 | 2 | **13** | Med | A2 |
| **227** | `--check` calls a correct install DANGLING in CI | 2 | 2 | 3 | **13** | High | A1 |
| **226** | Doc ships the literal `.` that #180 removed from the hook beside it | 2 | 2 | 3 | **13** | Med | A2 |
| **228** | Vendor-symlinked hooks rc=127 on a submodule-less checkout | 2 | 2 | 2 | **12** | Med | A1 |
| **223** | `skills/**/*.md` anchors are checked by nothing | 1 | 2 | 2 | **10** | Low | A4 |

Score determines what gets done; ordering constraints determine when. #223 is
last by score and still launches in Batch A, because it is the least contended
item in the set and fills a slot that would otherwise idle.

### Corrections to issue bodies, found before any worker saw them

Three of nine bodies were materially wrong. This is the fourth consecutive
backlog where the closed-in-fact and footprint greps changed scope, and it is
why Worker step 5 exists.

- **#223 is a test addition, not a repair sweep.** The body predicts *"Expect
  the first run to be the interesting part — 28 links have never been
  checked."* A GitHub-slugifier sweep of the tree found **27 anchored links, 27
  resolving.** The single non-resolver is `docs/FOO.md#some-heading` at
  `budget-and-metrics.md:367` — an illustrative example in prose, which the
  implementation must *exempt* rather than fix. Blast Med → Low.
  - **The instrument was wrong first.** The initial sweep reported three broken
    anchors, because its slugifier collapsed `\s+` to a single hyphen instead of
    one hyphen per space — so every em-dash heading (`### Phase 5d — Provision
    PostgreSQL` → `phase-5d--provision-postgresql`) mis-slugged. The two
    "findings" were artifacts of the checker. Corrected before reporting; noted
    here because an orchestrator's quick regex is exactly as falsifiable as the
    issue body it audits, and it arrives carrying more authority.
- **#229's headline claim already shipped.** `context-artifacts.md:126-129`
  already states *"A directory artifact is pruned only of `node_modules`/`.git`
  … does not honor `.socraticodeignore` or `.gitignore`."* That is the issue's
  lead finding, documented. Rescoped to the verified residual: the mechanism its
  own follow-up comment added.
- **#228's premise dissolved at the gate.** Filed against `HOOK_COMMAND`; the
  prose-only decision removes it from `install-hook.sh` entirely, so it no
  longer collides with #222's dedupe comparison. Blast High → Med.

## Conflict zones

**Source files are fully disjoint.** Every point of contention in this backlog
is in the test surface — the half no issue body mentions, and the half a
source-file overlap map cannot see.

| Zone | File | Contenders | Resolution |
|---|---|---|---|
| 1 | `tests/structural/test_refresh_hook_install.py` | A1 ∩ A3 | Class-boundary split |
| 2 | `tests/structural/test_reminder_hook_vendored.py` | A1 ∩ A3 | Class-boundary split |
| 3 | `tests/structural/test_socraticode_graph_yield.py` | A2 owns, A1 reads | Read-only for A1 |
| 4 | `skills/init-socraticode/references/code-exploration-policy.md` | A1 owns, A2's tests read | Read-only for A2 |
| 5 | `tests/structural/test_skill_self_budget.py` | all four | Read-only for **everyone** |

**Zone 1** is the sharp one. `test_refresh_hook_install.py` carries six
assertions on `install-hook.sh --check`'s literal output strings —
`SessionStart entry: yes` (`:154`, `:244`), `DANGLING` (`:319`) — and **#222 and
#227 rewrite every one of them.** Neither issue mentions a test. The same file's
`:487` asserts `"install-refresh.sh" in r.stderr`, which is precisely what
#224's `.install` manifest replaces.

**Zone 2** is load-bearing in the opposite direction.
`TestDoctorCoversTheSymlinkedHook` at `:313` asserts the doctor did *not* flag a
resolving hook symlink — and #224 teaches the doctor a new per-hook
registration warning that this fixture will trip, because the fixture's hooks
resolve but carry no `SessionStart` entry. A3 owns that class and must
re-baseline it rather than reconcile to it.

### Window ownership, named by class rather than line

A1 merging first shifts A3's line numbers, so a range written at planning time
is stale by the batch that consumes it. Modifications stay inside the owned
class; **new** tests go to a new per-agent file, which resolves the append half
and the modify half separately.

| File | A1 owns | A3 owns |
|---|---|---|
| `test_refresh_hook_install.py` | `TestInstallRefresh` | `TestDoctorReportsAHalfInstall` |
| `test_reminder_hook_vendored.py` | `TestTheScriptIsVendored` … `TestItNeverBlocksASession` | `_doctor` helper + `TestDoctorCoversTheSymlinkedHook` |

## Dependency graph

Both edges are invisible to file overlap. Neither forces sequencing — but
unnamed, either turns a batch-gate failure into a misattribution.

```
A4 (#223) ──covers──▶ A1, A2, B1     VERIFICATION-MODE ASYMMETRY
                                      A4 adds the first gate in this repo's
                                      history to check skills/**/*.md fragments.
                                      A1, A2 and B1 all write markdown into its
                                      scope, and all verify in their own
                                      worktrees under the OLD suite. The
                                      orchestrator's batch/a run is the first
                                      under the new one.

A3 (#224) ──transcribes──▶ A1        SEMANTIC, NOT TEXTUAL
                                      A3's *.install manifests hold
                                      install-hook.sh's argument list. If #227
                                      changes flags, A3's manifests go stale
                                      with no merge conflict to say so.

A2 (#220) ──defines──▶ A2 (#225)     INTRA-AGENT, define → use
                                      #225's staleness line cannot pick a
                                      severity until #220's contract exists.
                                      Which is why they are one agent.
```

## Batch execution plan

### Batch A — 4 parallel agents on `batch/a`

Exactly at the ceiling.

| Agent | Issues | Owns | Test surface |
|---|---|---|---|
| **A1** | #222 → #227 → #228 | `managing-skills/scripts/install-hook.sh`, `init-socraticode/references/code-exploration-policy.md`, `managing-skills/SKILL.md` | `test_hook_installer_generic.py` (whole); `TestInstallRefresh`; `TestTheScriptIsVendored`…`TestItNeverBlocksASession` |
| **A2** | #220 → #226 → #225 | `init-socraticode/scripts/mcp-driver.mjs`, `init-socraticode/references/socraticode-doc.md` | `test_socraticode_graph_yield.py`, `test_context_artifact_parity.py`, `test_health_timeout_contract.py` |
| **A3** | #224 | `managing-skills/scripts/doctor.sh`, new `*.install` manifests | `TestDoctorReportsAHalfInstall`; `_doctor` + `TestDoctorCoversTheSymlinkedHook`; `test_doctor_*.py` |
| **A4** | #223 | `tests/structural/test_relative_links.py` | itself |

**Intra-batch merge order: A1, A2, A3 in any order; A4 merges last.** This is
epistemics, not contention — see Key decisions.

### Batch B — 1 agent, after A is merged to `main`

| Agent | Issues | Owns | Gate |
|---|---|---|---|
| **B1** | #229 (residual) | `init-socraticode/references/context-artifacts.md`, upstream report to giancarloerra/SocratiCode | After `batch/a` → `main` |

Single-agent, so **no `batch/b` branch** — the feature branch serves directly.

## Key decisions

**Why A4 merges last.** A4's anchor gate is the first thing in this repo ever to
resolve `skills/**/*.md` fragments, and A1 and A2 are both writing markdown into
its scope. Merged last, a red gate is unambiguously "the new check meeting new
prose". Merged first, the identical red surfaces at A1's merge and reads as A1's
defect. The ordering buys attribution, not safety.

**The verification-mode asymmetry, stated so it cannot be misattributed.** Every
Batch A agent verifies in its own worktree under a suite that does not yet check
anchors. The orchestrator's post-merge run on `batch/a` is the first execution
under the new gate. If it goes red on an anchored link, the responsible agent is
whoever wrote the link — not A4, whose gate is working correctly by definition
at that moment.

**Why #222, #227 and #228 are one agent.** The original argument was that all
three interleave in `--check`. The prose-only decision on #228 weakened that
half — but replaced it with a stronger one: #227's recipe documentation and
#228's first-session note land in the **same section** of
`code-exploration-policy.md`. Overlapping windows in one file mean sequencing,
and sequencing inside one agent is cheaper than a batch boundary.

**Why #220, #226 and #225 are one agent.** A define→use chain that cannot be
split: #220 settles what `findings` means, #226 changes how the driver resolves
its path argument, #225 is the first consumer of both. #225 literally cannot be
specified until #220's option is chosen.

**#220 — severity on one array** (the issue's option 2). Keeps a single
`findings` array and gates `exitCode` on a per-finding severity rather than on
emptiness. Rejected: a second `observations` array (option 1), which is cleaner
in the abstract but is a JSON contract change — `socraticode-health.sh` and
every consumer parsing the driver's output would need to learn a new key.
Rejected: suppressing the line on an `ok` verdict (option 3), which discards a
number an operator may want and leaves #225 with no answer about where a
staleness finding belongs. The rationale for the rejected options is preserved
here rather than deleted, because #207 will revisit this seam when upstream
ships.

**#224 — per-skill `.install` manifest** (the issue's option 2). A one-line file
beside each hook holding its `install-hook.sh` arguments, which `doctor.sh`
reads and prints. Rejected: a hook→installer table inside `doctor.sh` (option
1), which is the smaller change but needs a `doctor.sh` edit every time a skill
adds a hook. The manifest puts the constants next to the hook they belong to —
where #200 already moved them — and stops needing edits as skills are added.

**#226 — both routes.** The driver resolves a relative path argument the way
`socraticode-health.sh` does, *and* the doc shows the explicit spelling. The
driver half is what fixes every consumer who has already copied the bad line
into their own `docs/`; the doc half is what stops the next one. This is why
#226 belongs to A2 rather than standing alone as a one-line doc fix.

**#228 — prose only, both skills.** One line in `code-exploration-policy.md`
Steps A/C and one in `managing-skills`' hook docs: on a fresh clone or new
worktree the hook fails until `.skills/doctor.sh` has run once, and that is
expected. Rejected: the self-guarding registered command, which fixes the rc=127
noise but — for `socraticode-health.sh` specifically — converts a loud failure
into exactly the silence #179 identifies as the dangerous state.

**An open factual question A1 must settle rather than assume.** #228 flags it
and does not answer it: does Claude Code run a `SessionStart` event's matching
hooks in parallel, or sequentially in array order? If in parallel, no ordering
of `.skills/doctor.sh` can make it heal the tree before its sibling hooks run,
and the repair is always one session late. Two skills currently prescribe a
layout that implies ordering helps. A1 verifies which is true and writes down
the answer; it does not repeat the implication either way.

**`tests/structural/test_skill_self_budget.py` is read-only for every agent.**
It is the one file all four agents' verification depends on. If a ratchet needs
raising, that is a post-merge PR after Batch B lands — never an in-flight
amendment, which is how three concurrent edits to one foundation file happen.

**A ratchet caution for A1, not a gate.** `managing-skills` carries **no**
`references/` directory, so #228's prose has nowhere to demote to and lands in
`managing-skills/SKILL.md`, under a never-raise 8,750-token ratchet. Current
size leaves room. Measure rather than assume.

**No chain-appending artifacts.** No migrations, no numbered ADRs, no sequence
files. A3's `.install` manifests are a new convention but single-owner, so the
one-chain-appending-agent-per-batch rule is satisfied trivially.

## Runtime note on issue-body decay

This backlog is five sequential mutations of what the bodies describe. Three of
nine were already materially wrong at planning time (see Corrections above), and
staleness rises with batch depth because earlier batches move the code the later
bodies describe. **B1's body describes a tree that A2 will have edited** —
`socraticode-doc.md`'s index-scope section is adjacent to what #229 argues sets
the wrong expectation.

Every worker re-verifies every file:line, every claimed call site and every
prescribed implementation against the tree in front of it, and **reports the
corrections rather than implementing around them silently.** The required
report-back slot is: the suite's collected count as `N passed, M skipped` —
never a bare "green" — and everything in the issue body that turned out to be
wrong. The second half is asked for with its second clause: *the corrections,
not a report that matches the prediction.* Without it, agents reliably produce a
report shaped like agreement.

## Deferred items

- **#207** — retire the edge-yield workaround once giancarloerra/SocratiCode#112
  lands. Deferred on an upstream blocker that sits outside this set, so any slot
  given it is dead work. #220's contract decision is made in a shape #207 can
  adopt; see Key decisions for the rejected options and why.
- **#229's upstream half is in scope, but its resolution is not.** B1 files the
  two-line mechanism (the hardcoded `["**/node_modules/**", "**/.git/**"]` walk,
  and the binary guard whose `catch` cannot fire because
  `readFile(path, "utf-8")` returns replacement characters rather than throwing)
  against giancarloerra/SocratiCode. Whether upstream acts on it is not this
  backlog's gate.

## Out of scope

- **#163, #97, #96, #88, #68** — open, and outside the named range. #97 (skill
  shadowing across seven trigger phrases) and #96 (`curating-context` library
  drift) are both real and both structural; neither belongs in an
  adoption-feedback batch whose contention map is built around two script
  families.
- **Raising any budget ratchet.** Post-merge PR territory. See Key decisions.
- **The #227 follow-on the issue offers at the end** — consumers transcribing
  the prefetch query into their own `docs/SOCRATICODE.md`, which goes stale
  silently once the reminder hook is a symlink. Genuinely a separate issue, and
  the reporter offered to file it. Not folded into A1, whose scope is already
  three issues.
