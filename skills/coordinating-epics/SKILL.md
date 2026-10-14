---
name: coordinating-epics
description: Coordinates an epic burned down one child at a time, where the operator implements each child in a separate agent thread and returns to report. Each check-in verifies the child from evidence (merged, CI green by job on the final SHA, live on the host), edits the epic only through a guarded editor, harvests contract changes and notes for later children, re-scans by number watermark, updated-since and commit range, re-checks blockers and gates, and hands off the next issue with a brief posted on it. Also creates the epic (from a design doc, a backlog plus a rule, or an audit) and closes or parks it. The coordinator never writes code. Serial and operator-paced; for a parallel agent team use orchestrating-issue-backlog. Use when the user says "coordinate the epic", "burn down", "check-in", "I finished #N", "next issue", or "what's next on the epic".
compatibility: Designed for Claude Code or a similar harness with a Bash tool. Needs git, an authenticated gh, and python3 3.9 or later.
metadata:
  author: gregoryfoster
  version: "0.1"
  triggers: coordinate the epic, burn down, check-in, I finished #N, next issue, what's next on the epic
---

# Coordinating Epics

One coordinator thread holds one epic. The operator implements each child in its own thread and comes back to report. The coordinator confirms the work from evidence, carries what it changed to the children it affects, finds what arrived since the last check-in, and names the next child with a brief. Built from eleven burn-downs whose findings were posted on [#348](https://github.com/gregoryfoster/skills/issues/348), 2026-09-27 to 10-14.

**Activation triggers:** "coordinate the epic", "burn down", "check-in", "I finished #N", "next issue", "what's next on the epic".

## The Iron Law

<!-- skill:required id=iron-law -->
```
NO CODE IN THE COORDINATOR THREAD
NO TICK WITHOUT EVIDENCE READ IN THIS CHECK-IN
NO EDIT TO THE EPIC'S BODY EXCEPT THROUGH epic-edit.sh
```

**What the coordinator may write:**
- the tracker: the epic, comments, issues it files, closures the operator approved;
- a docs PR that amends the design;
- an extra-small, non-code operational change the operator approves, read before and after;
- a documented mechanical procedure, with consent.

It writes no code and cuts no release. On any "proceed" or "fix it" it asks "here, or in a separate thread?", and defaults to a separate thread. Prerequisite work for a child is coordinator work: filing a cross-repo ask, operator setup, a key handover. Its results go on the child as a pre-flight comment.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "The issue is closed, so it's done" | Closed means merged, or not even that. Verify live, with the recipe the epic records. A migration means its head; a route means the served spec; a timer means its journal. |
| "The closing comment says CI is green" | Read the check-runs yourself, by job, on the final SHA and on `main`'s tip. Review rounds land after the close. |
| "Nothing mentions the epic, so nothing's new" | Implementers file follow-ups that never link it. `scan.sh` reads the number watermark, updates since, and the commit range. |
| "It's one line; I'll fix it here" | The role holds only while it holds. Ask, and default to handing off. |
| "I'll `sed` the box" | Every hand edit of the body broke something in some run. `epic-edit.sh`, and a box ticked elsewhere is a claim to verify. |
| "The issue says X" | Bodies decay as children merge. Re-check against `origin/main` and the live system, and label the claim `[stated]` until you have. |
| "The operator will want the next one" | Say how it was picked. Ask when the order rule doesn't decide it. |

## Script path resolution

The skill's `scripts/` directory ships inside the skill, not at the project root. Resolve each script once, and substitute the printed path wherever `<name.sh>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63), [#301](https://github.com/gregoryfoster/skills/issues/301)):

<!-- skill:required id=skill-scripts -->
```bash
N=coordinating-epics
for S in epic-edit.sh scan.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

## Starting

**Adopt an epic that exists.** Read it in full, with its comments. Bring its state onto [the template](assets/epic-template.md): the header block, the order rule, the checklist by tier, the log. Then take it as the baseline:

```bash
bash "<epic-edit.sh>" --repo OWNER/REPO --epic N --adopt-live --ops - <<<'[]'
```

**Create one.** There are six ways in: a design doc's Steps table, a backlog plus the operator's one-line rule, a number range, children that need scoping first, an upstream adoption checklist, and a whole-backlog audit. [creation.md](references/creation.md) has each. All of them produce the same things:
- a disposition per issue: keep, rework, close, park, move or split;
- the order rule, its tiebreaks and the boundary decisions, written once;
- an exit criterion;
- the host's verify recipe, and its gate *run* (a red gate is the first child);
- a test baseline;
- the first cursors.

Show the operator the drafted body and the proposed closures before anything is written. For a whole-backlog or number-range epic, write it with `--account` (or `--account N` for a range from #N), so no open issue goes missing.

## The check-in

On "I finished #N", "next", or a report between threads:

0. **Read the state.** Run `bash "<scan.sh>" --repo OWNER/REPO --epic N > "$SCRATCH/scan.json"` for what arrived, and `epic-edit.sh … --dry-run` for whether the body moved. A box the implementer ticked is a claim. An operator request to unblock someone outside waits on nothing: do it first.
1. **Verify from evidence** ([check-in.md](references/check-in.md) §1):
   - the whole commit range since the hand-off;
   - CI by job on the final SHA and on `main`'s tip;
   - the epic's verify recipe for each kind of deliverable;
   - wire-visible changes the host's changelog rule can't see;
   - the main checkout on `main` and clean;
   - "Done when" ticked on evidence;
   - follow-ups the PR mentions but never filed.

   When something is missing, say what, and don't tick.
2. **Harvest** (§2):
   - contract diffs later children depend on;
   - `For #N:` notes, moved to the issue they name;
   - new states, codes or messages;
   - verification debt;
   - accepted limitations;
   - corrections to any claim, searched everywhere it was made.

   Write them back as **comments**. A comment only appends, so it can't race.
3. **Re-scan and slot** (§3). Each new item is a child, closed-in-fact, a split, out of epic, a duplicate, or parked. Measure before you slot.
4. **Re-check blockers and gates** (§4). Probe each one's observable condition; don't wait to be told. Read the latest comment on each cross-repo ref, and the trigger of each parked item.
5. **Choose the next child** (§5): the order rule, then the tiebreaks written on the epic. Say when the next child is the last unblocked one. When nothing is unblocked, the hand-off is the blockers instead: each with its owner, its evidence, and the options.
6. **Hand off** ([hand-off.md](references/hand-off.md)). Post the brief on the issue, after a pre-flight against `origin/main`: what it renames or removes, and who uses that today. Reply with the next ID and a kickoff prompt of 2–6 lines that points to the brief.
7. **Write the epic in one call.** The ticks and notes, the header, and a log line, which is written even when nothing changed. With `--scan "$SCRATCH/scan.json"` (the report you read: step 0's, or a later re-scan you've acted on), `Last check-in` takes `{checked}`, the scan's own time, and `Last issue seen` takes `{last_seen}`. The next window then starts where that scan looked. Never type either value, and never pass a report you haven't read. The editor refuses one whose new issues the body doesn't mention.

## The implementer contract

Every kickoff prompt carries these, or points to the brief that does:
- Work in a worktree. Never change the branch of the checkout the repo deploys from.
- Review the brief against `origin/main` first, and post corrections before building.
- Notes for later issues go under a `For #N:` heading.
- List the verification you skipped, and why. Record accepted limitations.
- Write the post-merge host steps on the issue.
- Pause for the operator before shipping.

## Talking to the operator

- **One structured question per check-in,** with a recommendation and the measured facts behind it. Ask it one check-in before the child that needs the answer.
- **State a decision once,** and write it on the line with its date ("Decided 2026-10-14: one PR"). Don't reopen it at the next check-in.
- **Label claims** `[measured]`, `[traced]` or `[stated]`. Frame hazards as things to weigh, not rules.
- **A wrong claim, once posted, is corrected in place,** visibly. Then search for everywhere else it was made.
- **A declined recommendation is fine.** Record it and go on.

## Ending

[close-out.md](references/close-out.md) covers four endings:
- the closing checks, run only after an empty re-scan;
- the runbook for a final child the operator runs;
- an epic that runs out of children before its exit criterion;
- parking-lot mode.

If the thread goes on coordinating follow-ups, the closing summary restates the role, so a later "proceed" reads as coordination, not implementation.

## Sibling repos

[siblings.md](references/siblings.md) covers:
- cross-repo waits and their unblock conditions;
- external replies, each posted only with the operator's consent;
- checking a sibling's claim before relaying it;
- sibling epics;
- a private host writing to a public repo.

## Detail Docs

- [creation.md](references/creation.md): the six ways in, dispositions, ordering, the verify recipe and baseline, creation mechanics
- [check-in.md](references/check-in.md): verify, harvest, re-scan, blockers and gates, choosing the next child, writing the epic
- [hand-off.md](references/hand-off.md): the brief, the kickoff prompt, pre-flight, special briefs
- [close-out.md](references/close-out.md): closing checks, the final-child runbook, an exhausted epic, parking-lot mode
- [siblings.md](references/siblings.md): cross-repo blockers, waits, replies and sibling epics
- [assets/epic-template.md](assets/epic-template.md): the epic body, which is the run's whole state

## Process Logs

[references/process-log.md](references/process-log.md) holds one entry per run, the rules promoted into the skill with the runs they came from, and how to add an entry. Journal every run at close-out, or when it parks. A finding goes into the skill when it recurs in two runs, or when it prevented damage once.

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by `tests/structural/test_skill_self_budget.py`; both readings must clear it. Each `references/` doc is held to the 10,000-token per-doc budget.
