## Session 2026-10-12 — CannObserv/processor#24

The coordinator run over Processor's backlog. It started on 2026-10-03, one day after Processor's v1 went live, while Watcher, its sibling, moved from shadow mode to cutover to deleting its own extraction code. The operator gave no ordering rule, so the coordinator proposed one. The backlog was burned down on 2026-10-11, and the epic became a parking lot. The last check-in was on 2026-10-12, when the first parked item's trigger fired. As of 2026-10-14 the epic is still open as a parking lot, holding CannObserv/processor#21 and CannObserv/processor#37, so this entry is dated by that last check-in. Its findings run from 64 to 139 on gregoryfoster/skills#348 and are cited `processor#24-F<n>` (F87). Below they appear as F<n>.

### Shape

- **Way in:** a backlog with no rule. The coordinator proposed an event window: do first what is cheapest while the bus is empty, before Watcher turns shadow mode on. It added a standing rule, "a shadow mismatch outranks everything", and put both under "challenge it here" (F64). It also audited the design doc's cross-repo table against the target repos (F65).
- **Children:** six open issues at creation. One was the service's umbrella issue, parked with a re-entry test (F67). The audit added one more, filed during creation. About eleven more were slotted mid-run, at least four of them filed by the coordinator. The order ran in tiers: before cutover, then deploy safety (added mid-run, F100), then agent tooling.
- **Check-ins:** creation plus 15. Fourteen ran from 2026-10-03 to 2026-10-11, and one parking-lot check-in followed on 2026-10-12.

### What was different

- **The coordinator was also a party to the work.** It ran Processor's side of a live agent-to-agent channel that gated Watcher's shadow flip (F72, F73, F77).
- **The coordinator's own host was the deploy target.** One child rebooted it. Another moved deploys to a release directory under a service user, which rewrote the epic's own verify recipe (F69, F95, F97).
- **Milestones in another repo drove the run:** Watcher's shadow flip, its cutover, its soak and its deletion of extraction code (F102–F107, F119, F120).
- **Briefs labelled each claim** `[measured]`, `[traced]` or `[stated]`, and the implementers upgraded traced claims before building on them (F88, F110, F113).
- **It was the first run to end as a parking lot.** That end state was decided before the last item shipped (F130, F135, F137).

### Findings that changed the protocol

**Creation**
- With no operator rule, propose one, with its tie-breaks, for the operator to challenge. An event window has no date, so re-read the live flag at every check-in (F64).
- Audit every "cross-repo changes" or "follow-ups" table in the design doc against the target repos. Of eight rows, two had never been posted and one operator step was tracked by nobody (F65).
- An issue that transcribes another repo's rules decays fastest. Read that thread's newest comment before slotting the issue (F66).
- Sort out umbrella and tracking issues before ranking. Park each with a re-entry test (F67).
- A grep that finds nothing is weak evidence. Write "probably moot: confirm", and leave the confirming to the implementer (F68).
- Offer a split along an approval gate, and record the offer on the line (F71).
- Paired lockstep issues in two repos get a conjunctive re-entry test: the release exists **and** the peer is ready to take it in the same step (F81).
- Before sizing an adoption ask, measure how far the pin is behind upstream. "Take release X" crossed five minor versions (F80).

**Verify**
- Proof on a live-traffic service has a floor set by the traffic's cadence. The implementing thread owns the live evidence in its closing comment. The coordinator waits one cadence or asks for the trigger, and doesn't collect the evidence itself (F84).
- List every non-green run on the PR with a one-line cause, found by reading its log. A red run was nearly blamed on the issue in progress (F96, F122).
- If "Done when" includes an operator install step, the PR says "Refs" rather than "Closes", and the issue closes only on the install's live evidence. Check that the close came after the install, not only after the merge (F99).
- When an item changes the deploy model, take the new recipe from the item's merged docs. The check-in that verifies the item is the recipe's first run (F97).
- When the shipped thing is something the coordinator's own session runs, one real use is part of the verification (F136).
- For a dependency bump, the live gate is each source's output digest before and after the bump (F139).
- Read each "not filed" item against the epic's list of gates. A CI gate on deploy turned a flaky test and a Docker Hub outage into deploy blockers (F109, F117).

**Harvest**
- A box moved between items gets a pointer on the issue it left (F94).
- A decision that transfers ownership lists the new owner's duties: here a catch-up policy for a pin eleven minor versions behind (F131).
- When a local decision amends something a peer agreed to, telling the peer is part of done (F128).
- For each milestone, list the local docs and rules that depend on it. File the doc follow-up when it lands, even when nothing fails (F120).

**Re-scan**
- File and slot new issues **before** writing the next hand-off (F116).
- At every check-in, re-read the state of every cross-repo ref in an open item, not only the blockers of parked items (F86). For a notice item, check the target's current committed text, not the quote from when the item was filed (F90).
- Rewrite Measured state from scratch at every check-in, and stamp each bullet. For each parked item, re-run the query that would find its trigger, a keyword search and not only the known numbers. Appended bullets hid an upstream ask for five days (F133).
- When any release lands, check every parked item against it, not only the one whose trigger fired (F138).

**Blockers and gates**
- A standing rule needs its probe written beside it in the epic (F82). Record a scheduled fault injection there too, with its window and expected log signature (F83).
- Check a probe anomaly against the verification-debt list before triaging. A broker reboot discharged a three-day-old debt (F98).
- Correlate across peers before blaming one. Then check the network layer's log and measure the user-facing impact. A first occurrence with no impact gets a re-entry rule, not an issue (F123).
- Record **Last probe** separately from Last check-in, start the next probe from it, and probe last. A five-hour blind window held two production changes (F112, F115).
- Keep a **Milestones** block near the top of the epic, saying where each event will be announced, and read it first (F102, F107). Draft how the rules and the probe will read after each milestone (F103). List the rules each milestone switches on **and** off (F119). Flag parked items whose re-entry test depends on peer state a milestone removes (F106).
- During a peer's soak, every hand-off says whether deploys are allowed (F104). A policy that creates recurring cross-repo posts doesn't grant standing approval for them (F111).
- When a decision replaces an oracle, prove equivalence against the old one while both still exist. Here 13 of 13 goldens were reproduced (F126, F132).

