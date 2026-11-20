# A fleet executor: a plan approved off the host, and a standing approval

A cohort can move its patch runs off each host's own session and onto an executor: a short-lived machine that runs this skill's own scripts on hosts. The owner approves, once a cycle and off any host, a plan listing each host's pending updates, its held steps and its reboot. The Iron Law's first line accepts that plan in place of the host's own session, and so does the host's own standing approval, a line in its knob (#673). This page is what the skill does with each.

Diagnosis stays where it is. A host the plan doesn't cover, or whose reading falls outside the plan's envelope, stops: it's worked on in a session, as before.

## What the skill can and can't see

**The approval itself happens off the host**, a passkey on the executor's side, for example. The skill can't verify it and doesn't claim to. What it can do:
- **read the plan file, and hash it itself** (SHA-256), so the record binds the exact plan that gated each step;
- **hold each step to the plan:** the plan must cover this host and this step, and must not have passed its `not-after`;
- **hold the bulk to the plan's envelope,** from its own fresh reading (below).

Each step's JSON records its approval:

| `approval` | When |
|---|---|
| `{"by": "plan", "plan", "sha256", "approved_at", "approved_by"}` | `--approve --plan FILE`. `approved_at` and `approved_by` are the plan's own statement, copied, never verified; `sha256` is the skill's. |
| `{"by": "standing", "lane", "review_by", "reason", "line"}` | `--approve --standing`: the knob's line, [below](#a-standing-approval) |
| `{"by": "session"}` | `--approve` alone: approval given in the host's own session |
| `null` | no `--approve` |

The skill can't tell an executor's bare `--approve` from a session's. **An executor always passes `--plan`**, and its own record carries the plan too. `approved` stays beside `approval`, as before.

## The plan file

The knob's grammar ([knob.md](knob.md)): one directive a line, `#` a comment at the start of a line or after whitespace, and `[host <name>]` sections. Each section names one host exactly: no glob. It's a line file, not JSON: the scripts read no JSON, and a host needs no `jq` or `python3` for it.

| Directive | Where | Meaning |
|---|---|---|
| `plan <id>` | once, before any section | the plan's id: letters, digits, `.`, `_`, `:` and `-` |
| `approved <YYYY-MM-DDTHH:MM:SSZ> <by...>` | once, before any section | when, and by whom, as the executor states it |
| `not-after <YYYY-MM-DDTHH:MM:SSZ>` | once, before any section | after this, every step under the plan is refused. The executor's statement, taken as given; the knob's windows still gate every step |
| `lane security\|maintenance\|origin:<origin>` | once a section, required | the bulk's lane, which its held steps run too |
| `reboot yes\|no` | once a section, required | whether the plan approves the reboot, 3(b) |
| `package <name> <version> <class>` | a section, repeated | each planned package, at its candidate, of the class `probe.sh` names: `security`, `updates`, `esm`, `ubuntu-other` or `third-party:<origin>` |
| `held <step>` | a section, repeated | each held step the plan approves, 3(a) |

```
plan cycle-2026-11-20
approved 2026-11-20T15:02:11Z owner, by passkey
not-after 2026-11-20T23:00:00Z

[host co-watcher]
lane security
reboot yes
held postgres
package libc6 2.39-0ubuntu8.7 security
package postgresql-16 16.11-0ubuntu0.24.04.1 security
```

**A line that doesn't parse makes the whole plan malformed,** and every step under it is refused, never guessed at: an unknown directive, a directive out of place, a value set twice, a section repeated, or a covered section with no `lane` or `reboot`.

## What each step checks

| Script | Refused unless |
|---|---|
| `recovery-point.sh --approve --plan FILE` | the plan covers the host, and hasn't passed its `not-after` |
| `apply.sh --approve --plan FILE --step bulk` | that, the plan's `lane` is the bulk's, and the bulk's reading is inside the envelope. Then again against the lists the bulk refreshes, before it holds anything: each package it will install, its own or one held for a step the plan approves, at the plan's version or a newer one; an unplanned one held for an approved step stops it |
| `apply.sh --approve --plan FILE --step <held step>` | that, a `held` line names the step, the run's bulk ran under this plan, and each package the step releases is one the plan lists, at its version or a newer one |
| `reboot-chain.sh --approve --plan FILE` | that, the plan says `reboot yes`, and the run's bulk ran under it |

The bulk records which approval it ran under in the run's `approval` file, the plan by its sha256, so a held step or a reboot under another plan is refused. **One gap stays:** a package the dry run didn't select and no group holds, published in the lane between the dry run and the bulk, looks like one outside the lane, so the bulk can't hold it to the plan. Count shortly before the run.

Each reports `gate.plan`: the plan's file, id, `sha256`, `not_after`, `lane` and `reboot`, whether it `covers` the step and, if not, `why`, and for the bulk, `inside` and its `differences`.

## The envelope

`apply.sh` compares the plan against the bulk's own fresh reading: the dry run's selection, each selected package's candidate and class (the summary `probe.sh --dry-run-into` writes), the held steps the selection reaches, and the reboot prediction, an already-due reboot included (#655).

| Difference | Inside? |
|---|---|
| `version-newer`: a planned package whose candidate is newer than planned | inside |
| `new-security`: an unplanned package in the security lane | inside |
| `not-pending`: a planned package the dry run no longer selects | inside, noted |
| `version-other`: a planned package at a candidate that isn't newer | outside |
| `class-changed`: a planned package whose candidate is of another class than planned. In a security lane whose origins are security alone, a planned security package that reads `updates` is inside: the simulation shows the newer `-updates` version over the `-security` one the step installs | outside |
| `new-package`: an unplanned package from `-updates`, ESM, Ubuntu's other pockets, or a followed origin | outside |
| `new-origin`: a package from an origin the plan's packages don't name | outside |
| `held-step`: a held step the selection reaches that the plan doesn't name. A data store restarts in a held step, so this is the new data-store restart | outside |
| `reboot`: the run reboots, or whether it does can't be read, and the plan says `reboot no` | outside |
| `unread`: the selection, a package's candidate or class, or the reboot couldn't be read. Unknown never passes | outside |

With `--approve`, each outside difference is a refusal: the host stops for this cycle. The step's JSON lists every difference, inside ones included, so the owner sees what the envelope let through.

**The read-only check:** after a fresh `probe.sh --refresh-into DIR --dry-run-into DIR`, `apply.sh --step bulk --plan FILE --dry-run DIR`, without `--approve`, runs the whole gate and changes nothing. Its only refusal for the plan is the missing `--approve`; `gate.plan.inside` says whether the host is in. An executor runs it before the recovery point, and drops a host that's out.

## A standing approval

`standing <lane> [no-reboot] [no-datastore] [no-held] <review-by> <reason>` ([knob.md](knob.md)) is **the owner's declaration, in the host's committed knob,** that a step of one lane needs no approval in the session and no plan, within its limits. It's adopted host by host, and reviewed like any other knob change. Its review-by date keeps it from outliving that review: once passed, it's an `expired-standing` finding and approves nothing, until it's renewed. `--standing` reads that date against the host's own clock, never `--today`, which is the caller's.

`--standing`, beside `--approve` and never with `--plan`, holds each step to it:

| Script | Refused unless |
|---|---|
| `recovery-point.sh` | any unexpired line, the security lane's first: it changes no package |
| `apply.sh --step bulk` | an unexpired line for the bulk's `--lane`, and the bulk's reading within its limits |
| `apply.sh --step <held step>` | an unexpired line for the lane its bulk ran in, read from the run's `dry-run` record (unread, it's refused), and the step within its limits |
| `reboot-chain.sh` | an unexpired line for the run's lane, without `no-reboot` |

