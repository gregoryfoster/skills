## Session 2026-11-06 — gregoryfoster/skills (epic #516, Wave 8 set R: the red budget gate, #551's held pin, and the refresh hook)

The fifth of Wave 8's local orchestrators, after set T ([its entry](2026-11-06-skills-wave8-set-t.md), written by this run from set T's wrap-up).
- **The brief was the plan** (a comment on #596). Steps 1–9 were skipped.
- **Shipped:** #596, #551, #575, #566 and #584, plus four review rounds (CR 1888–1917). Follow-ups #603 and #605 were filed. The wrap-up is on #516.

**Shape:** three chains, no shared file between chains.
- **Parallel:** #596 (A), #551 (B), #575 (C1). #551's held branch was re-made onto `main` with `merge --no-ff` before any worker launched, so its worker started from the merged tree.
- **Serial:** #566, then #584, on the hook #575 had just changed. Each later brief carried a "Handoff from" section with the line windows and the budget the previous worker left.
- **Reviews ran beside the chain:** chains A and B were reviewed and fixed while chain C was still building. Chain C was reviewed after its last merge, split by area (state machine, readers), with one fix worker per area running at once on disjoint windows of one script.
- **Counts:** the base matched the brief exactly (9,737 / 327 / `8980eca09597`). Every merge closed by arithmetic: 9,745, 9,761, 9,811, 9,835, 9,840, 9,844, then 9,854 with this entry and set T's (+5 each). The skip hash never moved.

## Lessons

### 1. A body's line number and a shipped knob's name are the cheapest corrections, so make them first
#575 named a knob that never shipped. Correcting the issue before launch meant the worker never saw the wrong name. #551's "about `:33`" was `:37`, which the orchestrator's own grep of the merged tree caught before the brief went out.

### 2. A fix for "two sessions at once" needs a review that runs two sessions, and then reviews of the fix
#566's compare-and-swap stopped a second rollback, but not a rollback of a commit another session had just pushed. The round-1 reviewer reproduced that 3 of 3 with a pre-push barrier over a `file://` origin (CR 1896), and found the older heal race that fed it (CR 1897). The worker's tests had interleaved two reconciles that were both refused, which is the issue's own case: right, and not the whole race.

CR 1897's fix (take the dead marker by rename) then needed three more rounds. Each was scoped to the previous round's fix commits, and each found a defect that fix had introduced: a leftover take adopted later (CR 1906), a take dropped that was the only record of a kill (CR 1911), a same-second name collision the worker found itself, and a bash 5 `set -e` exit on a vanished file (CR 1914). Severity fell every round, from 🔴 to microsecond windows. The briefs told each fix worker to prefer removing a state to adding one; the round-3 fix (keep a take while anything it names is staged) did that, and was the first whose review found nothing worse than a test gap in its main path. Four rounds of review on one state machine is the cost of fixing an old race inside a set; filing it separately is the alternative, and it was weighed after round 2 and declined because later fixes were built on it.

### 3. A rule copied into N readers is N fixes, and the sweep finds N+1
#584 named two inline `merge_mode` readers. The worker found a third (the doctor's token check) and a fourth file read from the same raw entry (the hook's `.env` fallback). The round-1 reviewer found two gaps in the rule itself (a `--separate-git-dir` primary, an inherited `GIT_DIR`). Both were in all six places, including the `merge-mode.sh` copies the rule came from. The parity tests made the fix one change, because the readers are held to `merge-mode.sh`'s answers. The four copies outside the window went to #605.

### 4. The PATH trap moved from the gate to the commit hook
The brief warned that a missing `~/.local/bin` changes the skip hash. Workers met the other half: a commit hook run without `/opt/homebrew/bin` fails two socraticode tests for want of `node`, and an `export` doesn't carry between an agent's shell calls. A small commit script in the worker's scratch dir that exports `PATH` was what worked; the later briefs said so.

### 5. A budget-tight reference fills from both ends
`auto-refresh-hook.md` went from 9,463 to 9,916 of 10,000 across three issues and four review rounds, each worker told the figure the last one left. Three fix workers paid for their own sentences by trimming rationale, and a reviewer diffed each trim for a lost rule.
