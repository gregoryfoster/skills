## Session 2026-10-02 — CannObserv/cannobserv#234

The coordinator for CannObserv/cannobserv#234, the co/v1 Cohort D epic, ran from 2026-09-30 to 2026-10-02 and was compacted once. The epic existed, but its children weren't yet buildable, so most check-ins began with a scoping pass. It completed Cohort D in two releases, closed the epic, and handed off Cohort E's first child from CannObserv/cannobserv#235. Implementation happened in separate threads. Its findings are one comment on gregoryfoster/skills#348, posted 2026-10-02. Findings as of 2026-10-02; later check-ins weren't reported on #348.

### Shape

- **Way in:** scoping first. Each child was an epic line marked "not yet scoped". The coordinator turned it into a decisions comment and then an implementation issue before any hand-off.
- **Size:** Cohort D's three children, `information_set` (CannObserv/cannobserv#506), `information` (CannObserv/cannobserv#512) and a test-and-docs follow-up (CannObserv/cannobserv#511), shipped in v0.21.0 and v0.22.0. Then Cohort E's first child, CannObserv/cannobserv#519.
- **Check-ins so far:** the comment gives no count. It covers Cohort D's three children, the two releases and the hand-off into Cohort E.

### What was different

- Each child needed scoping, and sometimes an upstream ask, before anyone could build it. The hand-off grew into an implementation issue the coordinator wrote itself.
- The coordinator cut releases between children and filed adoption checklists in the consumer repo, so it committed to `main`.
- Its blockers lived in an upstream repo, where a closed issue was not yet a deployed fix.

### Findings that changed the protocol

Numbers are the comment's own (23–34). The private-launch run's comment on #348 also uses 23–37, so cite these as the cannobserv run's.

**A third way in (open question 2)**

- 23: scoping before hand-off is a way in. A status brief from evidence, the open questions put to the operator with a recommendation each, then a decisions comment on the epic that becomes the child's spec.
- 24: the hand-off is an issue body with authorities (the decisions comment wins, and a conflict means stop and ask), a template (the last shipped child), traps found while drafting, open questions for the pre-build review, tests, docs and downstream notes, out of scope, and working notes. The operator's kickoff became "pick up #N", and every implementer posted a pre-build review first.
- 25: probe the behaviour the design depends on. A one-line venv check confirmed that Pydantic's `model_copy(update=…)` marks the updated field as set. Without that, an append on a partly loaded record would send a full replace that wipes stored elements. It went into the issue as a named trap.

**Blockers**

- 26: each cross-repo blocker names its own "landed" test: a deploy, a contract pin or a release tag. One upstream issue was closed with its PR merged but wasn't on staging. The schema-pin drift check against the live OpenAPI document decided it.
- 27: for a child that waits upstream, the operator picks the interim. Record it on the line ("waits on …, no interim") so the blocker re-check knows what to look for.

**Releases and downstream**

- 28: releasing between children is a coordinator step. Cut the release, file the consumer's adoption checklist ordered by how badly each change fails, point the consumer's tracking issue at the version, and link the checklist from the CHANGELOG. Before releasing, check the unreleased notes for limitations lifted upstream since the merge.
- 29: downstream audits follow inheritance and delegation. Three consumer service classes inherited the facade's methods, and a search for direct calls missed them.

**Re-scanning (open question 3)**

- 30: before framing a decision that spans cohorts or repos, search sibling repos' recent issues by subject keywords. The consumer repo was already working on the datetime timezone fix the coordinator was about to frame, and had filed the library-side proposal (CannObserv/cannobserv#518). CannObserv/cannobserv#519 adopted its "refuse naive" rule from day one.

**What the coordinator may write (open question 6)**

- 31: the coordinator commits only between children, never while a child's branch is open, and its commits get the same review as an implementer's. Otherwise it hands even small code changes to a thread.

**Claims**

- 32: check each factual claim in a coordinator-written issue or comment against the source before posting. Correct a posted one in place, with the correction visible.
- 33: a scope move between epics is written on both epics, with the reason. Two Cohort F entities turned out to be types of a Cohort D entity on the new backend.

**Continuity**

- 34: the epic's table survived compaction. Each row held its decisions comment, implementation issue, merge commit and release version. The plan for the operator's return lived only in host memory, so the epic should carry a **Next:** line beside its "Last check-in" line.

### Reversals

- 31: the read-only stance didn't hold. The coordinator wrote CannObserv/cannobserv#511's test and docs, the release commits and the CHANGELOG. A code review of its own commits found five issues: two loose assertions in a live test and three inaccuracies in release notes.
- 32: two wrong claims were posted and then corrected in place, one with strikethrough and a "Corrected:" note, one by rewording. Drafts with wrong claims about a function's title inputs, a CLI flag name and a lookup's taxonomy were caught before posting.
- 28: an upstream fix landed between CannObserv/cannobserv#506's merge and its release. Without CannObserv/cannobserv#511 to remove the documented limitation, v0.21.0 would have shipped notes describing one that no longer existed.

### What v1's scripts would and wouldn't have caught

- **Would:** finding 34. `epic-edit.sh`'s `header` op sets a `- **Next:** …` line and its `log` op appends a dated entry, and both are read back after the write.
- **Partly:** finding 26. `scan.sh` reports each cross-repo ref in the body with its state and last activity, so a closed upstream blocker shows as closed. That is the signal finding 26 warns against. The landed test (staging deploy, schema pin) is still the coordinator's to run.
- **Would:** finding 31's visibility. `scan.sh`'s commit range lists every commit since the last verified SHA, attributed to a child, the epic or nobody, so the coordinator's own commits on `main` appear in the next scan.
- **Wouldn't:** findings 30, 32 and 33. `scan.sh` reads one repo plus the refs already in the body, so a parallel effort that never mentions the epic stays invisible. The lint checks refs, placeholders, variables, comment links and secrets, not whether a claim is true. A scope move is two `epic-edit.sh` calls on two epics, and nothing pairs them.
