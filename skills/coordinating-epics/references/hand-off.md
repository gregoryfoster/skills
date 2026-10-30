# The hand-off

What the coordinator gives the implementer: a brief posted on the issue, and a short kickoff prompt that points to it. A citation such as "processor F88" names a run's entry in [process-log.md](process-log.md), then that run's finding number.

## Where it goes

- **The brief goes on the issue as a comment.** The implementing thread finds it there, not in the coordinator's conversation. The chat reply only points to it (private-launch 29, processor F29).
- **An issue the coordinator files itself carries the decision and the brief in its body.** The hand-off is then the issue itself (watcher F49, cannobserv 24).
- **Brief only the child that is next now.** If a reorder makes a posted brief's first line false, edit the brief (processor F116, F124).
- **If another coordinator already briefed this issue,** point to that brief and add only what's new (broker 139).

## Pre-flight, before writing

Run these against `origin/main` without switching branches: `git fetch`, then `git show origin/main:<path>` and `git grep <pattern> origin/main` (private-cli 44). Then:
- **What does the child plan to rename or remove, and what references it today?** That covers anchors, ids, components, units, and log filter keys. One pass found two hazards nothing in the issue warned of (archiver 30).
- **Re-measure the evidence the issue was filed on,** and grep for renames since (broker 122). Strike consequences that no longer hold against today's schema, data and operation (private-backlog 124, 145).
- **Check the live system the issue touches, not only `main`** (status 41, 47, 53, 76):
  - frozen contracts;
  - other repos' release state;
  - credentials or peers that exist only elsewhere.
- **Probe the behaviour the design depends on.** A one-line check in the venv decided one design (cannobserv 25).
- **Search the cohort for an existing implementation** of the same mechanism, and brief "port this" when one exists. Name the precondition that made it safe there, and whether it holds here (private-backlog 105, 146; processor F121).
- **Search upstream for a known issue** before designing a workaround (broker 115).
- **Measure usage, and test the suspected cause against the incident data.** Either can re-tier, split or redirect the child (private-backlog 138, 141).
- **Probe an operator step live before handing it over.** It may already be done (broker 97).
- **Check that recommended tags and refs resolve** (broker 148).
- **Settle an open design question before naming the child.** Read the code for the facts, offer options with that evidence, and post the decision on the issue (private-launch 28, private-backlog 136).

## What the brief holds

Shape it from cannobserv 24 and the runs since:
- **Authorities:** which comment is the spec, and "where it and this issue disagree, stop and ask".
- **What changed since filed,** from the harvest.
- **Blockers now clear,** and which docs PR to merge first, if a child depends on one (archiver 13, 16).
- **Hazards, as things to weigh, not rules,** so the thread can overrule the brief when the code says otherwise. When it does, record the coordinator's error on the epic line (status 11, broker 127).
- **Claims labelled by evidence:** `[measured]` read from the live system; `[traced]` followed through the code; `[stated]`, the issue or a person says so. The implementer upgrades a `[traced]` claim before relying on it (processor F88, F113). Give a bug's mechanism from the code, not the issue's title, with its label (processor F110).
- **Diagnoses framed as "confirmed so far",** with a request to look for other symptoms of the same mechanism (private-backlog 144).
- **Open operator decisions, in brackets with a recommendation:** `[Operator decision: … — recommend Y]`. Starting the thread counts as approving the recommendation. The implementer never settles a decision by default (status 55, 69, 70).
- **Expected side effects marked as expected,** such as a known-red window between merge and a host step, so no one chases them (archiver 51; status 80, 82).
- **Moving targets** given as "the live value at ship time; X when this was written" (private-backlog 154).
- **The deploy policy,** whenever a peer is in a soak (processor F104).
- **Templates:** the last shipped child that looks like this one.
- **Out of scope.**

## The kickoff prompt

Two to six lines, pasted into a fresh thread:

```text
Pick up OWNER/REPO#45. The brief is the latest coordinator comment on it; read it first.
Work in a worktree off origin/main; never change the deploy checkout's branch.
Review the brief against the code and post corrections before you build.
Put notes for later issues under "For #N:"; list skipped verification and accepted limits. Write the post-merge host steps on the issue.
Run the code review and fix its findings, or record each declined one with its reason, before you report.
The report names the final SHA. Pause before shipping.
```

**A prompt instruction the implementer skips gets noted, and the wording adjusted. It isn't enforced** (status 42). **A review "stet" that recurs across close-outs** points to a gap in the prompt. Offer the operator a one-line addition; don't add it on your own (watcher F31, F34).

**For a recurring kind of request,** hand off only the difference from the last one (status 57, 81).

## Special briefs

- **A bug class:** ask for the whole class to be listed, not only the instance (status 83, 86).
- **A chain of review-born follow-ups** (#31 → #33 → #34 → #35): ask for a structural guard test that fails CI for the whole kind of mistake. In two runs this ended the chain (status 88, 90; watcher F51, F56).
- **A flake:** ask for a forced, deterministic reproduction, not more loops (status 96).
- **A child that writes production data:** name the write gate, and how narrow the write must be. Send one field, not a read-modify-write of the whole record. Check each derived value against its back-link. Stop for the operator before writing (private-cli 45).
- **"This command breaks prod":** put the safe reproduction and the restore command at the top (private-backlog 135).
- **Destructive or irreversible steps:** name each one as "needs your approval in the thread", so the stop is expected (broker 138).
- **A doc correction:** list every doc found by searching the claim's terms, not its figure (broker 154).
- **An item that changes how code reaches production:** flag the deploy recipe steps it affects. Take the new recipe from the merged docs, and treat its first use as its test (processor F95, F97).
- **A decision that replaces a reference implementation:** require an equivalence check while both still exist (processor F126, F132).
- **Hardening or security:** include a measured host survey. The issue's threat model is a hypothesis to check (processor F93).
- **A follow-up filed narrowly:** widen its scope with a one-minute grep, and name its traps (status 87).
- **A scope item that says "check the sibling surfaces for the same shape":** warn that the epic will grow at the next check-in (power-map 61).
- **An item with operator prerequisites:** the brief says "draft the cross-repo asks and stop" (private-backlog 116).
- **Bundled issues:** one brief on the primary, a pointer on each of the others, the decision on every epic line, and the interactions between them listed (private-backlog 131, 142).
- **An optional owner choice that changes the size:** fence it off, say how big it is, and offer it its own issue (broker 156).
