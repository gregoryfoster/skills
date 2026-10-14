## Session 2026-10-02 — private-cli

A burn-down in a private CLI repo, started from an upstream library release's adoption checklist. The coordinator ran from 2026-09-29 to 2026-10-02 in one thread, and each child was implemented in its own thread. The checklist closed within two days, and the coordinator carried on over the general backlog and then a second release's checklist that arrived mid-run. The tracker was never a GitHub epic: it lived in a host memory file. Its findings are one comment on gregoryfoster/skills#348, posted 2026-10-02. The host and its upstream library are private and this log is public, so this entry names mechanisms only. Findings as of 2026-10-02; later check-ins weren't reported on #348.

### Shape

- **Way in:** an adoption checklist written upstream, with one required fix, two optional simplifications and a suggested order.
- **Size:** the checklist's items plus the version bump, then two transport bugs from the backlog, then a second release's adoption.
- **Check-ins so far:** 11.
- **Tracker:** a host memory file with a one-line index pointer. No design doc and no GitHub epic.

### What was different

- Another repo wrote the epic, and that repo couldn't see this one's open PRs.
- The burn-down outlived its epic, so the coordinator had to say how it chose from the backlog.
- Implementing threads edited the tracker file themselves.
- Two triage outcomes ended in not doing the work as filed: a split, and a close as not planned.

### Findings that changed the protocol

Numbers are the comment's own (38–53). Another run's comment on #348, posted the same day, also starts at 38, so cite these as the private-cli run's.

**Starting from an adoption checklist (a fourth way in)**

- 38: at creation, list the host's open PRs and branches against each checklist item. An open interim PR added a warning that would become false once a cleanup landed. The order became: merge the interim, bump, finish the cleanup, remove the warning.
- 39: record an interim fix's debt on the later step that pays it, and update the record when a review rewrites the same passages in between.
- 40: read every per-change "Downstream" note and the dependency diff, not the summary. A summary said no code change was needed while one note said a fix was, and that fix gated the bump.

**Triage**

- 41: classification gets a fourth outcome, **split**. A tracker blocked on upstream held a separate bug that was live in production. It was checked against the code, filed on its own, linked and named next.
- 42: close as not planned is a check-in outcome, and the closing comment carries the evidence. A read-only look at a sibling repo showed that a proposed large production write targeted a display-only field already planned for retirement.
- 43: when the operator repairs data by hand, read it back from the public API before writing that it's done.

**Hand-off**

- 44: read `main` without switching branches. `git fetch`, then `git show origin/main:<path>` and `git grep <pattern> origin/main`, gave line-accurate briefs from a checkout parked on a stale branch.
- 45: a brief for a production write names the write gate and its width: send only the one field, check each derived value against the record's back-link, and stop for confirmation before writing.
- 46: add an "epic exhausted" step: close, or switch to backlog mode with the operator's rule restated. The next pick here depended on a fact only the operator knew, about where the CLI runs.
- 47: a new upstream release goes ahead of the named next item. Its brief added three things the checklist lacked, including refusing three commands that the bump would otherwise leave writing part of their work and then crashing.

**Verifying**

- 48: when an implementer corrects the coordinator's premise, search the epic, the trackers and sibling issues for the same claim.
- 49: look for a limit that repeats across close-outs. Three in a row said "not live-verified" for the same reason, which meant no change to the new backend had run end to end.
- 50: query check-runs per merge. Only one child's CI was checked independently of its closing comment.

**State**

- 51: a memory-file tracker needs the private-launch run's anchoring rule: anchor on text that doesn't change, check that the substitution happened, re-read before writing. Twice a `sed` meant to update the index line did nothing because another thread had already rewritten it, and a `grep -c` returning 0 was the only sign.
- 52: the index pointer carries only the state and the **Next:** item. It had grown past 600 characters of step history.
- 53: re-check blockers against the upstream tag list at every check-in, and give each blocker a written re-entry action, so a new release maps to its downstream work mechanically.

### Reversals

- 38: the upstream checklist's suggested order was replaced at creation.
- 48: the coordinator's recommendation repeated a premise from the upstream checklist, that a command would leave a record orphaned. The implementer's pre-build check found that an earlier call raises first. The coordinator re-read the code and posted the correction where the premise had also been repeated.
- 42: a filed follow-up closed as not planned, with the operator's agreement.

### What v1's scripts would and wouldn't have caught

- **Wouldn't apply:** both scripts read and write a GitHub issue body. A tracker in a host memory file is outside them.
- **Would, had the tracker been an epic:** finding 51. `epic-edit.sh` refuses with exit 3 when an anchor is missing, finds lines by ref rather than by old text, and reads back every write, exiting 4 on a mismatch. A silent no-op substitution is the case it was built against.
- **Partly:** finding 53. `scan.sh` reports each cross-repo ref's state and last activity, but not the upstream tag list, so "the new release carries none of these" still takes a separate read.
- **Wouldn't:** findings 38 and 50. At creation there are no cursors, so open PRs aren't matched to checklist items, and neither script reads check-runs.
