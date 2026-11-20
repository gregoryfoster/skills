## Session 2026-11-17 — private-library

The host repo is private, so this entry names mechanisms only; it was filed upstream as gregoryfoster/skills#678. This host's earlier entries are [2026-10-20](2026-10-20-private-library.md) and [2026-10-27](2026-10-27-private-library.md).

**Way in:** a whole-backlog audit ([creation.md](../../creation.md)). Three read-only agents audited the backlog the day after a shared library's backend cutover, and the coordinator spot-checked their claims. The epic's dispositions were 15 lines in four tiers, 7 parked and 4 closed with the operator's approval. Its rule was the operator's one line: cutover follow-ups, then bugs, then what other repos wait on.

**Shape:**
- 68 child lines at the park: 63 ticked and 5 open, each waiting on an outside trigger. That makes about 53 slotted mid-run: implementers' residuals, review-born follow-ups, sibling requests and upstream releases that unblocked work.
- 75 check-ins over 22 days (2026-10-27 to 2026-11-17), in one thread that outlived several context compactions. The epic body and a scratch directory of ops files, briefs and scans carried the state.
- 19 library releases, 11 of them MINOR. The operator cut every one, usually in a separate thread, and the coordinator verified them.
- **Ending:** parking-lot mode. Every open child waits on an upstream release, the owner's account steps on a public package index, or a sibling's adoption.

### What was different

- **Releases were children in all but name.** The operator held one breaking MINOR for two days while eight changes queued behind it. Each breaking child drafted its consumer-adoption note on its own issue, unposted. At the tag, the coordinator merged the drafts into one consumer issue, re-checked against the consumer's current `main`, and filed it only with consent.
- **One child grew from a design question into a five-PR lift.** The operator asked for the tradeoffs instead of choosing, then declined the coordinator's recommendation in favour of the largest option, giving a reason ("utilization across repos will only grow"). It became a design doc, four code PRs, a release and three cross-repo adoption issues. The growth is what made the operator cut the held release first.
- **The verify recipe gained a release type.** Its evidence was the tag on `main`, the version check, and the publish log: which path the gate took, whether the cloud auth step succeeded, and a per-file checksum read back from the index.

### Findings

**Verify**
1. **Tree equality is a cheap bulk check.**
   - One implementer thread landed the five-PR child and its release before reporting.
   - The coordinator verified all of it in one loop. For each PR it read CI by job on the head and on the merge, and checked that the merge's tree equals the head's (`git rev-parse <sha>^{tree}`). Equal trees prove nothing landed beside the reviewed head.
   - **Candidate:** `verify-ci.sh` reports tree equality alongside the job table.
2. **A docs-only merge has no CI run on `main`.**
   - A path filter skips the workflow, so "CI on `main`'s tip" had nothing to read.
   - The check became: the last code merge's run, plus a diff from it to the tip that touches only ignored paths. The release gate makes the same argument when it reuses a pass.
   - **Candidate:** check-in.md says so beside the "CI on `main`'s tip" rule.
3. **Runtime mutation can prove a fix from the coordinator thread without touching the tree.**
   - For a two-part race fix, a pytest plugin kept in the scratch directory monkeypatched each half away at import. It ran the suite under `PYTHONPATH=<scratch> pytest -p <plugin>`. Each mutation reproduced failures (3 and 3), so both halves are load-bearing.
   - A refactor's new routing gate was exercised the same way, against a scratch copy.
   - Nothing is written to the tree and nothing is committed, so the Iron Law holds, and the tick rests on evidence rather than the PR's claim.
   - **Candidate:** check-in.md names runtime mutation as admissible tick evidence for a fix whose tests could pass vacuously.
4. **A flaky-test child found a live bug.**
   - A test-only child (a wall-clock bound beside a watchdog invariant) led its implementer to a live race in the sync HTTP transport. A retry sleep that overran its deadline let the watchdog shut down a pooled keep-alive socket, and the next attempt started after the deadline.
   - It was filed, fixed in the same thread, and slotted into the bugs tier already ticked, with its own verification.
   - The brief had undercounted too: dropping the bound removed one of two exposures, not both.

**Briefs and the coordinator's own claims**

5. **"Re-check the brief against `main` first" kept paying.** Implementers corrected briefs in place several times. Among the errors:
   - a method census split differently (15/11/1, not as briefed);
   - a cross-repo gap cited as open had closed two months earlier;
   - an async-parity duty that no consumer needed;
   - a re-read through the single-record read, when every list row omits the body by an upstream rule;
   - call-site counts.

   Several were `[traced]` or recalled, not measured, so the label rule did its job: they were visibly unverified when posted.
6. **A `[stated]` budget in the header goes stale.** A doc's token count was carried as `[stated]` for days. Measured exact at the park, it was 943 lower, because a child had moved records out.
   - **Candidate:** measure exact at the park, and whenever a child touches a doc the header tracks.

**Tooling**

7. **The editor's lint caught four wrong refs this run, every one correctly.** Each was a bare `#N` written after a cross-repo ref on the same line, which reads as the host's issue.
   - **Friction:** the lint also refuses a short ref inside quoted text, such as an issue's own heading, so the quote had to be paraphrased.
   - `add-line` takes `line`, not `text`. The USAGE error says so plainly.
8. **The refresh-hook PR sat open for two days.** It was merged on the operator's word, once the coordinator had confirmed two things: the submodule move was a fast-forward (227 upstream commits), and the PR was conflict-free. No CI ran, since the paths are ignored. Same pattern as the [2026-11-17 status](2026-11-17-status.md) run's S6.

**Scheduling**

9. **The park's timer is a one-shot re-created at each check-in, not a recurring cron.** Per the same status run's S1, a recurring session cron expires silently after 7 days.
   - The operator asked for a check-in every 12 hours, reset at each check-in. So the coordinator schedules a one-shot 12 h out, and every check-in (the operator's or the timer's) deletes it and schedules the next.
   - It still dies with the session. The epic's parking-lot section says so, so nothing claims a watch that isn't running.
   - **Candidate:** close-out.md's parking-lot mode recommends this pattern, and requires the epic to state the session-scope caveat.

### Ending

Parked 2026-11-17 on an empty re-scan. Retitled "parking lot", with `Next: none`.
- A **Parking lot** section gives each of the 5 open children brief-grade content: an observable trigger with its probe, the steps when it fires, the hazards, and the dated evidence.
- The 9-row Parked table was re-read. One sibling epic it cited had closed, and that row was corrected.
- The 12 h timer continues as the watch.
