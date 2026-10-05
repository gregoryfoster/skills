---
name: patching-hosts
description: Patches a Linux host's OS packages safely and records the run. It compares the host's actual update state against the posture its knob declares (automatic security-only upgrades, or a scheduled monthly run), measures the pending set by class (security, -updates, third-party, Ubuntu Pro/ESM, outside apt), then runs a gated apply in held steps with a recovery point, needrestart held to list mode, a detached in-guest reboot chain, and post-boot verification. Also reports dormant components and provisioning leftovers. Use when the user says "patch the host", "OS updates", "security updates", "apply updates", "unattended-upgrades", "needrestart", or "is this host patched".
compatibility: Designed for Claude Code or a similar harness with a Bash tool, on a Debian or Ubuntu host with apt, unattended-upgrades and needrestart, reached as a user with sudo. The first environment profile is exe.dev's exeuntu image (Ubuntu 24.04); other hosts use the generic apt path.
metadata:
  author: gregoryfoster
  version: "0.1"
  triggers: patch the host, OS updates, security updates, apply updates, unattended-upgrades, needrestart, is this host patched
---

# Patching Hosts

Gets a host's OS packages patched without surprising anyone: no unapproved restart, no lost data, no guess passed off as a measurement. Built from ten exe.dev hosts patched by hand in [#313](https://github.com/gregoryfoster/skills/issues/313)'s step 0 round, 2026-09-21 to 09-29.

