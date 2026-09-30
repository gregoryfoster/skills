---
title: patching-hosts — a generic OS-patching skill with a reference policy, a read-only probe and learned environment profiles
date: 2026-09-25
revised: 2026-09-29 (after the step 0 round of ten hosts)
status: draft
---

# patching-hosts skill (#313)

## Problem

Every exe.dev VM on the default image has OS patching off. exeuntu masks the
apt timers (re-checked at `ae8be4d`, 2026-09-24), and nothing on the host says
so. broker's production VM had 97 security updates pending once its lists were
refreshed on 2026-09-25, against 27 of any kind counted against the stale lists
(CannObserv/broker#65).
The opposite failure is live too: on a VM with Ubuntu's stock settings,
needrestart restarted a daemon every morning under running work. No cohort
repo documents a patch policy, and no skill can tell a host's configured state
from its actual one. #313 proposes the skill; the 2026-09-25 review comment
records the decisions this plan builds on.

Step 0 has since patched ten hosts by hand, 49 to 257 security updates each,
all green (#313 comment 5898628226). The procedure held on every host. What
varied between hosts is what the skill has to probe for or be told.

## Approach

A new generic skill, `skills/patching-hosts/`, built to #313 §2 with these
decisions folded in:

- **Two postures; the knob picks one** (revised 2026-09-29).
  - **`automatic`** is the generic reference policy: security-only automatic
    upgrades, no automatic reboot, and needrestart listing restarts rather
    than performing them. It's Ubuntu's stock unattended-upgrades posture
    plus one needrestart setting.
  - **`scheduled`** is D4's answer, and the cohort's choice. The host is
    patched in a monthly, owner-approved run, and the apt timers stay
    masked. The round showed why: `postgresql-16`, `containerd` and `polkit`
    restart their own services from their maintainer scripts, whatever
    needrestart is set to. So `automatic` on a data-store host means
    unscheduled data-store restarts.
  - The probe compares the host against the posture it declares. With no
    knob, it only reports.
- **Host-config knob, `.skills/patching-hosts`.** Holds only what the owner
  knows: host class, posture, window, runbook services, health checks, and
  where records go. It declares exceptions to the policy, each with a reason
  and a review-by date.

  One file describes every host a repo deploys to, because the cohort
  already has both shapes: production, staging and dev hosts in one repo,
  and a primary plus throwaway workers in another. Lines outside any section
  apply to all hosts, and a `[host <glob>]` section overrides them for the
  hosts it matches. The class is one of `production`, `staging`, `dev` or
  `ephemeral`. An ephemeral host is patched by rebuilding its image, so it
  gets a report and never an apply.

  What constrains a window differs on every host (a queue, a backup timer,
  ingest, callers, an in-host restarter), so the knob declares it. The
  grammar is [knob.md](../../skills/patching-hosts/references/knob.md).
- **A read-only `probe.sh`.** Reports environment, each update channel's
  configured and actual state, list age, pending updates by origin, restart
  and reboot signals, and policy deviations. Any deviation not declared as an
  exception is a finding. An absent setting is reported as `unknown`, never as
  its default.
- **Dormant components.** The probe also lists installed services that
  nothing uses: an engine with no workload, a daemon with no listener and no
  reference in the repo. Each one is patch surface, disk and attack surface
  for no benefit. The round has found two so far: a pre-cutover Postgres on
  power-map (CannObserv/power-map#576), and Docker running with no
  containers on notifier, whose inactive nginx is also in its security set.
  The skill reports the evidence and proposes pruning. It never removes
  anything itself; removal is a separate change the owner approves. A
  component the owner keeps is declared as an exception, with its reason and
  review-by date. A prune follows a staged calendar the operator can shorten
  (step 6b).
- **Provisioning leftovers.** The probe reports provisioning state that
  outlived its run. The first case is `/exe.dev/setup`, whose secret
  survives a failed `exe-setup.service`, and which the platform delivers
  again on every boot (CannObserv/notifier#93, CannObserv/replicator#122).
  The contract and the remedy order (revoke the key first; everything else
  comes back at the next boot) are in the
  [profile](../../skills/patching-hosts/references/environments/exe-dev-exeuntu.md#provisioning-leftovers-exe-setupservice).
  The probe reads each boot's `ConditionResult` and reports secret patterns
  by name and line, never the value ([readings.md](../../skills/patching-hosts/references/readings.md)). It never
  runs a remedy itself.
- **A gated `apply.sh` and a detached `reboot-chain.sh`, in the shape all
  ten runs used**: a recovery point off the node, then a bulk step with the
  data-store and Docker packages held, each held group under its own
  approval, then an in-guest reboot chain and post-boot checks. The
  procedure, with each trap it avoids, is [run.md](../../skills/patching-hosts/references/run.md).
- **Two lanes** (decided 2026-09-29, from the gap on #313 comment
  5879792979).
  - **The security lane** is everything above, `-security` only. It runs
    daily under `automatic` (the apt timers), and monthly under `scheduled`.
  - **The maintenance lane** is monthly. It uses the same run, but its
    selection is Ubuntu `-updates` plus each host's approved third-party
    origins. The profile gives every origin a policy: *follow*, *pin*, or
    *hold, with a reason*.
  - Every run records what it **left pending, by class**: security,
    `-updates`, third-party, **Ubuntu Pro/ESM**, and outside apt.
    `noble-security` doesn't patch universe (wslcb: 546 universe packages,
    29 esm-apps updates pending), so "0 security pending" never covers them.
  - **Under `scheduled`, both lanes run in the same monthly window** (decided
    2026-09-29).
- **An owner for every component, and a way to tell them.** The probe
  names an update owner for each component apt doesn't reach.
  - Binaries the image ships belong to the image, or the platform's
    `exeuntu update`.
  - What a repo installed itself belongs to that repo.
  - When the probe sees an update available for a component whose owner
    is another repo (CannObserv/provisioner above all), the
    skill proposes an issue for that owner. On approval, it files the
    issue (step 6c).
- **One profile, `exe-dev-exeuntu`, covering two image generations**:
  [environments/exe-dev-exeuntu.md](../../skills/patching-hosts/references/environments/exe-dev-exeuntu.md).
  Every fact in it is dated and sourced. A second profile, for DigitalOcean
  plus Lima (the WordPress host), is deferred past v1.
- **An infrastructure repo owns the image** (decided 2026-09-29). Four
  findings belong to the image, not to any host:
  - the masked timers, with `Periodic::Enable "0"`;
  - the volatile journal;
  - the setup script re-delivered on every boot;
  - `exe-init` builds that start sessions at -1000.

  CannObserv/provisioner, a new private repo, is stood up as part of this work
  (step 0b). It's the `image` owner that step 6c's notices go to, and the home
  of the base image and provisioning template (step 9).
- **A process log**, modelled on `orchestrating-issue-backlog`'s.

The skill never unmasks a timer or edits apt or needrestart config on its own
initiative. Reaching the policy is the provisioning's job: the future cohort
base image, or an owner-approved remedy the profile documents.

## Tradeoffs / alternatives

- **Probe and propose only; leave applying to the agent** — rejected. Applying
  is the stateful, dangerous step, and this repo's rule is exact scripts for
  those. An ad-hoc `apt-get upgrade` would also pull non-security updates and
  let needrestart restart services.
- **No built-in policy; the knob must state one** — rejected. With no knob
  there would be nothing to compare against, and the reference policy is the
  distro's own default, so shipping it keeps the skill generic.
- **YAML or TOML for the knob** — rejected for v1. Every other knob uses a
  `#`-comment line grammar, and the probe must parse it on stock Ubuntu with
  nothing extra installed.
- **The skill unmasks timers to reach the policy** — rejected, per #313 §2(a)
  step 5. It reports the deviation and names the remedy; the owner or the base
  image acts on it.
- **Name it `maintaining-hosts`** — rejected. The archiver comment puts
  platform-binary policy in the profile and reporting in the core, so
  `patching-hosts` covers it without the wider name.

## Steps

0. **The step 0 round: done (2026-09-21 → 09-29).** Ten exe.dev hosts were
   patched by hand, one at a time. Each had a coordinating issue in its own
   repo, the host's own agent, and a Mayfly channel, and each ended at the
   patch plus the needrestart drop-in, with the update posture unchanged.
   - The runs, their counts and the synthesis are on #313 (closing comment
     5898628226). Each host's comment there is the process-log source for
     step 7.
   - The round's lessons are folded into the Approach and into steps 3, 4,
     6 and 6a below.
   - **Deferred:** the WordPress host (DigitalOcean plus Lima). It needs its
     own profile.
   - **The policy, when a host adopts `automatic`, must set
     `APT::Periodic::Enable "1"`** in a file sorting after
     `docker-disable-periodic-update`. The Docker base image sets it to 0,
     which makes the timers no-ops even when unmasked (CannObserv/archiver#278).

0b. **Stand up CannObserv/provisioner** (decided 2026-09-29). It must exist
    before step 6c has an `image` owner to notify.
    - **Created 2026-09-29: private, empty.** You chose the name and
      visibility.
    - **Seeding it happens in its own session,** not from this repo, per the
      no-cross-repo-commits rule:
      - an AGENTS.md;
      - the vendored skills submodule, with `using-mayfly-chat`.

      A bootstrap issue there carries the brief.
    - **Four issues, one per image-level finding** (Approach), each filed on
      your go-ahead.
    - Step 6c's rule keeps private identifiers out of notices to a **public**
      repo. A private provisioner may name any host.

    *Done when* the repo is bootstrapped, its four issues are filed, and the
    knob grammar's default `image` owner names it.

1. **Scaffold. Done 2026-09-29** (`4ac1799`): `SKILL.md` with its
   frontmatter, the core, the self-budget line and the five references,
   plus the README and `docs/KNOBS.md` rows. `skills-ref validate` and the
   structural suite pass. **Left for later steps:** each script's
   per-script resolution block lands with that script, starting with
   `probe.sh` in step 3.
2. **Policy and knob.**
   - `references/policy.md`: the reference policy, what each deviation means,
     and the exception grammar (`exception <what> <review-by> <reason>`).
     Keeping a dormant component uses the same grammar, as
     `exception keep:<component> <review-by> <reason>`. Each prune stage is
     declared in the same way, as `disabled:`, `removed:` or `purged:`. The
     review-by date is the calendar: when it passes, the entry expires, which
     is already a finding, and the probe proposes the next stage. `purged:`
     stays until the base image stops shipping the component.
   - The `.skills/patching-hosts` grammar and a row in `docs/KNOBS.md`. With
     no knob, the host is treated as production and the skill only reports.
   - The grammar is written: [knob.md](../../skills/patching-hosts/references/knob.md) (2026-09-29). This step
     implements its parser.

   - The `[host <glob>]` sections, and how a host finds its own. It is
     matched by `--host`, or else by `hostname`. An exact name beats a glob.
     Two globs that match equally are a configuration finding, not a silent
     choice. A file with sections and no match is treated as production,
     report-only.

   *Done when* `test_skills_knob_inventory.py` passes, and a parser test
   covers:
   - comments and a malformed line;
   - a past review-by date (an expired exception is a finding);
   - section precedence (global, then glob, then exact), plus the tie and the
     no-match cases;
   - every line kind above.
3. **`probe.sh`, read-only.** Flags: `--help`, `--root DIR` (reads a filesystem
   tree instead of `/`), `--config`, `--host NAME` (the output names the
   section that matched), and `--refresh-into DIR` (refreshes apt
   lists into a scratch directory, never `/var/lib/apt/lists`). Masks are read
   from the filesystem so the probe works offline. It reads the effective
   `APT::Periodic::Enable` through `apt-config`, and reports security updates
   held by an exception separately from those pending. It emits JSON on stdout
   and diagnostics on stderr.

   **The readings are specified** in [readings.md](../../skills/patching-hosts/references/readings.md)
   (2026-09-29), each with the mistake it prevents. The probe implements
   them, plus a `--post-boot` mode for the checks in [run.md](../../skills/patching-hosts/references/run.md) §6.

   Its `dormant` section follows the verdict rules in
   [policy.md](../../skills/patching-hosts/references/policy.md#dormant-components).
   Each engine the probe knows (Docker, Postgres, Redis, nginx, Ollama and
   Qdrant to start with) gets one entry with its evidence:
   - the unit's state and whether it is enabled;
   - its listening sockets;
   - its workload: containers, images and volumes; non-template databases
     and their sizes; enabled sites;
   - whether the repo's `deploy/` units, docs or knob name it;
   - its packages in the pending security set;
   - whether it came with the image or was installed on the host, from the
     install date against the image's date.

   The verdict is `in-use`, `dormant`, `kept` (a declared exception) or
   `unknown`. It is never `dormant` on evidence the probe couldn't read. A
   database whose activity needs a login is `unknown` unless the operator
   supplies that read, as notifier's harness required.

   *Done when* stub-binary tests (the
   `test_socraticode_claude_age.py` pattern) cover:
   - §1's masked timers under `"1"`, reported as a finding;
   - `Periodic::Enable` resolving to 0 with the timers unmasked, reported as
     a finding;
   - an absent setting, reported as `unknown`;
   - `reboot-required` together with `reboot-required.pkgs`;
   - a deviation with a declared exception and one without;
   - Docker active with zero containers, reported as `dormant`; the same
     with a `keep:` exception, reported as `kept`;
   - a Postgres whose activity can't be read, reported as `unknown`;
   - idle evidence younger than 30 days, reported as `unknown`;
   - a 0755 `/exe.dev/setup` holding a `tskey-auth-` literal, with the unit
     failed, reported as a finding. The output names the pattern and the
     line, and **the fixture's secret string appears nowhere in stdout or
     stderr**;
   - no `/exe.dev/setup`, but a journal showing `ConditionResult=yes` on
     every retained boot, reported as a script **re-delivered each boot**,
     not as clean;
   - an argv log showing no installing, removing or list-writing command was
     run;
   - `Storage=persistent` with `systemd-journal-flush` masked and an empty
     `/var/log/journal`, reported as **volatile**;
   - an earlyoom whose journal holds two starts with different arguments:
     the reading comes from `cmdline`;
   - a runbook service without `After=` its data store, reported as a
     finding even when its first start succeeded;
   - a session chain whose adj test would skip: the adj is read anyway.
4. **The `exe-dev-exeuntu` profile.** Written 2026-09-29:
   [environments/exe-dev-exeuntu.md](../../skills/patching-hosts/references/environments/exe-dev-exeuntu.md).
   It covers the detection markers, the two image generations, the update
   channels, the self-restart table, `/tmp`, the `exe-setup.service`
   contract, clean-shutdown evidence, sessions and OOM, and the image
   owner's findings. This step:
   - wires its detection into the probe;
   - adds a generic apt fallback section to `SKILL.md` for hosts no profile
     matches.

   *Done when* the probe names the profile and the generation on each
   fixture, and the links and references tests pass.
5. **Validate against the real image, offline.** Run `probe.sh` inside the
   exeuntu image, pinned by digest, in a throwaway container. Confirm the
   detection, the masked readings and the needrestart version. The digest
   and `NEEDRESTART_MODE` questions were answered in step 0. *Done when* the
   profile's detection matches the image.
6. **`apply.sh` and steps 5–7 of the core.**
   - `apply.sh` refuses without `--approve`, refuses on a host that declares
     a `datastore` but has no recovery point off the node, and refuses on an
     `ephemeral` host (the remedy is to rebuild its image). A host with no
     data store needs only its before-versions.
   - It writes the before-versions (`dpkg-query -W`, `apt-mark showhold`,
     `apt-mark showauto`) to a root-only record file.
   - `--step bulk|<held group>` runs one step. The bulk holds every `hold`
     glob, and each held group is its own invocation under its own approval.
   - It refuses a step while the knob's `inflight` command prints non-zero.
   - Each step runs `NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v`,
     with no memory cap, and records wall time and max RSS.
   - The verdict comes from the exit code, `All upgrades installed` and an
     empty `dpkg --audit`. On failure it stops and prints the abort branch:
     `dpkg --configure -a`, then the snapshot.ubuntu.com versions. The round
     never exercised this, so it's tested by stubs only.
   - A data-store step stops each `restarter` first, polls health every
     second (logging each code with its timestamp), then starts the
     restarter and proves it's active.
   - It never reboots, unmasks, enables, or removes anything by name. It
     re-probes and runs the knob's health checks.

   *Done when* stub tests prove:
   - each refusal;
   - the recorded before-versions;
   - the holds, released only for the named step, and never touching a
     package the owner held before the run (`showhold` ends equal to its
     recorded value);
   - `NEEDRESTART_MODE` and `choom`;
   - a failing verdict stops the run;
   - no `systemctl unmask`, `enable` or `reboot`, and no `apt-get remove` or
     `purge`, was run.

6a. **The recovery point and the reboot chain.**
    - **`recovery-point.sh --approve`** dumps each declared `datastore`.
      - Postgres: `pg_dump -Fc` through `sudo sh -c 'umask 077; cat > …'`.
        A `>` from the session shell can't write to `/var/backups`
        (CannObserv/address-validator#235).
      - Redis: `BGSAVE`, then a copy of the RDB file.

      It gates on `pg_restore --list` and mode 600, and prints the sha256
      for the owner's off-node copy. **It prefers the host's own backup
      regime** when the probe finds one that succeeded recently (watcher).
      The dump is written with a stated retention, and flagged when it
      holds personal data (address-validator's `raw_input`).
    - **`reboot-chain.sh --approve`** writes and launches the chain as a
      0700 root script, via `systemd-run --on-active=… --timer-property=AccuracySec=1s`.
      The accuracy setting matters: by default the timer fired 41 s late on
      wslcb. The chain survives the operator's disconnect, logs to
      `/var/backups/`, and runs:
      1. the `inflight` gate (abort if it fails), run as the invoking user
         and shown verbatim in the script, never as root;
      2. stop the restarters, then the runbook services;
      3. `CHECKPOINT`, then stop the data store;
      4. `journalctl --sync`;
      5. copy the journal, read it back with `journalctl -D`;
      6. `sync`, then `systemctl reboot`.

      It never restarts through the platform, which is a hard reset.

    *Done when* stub tests prove:
    - the dump's mode, and that it's written as root;
    - the `--list` gate;
    - the chain's order;
    - the abort when the gate fails;
    - the journal copy comes after every stop;
    - no platform restart command appears.

6b. **Pruning: `references/pruning.md` and two scripts.** The skill proposes
    and the operator runs. Scripts cover only the steps that are mechanical
    enough to be the same on every host.
    - **The calendar.** The default is:
      1. disable (stop, disable and mask the unit, plus its sockets and
         timers);
      2. remove;
      3. purge, after a soak of 30–90 days.

      Each stage waits for its review-by date. **With a savepoint the remove
      stage is skipped**: disable, soak, savepoint, then purge. That is the
      better path for security, because `remove` leaves config behind
      (sometimes secrets) and keeps an `rc` package the probe must explain.
      The operator chooses the path and can shorten any soak.
    - **The savepoint is optional.** It holds:
      - a tarball of the component's config;
      - the before-versions;
      - where data exists, a dump or archive off the node, with its retention
        stated.

      The skill warns, but does not refuse, when a data-holding component
      goes without one. Without a savepoint, the remove stage is the
      reversible step and stays in the calendar.
    - **`prune-plan.sh`, read-only.** For one component it emits JSON with:
      - the units, sockets and timers to disable;
      - its reverse dependencies;
      - the simulated removal set (`apt-get -s`), including the packages it
        drags along and any metapackage it would take;
      - the lines in the package's purge script that delete files, and its
        debconf defaults;
      - its data and config paths, with sizes;
      - any `rc` residue.
    - **`prune.sh --stage disable|remove|purge --plan FILE --approve`.** It
      acts only on the set the plan file names. It refuses when a fresh
      simulation differs from that set, so an approval binds to exact
      packages. It never runs a bare `autoremove`, and never removes data
      the plan doesn't name. Backups of data stay with the operator, because
      they differ by component.

    *Done when* stub tests prove:
    - each refusal;
    - that a disable covers `docker.socket` as well as `docker.service`;
    - the drift refusal when the simulated set changes;
    - that no command outside the approved set was run.

6c. **The maintenance lane and owner notices.**
    - **`apply.sh --lane maintenance`** reuses the security lane's gates,
      recovery point, window and reboot decision. Only the selection
      differs: Ubuntu `-updates` plus the origins the profile marks
      *follow*. It applies through `apt-get upgrade`, with the same holds
      and the same `NEEDRESTART_MODE=l`.
    - **Tailscale** goes in the maintenance lane, because upgrading
      tailscaled drops every host's tailnet path, so it needs a planned
      window. A Tailscale security bulletin expedites it into an
      out-of-cycle window. The profile records where those bulletins are
      watched, and by whom.
    - **The knob gains `owner <component-glob> <repo>` lines.** The default
      owner of something the image ships is `image`, meaning the
      image-generation repo once it exists; until then, the host's own repo.
    - **`notify-owners.sh`** turns the probe's "update available, owner
      elsewhere" rows into issues in the owner's repo.
      - `--dry-run` is the default, and prints each issue it would file.
      - `--file --approve` files them through `gh`. Filing is an outward
        write, so it never happens without approval.
      - It files one issue per component. A hidden marker
        (`<!-- patching-hosts:update <component> -->`) lets a later run find
        the open issue and comment the newer version on it, rather than open
        a duplicate.
      - An issue carries the component, installed and available versions,
        the evidence source, and the hosts affected. It carries no host
        secrets, and no private-repo identifiers when the owner's repo is
        public.

    *Done when* stub tests prove:
    - `--lane maintenance` selects `-updates` and the *follow* origins, and
      never a *hold* one;
    - `notify-owners.sh` files nothing without `--file --approve`;
    - a second run finds the open issue by its marker and comments instead
      of filing a duplicate;
    - the body carries no value that matched a secret pattern.
7. **Process log.**
   - `references/process-log.md` as the root, with a 2026 index and "Adding
     an entry" rules copied from the orchestrator's: a vendored copy files an
     issue upstream, and a private consumer's entry names no identifier of its
     own.
   - One new rule: **an entry that lists pending security updates lands only
     after they are applied**, and records counts and families, not versions.
   - Seed entries from step 0: the two pre-round readings (broker 2026-09-21
     and archiver 2026-09-22), plus one entry per patched host, from its
     #313 comment. Host 6 stays anonymous.

   *Done when* `test_process_log_entries.py` passes.
8. **Gate.** *Done when* `bash scripts/pre-ship.sh` is green (budgets, ruff,
   shellcheck, the full structural suite) and every script's `--help` output
   is accurate.
8b. **Exercise the skill by hand on every host** (decided 2026-09-29).
    - After the skills submodule bump, each host's own agent runs the skill
      end to end, with the owner approving in that session. The run is also
      that host's maintenance-lane catch-up, so it closes the gap until the
      first monthly run.
    - The order is replicator (no data store) first, then one Postgres host,
      then the rest.
    - Every rough edge becomes an issue in this repo, fixed before the next
      host: a wrong reading, a missing knob line, or a step the scripts
      couldn't do.
    - Each host commits its `.skills/patching-hosts` knob in this run.
    - A Mayfly channel is optional: the skill carries what the round's
      briefs did.

    *Done when* every exe.dev host has had one run under the skill, and each
    rough-edge issue is closed or deferred with a reason.
9. **Follow-ups, drafted and filed only on your go-ahead per repo:**
   - in this repo, a once-a-day `SessionStart` hook that prints the probe's
     one-line status;
   - in CannObserv/provisioner (step 0b), the cohort base image and the
     Terraform hardening. They should include a provisioning-script
     template that:
     - logs under `$HOME`;
     - removes the script and any key file from an `EXIT` trap ("a trap is
       unconditional; a trailing line is not", co-index's
       `deploy/index/setup.sh.template`);
     - uses only single-use, short-lived auth keys, like notifier's, which
       had expired by the time it was found. The copy delivered again at
       each later boot is then already dead;
     - is **idempotent**, because it runs on every boot, not once.

     A template fixes only VMs created from it. A VM that already exists
     keeps the script it was created with, until the platform clears it.
   - in each host repo, a census and remediation issue after release, broker
     first. It carries that host's dormant components, each as prune or keep.
   - where a dormant component shipped with the image on every host, the
     prune belongs in the cohort base image, not in a removal on each host.
     That keeps provisioning reproducible. **How a prune is promoted into
     provisioning gets its own design process** in CannObserv/provisioner, not in
     this plan;
   - **a cohort backup pattern**, in CannObserv/provisioner. Three hosts have no
     backup regime (CannObserv/archiver#233, CannObserv/address-validator#240,
     CannObserv/wslcb-licensing-tracker#185), and watcher's is a working
     template;
   - **a second profile**, for DigitalOcean plus Lima, before the WordPress
     host's run.

## Decided at review (2026-09-25)

- **`apply.sh` ships in v1** (step 6).
- **One knob covers several hosts.** The cohort has both shapes, so the knob
  carries `[host <glob>]` sections and an `ephemeral` class (Approach, step 2).
- **Broker is patched first** (step 0). It is still unpatched, and #313
  already names its pending packages in public, so this is live exposure. The
  run also frames the issue.
- **A `dormant` verdict needs 30 days of evidence (2026-09-27).** The probe
  reports each piece of evidence with its age: uptime, database statistics
  since their reset, and container history. Anything younger than 30 days is
  `unknown`, not `dormant`, so a monthly job or freshly reset statistics
  can't make a live component look unused.
- **A removal by hand is recorded in the knob (2026-09-27).** When the
  component came with the image, the fix is the base image (CannObserv/provisioner).
  Until provisioning catches up, a removal on a single host is drift from
  that image, and the knob declares it so the probe doesn't report it as
  unexplained variance.
- **How a prune is carried out (2026-09-27):**
  - `remove` against `purge` is the operator's choice for each case;
  - the savepoint is optional;
  - disable comes first, on a disable → remove → purge calendar, and a
    savepoint lets the operator skip the remove stage, which is better for
    security;
  - the skill proposes and people run it, with scripts wherever the steps
    are stable (step 6b).
- **A maintenance lane, owners, and owner notices (2026-09-29).**
  - A monthly maintenance lane for `-updates` and approved third-party
    origins. The round finishes security-only, as decided, then every host
    catches up once, and the lane is monthly after that.
  - Tailscale sits in the maintenance lane, with advisory-triggered
    expediting.
  - Binaries outside apt: the image or platform owns what the image ships,
    and each repo owns what it installed. The skill reports staleness and
    the owner, and updates none of them.
  - The skill supports filing an update notice with the owner's repo,
    above all the eventual image-generation repo. It's approval-gated and
    deduplicated (step 6c).

- **After the round (2026-09-29, #313 comment 5898628226):**
  - **Cadence: monthly.** The cohort's posture is `scheduled`: a monthly,
    gated run per host covering both lanes, with the apt timers left
    masked. That answers D4.
  - **An infrastructure repo** is stood up as part of this work (step 0b):
    CannObserv/provisioner, private (named 2026-09-29).
  - **The gap until the first monthly run** is closed by exercising the
    skill by hand on every host (step 8b). That run is each host's
    catch-up.
  - **The WordPress host is deferred.** It's a different environment.

## Open questions / risks

- **D4 is answered** by the `scheduled` posture (Decided, 2026-09-29).
  **Who is accountable for the window** is the host repo's owner: the knob
  names the window, and the monthly run is owner-approved in that host's
  own session. A reminder or calendar for the monthly run is not designed
  yet. The once-a-day `SessionStart` status line (step 9) is the first
  candidate.
- **CannObserv/provisioner's bootstrap** runs in its own session. Until
  it's seeded, the four image issues can be filed, but no agent there can
  act on them.
- **Ubuntu Pro.** The ESM class stays pending on every host until someone
  decides whether to attach Pro. That's an owner question, not the
  skill's; the skill only reports it.
- **Steps 6a, 6b and 6c make v1 larger.** 6b and 6c can ship as v1.1 if v1
  runs long. 6a can't, because step 8b's runs need it. The probe's `dormant`
  section (step 3) doesn't depend on any of them.
- **Step 8b costs about ten owner-approved runs.** Each run is also that
  host's monthly catch-up, so the cost is paid once either way.
- **Profile detection uses markers, not the image digest.** Step 0 found no
  digest in any documented place in the guest (broker#65, M3). Detection
  therefore uses markers: the `exe-setup.service` unit, `/usr/local/bin/exeuntu`,
  the absence of a `linux-image` package, and the kernel string. The absence of
  `exeuntu` marks an older image.
- **Answered in step 0 (2026-09-25):** M1 and M2 are settled, and step 5 need
  not measure them again.
  - A stock Ubuntu 24.04 container shows that `NEEDRESTART_MODE` and
    `NEEDRESTART_SUSPEND` survive
    `sudo → unattended-upgrade → dpkg → hook`.
  - Without either one, needrestart restarts services automatically in
    Ubuntu mode.
  - On broker, `unattended-upgrade` ran with its timers masked and took
    exactly the 97 security updates.
- **Self-budget.** `SKILL.md` is held to 6,000 tokens. The procedure stays
  there; the policy, profile and log detail go in `references/`.
