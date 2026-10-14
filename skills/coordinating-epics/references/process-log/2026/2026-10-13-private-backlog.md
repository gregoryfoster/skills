## Session 2026-10-13 — private-backlog

A whole-backlog audit of a private service repo, posted on gregoryfoster/skills#348 as "a seventh burn-down". The repo is private and this log is public, so this entry names mechanisms only. The way in was an audit of every open issue plus the operator's rule: *"technical correctness and operational stability, so feature development can resume safely; front-load anything an external repo is waiting on."* As of 2026-10-14 the epic is still open. Its last check-in was about 2026-10-13, so this entry is dated by that check-in. Findings are numbered 83 to 154, continuing #348's numbering, and are cited by number only.

### Shape

- **Way in:** whole-backlog audit. 78 open issues, the oldest six months old, with no design doc and no epic.
- **The audit:** four parallel read-only agents split by age and area, plus a fifth scanning sibling repos for asks. About six minutes of wall-clock time.
- **Dispositions:** 25 closures proposed (10 done, 15 not planned) and 30 parks, which left about 33 in scope. The operator's walkthrough closed 16 of the 25 and kept 9.
- **Slotted mid-run:** bugs the audit found that no issue described, implementer follow-ups, a systemic issue clustering a recurring failure class, and one issue a sibling filed into the repo to supersede one the coordinator had filed.
- **Check-ins:** at least 16, from 2026-10-05 onward.
- **Days:** 2026-10-04 to about 2026-10-13.

### What was different

- **The epic was mostly closures and parking.** At this scale "backlog empty" is never the end, so the exit criterion was written at creation.
- **The audit was fanned out,** and the closures were held pending approval instead of executed.
- **Silent scheduled-job failures recurred.** A nightly CI job had failed every day for about ten weeks behind `continue-on-error`, and two more timers failed silently soon after. Together they became one systemic issue.
- **Production was quiet** for most of the run, which made disruptive ops items cheap and made live verification depend on scheduled runs.
- **The operator overruled the coordinator's "no issue" calls,** and the protocol changed to show those calls up front.

### Findings that changed the protocol

**Creation**
- Fan the audit out across read-only agents with a fixed per-issue schema: disposition, type, size, surface, live or latent risk, dependencies and shared files. Ship the schema and a "read-only, no GitHub writes" preamble (83).
- Brief subagents with the host's known tool failures. All five agents rediscovered the same broken CLI command (93).
- Hold proposed closures in a "pending approval" section, and park items in a table with a trigger per row, outside the checklist (84).
- The audit finds bugs no issue describes. Check each with `git grep` on `origin/main`, then file it or fold it into a line in the same function (85).
- Prove every open issue is accounted for: open numbers minus the refs in the drafted body must be empty (86).
- A guard that is cheap to tighten goes first, ahead of live risk, because it protects every later fix (89).
- State the exit criterion at creation (90).
- A quiet production system is an event window. Put the window and its probe in standing checks, next to calendar deadlines (91).
- Run every standing probe once when you write it, and paste its output into the creation log. One used a status value that doesn't exist (98).

**Verify**
- Read job-level check-runs, not run conclusions. Treat any failure on the SHA, including a scheduled job, as a re-scan input (97).
- "Cancelled: no runner" is neither green nor red. Tick on the job the change affects, name the pending ones on the line, and re-check them next time (99).
- Cover the range from every comment since the hand-off, not the SHA in the closing comment (100).
- Read `git log` over the whole range. An operator-run pass outside the burn-down held the exact repair one issue asked for (140).
- Wait for the final SHA's CI before ticking. Poll on `status`, and read `conclusion` only once the job has completed; a null conclusion rendered as an empty string ended one wait loop early (126, 132).
- A job missing from the head commit's checks may be path-filtered. Check the workflow's filter against the range diff (143).
- Verify a done item by its next scheduled run, because scheduled consumers of a shared client are the regression surface (122).
- Check for failed units during verification. Experiments leave debris that the next monitoring item would report (115).
- Before carrying out an approved clean-up, check it hasn't already been done (114).

**Harvest**
- A `For #<epic>:` heading in the kickoff prompt made harvesting a grep (103).
- Read every comment after the close and harvest each item's latest state. Two of four follow-ups were handled before the last comment (110).
- Cluster a recurring failure class into one systemic issue, and let the operator set its tier (104).
- Turn an implementer's "found a trap" aside into an issue the same day. Asides aren't in the follow-ups section and get lost (134).
- An item's live proof can reproduce the next item's bug. Look at the proof's other properties (123).
- A measurement taken for one brief can turn up evidence for another item. Write it on that item's line (120).
- A decision forced by a constraint settles part of an open design issue. Post it there as "decided by constraint" (119).
- An implementer's split-off issue can arrive as a ready-made brief. Add only the deltas you re-measured (117).

**Re-scan**
- Re-scan by `updated_at` as well as number, and read new comments on closed issues. A sibling posted its contract on a closed issue of ours, and it sat unseen for a day (152).
- Re-read every upstream ask the epic tracks as "waiting on them" at each check-in (152).
- An upstream can file an issue that supersedes one the coordinator filed. Confirm the upstream release is live before re-slotting, and move the dependency edges to the replacement (109).

