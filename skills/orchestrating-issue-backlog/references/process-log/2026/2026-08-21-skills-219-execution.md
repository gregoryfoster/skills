## Session 2026-08-21 — gregoryfoster/skills (#219 execution)

Execution addendum to [2026-08-21-skills.md](2026-08-21-skills.md). One batch,
three agents, one CR round, merged to `main` at `2d0f4f5`. Suite `2994 → 3035
passed, 159 skipped, 1 warning`.

### Journaling the session invalidates the baseline the session then briefs

The orchestrator measured `2991 passed, 159 skipped` at Step 1–2, ran the
interview, wrote the plan, **wrote the process-log entry**, committed both, cut
`batch/a`, and briefed all three workers with 2991 and "stop and report if it
does not match."

The correct figure was 2994. The process-log entry is a new
`skills/*/references/*.md`, and the structural suite parametrizes exactly three
tests over any such file (`test_content_invariants`, `test_relative_links`,
`test_self_links`). **The orchestrator's own Step 10 artifact moved the number
its Step 1–2 measurement had produced**, and nothing in the procedure re-reads
it in between.

Consequences, all of which actually happened:

- Two workers halted at their step 5, as instructed, and one of those halts cost
  a full suite run to diagnose.
- A third judged the *reason* given for the halt ("a mismatch means your
  worktree was cut from the wrong base") to be falsifiable, tested it —
  `HEAD == batch/a == main == origin/main == 3267bc9`, clean tree — found the
  base provably right, and continued deliberately, reporting the number rather
  than adopting it. That is the correct call and the instruction did not license
  it: it names one cause for a mismatch and there are two.
- The orchestrator's correction message went out to two live agents mid-run.

**The rule this wants:** measure the baseline **after** committing the plan and
the log, not before — or re-measure at launch, in the same breath as Rule 1's
sync. The existing procedure already treats a stale *tree* as corrupting
(Rule 1); this is a stale *number*, produced by the orchestrator's own hand,
and Rule 1 does not cover it because the tree was current the whole time.

A second clause belongs with it: **the brief should name the mismatch's two
causes**, not one. "Stop if it does not match" plus a single explanation invites
an agent to either halt on a benign drift or, worse, reconcile silently because
the one named cause visibly does not apply.

### The orchestrator is reliable about decisions and unreliable about implementations

**3 of 3 workers corrected their brief.** Not a new count — the last three
sessions ran 9/9, 7/7, 4/4. What is new is *which half* was wrong.

Every **decision** the orchestration gate made survived contact: verdict-aware
wording (#216), a finding with exit 1 (#214), options 1+3 over the issue's own
recommended option 2 (#217), the Shape A bundle, the read-only declarations, the
rescope of #216 to its residual. Not one was reversed.

Every **prescribed implementation** that named a specific symbol or file was
wrong, and two would have shipped defects:

| Prescribed | What it actually was |
|---|---|
| "reuse `expectedArtifactCount` (`:606`)" | `:612`, and it `die()`s — `process.exit(1)`, the one call `cmdHealthCheck` documents that it must never make. An invalid manifest would have cost the JSON contract *and* skipped every graph check. |
| "add the job to `context-cadence.yml`" | A rendered artifact of `install-cadence.sh`, whose `--check` compares existence not content — the addition would have been deleted silently by the tool that installed it, at some later date. |
| "`parseArtifacts` (`:382`) supplies the count" | `:380`, and it cannot supply the denominator at all: its own selftest pins `7 configured, not yet indexed → {done:0,total:0}`, identical to "no manifest". |

The pattern is legible in hindsight. The orchestrator reads at grep depth —
enough to see that a symbol exists and roughly what it is for. Decisions need
exactly that altitude. Implementations need the semantics one layer down, which
the orchestrator never has and the worker always does.

**So: brief constraints and decisions, not implementations.** Name the
read-only files, the decided approach, the rejected alternative and why. Where a
specific symbol seems right, offer it as a lead to verify rather than an
instruction to follow — the difference is what turns a defect into a report.
Worker step 5 already tells the agent to treat the body as a proposal; the
symmetric obligation on the orchestrator is to stop writing briefs that read
like specifications.

### A review finding can hide a second defect one layer down

CR finding 2 read as a one-line scope extension: the new weekly job runs
`test_skill_self_budget.py`, so add `test_policy_surface_budget.py`, which binds
`AGENTS.md` and `docs/` through the same opt-in switch.

Implementing it surfaced that the sibling file **skips without warning** when
`count_tokens` is unreachable. Its sibling warns first, and the job's whole
design rests on escalating that warning. Adding the file as the finding
described would have shipped #217's silent success on the very surface the fix
was extending to cover — a green weekly job that measured `AGENTS.md` not at all.

**Generalizes:** when a finding says "extend gate X to cover surface Y",
verify Y **degrades** the way X does before extending. Coverage is the visible
half; the failure mode is the half that decides whether the extension is worth
anything. Measured both ways here rather than asserted — bogus key, 78 errors
where there had been silent skips.

### Verify the trust assumption that would rebuild the bug

CR finding 4 asked the driver to skip its second MCP round-trip when
`codebase_status`'s numerator already equals the declared count. That is a
*trust* assumption about the exact reading #214 exists because nobody should
trust — if the server ever rounded up, the short-circuit reinstates the gap.

Checked against a live install rather than reasoned about:
`cannabis_observer/code/cli` sits at 12 of 13 artifacts behind `Status: green`,
and `codebase_status` there reports `Context artifacts: 12/13 indexed`. The
count is honest; only the *name* is missing, which is precisely what the
issue said. The short-circuit is safe and the reason is now in the comment.

(Incidentally a second live instance of #214's gap in the cohort, found by the
implementing agent while verifying the parser's fixture shape against a real
server instead of against the issue text.)

### The orchestrator's own fixes needed the same scrutiny it applied to the workers

Two defects introduced while implementing six accepted CR findings, both caught
before the commit:

- The short-circuit's first draft used an early `return` — inside the
  `withClient(async () => {…})` callback, so it would have skipped every graph
  check below it. A worse bug than the one being fixed.
- The `estimate_caveat` edit broke
  `test_the_caveat_still_serves_a_caller_with_no_policy_estimate`, which
  correctly refuses to quote a SKILL.md worst case at a call site whose
  population is described by a different band. The test was right.

Nothing structural to promote; recorded because a CR round performed by the
orchestrator on its own agents' work has no reviewer of its own, and the two
defects above are what that absence looks like.

### Still blocked from promotion, second time in one session

The first lesson above is a genuine Rule 1 clause. `SKILL.md` measures 23,054
against its 23,110 ratchet — **56 tokens** — and #217's new WARN now names this
file as 4,012 over its worst permissible exact reading, the largest gap in the
library. Promotion needs an offsetting trim, and a trim is its own session.
Logged here, twice noted, unpromoted.
