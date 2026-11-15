# Epic body template

The epic's body is the run's whole state. A coordinator thread that is compacted, or resumed on another day, rebuilds its context from this body and the comments under it. Host memory may keep a pointer to the epic, and nothing else.

Copy the block below into the epic and fill it in. The **core** sections are in every epic. Add the **optional** ones only when the run needs them, and drop a section once it is empty for good. `epic-edit.sh` finds lines by their leading ref and sections by their heading, so keep each item led by its ref, and keep each heading unique.

- **Header lines** use the `- **Field:** value` form. `scan.sh` reads `Last check-in`, `Last issue seen` and `Last verified SHA` from them, and `epic-edit.sh`'s `header` op writes them, turning a paragraph-form header into this list.
- **Checklist items** lead with their ref: `- [ ] #12 …`, or `- [ ] owner/repo#3 …` for another repo's issue. An ordinal may come first (`- [ ] 12. #447 …`), and an ordered marker is a task item too (`1. [ ] #348 …`), but a ref in a code span leads nothing: GitHub doesn't link it (#403).
- **Headings hold no time.** A heading is an anchor, so stamp the bullets under it instead: `## Measured state`, not `## Measured state (2026-10-15T15:01Z)` (#413).
- **A ticked line is its title and a link** to the comment on the child that holds its evidence: `- [x] **#12** <title> · [verified](<comment URL>)`, written by the `compact` op. Once ticked, a line stays this size (#654).
- **The log lives in comments** on the epic, one per check-in, written by the `log-comment` op; `## Log` holds only a pointer. The body stops growing with history, and past the host's size cap a write silently keeps the old body (#653).
- **The coordinator's own comments carry a fixed first line,** which `scan.sh` reads, never the author: `**Check-in log, <date>**` on the epic, and `**Coordinator record, owner/repo#<epic>**` on a child, for the verification or record comment a tick links.
- **Notes on a line** are appended, dated and short, each its own field after a middle dot (`·`): `- [ ] #12 … · S · Decided 2026-10-14: one PR.` The `note` op writes the dot, so its text is the note alone: `Still open: census on the next export.` or `Deploy no earlier than 2026-10-15T18:00Z.`

````markdown
<one paragraph: what this epic delivers, and the exit criterion in one sentence>

- **Last check-in:** 2026-10-14T18:03Z
- **Last probe:** 2026-10-14T18:01Z
- **Last issue seen:** #57
- **Last verified SHA:** 1a2b3c4
- **Next:** #45, brief on the issue

## Order

<The operator's rule, verbatim, e.g. "prioritize bugs and smaller workstreams".>

Tiebreaks the coordinator added, numbered so the operator can challenge one:
1. Dependency outranks size.
2. Context freshness: the child whose code just changed goes next.

Overrides: <date: the operator moved #N ahead, and why>.

## Boundary decisions

- <A classification rule the operator settled once, e.g. "a correctness bug on a surface being kept stays open, even unused">, decided <date>.

## Exit criterion

<What "done" means here, e.g. "tier A and every item tagged pre-launch closed", which is not the same as "the backlog is empty".>

## Verify recipe

- Gate: <the host's real gate, e.g. "CI test job on the merge SHA", or "local pre-commit; this repo has no CI"> (run at creation: green).
- Deploy: <how a merge reaches production, and the proof, e.g. "service ActiveEnterTimestamp after the merge time">.
- Baseline: <command, environment step, passed/skipped counts, date>.
- By deliverable: migration → its head; route → the served OpenAPI; timer → its journal; <the host's others>.

## Tier 1 — <name>

- [ ] #45 <title> · <size> · blocked by owner/repo#3 (merge) · approval gate: prod read
- [ ] #46 <title> · can share a thread with #45

## Tier 2 — <name>

- [ ] #50 <title>

## Log

Each check-in's entry is a comment on this epic, first line **Check-in log, <date>**.
````

Optional sections, each added under its own heading after the tiers:

````markdown
## Milestones and gates

- <milestone>: announced at <where>. Switches on <rule>, and off <rule>. Re-check <parked items> when it lands.
- Gate: <a soak, a CI gate on deploy, a calendar window>, until <date>; checked each tick.

## Waits

| Ref | Who waits | On what | Asked | Unblock condition |
|---|---|---|---|---|
| owner/repo#3 | us | their SDK release | 2026-10-12, on the issue | tag v1.4 exists and the served build matches |

## Parked

| Ref | Re-entry trigger | Last re-read |
|---|---|---|
| #21 | the producer writes observations again | 2026-10-14 |

## Proposed closures (pending approval)

- #30 · done in fact by #28 · evidence: <commit or query> · the one reason to keep it: <…>

## Verification debt

| What is unverified | Why it was skipped | How to discharge it | Discharged by |
|---|---|---|---|
| browser swap on the edit form | no dev data with assignments | assign a throwaway spec on dev, then drive the form | (open) |

## Watching

- <observation> · threshold <…> · evidence <…> · since <date>

## Standing checks

- `<probe command>` → expect `<steady-state output>`. Last run <date>.
- Due 2026-10-21: <a dated deferral, and exactly what to confirm>.

## Measured state

Rewritten from scratch at each check-in, never appended to.

- <fact the dispositions rest on>, measured <date-time>.

## Overlaps

| Surface | Items |
|---|---|
| `src/api/routes.py` status mapping | #45, #46 |
````

## Filled example

Illustrative, shaped like CannObserv/archiver#300's run on the day its last unblocked child closed. The titles, version, SHA and plan path are invented. Its order came from a design doc, so its tiebreaks are the ones the run added.

````markdown
Replication of power-map entities into archiver, per docs/plans/2026-09-30-replication.md. Done when the cutover (#309) is verified in production.

- **Last check-in:** 2026-10-05T23:09Z
- **Last issue seen:** #315
- **Last verified SHA:** 8c41d0e
- **Next:** none unblocked; see Waits

## Order

The design doc's Steps table. Tiebreaks: 1. context freshness; 2. migrations one at a time; 3. safety net before capability.

## Verify recipe

- Gate: CI on the merge SHA, plus the CHANGELOG entry the PR template requires.
- Deploy: `archiver.service` ActiveEnterTimestamp after the merge; `alembic_version` for migrations, read-only.

## Phase 1

- [x] **#301** Store schema for replicated entities · [verified](https://github.com/CannObserv/archiver/issues/301#issuecomment-…)
- [x] **#311** Index the replica lookups · [verified](https://github.com/CannObserv/archiver/issues/311#issuecomment-…)
- [x] **#308** Move dialog for replicated entities · [verified](https://github.com/CannObserv/archiver/issues/308#issuecomment-…)
- [ ] #304 adapter on the SDK · blocked by CannObserv/power-map#607 (merge) and the API key (verify)

## Waits

| Ref | Who waits | On what | Unblock condition |
|---|---|---|---|
| CannObserv/power-map#607 | us | the SDK and `410` on `getOrg` | `410` declared in power-map's served /openapi.json |

## Log

Each check-in's entry is a comment on this epic, first line **Check-in log, <date>**.
````

The check-in's log comment on that day:

````markdown
**Check-in log, 2026-10-05**

#308 closed and live. No new issues. Epic blocked: #304 waits on CannObserv/power-map#607. Next: none.
````
