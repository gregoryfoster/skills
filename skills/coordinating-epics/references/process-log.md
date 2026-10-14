# Process Log — coordinating-epics

What each run of the [`coordinating-epics`](../SKILL.md) skill taught it, one entry per run. A run is one coordinator thread over one epic, from creation or adoption to close-out or parking. An entry records:
- the way in ([creation.md](creation.md)) and the run's shape: children planned, children slotted mid-run, check-ins, days;
- what was different about this run;
- the findings that changed the protocol, and the ones that reversed an earlier rule;
- what the scripts caught or missed.

Runs are appended in date order. A pattern that recurs in two runs, or that prevented damage once, is promoted into the skill: [`SKILL.md`](../SKILL.md) or the reference that owns the step. It is then listed under "Rules promoted into the skill" with the runs it came from.

**This file is the root of the index.** Each run is its own entry file under `process-log/<year>/`, named `<date>-<repo>.md`. Each year's rows live in that year's own index, `process-log/<year>/index.md`. Journaling a run means two things: write the entry file, and add one row to that year's index. See "Adding an entry" at the foot of this file.

## Years

- **2026** — [run index](process-log/2026/index.md)

---

## Rules promoted into the skill

Which runs each rule came from, wherever it now lives. The 2026 seed entries are the eleven runs whose findings were posted on [#348](https://github.com/gregoryfoster/skills/issues/348) before the skill existed. Each was a coordinator thread working by hand, and their rules were written into the skill as it was built. Private runs are named by their shape: `private-launch`, `private-cli`, `private-backlog`.

- **The coordinator writes no code, and asks "here, or in a separate thread?" on any request to implement** (SKILL.md Iron Law). From 2026-10-09 archiver (finding 60), with the release-cutting variant from 2026-10-02 cannobserv (31).
- **Every epic body edit goes through one guarded editor:** live fetch, baseline diff, anchors by ref, derived counts, lint, read-back (`epic-edit.sh`). From 2026-10-09 archiver (2, 11, 12), 2026-10-02 private-launch (34), 2026-10-02 address-validator (47, 48), 2026-10-13 private-backlog (92, 102, 108, 113), 2026-10-11 watcher (F43, F61), 2026-10-14 broker (99, 100, 145, 147) and 2026-10-12 processor (F101, F129, F134).
- **A box ticked elsewhere is a claim to verify, not an error** (`epic-edit.sh --accept-ticks`). From 2026-10-13 status (56, 60) and 2026-10-14 broker (126, 141, 147).
- **Re-scan by three cursors: number watermark, `updated_at` since, and the commit range** (`scan.sh`, [check-in.md](check-in.md)). From 2026-10-09 archiver (10, 17), 2026-10-13 status (18), 2026-10-13 private-backlog (140, 152), 2026-10-11 watcher (F13, F39) and 2026-10-14 broker (93, 95, 128).
- **Closed is not live: verify on the live system, by deliverable type, with the recipe the epic records at creation** ([check-in.md](check-in.md)). From 2026-10-09 archiver (8, 49), 2026-10-02 address-validator (43), 2026-10-13 status (34, 46), 2026-10-14 broker (131) and 2026-10-11 watcher (F20, F58).
- **Verify the whole range since the hand-off, and CI by job on the final SHA and the tip of `main`** ([check-in.md](check-in.md)). From 2026-10-13 status (15), 2026-10-13 private-backlog (97, 99, 100, 126, 143), 2026-10-14 broker (95, 102, 128) and 2026-10-12 processor (F96, F122).
- **Write back as comments; relocate `For #N:` notes to the issue they name; harvest contract diffs** ([check-in.md](check-in.md)). From 2026-10-09 archiver (14, 15, 19, 32), 2026-10-02 private-cli (48) and 2026-10-13 private-backlog (103, 110).
- **Each cross-repo blocker has an observable unblock condition, an owner and the stages it gates** ([creation.md](creation.md), [siblings.md](siblings.md)). From 2026-10-09 archiver (7, 22, 28, 43), 2026-10-02 cannobserv (26, 27), 2026-10-02 private-cli (53) and 2026-10-12 processor (F81, F133).
- **Measure before you slot, ask or brief** ([creation.md](creation.md), [hand-off.md](hand-off.md)). From 2026-10-02 private-launch (25), 2026-10-02 power-map (55), 2026-10-02 address-validator (40), 2026-10-13 private-backlog (138, 147) and 2026-10-12 processor (F78).
- **A disposition per issue at creation: keep, rework, close, park, move or split, with a reopen trigger on every close and park** ([creation.md](creation.md)). From 2026-10-02 power-map (54, 59), 2026-10-02 private-cli (41, 42), 2026-10-13 private-backlog (84, 94), 2026-10-11 watcher (F7, F8) and 2026-10-12 processor (F67).
- **State a decision once, and write it on the line with its date** ([SKILL.md](../SKILL.md), [creation.md](creation.md)). From 2026-10-13 status (9, 52), 2026-10-02 private-launch (24, 27), 2026-10-02 power-map (56), 2026-10-13 private-backlog (94) and 2026-10-11 watcher (F18).
- **The brief goes on the issue; the kickoff prompt points to it and carries the implementer contract** ([hand-off.md](hand-off.md)). From 2026-10-02 private-launch (29), 2026-10-02 cannobserv (24), 2026-10-09 archiver (synthesis), 2026-10-12 processor (F29, F92) and watcher#368 set-up (368-F1, 368-F2).
- **Label each claim `[measured]`, `[traced]` or `[stated]`, and frame hazards as things to weigh** ([hand-off.md](hand-off.md)). From 2026-10-13 status (11, 35), 2026-10-12 processor (F70, F88, F110), 2026-10-11 watcher (F41) and 2026-10-14 broker (127).
- **One structured operator question per check-in, with a recommendation and the measured facts** ([SKILL.md](../SKILL.md)). From 2026-10-02 private-launch (27, 28), 2026-10-12 processor (F78, F125), 2026-10-13 private-backlog (103) and 2026-10-14 broker (121).
- **A verification-debt ledger with what, why skipped, how to discharge, and discharged-by** ([check-in.md](check-in.md), [assets/epic-template.md](../assets/epic-template.md)). From 2026-10-09 archiver (18, 33, 37, 56), 2026-10-11 watcher (F1, F16, F38) and 2026-10-14 broker (140).
- **For a chain of review-born follow-ups, ask for the whole class, then a guard test** ([hand-off.md](hand-off.md)). From 2026-10-13 status (83, 86, 88, 90) and 2026-10-11 watcher (F51, F56).
- **The epic ends on an empty re-scan, with its open lines resolved, its watching section settled and its role restated** ([close-out.md](close-out.md)). From 2026-10-09 archiver (58, 60), 2026-10-13 status (48, 98), 2026-10-11 watcher (F58, F63) and 2026-10-12 processor (F130, F135, F137).
- **Log every check-in, including one that found nothing** ([check-in.md](check-in.md)). From 2026-10-02 address-validator (49) and 2026-10-13 private-backlog (125).
- **A private host's findings name mechanisms, not identifiers, wherever they land in public** ([siblings.md](siblings.md), "Adding an entry" below). From 2026-10-02 private-launch (37) and 2026-10-02 power-map (60).

---
## Adding an entry

**First: is this skill vendored here?** Where the host repo consumes it as a git submodule, the entry does **not** go in the vendored copy. Draft it in the host repo, and file it upstream as an issue against this repo, with the owner's approval, as for any issue in another repo; this repo adds the entry. Writing it in place leaves the host reporting a modified submodule. This is the same rule as `orchestrating-issue-backlog`'s log.

**Second: is the host's repo private?** This log is public. Where it is, the entry names no identifier of the host's own:
- not its repo, issues, files, routes, units or data;
- nothing that would let a reader find it.

Call it "private-<shape>" (`private-launch`, `private-backlog`) and describe the mechanism instead. Check before drafting: a landed entry stays in git history.

1. Write `process-log/<year>/<date>-<repo>.md`, opening with a `## Session <date> — <repo>#<epic>` heading. Date it by when the run closed or parked, in UTC. A run still open when its entry is written is dated by its last check-in, and says so.
2. Add one row to `process-log/<year>/index.md`. Link the date cell to the entry as a bare filename, since the index sits beside its entries. For a new year, create its index from the previous year's, and add it to the Years list above.

**Keep the row to a headline of about 400 bytes,** and put the detail in the entry. A year's index is bound by the 10,000-token per-doc budget, and every run that year appends to it.
