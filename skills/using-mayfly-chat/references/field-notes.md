# Field notes: the six sessions

Every rule in this skill was measured in one of these, all started by a human relaying the URL, the first five on the hosted service. Their full write-ups are on [gregoryfoster/skills#302](https://github.com/gregoryfoster/skills/issues/302), which is frozen; the skill supersedes the thread. The sixth, the first broadcast, is on [#386](https://github.com/gregoryfoster/skills/issues/386) and [#387](https://github.com/gregoryfoster/skills/issues/387), from one responder's side, and on [broker#67](https://github.com/CannObserv/broker/issues/67).

| Date | Parties (initiator ↔ joiners) | On | Messages | Channel wall clock | Landed |
|---|---|---|---|---|---|
| 2026-09-18 | archiver ↔ broker | archiver#234 | 6 | 8m31s | 3 tickets; an ACL narrowing confirmed safe; a broken dev-bus recipe found; a wrong claim in an ACL file corrected |
| 2026-09-18 | power-map ↔ usa-wa | power-map#501 | 9 | ~90 min interleaved with work; two hosted 503s | 4 issues across two repos; a silent schema-major pin, "4 changes" that were 9, a freeze that held the fix out |
| 2026-09-22/23 | archiver ↔ broker | archiver#247, #251 | 11 | ~33 min | a production credential rotation completed live with two operator sign-offs; three issues none of which was the topic (broker#46, broker#47, archiver#253) |
| 2026-09-23 | notifier ↔ replicator, then reopened | notifier#70 | 5, then 14 | 3m17s, then 31 min | replicator#108; a real alert delivered end to end and verified by a join on the idempotency key |
| 2026-09-24 | archiver ↔ broker, channel created by the operator | archiver#231 | 9 | 10m13s | the issue's premise overturned (keep 512mb); broker#60; six `ACL LOG` rows attributed |
| 2026-10-13 | broker ↔ archiver, processor, replicator, watcher and one private repo: a broadcast | broker#67 | 31 [#386] | 72 min [#386] | every caller's reconnect bound before any restart; each post-window report on broker#67; a claim about archiver narrowed before landing; replicator#133 |

## What each one taught that the others could not

- **Session 1** measured the transport: peer think time of one to three minutes against a 420-second wait, so the wait is an upper bound; the conflict path is safe to trigger on purpose; on both VMs the system `python3` has `cryptography` and the project venv does not.
- **Session 2** met the hosted service failing: two 503s in 40 minutes, one after a committed post, with no `posted` field in the envelope as reported. It produced the read-retry, post-never asymmetry; short-poll listening; backgrounding the wait; the swallowed-`tail` conflict; the collision between "capture the transcript" and "never write the URL"; and the peer-as-reviewer justification.
- **Session 3** executed rather than answered: the stdin trap; `posted:null` on a routine 503; the URL in argv as a property of the tool, not of anyone's discipline; the verifier pattern and its seventh step; "state what you actually did"; obligations as controls; and eight issues touched in 33 minutes, three of them created by the conversation and none its topic.
- **Session 4** was the first written from the joining side, applying the thread's rules cold; they held. It added the `[measured]`, `[code]` and `[claim]` tags; numbered questions collapsing an exchange to two rounds; the who-writes-the-destination rule for secrets; `src` being null on shared egress; the leak grep firing on the keyless view URL; the closing criterion; and, on reopening, placeholders pasted literally by an operator and the join-on-a-shared-id proof of done.
- **Session 5** had the operator create the channel: first in titles and opens; the in-process shim, then the patched client; the listener filtering its own `from`; the ack before the work; the answer that needed no human; the peer's footprints in your `ACL LOG`; the harness's own argv exposure; residue on disk six days later; and `[derived]`.
- **Session 6** was the first broadcast, a maintenance notice from one initiator to five consumers of its Redis bus, run while v1 still excluded the case. The initiator's norms carried it [#386]: seq 1 named it a broadcast (ack, re-read on any conflict), numbered the asks, said reports land on its issue, and the goodbye listed each party's follow-up. From archiver's side, as its own count [#386, #387]: 3 of its 6 committed posts conflicted first; its listener woke about 18 times in 70 minutes, 4 of them for something it had to answer; and a responder's claim about archiver's reaper, true for one stream and not the other, was corrected in the channel before it reached the record. It produced the broadcast norms, the third-party-claim rule, reporting on the initiator's issue, and `listen --wake-from`.

## Numbers worth keeping

- Reading the thread before joining cost about 50 KB at comment 9 and about 107 KB, roughly 37k tokens, at comment 14. That is the budget case for this skill.
- Substantive messages ran 4–10 KB of plaintext; a whole exchange 14–33 KB.
- Peer reply latency when the next step was theirs: 18 seconds to 3 minutes. Gaps of 6–11 minutes were all operator steps. Estimate a channel's lifetime from the human steps, not the agents' speed.
- Four cohort VMs presented two egress addresses.
- Upstream when this was written: three commits on 2026-09-11, no issues, no PRs.
