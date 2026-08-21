# Session 2026-08-20 — gregoryfoster/skills (#213 execution)

Execution addendum to `2026-08-20-skills.md`. Three batches (4/4/1), nine
workers, twelve issues shipped, four follow-ups filed (#215–#218). Suite
2793 → 2986 passed. Design doc
`docs/plans/2026-08-20-skills-adoption-and-followup-backlog.md`.

## The headline: a ratchet that binds two readings, and only one is ever read

`SKILL_BUDGET_EXACT=1` on `batch/b` failed **two** skills at once:
`init-socraticode` 10,088 against 10,050 (already merged to `main` in Batch A,
past a green suite, a passed pre-commit hook **and a completed code review**),
and `using-git-worktrees` 6,009 against 6,000 — whose author had reported
"5,938 estimated, ~62 tokens of headroom."

`SKILL_BUDGET_EXACT` appears **only** in the test file. Not pre-commit, not
`context-cadence.yml`. The always-on gate reads an offline estimate that runs
12–13% low, so *every agent verifies against a number that is not the
contract*, reports green, and is correct by every gate it was told about.

The test's own docstring already recorded this happening — same file, 186
tokens over, same three gates. **Third occurrence, second on that file**
(→ #217). Two data points one batch apart show it is a briefing problem, not a
capability one: the #208 agent applied `POLICY_ESTIMATE_BAND`'s worst-case
inversion unprompted and reported a worst permissible reading; the #201 agent
reported the raw estimate as headroom. Nothing forced the difference.

**Rule for future briefs: an agent that grows a `SKILL.md` must report the
exact reading, or the worst-case inversion — never the estimate.** Batch C's
brief carried it and C1 came in 38% under with the exact figure quoted.

**Corollary for the orchestrator's own CR:** my Batch A review ran the default
suite and passed a file that was 38 tokens over. A CR that runs only the
always-on gate inherits exactly the blind spot the always-on gate has.

## Nine for nine corrected their brief, and the orchestrator was wrong five times

Every worker found something material. More usefully, five corrections landed
on *me*, not on the issue bodies:

1. **Click is not importable in this repo** (A2). I claimed it was. It cannot
   be — this is a skills-authoring repo. Consequence worth keeping: **no test
   here can execute any stack-variant skill's documented API**, so a false-API
   claim in `*-php` / `*-python-click` / `*-python-fastapi` is undetectable by
   anything but review.
2. **A `load_env` line reference I cited from a grep match I never opened**
   (A4). The file had zero `load_env` hits. Same instrument error the skill
   warns about, committed while briefing a worker to watch for it.
3. **`test_demoted_blocks.py:293` never bound to `cadence.md`** (B4). I
   briefed it as a deletion hazard; the pin binds a different file entirely.
4. **The tracking remedy for `.skills/worktree_venv`** (B2) — see below.
5. **"#186 made the reminder hook symlink-installed"** (B1). #186 vendored the
   *file* and changed the *prose*; **no script installed either socraticode
   hook**, which is the gap #200 closed. My correction of a stale body was
   itself wrong, in the opposite direction.

(4) is the one to generalize. I handed down "track the knob" reasoning from
#202. B2 found the repo already solves it: `resolve-worktree-root.sh` walks
`--git-common-dir` to the primary checkout *before* reading the knob, and
`test_worktree_root_contract.py:215`'s docstring says verbatim that the knob
"is untracked" and must still be honoured. **A handed-down remedy derived from
one issue is a hypothesis about a convention, not the convention** — the
worker standing in the code is better placed to check. My supporting claim
that `.skills/` is untracked by convention was also false: `skills-pin` is
documented as committed.

## Two workers converging on one finding is a fix signal, not a filing signal

B3 (changing when `repo_commit` is recorded) and B4 (editing `cadence.md`)
independently reported that the backfill falsifies the same `cadence.md`
passage — from different files, neither having seen the other's work. Single
reports went to issues (#215, #216, #218); the converged one I fixed before
merge, because shipping a doc that describes the superseded behaviour is the
exact failure class the backlog existed to clear.

## Ownership windows worked, including the one that turned out unnecessary

`test_guard_install_paths.py` holds `GUARD_DOC` (B4) *and* exercises
`install-refresh.sh` (B1) — found only by grepping which tests *read* each
agent's files, not which files they edit. Both got explicit separated windows
plus "no reordering anywhere else." B1 never needed its windows and said so;
B4 never needed the file at all. Zero conflicts across nine workers.

Two workers independently routed new tests to **new files** rather than the
shared ones, citing AGENTS.md's parallel-worktree rule back at me
(`test_worktree_venv_knob.py`, `test_plans_dir_contract.py`). The convention is
doing the work the windows were insurance for.

## A body wrong in a way that returns a plausible number

#212's four `gh api` invocations were **all wrong, none erroring** (C1, each
reproduced): `/timing` *does* expose `job_runs[]` but every `duration_ms` reads
0; the jobs endpoint defaults to `filter=latest` and hides billed re-runs; the
billing formula bills phantom minutes for skipped jobs whose duration is zero
or *negative*; the runs listing does support `created=>=DATE`. And the issue's
own anomaly rule **inverts** on a merely-busy day.

An issue distilled from two completed real-world audits is not thereby
verified — both audits had shipped on these commands. **"Two prior runs used
it" is provenance, not evidence.** Where a body hands over a command, run it.

## Q5, seventh consecutive negative for this repo

Ceiling 4, host-bound. Re-verified in one grep pass per Rule 5's
inherit-the-ceiling clause. Nine worktrees created and destroyed, no slot
pressure, no fall-through: Rule 6 clean on all nine signals.

Operational: **the pre-commit hook runs the full ~3-minute suite, exceeding the
default 2-minute Bash timeout.** It cost the orchestrator one killed commit and
at least one worker the same, before it went into every subsequent brief.
Worth stating in any brief for this repo.
