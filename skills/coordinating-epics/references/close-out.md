# Ending a run

There are four ways a run ends. It closes. It hands a final child to the operator. It runs out of children before its exit criterion. Or it parks. A citation such as "watcher F58" names a run's entry in [process-log.md](process-log.md), then that run's finding number.

## The final child the operator runs

When the last child is the operator's (a cutover, a migration run by hand), consolidate first. Comments from many check-ins pile up on that issue: step answers, renames, verification debt, accepted behaviours, preconditions. Fold them into one ordered runbook (archiver 55, 56):
1. Verification debt to discharge first, on dev. Debts that share setup run together; one debt's setup can create the state the next one needs.
2. Production steps, with the answers already known.
3. Read-only verification.
4. Expected quirks, from the accepted-limitations routing.

Tag each item with the child it came from. **Before the last item ships, propose the end state**: close, or park, and what stays watched (processor F130).

## Closing

**The epic ends only on an empty re-scan.** Until then, promise only "the last *known* item". The run that said "this is the last one" found three more (status 48, 98).

**Closing checks** (archiver 58; watcher F58, F63):
- **Every sub-issue is closed.** Every unticked line is ticked, moved to a follow-up issue, or marked out of scope. Promised out-of-epic issues are filed (archiver 59).
- **The final state is re-verified independently,** never taken from the last thread's report. For example: SQL equality on destinations, the public object returning 200, the follower's journal.
- **Watching and verification debt are settled.** Each item is resolved, filed, or moved to a dated issue. A check dated after the end goes to a dated issue rather than holding the epic open (watcher F60).
- **Readings that need uptime come before any restart** (watcher F58).
- **The implementers' unfiled observations** are listed in the summary for the operator to decide on, never dropped.
- **The accounting check passes,** for a whole-backlog or number-range epic: `epic-edit.sh … --account [N]`.

**The order:** write the final body, then post the summary comment, then close. The final body write passes `--closed-ok`: a final child's thread may have closed the epic already (#502 F5), and without the flag the editor refuses a closed epic (#519). Its summary then names who closed it and when; if that wasn't the operator, say so in the summary comment. A summary groups by theme, not by issue order, and records the live state left behind (status 98, watcher F63). Post the summary with `gh issue comment N --body-file <summary>` (check `test -s` first), then `gh issue close N`.

**If the thread keeps coordinating follow-ups,** the summary restates the role: "This thread continues as coordinator for #A and #B; implementation stays in separate threads." Without that line, a later "proceed" read as "implement here", and the coordinator built and shipped a child in its own thread (archiver 60).

**Journal the run** in the process log: an entry file and one index row. The log is public; see "Adding an entry" there.

## An exhausted epic

The children run out before the exit criterion, or the exit criterion is met with the queue not empty (watcher F32, F33; private-cli 46). Either way, it's a decision point. Ask one structured question, for example:
- finish the remaining queue;
- finish through a named item, then close;
- close now and file the rest;
- switch to backlog mode with the operator's rule restated.

Record the choice beside the exit criterion.

## Parking-lot mode

When the burn-down is done but items wait on triggers, the epic can stay open as a parking lot (processor F135, F137, F138):
- Rename the title so it says so, and set `Next: none`.
- **Every parked entry gets brief-grade content:** the trigger, what to do when it fires, the hazards, and the evidence it rests on. A trigger may reach an implementer with no hand-off.
- At each trigger, the coordinator verifies, as at any check-in. When any upstream release lands, every parked item is re-sized against it, not only the one whose trigger fired.
- In this mode a check-in can be one item: "#29 closed; verified; parked set re-read."
