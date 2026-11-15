## Session 2026-10-28 — CannObserv/replicator#135

A child epic of CannObserv/watcher#368 (headless Watcher). It was adopted three days after its creation, parked once its exit criterion was met, handed to another coordinator thread during the park, and closed after the sibling's producer flip. Replicator is a bus worker with no HTTP surface. It deploys as the main checkout plus a service restart.

The run prepared Replicator's consumer of a config/state stream for a producer change made in a sibling repo, then retired the docs' "until the flip" wording once the change happened. The shared contracts library lives in a **private** repo, so it is named here by role only: "the contracts repo" and "the library".

### Shape

- **Way in:** inherited, then adopted. The epic was filed from a cross-repo design doc's issue breakdown, with two children and no cursors. Adoption added the template sections in one call. `scan.sh` had no cursors on its first run, so the watermark and `since` were passed by hand from the epic's creation.
- **Children:** 2 at creation, 5 by the close:
  - one filed at adoption, on the operator's decision;
  - one review-born follow-up, bundled into an existing child by the operator;
  - one post-flip docs child, filed by the last pre-park implementer, parked, then built after the flip.
- **Check-ins:** adoption, 3 check-ins and one reorder up to the park (2026-10-17 to 10-19). Five status probes during the park. Then the hand-off, the flip read-back, the docs child's pre-flight and brief, and its verification (2026-10-26 to 10-28).
- **Baseline:** 1408 passed and 1 skipped at adoption, 1735 and 1 at the close. The skip didn't change. Most of the growth came from other epics' children running on the same host.

### What was different

- **A large version jump was hidden in a small child.** The behaviour child needed the library's next release, and the host's pin was 17 minor releases behind. The library's local mirror was also stale, two releases behind the index. The coordinator found this only by comparing the pin with the index during adoption; the issue said nothing about it. It became its own child, unblocked and ordered first, while the release it waited for was still being cut.
- **The upstream helper's rule differed from local behaviour.** The library shipped a decision function for the new ordering token. Given two frames without the token, it answered "stream order". The host's consumer also dropped a frame stamped older than the one it held, and a test pinned that behaviour. Calling the helper alone would have changed behaviour for every frame before the flip. The brief made it an operator decision: keep the local guard for frames without the token, and let the token decide alone once it's present. Starting the thread approved it.
- **A release reordered the queue.** Once the release was published, the behaviour child moved ahead of the docs child. Landing it first let the docs child describe the consumer as shipped, not as planned. One brief was edited in place, and the other written fresh.
- **The epic parked rather than closed.** The exit criterion was met before the sibling's flip, but the flip leaves a Replicator-side cleanup and a check against real frames. The operator chose parking-lot mode, with an AND trigger: the flip issue closed, and the new producer live.
- **The coordinator changed mid-park.** When the flip went live, the operator handed this epic to the thread already coordinating the host's whole-backlog epic. One hand-off comment carried the state, the readings and the due order. The receiving thread ran both epics from then on. This epic stayed the parked child's record, and the backlog epic only ordered it.
- **The AND trigger fired in substance, not in state.** The flip issue stayed open for its second half, a sibling-internal cleanup. The operator judged that this didn't hold the parked child, and unparked it.

### Findings

**Adoption**
- **Compare the host's pin to the index, not to the issue,** whenever a child needs an upstream release. "Patch bump plus a rule" was really a 17-minor jump.
- **Sync the local mirror before measuring version distance.** A stale mirror under-reported the gap by two releases.
- **Split a child that needs a release:** first a catch-up to the newest published version, which is unblocked now, then a one-minor bump that carries the behaviour. The catch-up absorbs the risk while the release is still being cut.

**Harvest**
- **A note harvested from an upstream plan goes stale when the plan ships.** Two of the planned rule's cases didn't ship. The coordinator marked its own note as corrected, in place and visibly, and posted the shipped rule beneath it, quoted from the released wheel.
- **Read the released artifact, not the report.** Unpacking the wheel showed the helper's exact branch for two unordered frames, and that settled the brief's one decision.
- **An upstream coordinator's "pointer posted" claim can be wrong.** The release comment listed a pointer on the host child that never arrived. Its content was already there from the harvest, so the gap cost nothing. It was reported, not chased.

**Verify**
- **"Not deployed yet" in a report can go stale within minutes.** The service had restarted after the report was written. Read the unit's start time and build stamp, not the comment.
- **Discharge "no traffic yet" debt at the next check-in, from the journal.** Count outcomes per build window, and use its timestamp to attribute a `worker stopped` line to the outgoing instance.
- **A multi-commit push builds only its tip.** An implementer's claim that CI ran on every commit didn't hold. The tip was green, so this was noted, not blocking.
- **The coordinator ran one approved host step itself:** the code-index refresh that the implementer's run had skipped because another session held the lock. It is non-code and idempotent, and the host steps called for it.

**Hand-off and the flip**
- **H1. Two epics in one thread can track one child twice.** Right after the hand-off, the receiving thread wrote that the parked child was "tracked as a child of" the backlog epic, while this epic stayed its record. That would have produced two checklist lines and two sets of ticks. It was corrected in place, on both the epic and the child. The rule that held: the record stays on the epic that parked the child, and the other epic orders it from its Parked table.
- **R1. A read-back can rest on absence, if the log's rule is traced.** The consumer logs an apply only when an interval changes, so "every host holds an ordered frame" was inferred from three zero counts plus the helper's rule, and labelled as inferred. The broker's own read of the stream confirmed it independently the same night.
- **R2. A sibling's account of your service's state is a claim.** The flip report said Replicator "ran on its conservative default" through the 2 h 47 m gap. The journal showed that the worker kept the frames its boot replay had applied, the old producer's last values. Those happened to equal the default. Corrected in the read-back, before anyone relied on it.
- **R3. Retention can be inferred from the replay count.** The new producer trims to 500 entries, and a replay the next day read exactly 500. Against the publish rate, that means the old producer's frames have very probably been trimmed. Labelled as traced; only the broker can read the stream.

**The parked child**
- **P1. A parked pre-flight is a list to re-run, not a result.** Re-run nine days later at the trigger, it found two moved line numbers and a site the issue never listed, the code-search manifest's descriptions. The doc's size had also shrunk the headroom the parked brief assumed (9726 to 9851 of 10000).
- **P2. A token search misses stale meaning.** The brief's sites came from a search for the flip's name. The implementer's review found a charter line that described the old producer as running without naming the flip. Search by meaning too: who produces, who publishes, "replaced by".
- **P3. The brief named a command that doesn't exist.** It pointed to a capped index-refresh invocation in the commands doc, but there isn't one, because the driver has no update verb (gregoryfoster/skills#483). The implementer used the session's already-running pinned server instead. The brief was corrected in place.
- **P4. Wording that will expire gets a trigger and an issue.** The docs now name the old producer's still-live publish grant as one cause of an unordered frame. That's true until the broker revokes it. The removal, and the later retirement of the unordered path, were filed as one issue with two triggers and parked on the backlog epic. They weren't left as notes on a closed epic.

### Ending

Closed 2026-10-28, after the post-flip docs child was verified live (`6efad10..02aa79f`, CI green by job, restarted, replay clean). There's no open child. The one follow-up, CannObserv/replicator#163, is parked on CannObserv/replicator#154 with its two triggers. The parent CannObserv/watcher#368 was notified at the close.