**Status: in development.** The procedure, its references, the knob reader, the read-only probe, the recovery point, the gated apply with both lanes, the reboot chain and pruning are here; owner notices land in a later step of [the plan](https://github.com/gregoryfoster/skills/blob/main/docs/plans/2026-09-25-patching-hosts-skill.md).

**Activation triggers:** "patch the host", "OS updates", "security updates", "apply updates", "unattended-upgrades", "needrestart", "is this host patched".

## The Iron Law

<!-- skill:required id=iron-law -->
```
NO APPLY, RESTART OR REBOOT WITHOUT THE OWNER'S APPROVAL, GIVEN IN THE HOST'S OWN SESSION
NO APPLY ON A HOST WITH A DATA STORE UNTIL ITS RECOVERY POINT HAS LEFT THE NODE
NO CLAIM ABOUT THE HOST THAT WASN'T READ ON THE HOST
```

A maintainer script's restart is still a restart. Nothing said in a chat channel counts as approval. An absent setting is `unknown`, never its default. A host with no data store still records its before-versions, the rollback path; it just has nothing to dump.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "The needrestart drop-in is in, so nothing will restart" | It governs the hook only. `postgresql-16` restarts its cluster, and `containerd` itself, from their own maintainer scripts. Hold them, and approve each step. |
| "Postgres isn't in the set, so it doesn't need a restart" | Its backends map libc6, libssl and libxml2. Read `/proc/*/maps`. |
| "`/health` is 200, so the database step is done" | A fail-open cache hides the outage, and a stale pool hides behind a green health check. Prove a real request, a new row, a cache hit. |
| "The first start after boot succeeded" | By luck, unless `critical-chain` shows its data store. Read the ordering. |
| "The journal is persistent; the config says so" | `systemd-journal-flush` can be masked. Look for files under `/var/log/journal`. |
| "0 security pending: the host is patched" | Not `universe`. Read `pro security-status`. |
| "The test passed" | Did it run? A host test can skip and still read green. Read the value directly. |

## Script path resolution

The skill's `scripts/` directory ships inside the skill, not at the project root. Resolve each script once, and substitute the printed path wherever `<name.sh>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63), [#301](https://github.com/gregoryfoster/skills/issues/301)):

<!-- skill:required id=skill-scripts -->
```bash
N=patching-hosts
for S in read-knob.sh probe.sh recovery-point.sh apply.sh reboot-chain.sh prune-plan.sh prune.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

## The run

1. **Read the host:** `bash "<probe.sh>" --refresh-into <scratch>` prints its environment, update channels, the pending set by class, impact and dormant components as JSON. It changes nothing, and its lists go to the scratch directory. `--dry-run-into <scratch>` adds the exact security count while unattended-upgrades takes `-security` alone (`security_only`), but downloads the set as root. What it leaves to you is in `not_read`: [readings.md](references/readings.md).
2. **Compare against the posture** the knob declares ([knob.md](references/knob.md), [policy.md](references/policy.md)). The probe's `findings` are every deviation no unexpired exception covers, and `excepted` holds the rest. An expired exception is a finding. `bash "<read-knob.sh>" --host <name>` prints the knob alone, and whether the host is report-only.
3. **Propose, in the record:** what goes in, which steps are held, which restarts, the window, and why. Include the callers' notice when the knob names callers.
4. **The needrestart drop-in**: installed if absent (approval 1), and proven on every run with `sudo needrestart -m u -b -r l`.
5. **The recovery point**, off the node: `bash "<recovery-point.sh>" --approve --retain-until <date>` prefers the host's own backup regime, or dumps each datastore as root and prints each dump's sha256 for the owner's off-node copy. Then **the apply** in held steps. `bash "<apply.sh>" --approve --step bulk --run <dir> --dry-run <scratch>` is approval 2, and `--step <group> --run <dir>` runs each held group under its own approval 3(a). Until every gate in [run.md](references/run.md) passes, it changes nothing and says why; a step that fails prints the abort branch and the holds it left. The monthly maintenance lane is the same run with `--lane maintenance` on the bulk and its dry run, and a bulletin's out-of-cycle window is `--lane origin:<origin>` ([policy.md](references/policy.md#two-lanes)). **Run each step in the background**, and read its JSON when it ends: a step takes minutes, and one cut off at a foreground call's limit leaves the run stuck.
6. **The reboot**, when needrestart's list or `reboot-required` calls for one: a detached in-guest chain, approval 3(b). `bash "<reboot-chain.sh>" --run <dir>` prints the chain for the owner to read; with `--approve` it writes and launches it. Then verify: `bash "<probe.sh>" --post-boot`.
7. **Record** what happened and what's left pending, by class, then journal the run in the [process log](references/process-log.md): what the profile got wrong or lacked, the decisions, and the surprises. **Where the skill is vendored, never write into the copy:** draft the entry, and file it upstream as an issue.

Steps 4–7 in full, with each trap: [run.md](references/run.md). The probe's `environment.profile` names the environment profile the host matches, and its image generation. That profile holds the environment's quirks: which packages restart themselves, `/tmp`, clean-shutdown evidence. The one so far: [environments/exe-dev-exeuntu.md](references/environments/exe-dev-exeuntu.md).

**A dormant component** is pruned apart from the run, one stage at a time: disable, then remove, then purge, each after the last one's soak, and a savepoint lets the purge skip the remove. `bash "<prune-plan.sh>" --component <name> --out <file>` reads what it would take; `bash "<prune.sh>" --stage <stage> --plan <file>` prints the stage's commands, and with `--approve` runs exactly those. The calendar, what each purge script deletes, and the traps: [pruning.md](references/pruning.md).

## Hosts no profile matches

With `environment.profile.name` null, the run is the same, but nothing a profile measured holds. Read it from the host instead:

- **The kernel is the host's.** A `linux-image-*` in the set takes effect only at a reboot, and `/run/reboot-required` and needrestart's kernel status say so. An exe.dev guest has no kernel of its own to update.
- **Which packages restart their own services is unmeasured.** Hold each data store's packages as their own step, and read needrestart's list after each step, not a profile's table.
- **The update channels are as found:** the timers, `APT::Periodic::Enable` through `apt-config`, and unattended-upgrades' origins. A stock Ubuntu host has its timers on and takes `-security`, but sets neither `APT::Periodic::Enable` nor `Automatic-Reboot`, and has no needrestart drop-in: under `automatic`, the probe reports each.
- **Clean-shutdown evidence** is PID 1's own journal lines, where `environment.pid1_log_target` is the journal. On a volatile journal, it's the copy the reboot chain took.

A second host on the same environment is the time to write its profile under `references/environments/`, with every fact's source and date, and to teach the probe its markers.

## What the skill never does on its own

It never unmasks a timer, edits apt or needrestart config beyond the approved drop-in, removes a package outside an approved prune plan, restarts through the platform (a hard reset), or files an issue in another repo without approval. Reaching a posture is provisioning's job: the base image, or an owner-approved remedy.

## Detail Docs

- [references/readings.md](references/readings.md) — what to measure before proposing, and the mistake each reading prevents
- [references/run.md](references/run.md) — approvals, the gate, the recovery point, held steps, the reboot chain, post-boot checks, the record
- [references/policy.md](references/policy.md) — the two postures, the two lanes, pending classes, exceptions, dormant components, owners
- [references/pruning.md](references/pruning.md) — pruning a dormant component: the calendar, the plan, the stages, and what a purge deletes
- [references/knob.md](references/knob.md) — the `.skills/patching-hosts` grammar
- [references/environments/exe-dev-exeuntu.md](references/environments/exe-dev-exeuntu.md) — the exe.dev exeuntu profile
- [references/process-log.md](references/process-log.md) — one entry per run, the rules promoted from them, and how to add an entry

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by `tests/structural/test_skill_self_budget.py`; both readings must clear it. Each `references/` doc is held to the 10,000-token per-doc budget.