**An origin lane the knob doesn't follow approves nothing** (`standing-origin`).

**The limits, and what stops a host.** `gate.standing` reports each difference in `gate.plan`'s shape, and with `--approve` each one is a refusal:

| Difference | When |
|---|---|
| `reboot` | `no-reboot`, and the run reboots: certain, already due (#655), or unknown |
| `held-step` | `no-held`, and the selection reaches a held group, or the step is one |
| `datastore` | `no-datastore`, and a held step may restart a declared data store. The default groups map to their engines: `postgres`, `redis`, and `docker` to a Qdrant's container. A knob's own group may restart anything, so it's refused wherever any data store is declared. A group whose engine isn't declared restarts none, and passes |
| `lane-scope` | the selection holds what the lane doesn't take: in the security lane, anything but security, unless the dry run's origins are security alone; in the maintenance lane, anything but security, `-updates` and followed origins |
| `unread` | the selection, a package's class or the reboot couldn't be read |

Without `--approve` nothing is refused for it, and `gate.standing.inside` is the read-only check, as for a plan.

## What stays out of a plan or a standing approval

- **Pruning:** `prune.sh` takes the owner's approval in the host's own session only. A removal is one-way.
- **The needrestart drop-in,** approval 1: a change to the host's repo.
- **Nothing said in a chat channel counts as approval,** and neither a plan file nor a knob line is one.