**Hand-off**
- When an external party is waiting on you, unblock them first, then do the bookkeeping (F72). Expect your own post to change the state you are about to write, and re-measure after posting (F73).
- A hand-off that reboots or redeploys the coordinator's host goes out only after the state is on GitHub (F69). On resume, list the background waits and re-arm each one from its cursor (F76).
- Measure live state. A host that has never rebooted since install turns a reboot into the first boot-ordering test (F70). Frame hazards as things to weigh (F75).
- Label each claim's evidence level, and ask the implementer to upgrade `[traced]` before relying on it. This applies to the diagnosis of a bug as well as to facts (F88, F110, F113).
- When a decision names a code identifier, check every writer of it and every test that uses it. The literal set was broader than the intent (F85). If a brief narrows the encoding without changing the intent, say so; don't reopen the question (F89).
- Probe the coordinator's own issues at hand-off. One filed during a live exchange asked for a field the library can't produce (F79).
- The implementer's first step is a review of the hand-off against its targets, with corrections posted on the issue (F92).
- A hardening item gets a measured host survey: identity, groups, reachable sockets, secret modes. That survey found a `docker` group membership, so code execution meant root (F93).
- At hand-off, check whether the item changes an assumption in the epic's recipe or probe, and mark it before the work lands (F95).
- Before offering options for cross-cutting infrastructure, check whether a cohort service already owns the job (F105). Check what sibling repos already did. Give a recommendation plus its traps (F121).
- When a brief reuses a component, state the context it was built for: sync or async, oneshot or long-running (F114).
- Before planning to stop a production service to prove a notice path, ask whether the other side can simulate the condition (F118).
- Post a brief only for the item that is next now (F124). The brief goes on the issue, and the kickoff prompt points to it (creation confirmations).

**Operator**
- Group the operator's decisions into one structured question per check-in, each with a recommendation and its evidence (F78). Ask the next item's decision at the check-in, with the measured facts in the option text (F125).

**State and writes**
- Treat a failed edit step as a failed edit. A failing assert still let the PATCH run (F101).
- The read-back proves the write, not the content. Lint the new body for the edit tool's artifacts first: escaped backticks, placeholders, stray braces, duplicate headers (F129).
- Every ID, URL and timestamp comes from a command's output in the same script, never from typing (F91, F127, F134).
- A live channel's outcomes land on a durable issue that the epic links. The epic never names the channel (F77).
- On a shared findings thread, cite findings as `<epic>#F<n>` (F87). A rule added to the skill issue goes into the epic's hand-off template in the same check-in (F108).

**Close-out**
- Propose the end state before the last item ships (F130). The switch was then four mechanical edits: the title, `Next: none`, the section heading and the log (F135).
- Before an epic becomes a parking lot, give each parked entry brief-grade content: the re-entry test, gates, coordination duties and done-when. The first trigger reached the implementer before any hand-off (F137).

### Reversals

- **Typed timestamps.** "About when this will post" became "run `date -u` just before composing" (F91). That failed again, because the edit text was composed before the command ran, so the time is now computed in the shell and interpolated (F127). v1's `epic-edit.sh` injects `{now}`.
- **Measured state.** Bullets were appended at each check-in. They are now rewritten from scratch with per-bullet stamps (F133). v1 has the `replace-section` op.
- **Probe window.** The probe started from Last check-in. It now starts from Last probe (F112, F115). v1's epic template carries a `Last probe` line.
- **Ordering.** New kinds of issue were first slotted by judgement. The rule is now amended visibly with a new tier and its reason (F100).
- **Early briefs.** Briefs were posted for items further down the list, and one was corrected two check-ins running. A brief now goes out only for the item that is next (F116, F124).
- **Alerting.** The options led with a self-monitoring workaround copied from Status. They now lead with the cohort service that owns the job (F105).
- **Live proof.** The plan was to stop a production service. The peer simulated the condition on its own side instead (F118).
- **Citations.** Findings were cited by bare number. They are now `<epic>#F<n>`, because numbers collided across runs (F87).

### What v1's scripts would and wouldn't have caught

- **Would have caught the edit accidents.** A failed assert can't reach the PATCH, since `epic-edit.sh` refuses with exit 3 and writes nothing (F101). The lint flags escaped backticks (F129) and resolves each new comment link, checking it is on the issue it names (F134). `{now}` removes the typed time (F91, F127), but a hand-typed time in the text still passes the lint.
- **Would have half-caught the stale parked items.** The `cross_repo` report in `scan.sh` lists every `owner/repo#N` in the body with its state, so the closed blocker CannObserv/watcher#342 would have shown (F86, F133). It wouldn't have found the upstream ask, a new issue in another repo that no line referenced. That took a keyword search.
- **Would have helped the hand-off order.** `scan.sh` runs first in the check-in, so new issues show before the hand-off is written (F116).
- **Wouldn't have caught the host-side failures.** Neither script reads a journal. That leaves out the probe and its blind window (F112), the digest gate (F139) and the cause of each non-green run (F96, F122, for v1.1's `verify-ci.sh`).
- **Wouldn't have stopped stale Measured state.** `replace-section` makes a rewrite easy, but nothing forces one. The lint doesn't check for duplicate section headers (F133, F129).
