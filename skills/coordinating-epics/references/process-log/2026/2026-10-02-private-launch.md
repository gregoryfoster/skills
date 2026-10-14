## Session 2026-10-02 — private-launch

A burn-down in a private repo, gated on a site re-launch. The coordinator ran from 2026-09-27 to 2026-10-02 over follow-up issues that an earlier orchestration wave had left behind. It had no design doc and no epic to start from, and the launch gate set most of the order. Its findings are one comment on gregoryfoster/skills#348, posted 2026-10-02. The host is private and this log is public, so this entry names mechanisms only: no repo, issue numbers, files, routes or data. Findings as of 2026-10-02; later check-ins weren't reported on #348.

### Shape

- **Way in:** a backlog plus the operator's rule, with a gate on top. Pre-launch before post-launch, then bugs, then data integrity, then the rest, smaller first within each tier.
- **Size:** 35 issues at creation, and 9 more arrived during the run. The gate tier grew from 3 items to 8.
- **Check-ins so far:** 17, closing 16 items.
- **Parent:** the tracker fed one line on a parent launch epic.

### What was different

- An external gate dominated the order. Ranking needed a tier above the operator's type-and-size rule, and a deferral label let the post-launch set be filtered out of view.
- The coordinator asked its boundary questions once and wrote the answers into the tracker as rules, so later classification needed no new question.
- An implementing thread ran a check-in on its own: it ticked its item, slotted its own follow-up and moved the host memory pointer.
- A parent epic needed syncing whenever the gate tier changed, not only at close-out.

### Findings that changed the protocol

Numbers are the comment's own (23–37). Another run's comment on #348, posted the same day, also uses 23–34, so cite these as the private-launch run's.

**Creating the tracker**

- 23: support a gate tier above the operator's ordering, plus a label that filters the deferred set out of view.
- 24: ask the boundary questions once and record the answers in a "Boundary decisions" section. When a new class appears mid-run, ask once more and append a rule.
- 25: measure a latent hazard before slotting it. Read-only counts against a dev clone of production settled each tier call in seconds, and the evidence went on the tracker line for the operator to check.

**Ordering mid-run**

- 26: new issues can go ahead of everything still queued. Within a tier, dependency outranks size. The tracker's order is a living sort.
- 27: offer a split once, as a structured question with options, and write the operator's decision onto the line with its date so no later check-in reopens it.

**At hand-off**

- 28: settle an issue's open design question before naming it. The coordinator read the code to find who writes the affected field, offered three options with that evidence, and posted the decision on the issue, where the implementer found it.
- 29: post the brief on the issue by default, with the kickoff prompt inside it, after re-checking its line references against `main`. The re-check corrected one reference.

**Verifying**

- 30: grep each merged PR body for `follow-up | out of scope | not filed | deferred | held`. One hit was a write path the PR had scoped out and nobody had filed.
- 31: "done with a residual" is a state. Tick the item, add a *"Still open: …"* note on its line, and carry the same note to the parent epic.
- 32: find out what "release" means in the host. Here it meant a manual staging deploy, since production deploys on a tag push. Verify against the deploy mechanism, not the word.

**State and writers**

- 33: every check-in starts with a step 0 that re-reads the tracker and detects work another thread already did.
- 34: anchors must not depend on checkbox state, and the write must chain on the transform's success. A failed assert was followed by a newline-chained `gh issue edit`, which re-uploaded the unchanged body.
- 35: list queries lag bulk label edits. A label-filtered list returned 28 of 32 just-labelled issues, so verify each one with a per-issue `view`.
- 36: keep exactly one line on the parent epic for the gate tier, and edit it in the same pass whenever the tier grows, ticks or picks up a residual.
- 37: when the host is private and the skills repo is public, the process-log step names mechanisms only and grep-audits the text before posting.

### Reversals

- 27: the coordinator recommended splitting an L-sized item into four child issues. The operator chose one issue and one PR, and the tracker line records that decision with its date.

### What v1's scripts would and wouldn't have caught

- **Would:** finding 34. `epic-edit.sh` finds an item by its ref, never by the line's old text, so an earlier tick can't break the anchor. It writes only after every check passes, so a failed transform uploads nothing.
- **Would:** finding 33. `epic-edit.sh` diffs the live body against the last body it wrote. A foreign `[ ]`→`[x]` flip is refused until the caller verifies it with `--accept-ticks`, and a slotted line from another thread is refused until merged and adopted with `--adopt-live`. `scan.sh`'s number watermark lists the run's arrivals whether or not they mention the tracker.
- **Wouldn't:** findings 35 and 36. Neither script touches labels, and `epic-edit.sh` edits one epic per call, so the parent's gate-tier line is a second call that nothing pairs with the first.
- **Wouldn't:** findings 30, 32 and 37. Nothing greps PR bodies or checks a deploy. The lint screens new lines for secrets and placeholders, not for private identifiers.
