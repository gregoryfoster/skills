# Session 2026-08-27 — gregoryfoster/skills (#239 execution)

## Session 2026-08-27 (execution addendum)

Execution of the same-day plan: Batch A ran 8 parallel (7 implementing + 1
read-only investigation), merged as 2067342 after one CR round; Batch B ran 2
(#88 held unmerged at the user's direction; #163's ten filings delivered).
Issues #96, #97, #163, #231–#238 closed; #240–#243 filed from the
investigation.

## Lessons

**The count-arithmetic slot worked at scale.** Baseline 3315 plus every
worker's reported delta (+1, +6, +6, +0, +11, +27, +28) predicted 3394; the
batch gate measured 3394. Two workers' counts (3321) also self-located their
merge position — they had merged `batch/a` before earlier workers landed —
so the counts doubled as an ordering record.

**Audit-day facts decay by execution-day, even in one session.** Five
orchestrator-brief errors were caught by workers: a parity assertion
attributed to the wrong file; a ratchet cited at 6,250 that #230 had deleted
(the 6,000 standard bound instead, with ~157 tokens of headroom, not ~800); a
SKILL.md headroom figure (~20) that was ~143 by launch; four "prerequisite"
repair issues that were all closed; and a "seven of twelve pins lack the
installer" claim that had gone to zero. The briefs' *decisions* all survived;
their *facts* had a half-life of days. Verbatim numbers in a brief need a
measured-at timestamp or a worker instruction to re-derive.

**The orchestrator CR must run the opt-in exact gate when any SKILL.md grew.**
The fourth #217-class breach: curating-context/SKILL.md at 7,661 exact vs the
7,600 ratchet, green under the default suite, green under pre-commit, green
under the worker's own projection (which undershot exact by ~90 tokens).
`SKILL_BUDGET_EXACT=1` over the touched skills is now a standing CR step in
this repo — it is the one reading nothing always-on checks.

**Fixing a budget breach trips the mirror suites — read the pin registry
first.** The CR tighten hit four pinned contracts in `test_demoted_blocks.py`
(the 2026-08-20 block-consistency lesson, reproducing during the *fix* of a
different finding). The efficient order: read the REGISTRY, revert exactly
the pinned spans, and take savings from sections with no registry entry
(Phases 2/3/4 here). Pin-free sections are knowable in advance — the
registry names its sources.

**A decided design can still be one refinement short of correct — the worker
is the last audit.** #237's approved shape ("keep the row whose bytes match
disk") would have reproduced the incident it fixes in the stale-branch
sub-case, because under merge-ort the working tree holds the pre-merge side
when a driver runs. The worker shipped three-way-first with disk arbitration
only on true collisions. Same lesson as 2026-08-21 ("decisions survived,
prescribed implementations did not"), now applying to a *gate-decided* design
rather than an issue body.

**A worker that stops with a status line has not failed — resume it, firmly
and synchronously.** B1 twice ended its turn "waiting for the suite" /
"watch armed" with no live background children, i.e. nothing could wake it.
Two SendMessage resumes — the second explicitly ordering a foreground suite
run and forbidding further stops — completed it with full context intact.
Killing and respawning would have discarded a verified red commit and 40+
tool calls of verification.

**One unplanned shared file crossed two agents and merged clean** —
`test_reminder_hook_vendored.py` (A6 re-aimed prefetch pins; A4 re-baselined
a `--check-only` pin). Disjoint hunks, auto-merge, batch-gate green. The
line-window analysis had missed it because neither issue named the file; the
batch-gate full-suite run is the backstop that makes this survivable.

**Baseline note:** this entry and the CR fixes added no tests; main after the
held #88 merge will be 3403 passed, 158 skipped.