**Blockers and gates**
- "Mentions us" is not "waiting on us". Classify each sibling hit as waiting on us, FYI or waiting on them, and check whether the ask is already done (87).
- External waits are coordinator lines. The coordinator drafts each reply and asks the operator before posting (88).
- A deferral due on a date goes in the standing checks with that date and what to confirm (149).

**Siblings**
- Before scoping a cross-cutting ops issue, check whether a sibling service already does the job. "Build alerting" became "adopt and wire" (105).
- Search the cohort for the same mechanism before briefing an ops item. Two siblings had tested backup regimes to port (112).
- When the operator points at a sibling's pattern, read the source. The recollection matched neither of the two real patterns (111).
- Before adopting a sibling's remedy, state the condition that made it safe there and check it holds here (146).

**Hand-off**
- An ops brief carries its own live measurements: the failing run's journal line, the real environment, a working sibling unit as contrast (101).
- A config file containing a setting doesn't mean the setting takes effect. Read the loader's prefix, alias and unknown-key rules (106).
- Measure who can reach what before recommending a security design (107).
- A long item with operator prerequisites can run itself if the brief says "draft the requests and stop" (116).
- When remaining items are equally urgent, order by context freshness. Slot a same-bug-next-stage finding immediately next (118, 133).
- State in the brief whether a forward fix can backfill history, with the retention evidence (121).
- Re-check an issue's stated consequences against the current schema (124).
- When the upstream has moved past an issue's pin, put the delta in the brief. Name a moving target as "the live value at ship time" (127, 154).
- Removing a vendored tree reaches every audit that excludes it. List the exclusions (128).
- Read the upstream's documented limits before sizing a fix to them (129).
- A suggestion in an issue body can break an enforced package boundary. Name the legitimate options (130).
- A bundling decision goes on both lines and both issues, with one brief and a pointer (131).
- When the bug is "this command breaks production", the brief forbids that reproduction and gives the safe one (135).
- Measure usage before handing off a large item, and test the issue's suspected cause against the incident data. Frame the diagnosis as "confirmed so far" (138, 141, 144).
- Name how co-threaded issues interact, not only that they share a file (142).
- For a dated security issue, re-measure how the system runs now, not just the code (145).
- When a brief narrows a broad catch, ask what it was absorbing, and test a malformed success response at each site (153).
- Measure the deciding fact before a design question. Carry the chosen option's cost into the brief, with the operator's own prerequisites checked (147, 151).

**State and writes**
- Derive assert counts from the previous body, never type them (92).
- Build readback patterns from the strings the transform inserted, never retyped text (96).
- Step 0 is an exact assertion: the only foreign change allowed is a verified tick. Ticks from the coordinator's own closures are expected, and a superseded line is rewritten to its replacement, not left ticked (102, 108, 125).
- Keep the last-written copy somewhere durable. When it's gone, GraphQL `userContentEdits` shows who edited the body and when (113).
- When the coordinator changes how it verifies something, edit the epic's standing checks in the same check-in. Its private memory had the fix and the epic didn't (148).

**Operator**
- Close what's done or superseded, and park ideas with a trigger. Record the rule in the epic (94).
- Re-verify each claim just before the closing comment, including an audit agent's (95).
- Ask follow-up questions as one structured question, each with a measurement and a recommendation (103).
- Record a design-choice issue's decision on it before slotting it (136).
- List every "recorded, no issue" call in the operator-facing summary with its reason, and later ask them up front (137, 139).
- Log every check-in, including one that found nothing (125).
- Finishing the live-risk tier is a decision point for the operator. Offer how to continue (150).

### Reversals

- **Foreign ticks.** Step 0 first allowed only the tick of the item being reported (102). A tick caused by the coordinator's own closure failed it (108), so the allowlist grew to include those. Check-in 7 allowed a tick by either the implementer or the coordinator (125). The verified-tick allowlist won.
- **Close or park.** The audit proposed closing 15 issues as not planned. The operator kept every idea and umbrella, and "park ideas, close only done or superseded" replaced the audit's rule (94).
- **"No issue" calls.** At first they were recorded in the epic log only. The operator overruled two from the summary (137), and the next check-in asked them up front (139).
- **Re-scan cursor.** The number watermark alone missed a reply on a closed issue. Updated-since was added (152).
- **Where the procedure lives.** The coordinator's improved CI check lived in its private memory while the epic carried the stale one. The epic won (148).
- **Tier order.** Carrying on in order was replaced by a decision point at the end of the live-risk tier. The operator chose a shortened tail (150).

### What v1's scripts would and wouldn't have caught

- **Would:** `epic-edit.sh` derives counts (92) and reads back the whole body, so there are no retyped readback patterns (96). It refuses any foreign change except ticks named in `--accept-ticks`, which covers 102, 108 and 125. `set-line` rewrites a superseded line. `--account` covers 86.
- **Would:** its default baseline lives in a per-user state directory, off the session scratch (113). It has no `userContentEdits` fallback; `--adopt-live` takes the live body after a manual read.
- **Would:** `scan.sh`'s updated-since cursor includes new comments on the epic's own items, closed ones too (152). Its commit range lists commits that name no item (140).
- **Wouldn't:** any CI reading (97, 99, 126, 132, 143), standing probes (98), or drift between the epic's standing checks and practice (148).
- **Wouldn't:** classify sibling mentions (87), or run the audit (83).
