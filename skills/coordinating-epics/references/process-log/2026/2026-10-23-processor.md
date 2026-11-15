## Session 2026-10-23 — CannObserv/processor#24 (parking lot to close)

The second half of the run in [2026-10-12-processor.md](2026-10-12-processor.md). The epic had been a parking lot since 2026-10-11, with three items waiting on upstream releases and one on a broker decision. Over the next twelve days, every trigger but one fired. The epic adopted this skill's v1 scripts mid-run. New issues reopened active work three times, including a security tier. The operator closed the epic on 2026-10-23, with one item left to continue alone. Findings F140–F178 are on [#348](https://github.com/gregoryfoster/skills/issues/348), cited `processor#24-F<n>`. Bare `#N` refs below are CannObserv/processor's.

### Shape

- **Way in:** a parking lot with brief-grade parked lines (F135–F138). Check-ins ran only on a trigger, a new issue, or the operator asking.
- **Children in this phase:**
  - three triggered shared-library bumps: #29, #21, #37;
  - the skill adoption, #52;
  - seven new issues: #57, #58, #62, #65, #66, #67, #70. Three were filed by the coordinator: #66 from a measurement, #67 under a rule it had set, #70 from a closed child's open list.
- **Check-ins:** about 14, from 2026-10-12 to 2026-10-23.
- **End:** closed by the operator with #54 alone, which waits on a broker window gated by another issue. 26 lines were resolved (25 shipped, plus #70 not planned), and 1 was out of the epic.

### What was different

- **The skill was adopted mid-run, on a live legacy body.** A pre-flight against a copy passed, but the dry-run diff against the live body showed a split header. Reading the diff, not the exit code, caught it (F140, F141, F144).
- **Upstream coordinators did much of the brief.** The shared library's coordinator replayed Processor's own corpus through each release and posted the moved goldens on the parked issue. So the coordinator verified rather than derived (F154, F155).
- **Pre-approved cross-repo posts.** The operator approved one child's posts in advance. The approval was recorded on the child, with its order, stop conditions and scope (F157).
- **A security tier arrived through a sibling's rollout.** co-processor was the cohort's Tailscale canary. A second exposure the issue mentioned only in passing (a venv's certifi) was measured here, live, and filed (F167, F171).
- **The coordinator's own triage was corrected by a child.** Two flaps it had called "the same signature" were different kinds of event. A cohort Mayfly questionnaire, answered by 8 peer agents with nothing filed in their repos, found the cause: a host memory-balloon reclaim, then per-VM pauses (F175).
- **The session scratchpad vanished mid-run.** Nothing was lost: the state lived on the epic and in memory (F165).

### Findings that changed the protocol (proposed)

**Verifying**
- For a version bump, the live gate is each source's first post-bump output equal to its last pre-bump output, and the close waits for every source to report (F139, F151).
- A docs-only child is verified against the last runtime-touching commit, not `origin/main` (F163). A host-only child swaps CI and `REVISION` for host reads (F170).
- Close any known limit that only needed time (F160). Before ticking, sweep the child's comments for open items and give each a home (F174).
- When a child feeds an outside status table, check that the row is complete, not just that the post exists (F178).

**Handing off**
- Before applying "coordinate if function X changes", check whose copy of X runs (F156). A brief that departs from a written rule also asks for the rule fix (F158).
- Grep every moving case ID across the test tree, not only the assertion that names it (F155).
- When a vendored skill takes a major version, check every skill it invokes against what's linked (F164).
- Check that each cross-repo venue a brief names is still open (F162).
- A coordinator-filed issue carries its probe, and "Done when" is that probe flipping, plus a control (F171).

**Recording**
- A rule the coordinator sets goes into the epic's governing text word for word, not "a rule was set" (F168, F173).
- Carry outside readings on an "Awaiting" line until they land or are waived (F172).
- At close, copy the facts a surviving item depends on from the watch blocks onto that issue (F176).

### Open suggestions for the scripts

- **One token for every repo:** `scan.sh` 404s and lint refusals on repos the epic's token can't read (F142, F169).
- **The usage text:** say that placeholders expand in every op (F166, which corrects F161).
- A disposition the count derivation reads separately (`not planned`, `out of epic`) (F177).
- An "awaiting" convention for outside readings (F172).
