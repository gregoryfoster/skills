---
title: patching-hosts — let a fleet executor run approved plans (#673 items 1, 3, 4)
date: 2026-11-18
status: approved
---

# patching-hosts: a fleet executor runs approved plans

## Problem

A cohort is moving its patch runs off each host's own session and onto an executor: a short-lived machine that runs this skill's own scripts on hosts. The owner approves, once per cycle and outside any host, a plan listing each host's pending updates, its restarts, its reboot and its window (#673, from CannObserv/provisioner#151).

The skill can't sanction that today:
- The Iron Law's first line accepts only approval "given in the host's own session" (`SKILL.md:21–26`). `run.md:3`, `policy.md:31` and the `--approve` help and refusals in `apply.sh`, `recovery-point.sh` and `reboot-chain.sh` repeat it.
- The knob has nowhere to say how a host is rebuilt onto a new VM (item 3).
- It has nowhere to say what a host pre-approves (item 4).

Item 2, pending updates in the inventory reporter, moved to #486.

## Approach

**1. The approval clause (item 1).** The Iron Law's first line becomes:

```
NO APPLY, RESTART OR REBOOT WITHOUT THE OWNER'S APPROVAL: IN THE HOST'S OWN SESSION, OR BY AN APPROVED PLAN THAT COVERS THE HOST
```

`, OR BY THE HOST'S OWN STANDING APPROVAL` is added when item 4 is built (see 4). Lines 2 and 3 are unchanged. An executor that runs the scripts on the host over SSH still reads on the host.

- **What the skill sees.** The approval itself, a passkey step for example, happens off the host, so the skill can't verify it and doesn't claim to.
  - The executor puts the plan on the host and passes `--plan FILE` beside `--approve`.
  - The skill hashes the file's bytes itself (SHA-256), so the record binds the exact plan.
  - Each step's JSON and the run record carry `approval: {by: "plan", plan, sha256, approved_at, approved_by}`. The last two are copied from the file and marked as stated, not verified.
  - Without `--plan`, the same object reads `{by: "session"}`. The `approved` boolean stays, so existing readers don't change.
- **The plan file** is a line file in the knob's own grammar (directives, `#` comments, `[host <name>]` sections with exact names), defined in a new `references/executor.md` in the skill's own terms. It isn't JSON: the scripts carry no JSON reader and add no `jq` or `python3` dependency on a host (revised at build, 2026-11-19). It holds:
  - `version`, `id`, `approved_at`, `approved_by` and `not_after`;
  - per host: `host`, the knob's commit, the lane, the packages (name, version, class, origin), the held steps, the data-store units those steps restart, `reboot` (true or false), and the window.

  The skill reads only its own host's entry, found by `--host` or `hostname` as the knob does. It refuses a plan that doesn't name the host, or the step being run, or whose `not_after` has passed.
- **Who checks the envelope: the skill.** The rules are in the skill's own terms (lanes, classes, held steps, the reboot prediction). An executor that re-implemented them would drift from the gate it's meant to agree with.
  - The check is part of `apply.sh`'s gate, reported as `gate.plan` with `inside` and `differences[]`, using the selection, held-step and `predict_reboot` code the gate already runs, #655's already-due reboot included.
  - `apply.sh` without `--approve` already runs the whole gate and lists every refusal, so **`apply.sh --step bulk --plan FILE --dry-run DIR` is the executor's read-only check**, run after a fresh `probe.sh --refresh-into DIR --dry-run-into DIR` and before the recovery point. With `--approve`, any difference outside the envelope is a refusal: the host stops.
  - The envelope, from #673:
    - **Inside:** a planned package at a newer version; a new package in the security lane. A planned package no longer pending is noted, not refused.
    - **Outside:** a held step or data-store restart the plan doesn't list; a reboot when the plan says `false`, where an unknown prediction counts as outside; a package from `-updates` or a followed origin that the plan doesn't list; an origin the plan doesn't name.
    - A new security package that brings a kernel, and so a reboot, is outside by the reboot rule.
  - `recovery-point.sh --plan` checks only that the plan covers the host and hasn't expired. `reboot-chain.sh --plan` also refuses when the plan's `reboot` is `false`.
- **What `--approve` means** when an executor passes it: with `--plan`, "this plan, approved off the host, covers this step", and the gate holds the step to the plan. Alone, it is session approval, as today. The skill can't tell an executor's bare `--approve` from a session's, so `executor.md` says an executor always passes `--plan`, and the record shows which kind of approval it was.
- **Out of the plan's reach:**
  - `prune.sh` stays session-only (a removal is one-way);
  - the needrestart drop-in stays a repo change (approval 1);
  - nothing said in a chat channel counts, as before. A plan file is not a chat message.

**2. The rebuild section (item 3): `rebuild-*` directives, not a new header.** `[host <glob>]` sections already scope directives per host, so the rebuild lines get precedence, line numbers and malformed-line handling for free. A `[rebuild]` header would add a second scoping axis on top.

| Directive | Kind |
|---|---|
| `rebuild-image <family>` | one value |
| `rebuild-install <command>`, run from the repo's checkout on the new VM | one value |
| `rebuild-restore <command>` | one value |
| `rebuild-check <command>`, a go/no-go check that must exit 0 | list |
| `rebuild-secret <absolute path>` | list |
| `rebuild-step <host> <name> <command>` and `rebuild-undo <host> <name> <command>` | keyed by host and name |

The step and undo lines are what this repo runs when `<host>` moves. They are declared in the dependent's own knob, so the owner of what runs also declares it.

- **What the reader prints:** `read-knob.sh` prints `rebuild: {image, install, restore, check[], secret[], step[{host, name, run, undo, line}]}`, or `null` when the knob has no rebuild line.
- **The reader runs nothing and opens nothing,** as now.
- **Secrets are paths only:** the reader never opens or stats one, and no script prints a secret's contents.
- **New finding kinds,** raised only by a knob with a rebuild line, so every knob at `817963f6` reads as it did:
  - `rebuild:secret-path` (not absolute);
  - `rebuild:no-undo:<host>:<name>`;
  - `rebuild:incomplete` (any rebuild line, but no image, install, restore or check).
- **Grammar** goes in `knob.md`, one table row. Its meaning goes in `executor.md`.

**3. Standing approval (item 4): specify now, build later. The operator decides.**

```
standing <lane> [no-reboot] [no-datastore] [no-held] <review-by YYYY-MM-DD> <reason>
```

- One line per lane. A line past its `review-by` date is an `expired-standing` finding and is not honoured, as an exception isn't.
- `--approve --standing` holds the step to the lane's line:
  - **`no-reboot`** refuses unless the prediction, already-due reboot included, reads "no reboot". `reboot-chain.sh --standing` refuses outright.
  - **`no-datastore`** refuses a held step that restarts a declared data store, and a selection that reaches one.
  - **`no-held`** refuses every held step.
  - Anything outside the scope is a refusal, so the host stops.

**Recommendation: specify only, in this plan, and build it with #627's design.** #627's option 1, the limited unattended lane, needs the same grammar and adds a second caller, a timer. Two designs would mean two grammars. The provisioner's first version also uses per-cycle plans only, so nothing consumes item 4 yet.

**4. #627.** For hosts in the executor's scope:
- **Answered:**
  - ask 1's "a run happens without the operator at the keyboard", by per-cycle plan approval, not by an unattended lane;
  - ask 3's "what stays interactive": whatever is outside the envelope stops the host, and goes to a session;
  - ask 2's prompt, since the approval request is the prompt.
- **Not answered:**
  - ask 4, the Dependabot batch;
  - class 6, language dependencies (the envelope is apt's lanes);
  - any host outside the executor's scope, which keeps #627's problem whole;
  - a flexible window, since the executor runs in the knob's fixed windows.

The coordinator decides #627's disposition at verification.

## Tradeoffs / alternatives

- **Leave the envelope to the executor, and only document it in the skill.** Rejected: the rules are the gate's own readings, and two implementations drift. This repo can test the skill's.
- **A standalone `check-plan.sh`.** Rejected: it would duplicate `apply.sh`'s selection, held-step and reboot code, or move them out of a 2,287-line script for one caller. The gate already reports without `--approve`.
- **`--plan` implies approval, with no `--approve`.** Rejected: `--approve` stays the act and `--plan` its evidence, so every caller and record reads the same way.
- **A `[rebuild]` section header.** Rejected, as above.
- **Rebuild steps for dependents declared in the rebuilt host's knob.** Rejected: its owner would be declaring commands that run on someone else's host.

## Steps

Chain B, after #655, unless noted:

1. **Red tests first:**
   - a plan covering the host passes the gate with `approval.by = plan` and the file's SHA-256;
   - each outside kind refuses, and each inside kind passes, as a table of fixtures over the gate's existing fakes;
   - an expired plan, a plan for another host, and a step that isn't planned each refuse;
   - `reboot-chain.sh --plan` refuses when the plan's `reboot` is `false`.
2. **The code:** `--plan FILE` in `apply.sh`, `recovery-point.sh` and `reboot-chain.sh`; `gate.plan`; the `approval` object. Their `--approve` help and refusals name both forms.
3. **The docs:**
   - the Iron Law's line 1;
   - `run.md`'s opening and its Approvals, one sentence pointing to `executor.md` (`run.md` is 9,309 of 10,000 after #655);
   - `policy.md:31`;
   - a new `references/executor.md` (the plan file, the envelope, what is recorded), linked from `SKILL.md`;
   - a rationalization row: "the plan was approved, so a host that moved since is covered".
4. **(Chain A, after #656.)** The `rebuild-*` directives: red tests in the knob suite, then `_knob-lib.sh`, `read-knob.sh`'s output and help, and `knob.md`'s row.
5. **(Chain A, only if the operator says build.)** `standing` lines, `--standing` in the three scripts, and the third Iron Law clause.
6. **Verify:**
   - every knob fixture that reads clean at `817963f6` reads the same;
   - exact tokens for each edited doc;
   - Linux patching-hosts tests;
   - `read-knob.sh` against cohort knobs (read-only).

## Decisions at review (operator, 2026-11-19, #673)

- **Item 4 is built in this set,** not only specified. So the Iron Law's first line takes all three clauses at once, and step 5 runs.
- **The Iron Law stays a required fragment, and a test pins its text,** so any later change to it is a deliberate edit that the test names.
- **`rebuild-step` and `rebuild-undo` are keyed by host,** the rebuilt host's name.
- **A plan's `not_after` is the executor's statement,** taken as given.

The envelope in `apply.sh`'s gate and the `rebuild-*` directives stand as written.

## Open questions / risks

- **Item 4:** build in this set, or specify here and build with #627? My lean: specify.
- **The Iron Law is a required fragment.** An override that copies it fails `test_override_required_fragments` until it is re-synced. Each cohort repo's bump notes say so.
- **`rebuild-step`'s key** (host and name): is a dependent's step better keyed by the rebuilt host's repo than by its host name? Host names are what the knob already matches on, so I chose the host.
- **The plan's `not_after`** is the executor's statement. The skill trusts it as given, and the knob's windows still gate every step.
- **Risk:** an executor that omits `--plan` is recorded as session approval. The skill can't prevent that. It is documented, and the executor's own record must carry the plan.
