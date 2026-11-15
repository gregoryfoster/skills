## Session 2026-10-27 — private-library

The host repo is private, so this entry names mechanisms only; it was filed upstream as gregoryfoster/skills#502.

**Way in:** adoption ([creation.md](../../creation.md)). The epic already existed, written as a pre-cutover burn-down for a shared library moving to a new backend. It was adopted 2026-10-15 with `epic-edit.sh --adopt-live --lint-all`, after a dry run, and the re-scan from its newest child found 16 issues filed since.

**Shape:**
- 24 children ticked across tiers ordered by cutover weight: wrong data first, then the equivalence gate, then quality and hygiene, with the runbook last.
- 12 library releases are named on the epic. Each carried a downstream adoption note to the one consumer.
- The final child was an operator-run runbook, so the epic stayed open through the flip by an owner decision.
- 19 log entries over 12 days. It launched 2026-10-26; the epic closed early 2026-10-27 UTC on an empty re-scan.

**What was different:**
- The gate was a live equivalence run, comparing the old production stack with the new stack's rehearsal migration. Its reds were triaged into harness children, verified per entity, and re-run on each upstream rehearsal.
- The flip itself belonged to the upstream repo's launch runbook. The host's runbook could only mirror it, and it had to be corrected after the launch to say what had actually been done.

### Findings
1. **After a promotion, an old hostname can reach production.**
   - Opt-in live smokes defaulted to the pre-production hostname. Their only gate was credentials, and 14 of 17 wrote throwaway records.
   - After the launch, that name served the production box.
   - The coordinator caught it with a read-only probe, comparing the site index's `home` field across all three names, and posted a hold before anyone ran the suite.
   - The guard it briefed is closed by default: every smoke is a writer unless marked read-only. It is keyed on the identity the host serves, not on its name, so it survives a future alias. An inventory test pins it.
   - **Candidate rule:** a cutover runbook's post-flip section lists every default hostname in the host's tests and scripts, and probes what each one now serves.
2. **The gate window can close on you; decide the fallback evidence before the freeze.**
   - The gate's legacy side ceases to exist at launch, and its run window, between two upstream steps, passed without a run.
   - The owner accepted it as not run, on recorded evidence: the last full run with every red triaged and verified fixed, two consecutive zero-finding upstream rehearsals, and no operational code change since.
   - That held up, but it was decided after the fact. **Candidate:** the runbook names its substitute evidence in advance.
3. **A claim taken from notes was wrong again.**
   - The coordinator read a development-environment doc, which describes the two machines the *library* is developed on, as the consumer's host count.
   - "Flip both consumer machines" went into the merged runbook. The owner corrected it at launch: there is one.
   - This is the second run with this failure ([2026-10-20 private-library](2026-10-20-private-library.md), finding 2). **Candidate rule:** an inventory claim (hosts, machines, consumers) stays `[stated]` until the operator confirms it.
4. **Upstream's mechanics drifted from what the host recorded.**
   - The epic, and its parent, described the flip as a tunnel-target swap. As executed, it was a DNS record removal plus two hostname routes added to the tunnel.
   - Upstream's rollback section named only one of those two hostnames. The owner raised the gap upstream.
   - **Candidate:** at the final child, re-read the upstream runbook at its current commit, and diff it against the commit the host's runbook cites.
5. **The final child's thread closed the epic itself.**
   - The implementation thread ran the read-only verification, posted the summary and closed the epic. That skipped the final body write: the cursors were stale and the log had no closing line.
   - The coordinator then ran the closing checks after the fact. CI by job, the guard's offline tests and the live read-only probes all agreed.
   - `epic-edit.sh` wrote to the closed epic without complaint.
   - **Candidate:** the final child's kickoff says "the coordinator closes the epic", or close-out.md allows a post-close final write.
6. **Scripts.**
   - `scan.sh` caught every new issue, including three filed during the launch that were out of epic.
   - `epic-edit.sh`'s lint refused a bare ref after an owner/repo-qualified one, twice. It was right both times.
   - Missed: a `diff` read-back of a `gh` body tripped on jq's trailing newline twice. Once it hid a successful write behind a non-zero exit, and once it stopped a chain before a comment was posted. A read-back helper that normalizes the trailing newline would remove both.
