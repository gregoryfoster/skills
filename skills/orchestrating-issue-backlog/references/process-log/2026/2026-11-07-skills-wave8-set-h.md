## Session 2026-11-07 — gregoryfoster/skills (epic #516, Wave 8 set H: the patching-hosts and host-disk field batch)

The sixth of Wave 8's local orchestrators. Every item came from a cohort host's real run since 2026-11-03.
- **The brief was the plan** (a comment on #592). Steps 1–9 were skipped.
- **Shipped:** #581, #593, #594, #582, #592, #464 (asks 1 and 2), #556, #558, #604, and four journal entries (#580, #583, #595, #474), plus four review rounds (CR 1938–1984). Follow-ups #607 and #608 were filed. The wrap-up is on #516.

**Shape:** four chains.
- **Parallel:** A1 (#581, #593, #594, #582: `probe.sh`), B (#556, #464 ask 2: `apply.sh`, the knob), C (#558, #604: maintaining-host-disk), J (the journals).
- **Serial:** A2 (#592, #464 ask 1) started from `batch/h` once B had merged (it shares `knob.md` and `run.md`) and A1 had too (it shares `probe.sh`). Each later brief carried a "Handoff from" section.
- **Reviews ran beside the chains.** Each worker stayed alive after its merge and took its own review fixes by message, so the fix rounds kept the worker's context and worktree. Reviewers were fresh agents in their own worktrees, given the code range and the issue, never the worker's conclusions.
- **Counts:** the base matched the brief exactly (9,854 / 327 / `8980eca09597`). The first integration gate, after four merges, read 1 failed (lesson 1). Every later one closed by file: 9,993 / 392 after the round-2 fixes, where all 65 new skips are journald tests that need GNU `stat` and `systemd-analyze` and ran on Linux (ubuntu 22.04 to 26.04). The skip hash moved for that reason only.

## Lessons

### 1. Two workers on disjoint files still collided, through a test that pinned the other's text
B's #464 doc test asserted `probe.sh`'s refusal of `--lane` without `--dry-run-into`. A1's #593 replaced that refusal with a warning, in parallel. Neither worker's gate saw it: each ran on its own branch. The integration gate after the first four merges was the first red (1 failed). The file map said "no shared file"; the test read a file across the boundary. Two workers then fixed the same test at once, because the orchestrator routed it to one and the other's commit hook met it first: a "drop it" message arrived after the commit. **Route an integration failure to the worker whose hook will hit it next, and tell every other worker on the batch it's taken.**

### 2. A state machine fixed by adding states keeps producing defects; the round that removed states ended it
#592's `cadence:overdue` dated the last run by the run directory's name. Round 1 found that a recovery point taken before the window made that window read as missed (CR 1956). The fix dated runs by the bulk's line in `steps`, and added "no run" for a directory without one. Round 2 found that a retention sweep then turned every overdue host into "no run" (CR 1969). Its fix added "emptied" and "unread". Round 3 found that one old cut-off bulk switched the check off for good, and that every rebooted run's `journal/` subdirectory defeated "emptied" (CR 1979, CR 1980). Each round's 🔴 came from the previous round's new state. The round-3 fix brief said to remove states instead: date a directory by its bulk line where readable, else by its name, and let the period floor (CR 1957) absorb the original false positive. Round 4 found none of the earlier 🔴s back, and one false sentence: the brief's own bound on the simplification's cost ("hides at most one period"). An abandoned attempt resets the count. That cost was stated truthfully, as "the last attempt", rather than fixed with a fifth state (CR 1984), and the operator was asked to confirm it. This is set R's lesson 2 again, on a different state machine.

### 3. Measure the instrument across versions before writing a rule about it
#604's journald merge rule went through three versions. The first was `cat-config`'s (the main file is the first of four directories). Round 1, running `systemd-journald` itself, found that journald reads `/etc` only (CR 1950). Round 2, on newer images, found that rule was only true up to 255 (CR 1963). The worker then measured the boundary at 256 on Fedora, not the reviewer's 257. Round 3 found that a dangling symlink is passed over, not treated as a mask (CR 1975). The oracle that settled each round was the daemon run standalone in a privileged container, read by its own `Fixed … max_use=` line. `systemd-analyze cat-config`, the obvious oracle, shares the very error it was meant to catch. #608 carries the same rule to patching-hosts' `read_journal`.

### 4. A brief's "already fixed" is a claim like any other
The brief said #474's second finding was fixed by #488. The journal worker read #488's closing comment and the tree: it wasn't. #607 now tracks it. The brief's other errors were paths (`tests/structural/`, `skills/curating-context/scripts/measure-context.sh`) and one line number. Workers posted each correction on its issue before building.
