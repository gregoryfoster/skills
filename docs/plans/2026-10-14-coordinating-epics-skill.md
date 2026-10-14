---
title: coordinating-epics — a serial, operator-paced epic coordinator distilled from eight burn-downs
date: 2026-10-14
status: approved 2026-10-14
---

# coordinating-epics skill (#348)

## Problem

Since 2026-09-27, eight coordinator threads have burned down epics one child
at a time:
- archiver#300, status#16, processor#24, broker#80, watcher#348,
  address-validator#272 and power-map#598;
- three private runs.

In each, the operator implements every child in a separate thread. They have
posted about 400 findings on #348, with no skill behind them. So each run
re-derives the protocol, and each hand-builds its own epic editor. The
editor's failures came back in run after run, even after each was "fixed":
- an empty body file blanked the epic (archiver 2);
- failed asserts still re-posted the body (archiver 12, third 34,
  processor F101);
- a stale output file nearly reverted the epic by a day (watcher F43);
- anchors went stale and hand-typed counts were wrong (broker 99,
  seventh 92).

The thread itself has become a liability: 290 KB, finding numbers that
collide, and four runs still adding to it. The 2026-10-14 review comment
(issuecomment-6176467469) answers the proposal's open questions. This plan
builds on that comment.

## Approach

A new generic skill, `skills/coordinating-epics/`, with these decisions:

- **Role.** One coordinator thread holds one epic. Each check-in runs:
  1. verify the child from evidence;
  2. harvest what it changed;
  3. re-scan for new issues;
  4. re-check blockers and gates;
  5. choose the next child;
  6. hand off.

  Close-out and parking-lot mode end the run.
- **Boundaries (hard).** The coordinator writes no code and cuts no
  releases. Its allowed writes are:
  - the tracker: the epic, comments, issues it files, closures;
  - docs PRs that amend the design;
  - extra-small, operator-approved, non-code operational changes, read
    before and after;
  - documented mechanical procedures, with consent.

  On "proceed" it asks "here, or in a separate thread?" and defaults to a
  separate thread (archiver F60).
- **Creating the epic** has six ways in: design doc, backlog plus a rule,
  scoping first, adoption checklist, whole-backlog audit, and a cross-repo
  parent. All six produce:
  - a disposition per issue: keep, rework, close, park, move or split;
  - the order rule, tiebreaks and boundary decisions, written once;
  - an exit criterion;
  - the verify gate, *run*;
  - a test baseline;
  - the accounting check;
  - the first cursors.
- **The epic body is the state.** `assets/epic-template.md` fixes:
  - the header line: `Last check-in · Last probe · Last issue seen · Last
    verified SHA · Next`;
  - the sections every epic has: order rule and overrides, boundary
    decisions, exit criterion, checklist by tier, log;
  - the optional sections: milestones and gates, parked (with triggers),
    proposed closures, waits, verification-debt ledger, watching, standing
    probes, measured state.

  The host's verify recipe (what proves a migration, route or timer is live)
  is recorded in the epic at creation. It is not a `.skills/` knob, so this
  skill adds no knob.
- **Writer discipline.** Implementers may tick a box. A pre-ticked box is a
  claim to verify. The coordinator sets every box explicitly by name, and
  edits the body only through `epic-edit.py`. Everything else is written as
  comments, which only append and so can't race.
- **The implementer contract**, carried in every kickoff:
  - work in a worktree;
  - review the brief against `main` before building;
  - put notes for later issues under `For #N:`;
  - list skipped verification and accepted limits;
  - write the post-merge host steps on the issue;
  - pause for the operator before shipping.

  The brief goes on the issue. The prompt in chat is 2–6 lines that point
  to it.
- **v1 scripts.**
  - `epic-edit.py`. It fetches the live body and diffs it against a baseline
    kept at `${XDG_STATE_HOME:-~/.local/state}/coordinating-epics/<owner>-<repo>-<n>/`.
    It applies named operations (`tick`, `annotate`, `log`,
    `replace-section`, `header`). It refuses to write if the body is empty,
    unchanged, or its anchors are missing. It derives checkbox counts from
    the old body and runs the accounting check (open issues minus refs in
    the body = an expected set). It lints refs (`owner/repo#N`, bare refs
    above the host's highest number), leftover placeholders and secrets.
    Then it PATCHes through `gh api`, reads the body back, and saves the
    baseline. Timestamps and URLs are injected, never typed. `--dry-run`
    prints the diff.
  - `scan.sh`, which reports three cursors as JSON:
    - issues and PRs above the watermark, type-filtered, counting the
      epic's own number;
    - `issues?since=<last check-in>` with comments on closed children;
    - `git log <last verified SHA>..origin/main`, each commit attributed.

    It also lists cross-repo refs in open and parked lines, with their
    state and last activity.
- **Layout.** SKILL.md holds the role, boundaries, loop and contract,
  within the 6,000-token ratchet. Each reference is under 10k tokens:
  - `creation.md`
  - `check-in.md`
  - `hand-off.md`
  - `close-out.md`
  - `siblings.md`
  - `process-log.md` plus `process-log/2026/`, copied from
    `orchestrating-issue-backlog`.

  The skill is self-contained. It copies the three rules it shares with
  `orchestrating-issue-backlog` rather than linking to them.
- **Promotion bar.** A finding goes into the skill if it recurred in at least
  two runs or prevented damage. Host specifics (systemd, Alembic, Redis,
  Tailscale, Mayfly) appear only as examples. Every promoted rule is listed
  under "Rules promoted into the skill" with the runs it came from.

## Tradeoffs / alternatives

- **Extend `orchestrating-issue-backlog` with a serial mode.** Rejected. Its
  rubric interview, conflict zones and batches are dead weight here, it is
  already near its budget, and its triggers would route both kinds of
  request to one skill.
- **Keep collecting findings on #348 first.** Rejected. Since about check-in 6
  of each run, findings refine existing rule classes instead of adding new
  ones, and every new run hand-builds the editor again.
- **Name it `burning-down-an-epic` or `coordinating-an-epic`.** Rejected. The
  role is coordinating (archiver synthesis), and the house style uses a
  plural object (`reviewing-code`, `patching-hosts`).
- **Make the verify recipe a `.skills/` knob.** Deferred. Each run worked it
  out at creation and recorded it in the epic (address-validator 43,
  broker 83), which survives compaction without a knob. Add a knob only
  if repos start repeating the same recipe across epics.
- **Ship all five scripts in v1.** Rejected. `verify-ci.sh`, the pre-post
  gate and `create-from-plan.py` wait for v1.1. The editor and the scan
  are where the damage and the cost were.

## Steps

1. **Scaffold.** Create `skills/coordinating-epics/`:
   - SKILL.md with frontmatter. The description names the cues ("I finished
     #N", "next", "check-in", "coordinate the epic") and says "serial,
     operator-paced, the operator implements". The triggers are in
     metadata.
   - The README table row.
   - `skills-ref validate` passes.
2. **`epic-edit.py`, test first.** Unit tests on fixture bodies cover
   refusal for an empty, unchanged or anchor-missing body; foreign edits
   detected against the baseline; idempotent `tick` when a box is
   pre-ticked; derived counts; accounting; and the lint cases. The
   `gh api` call is stubbed. Also `--help`, ruff, and checked temp writes.
3. **`scan.sh`.** It meets the house rules: `--help`, `set -euo
   pipefail`, `shellcheck`, a per-script resolution block in SKILL.md,
   JSON on stdout, and diagnostics on stderr. A fixture test with a
   stubbed `gh` and a throwaway git repo (with `GIT_DIR` scrubbed) proves
   each cursor.
4. **`assets/epic-template.md`** with the required and optional sections, and
   a filled example built from the archiver#300 run.
5. **References**: `creation.md`, `check-in.md`, `hand-off.md`,
   `close-out.md` and `siblings.md`. Each holds the promoted rules for its
   phase, with finding citations. Each is linked from SKILL.md and under
   10k tokens.
6. **Process log.** Copy `process-log.md` and its promotion rules. Write one
   seed entry per run, each opening `## Session <date>`. Private runs name
   no identifier. Fill in the "Rules promoted" table.
7. **Gate.** Run `bash scripts/pre-ship.sh` and get it green, including the
   budget, ruff, shellcheck and structural suites. Then the CR rounds.
8. **Wrap up on #348.** Post a comment saying v1 is in. Name #348's
   process-log home as where later findings go. File the v1.1 issues:
   `verify-ci.sh`; the pre-post gate; `create-from-plan.py` with the
   cross-repo parent mode; the `shipping-work*` closing-comment sections;
   and `TestGateScriptHardening` binding this skill's scripts.
9. **Adoption issues.** For each repo with a burn-down epic still open
   (as of 2026-10-14: broker#80, processor#24, watcher#368, and the
   private seventh run), file one adoption issue there. Each issue names
   v1's scripts, its epic template, and how to move the epic's existing
   body onto that template. Then comment on the epic with a link to the
   issue. One go-ahead from the operator per repo.

## Open questions / risks

Answered by the operator on 2026-10-14:

- **Pilot.** Deferred. The operator picks a pilot when v1 is ready.
- **Live runs mid-flight.** broker#80, processor#24, watcher#368 and the
  seventh run each get an adoption issue in their own repo (step 9). Each
  issue is cross-referenced from that repo's open burn-down epic, which
  can then switch to v1. Each one is filed only when it's reached, with
  the operator's go-ahead for that one.
- **Budget.** Partition as needed. A reference that would bust 10k tokens
  splits into more files and never gets an exemption.
- **`TestGateScriptHardening`.** Agreed. `epic-edit.py` and `scan.sh` are
  held by hand to the rule that a gate script never hides its producer's
  stderr. Widening the test to bind them is a v1.1 issue, filed in step 8.
