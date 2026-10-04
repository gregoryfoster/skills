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
    is another repo (the image repo above all), the
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

  **The image repo**, a new private CannObserv repo, is stood up as part of
  this work (step 0b). Each host's knob names it in an `image-owner` line,
  so step 6c's notices go there. It's also the home of the base image and
  provisioning template (step 9).
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

0b. **Stand up the image repo** (decided 2026-09-29). It must exist
    before step 6c has an `image` owner to notify.
    - **Created 2026-09-29: private, empty.** You chose the name and
      visibility. Because it's private, this public plan doesn't name it.
    - **Seeding it happens in its own session,** not from this repo, per the
      no-cross-repo-commits rule:
      - an AGENTS.md;
      - the vendored skills submodule, with `using-mayfly-chat`.

      A bootstrap issue there carries the brief.
    - **Four issues, one per image-level finding** (Approach), each filed on
      your go-ahead.
    - Step 6c's rule keeps private identifiers out of notices to a **public**
      repo. The image repo is private, so its issues may name any host.

    *Done when* the repo is bootstrapped, its four issues are filed, and
    each host's knob names it in an `image-owner` line (step 8b). The
    global skill never names it.

1. **Scaffold. Done 2026-09-29** (`4ac1799`): `SKILL.md` with its
   frontmatter, the core, the self-budget line and the five references,
   plus the README and `docs/KNOBS.md` rows. `skills-ref validate` and the
   structural suite pass. **Left for later steps:** each script's
   per-script resolution block lands with that script (`read-knob.sh` in
   step 2, `probe.sh` in step 3).
2. **Policy and knob. Done 2026-09-30:** `scripts/_knob-lib.sh`, the shared
   reader, and `scripts/read-knob.sh`, which prints what it resolves for one
   host as JSON. Tested in `tests/structural/test_patching_hosts_knob.py`.
   Building it settled three things knob.md now states:
   - globs layer by specificity, so a narrower glob refines a broader one, and
     only equally specific matches tie;
   - one-value directives take the most specific scope, lists are replaced
     whole, and keyed directives accumulate per key;
   - a malformed line makes every host report-only, and a range that ends
     where it starts is malformed.

   What the step set out to do:
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
     choice. A host that matches none of a file's sections gets the global
     lines only; with no global `posture`, that's `automatic`, report-only
     (knob.md).

   *Done when* `test_skills_knob_inventory.py` passes, and a parser test
   covers:
   - comments and a malformed line;
   - a past review-by date (an expired exception is a finding);
   - section precedence (global, then glob, then exact), plus the tie and the
     no-match cases;
   - every line kind above.
3. **`probe.sh`, read-only. Done 2026-09-30:** `scripts/probe.sh` over
   `scripts/_probe-lib.sh` and the knob library, tested in
   `tests/structural/test_patching_hosts_probe.py`. It ran clean on a real
   noble userland, and live in a throwaway container booting systemd 255 with
   Postgres 16, Redis and nginx. That run caught four bugs the stubs couldn't:
   - a held package never appears in `apt-get -s`, so holds are read from
     `apt-cache policy`;
   - a tab is IFS whitespace, so psql's empty fields collapsed;
   - stock Ubuntu's release pocket in Allowed-Origins isn't a widening;
   - idle time counts from when systemd started, not the kernel.

   Building it settled these, now in the references:
   - `--root DIR` reads a tree's files, and asks a running system only when
     `DIR/run/systemd/system` exists, systemd's own test.
     `--refresh-into` and `--dry-run-into` need a running system;
   - root-only readings go through `sudo -n`, and a knob command never runs
     as root. A reading the probe couldn't take is `null`, and named in
     `not_read` with what it leaves to the operator (readings.md);
   - each finding an exception can cover names its `<what>` (policy.md's
     table), and a covered one moves to `excepted`;
   - host strings print as ASCII, with `?` for any other byte.

   What the step set out to do: flags `--help`, `--root DIR` (reads a
   filesystem tree instead of `/`), `--config`, `--host NAME` (the output
   names the section that matched), and `--refresh-into DIR` (refreshes apt
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
   - a session chain whose adj test would skip: the adj is read anyway;
   - an owner's hold on a pending package without a `held:` exception,
     reported as a finding;
   - a cluster database no `datastore` line names, reported as a finding,
     while `postgres` and the templates are not.
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

   **Done 2026-10-01.** The probe reports `environment.profile`: the name,
   the reference, the generation and each marker as read. It settled:
   - **the profile matches** on the platform's markers (`/exe.dev/`,
     exe-init as `init=`) or the image's (the `exedev` account, the init
     wrapper at `/usr/local/bin/init`). The image doesn't carry
     `/exe.dev/`, so only the image's markers hold in an offline tree. The
     others (`exeuntu`, `exe-setup.service`, installed `linux-image-*`
     packages, the kernel release) are reported, each read on its own;
   - **the generation** comes from the two markers the profile's table
     differs by: no `exe-setup.service` and no `exeuntu` is `feb-2026`,
     `exe-setup.service` without `exeuntu` is `may-2026` (usa-wa's), both
     are `newer`, and `exeuntu` alone is `unknown`. Only the image's
     markers date it: on the platform's alone, it's `unknown`;
   - on exe.dev, the reboot reading says needrestart's kernel status means
     nothing there (run.md §4);
   - **whether a component came with the image** stays in `not_read`. It
     needs the image's build date, which no marker gives; step 5 reads the
     real image and can say what does.
5. **Validate against the real image, offline.** Run `probe.sh` inside the
   exeuntu image, pinned by digest, in a throwaway container. Confirm the
   detection, the masked readings and the needrestart version. The digest
   and `NEEDRESTART_MODE` questions were answered in step 0. *Done when* the
   profile's detection matches the image.

   **Done 2026-10-01**, on the image built from exeuntu `1b74aabd`
   (2026-09-29): index `sha256:c811379e…`, arm64 manifest
   `sha256:ede5b9a8…`. The amd64 manifest (`sha256:b613464b…`) wouldn't run
   here: this Docker has no amd64 emulation. Same build, and nothing
   checked depends on the architecture.
   - **Offline**, as root and as `exedev` through `sudo`: `exe-dev-exeuntu`,
     generation `newer`, from the image's markers alone (`/exe.dev/` is
     absent); all 5 units masked; `Enable` 0 from
     `docker-disable-periodic-update`; needrestart `3.6-7ubuntu4.5`. Under
     `scheduled` it found what the image lacks: the needrestart drop-in, a
     policy for its Tailscale origin, and fresh lists. Under `automatic` it
     added both timers, `Enable` and `Automatic-Reboot`.
   - **Booted under its own init**: `exe-setup.service`'s condition unmet,
     the journal persistent, needrestart in Ubuntu mode.
   - **A bug the stubs couldn't show**: the image enables `docker.socket`
     and disables `docker.service`, so the probe's container-image reading
     started dockerd. That changed the host, and restarted the idle clock
     Docker's dormant verdict reads. The probe now asks Docker only while
     `docker.service` runs.
   - **The image's build date, in the guest**: the image's own files carry
     the build's start, and apt's `history.log` ships with the build's
     runs. A `.list` file's mtime isn't provenance, since an upgrade
     rewrites it; a package's first `Install:` line in that history is.
     Wiring it in is left for when the dormant verdicts need it.
6. **`apply.sh` and steps 5–7 of the core.**
   - `apply.sh` refuses without `--approve`, refuses on a host that declares
     a `datastore` but has no recovery point off the node, and refuses on an
     `ephemeral` host (the remedy is to rebuild its image). A host with no
     data store needs only its before-versions.
   - A script on the node can't see that a dump has left it, so that
     refusal binds to the owner's attestation of every recovery-point
     file meant to leave the node, which is each database dump and RDB
     copy `recovery-point.sh` recorded:
     - one `--offnode-sha256 <hex>` per dump, each equal to a recorded
       sha256, typed after the owner checks their own copy;
     - for a `backup` unit, which writes straight off the node, a run of
       that unit that succeeded after the recovery point began (its
       `Result` and `ExecMainExitTimestamp`), plus `--offnode-object
       <name>`, typed after the owner confirms the object exists. A
       generic script can't parse what each backup unit logs, so the name
       is recorded as the owner's attestation, not compared.
   - It writes the before-versions (`dpkg-query -W`, `apt-mark showhold`,
     `apt-mark showauto`) to a root-only record file.
   - `--step bulk|<held group>` runs one step. The bulk holds every `hold`
     glob, and each held group is its own invocation under its own approval.
   - It refuses a step while the knob's `inflight` command prints non-zero.
     It also refuses when the step's span (now plus its expected duration,
     from the dry run) isn't wholly inside one `window`, or overlaps a
     `quiet` range. `reboot-chain.sh` checks the chain's launch the same way.
   - Each step runs `NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v`,
     with no memory cap, and records wall time and max RSS.
   - The verdict comes from the exit code, `All upgrades installed` and an
     empty `dpkg --audit`. On failure it stops and prints the abort branch:
     `dpkg --configure -a`, the snapshot.ubuntu.com versions, and the run's
     own holds, each to be released or declared as `held:<package>`. The round
     never exercised this, so it's tested by stubs only.
   - A data-store step stops each `restarter` first, polls health every
     second (logging each result with its timestamp), then starts the
     restarter and proves it's active.
   - It never reboots, unmasks, enables, or removes anything by name. It
     re-probes and runs the knob's health checks.

   *Done when* stub tests prove:
   - each refusal, including a step that starts inside a `window` but
     would run past its close, a step that starts outside a `quiet` range
     but would run into one, a missing or mismatched `--offnode-sha256`,
     one dump of two left unattested, and a `backup`-unit recovery point
     whose last successful run predates the recovery point, or that lacks
     `--offnode-object`;
   - the recorded before-versions;
   - the holds, released only for the named step, and never touching a
     package the owner held before the run (`showhold` ends equal to its
     recorded value);
   - `NEEDRESTART_MODE` and `choom`;
   - a failing verdict stops the run, and its output lists the run's own
     holds;
   - no `systemctl unmask`, `enable` or `reboot`, and no `apt-get remove` or
     `purge`, was run.

   **Done 2026-10-01:** `scripts/apply.sh`, tested in
   `tests/structural/test_patching_hosts_apply.py`. The probe's stub rig is
   now shared, in `tests/structural/patching_hosts_rig.py`. It ran live in a
   booted noble container, with Postgres 16.2 and Redis 7.0.15 from the
   release pocket and a timer as the restarter:
   - the bulk held five packages and left both daemons' PIDs alone;
   - each held step upgraded its group, and the maintainer scripts restarted
     Postgres and Redis;
   - health passed, the restarter came back, and `showhold` ended as
     recorded.

   Building it settled:
   - **the bulk refreshes the host's own lists first.** The probe's dry run
     counts against a scratch copy, and on a host whose timers are masked,
     the host's lists may be months old. Holds expand against
     `apt-get -s dist-upgrade` after that refresh, from any origin;
   - **three refusals beyond the list:**
     - `Automatic-Reboot` true: unattended-upgrade then reboots by itself,
       it takes no `-o`, and `APT_CONFIG` loses to `apt.conf.d`;
     - origins wider than `-security` without `exception uu:origins`;
     - a `dpkg --audit` that isn't clean before the step;
   - **four more from review (CR 99–124):**
     - a restarter that isn't a unit on the host: `is-active` reads a
       missing unit as inactive, so it would never be stopped;
     - a dry run that counted nothing, or began more than 24 hours ago;
     - a recovery point whose `backup` unit the knob doesn't declare;
     - an automatic apt run in progress, or a span that meets the range
       `apt-daily-upgrade.timer` can start in: systemd draws its random
       delay again at every reload, and a step's maintainer scripts reload
       it;
   - **a held step stops its restarters before it releases its group,** so
     a stop that fails leaves the group held, and a step that fails before
     its upgrade starts them again and can run again;
   - **a recovery point must have begun within 24 hours,** and a backup
     unit's run must have *started* after it began. The record's lines are in
     run.md §2, for step 6a to write;
   - **two probe bugs the live run caught.** `--dry-run-into` never made
     `archives/partial`, so every download failed once anything was pending.
     GNU time's status line on a failed command hid the max RSS.

6a. **The recovery point and the reboot chain.**
    - **`recovery-point.sh --approve`** dumps each declared `datastore`.
      - Postgres: `pg_dump -Fc` through `sudo sh -c 'umask 077; cat > …'`.
        A `>` from the session shell can't write to `/var/backups`
        (CannObserv/address-validator#235).
      - Redis: `BGSAVE`, then a copy of the RDB file.

      It gates on every pipeline stage exiting 0, then `pg_restore --list`,
      then a full read (`pg_restore -f /dev/null`), then mode 600. `--list`
      alone passes a dump truncated after its table of contents. It records
      and prints each dump's sha256 for the owner's off-node copy. **It
      prefers the host's own backup regime** when the probe finds one that
      succeeded recently (watcher). It then starts that unit and records
      its run's `Result` and `ExecMainExitTimestamp` instead of a sha256.
    - It also writes `pg_dumpall --globals-only` on the node, mode 600, and
      never asks for it to be attested: it holds role password hashes, so
      it stays on the node.
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
    - the globals dump written at mode 600, and never requested for an
      off-node attestation;
    - a truncated dump failing the gate, although `--list` passes it;
    - the chain's order;
    - the abort when the gate fails;
    - the journal copy comes after every stop;
    - no platform restart command appears.

    **Done 2026-10-01:** `scripts/recovery-point.sh` and
    `scripts/reboot-chain.sh`, tested in
    `tests/structural/test_patching_hosts_recovery.py` and
    `test_patching_hosts_reboot.py`. What the three acting scripts share
    moved from `apply.sh` into `scripts/_gate-lib.sh`. Building it settled:
    - **the record gained two lines,** `retain <date>` from the required
      `--retain-until`, and `personal <path>` from `--personal-data`;
      `apply.sh` reads both;
    - **pg_dump runs as postgres under root's own sh,** its output opened by
      that sh at mode 600: one stage, so its exit status is the pipeline's;
    - **a backup regime is relied on only where its last run succeeded,**
      and its run now must start after `began` and succeed, as the bulk
      checks; otherwise it dumps, and `--dump` dumps anyway;
    - **Redis is reached where its own config file binds,** since a host may
      bind only its tailnet address, and its password never leaves that
      file: redis-cli reads it from `REDISCLI_AUTH`, and the chain reads the
      file when it runs;
    - **two refusals beyond the list:** the recovery point refuses a
      filesystem with less free space than the data, since a full disk
      mid-dump can stop the data store on it, and the chain refuses, and
      aborts at its own start, while a package manager runs;
    - **without `--approve` the chain is printed, not written,** so the text
      the owner approves is the text that runs;
    - **from review (CR 125–141):**
      - every value in the chain is single-quoted, and a cluster's port must
        be a number. A unit's name is the knob's, and Redis's address and a
        cluster's port come from files the redis and postgres users can
        write: a `$( )` in any of them would run as root;
      - a chain that aborted at its own gate stopped nothing, so it can be
        launched again. Only one that's scheduled, running, or ran without
        an ABORT refuses a second;
      - a recovery point taken again removes the earlier record first, so
        an attempt that fails leaves none for the bulk to take;
      - the chain copies only the volatile journal. A persistent one
        survives the boot, and a copy of it, up to journald's 4 GiB cap,
        would land on the disk the data stores boot from;
      - the chain's timer gets the delay less the time the gate took, so it
        fires at the time its span was gated from;
      - Redis is reached where its unit's own `--port`, `--bind` or
        `--unixsocket` say, over its file's: a second Redis may share the
        file, and its recovery point would otherwise be the first's data;
      - the recovery point and the chain read a Redis password with one
        script, as Redis does: a single-quoted value or one with trailing
        space read wrong in the chain, and the SAVE before a stop failed;
      - the chain logs a SAVE Redis refuses from its reply: redis-cli exits
        0 on an error reply;
      - the Redis reached must be the unit's own process, its main PID the
        `process_id` INFO reports: a port redis_conn can't read, such as
        `--port ${VAR}`, would reach another Redis.

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

    **Done 2026-10-02:** `scripts/prune-plan.sh` and `scripts/prune.sh`, over
    a new `scripts/_prune-lib.sh` both share, documented in
    `references/pruning.md` and tested in
    `tests/structural/test_patching_hosts_prune.py`. Building it settled:
    - **a savepoint stage beyond the three:** the config tarball and the
      packages' versions, as root at mode 600. With one, the purge may
      follow the disable's soak. Data stays with the operator;
    - **the calendar is the knob's exceptions:** a stage refuses until the
      last stage's `disabled:` or `removed:` review-by date has passed, and
      `keep:` stops every stage;
    - **a plan binds packages, units, conffiles, Postgres clusters and group
      members.** It's good on the host it was taken on, for 24 hours, and
      only while a fresh read matches it;
    - **the disable stops, disables and masks in one systemctl call each,**
      so systemd orders the stops: dockerd before the containerd it runs
      on, whatever order apt lists them in;
    - **data goes only by `--purge-data`,** and only a path the plan names. A
      package's own purge script still runs, so where one deletes a data
      path, the purge refuses until `--purge-data` names it. postgresql-16's
      drops every cluster: it sets `postrm_purge_data` to true itself, so no
      debconf answer keeps one without a terminal (CR 146);
    - **the masks stay after the purge,** so a component installed again
      stays down until someone unmasks it;
    - **Ollama and Qdrant are disabled by script, and removed by hand;**
    - **`postgresql-common` is part of the Postgres component:** its units
      are the cluster's;
    - **no metapackage flag:** dpkg marks none (`postgresql`'s Section is
      `database`), so the plan names what a later autoremove would take
      instead, from apt's own "no longer required" list (CR 148).

6c. **The maintenance lane and owner notices.**
    - **`apply.sh --lane maintenance`** reuses the security lane's gates,
      recovery point, window and reboot decision. Only the selection
      differs: Ubuntu `-updates` plus the origins the profile marks
      *follow*. It uses the same `unattended-upgrade` command, with an
      `APT_CONFIG` file whose `Unattended-Upgrade::Origins-Pattern` adds
      `-updates` and each *follow* origin. The holds, `NEEDRESTART_MODE=l`,
      `choom` and the verdict are unchanged. It never runs a bare
      `apt-get upgrade`, which takes every origin, *hold* ones included
      ([run.md](../../skills/patching-hosts/references/run.md)).
    - **Tailscale** goes in the maintenance lane, because upgrading
      tailscaled drops every host's tailnet path, so it needs a planned
      window. A Tailscale security bulletin expedites it into an
      out-of-cycle window. The profile records where those bulletins are
      watched, and by whom.
    - **The knob gains `owner <component-glob> <repo>` lines, and an
      `image-owner <owner/name>` line** naming whom `image` means. The
      default owner of something the image ships is `image`. With no
      `image-owner` line, its updates are reported and no notice is
      proposed.
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

    **The maintenance lane, done 2026-10-02:** `apply.sh --lane
    maintenance` and `probe.sh --lane maintenance --dry-run-into`, over
    `lane_patterns` in `scripts/_probe-lib.sh`, tested in
    `tests/structural/test_patching_hosts_lane.py`. Building it settled:
    - **one run covers both lanes:** `APT_CONFIG` is read before
      `apt.conf.d`, and its list adds to the host's own, so the lane takes
      the security set too (unattended-upgrade 2.9.1 on noble);
    - **the dry run counts the lane,** and a bulk refuses one of the other;
    - **a held step runs its bulk's lane,** from `<run>/lane.conf`, and
      refuses a knob that follows other origins since;
    - **the host's own origins can't reach a held or pinned one:** a wider
      entry `uu:origins` let through refuses when it names one, names no
      origin, or names one by a pattern;
    - **an origin goes by its `o=` field or its site,** both of which
      unattended-upgrade matches; Tailscale by its site,
      `pkgs.tailscale.com`, whose bulletins the profile cites.

    **The owner notices are open:** the probe has no "update available,
    owner elsewhere" rows to file. Outside apt it reads a binary's age, not
    an available version, which takes a network call the probe doesn't
    make. The image repo was asked which notices it wants, and on what
    evidence (2026-10-02).

    **Tailscale's security bulletins (decided 2026-10-03):** the cohort's own
    monitoring pipeline (CannObserv's archiver, replicator, processor,
    watcher and notifier) will watch the feed, once it reads XML:
    - **XML and RSS support starts in co-core,** with a feed extractor that
      emits one line per item; Archiver's schema granularity is left to a
      design pass on its issue;
    - **what changed is #222's line diff,** in which a new bulletin is a `+`
      line;
    - **delivery is over the broker's bus, not through notifier,** which
      stays for delivery outside the cohort. The image repo, run as a
      service, reads watcher's `content.revisions` through its own read-only
      consumer group, confirms a new bulletin ID, and opens or updates the
      tracking issue, deduplicated by that ID. It reads and proposes, and
      never applies;
    - **each bulletin opens one tracking issue in the image repo,** which
      fans out to the hosts that run Tailscale;
    - **no interim watch** until then.

    The skill's part is step 6d. The cohort's side is filed (2026-10-03):
    co-core's feed extractor, watcher's and processor's matching steps,
    archiver's source specs, broker's onboarding of a read-only
    `content.revisions` consumer, and watcher described as general-purpose.
    The image repo becomes a service that reads the change and opens the
    tracking issue; the judgment and the window stay in a session the owner
    approves. The window's order is a canary on the least-exposed service
    node, then each other service node, then the broker last, since the
    cohort's bus rides the tailnet.

    *Done when* stub tests prove:
    - `--lane maintenance` selects `-updates` and the *follow* origins, and
      never a *hold* one;
    - `notify-owners.sh` files nothing without `--file --approve`;
    - a second run finds the open issue by its marker and comments instead
      of filing a duplicate;
    - the body carries no value that matched a secret pattern.
6d. **An expedited run of one origin, and Tailscale's own auto-update.**
    - **`apply.sh --lane origin:<origin>`** takes one followed origin's
      updates and nothing else, for a security bulletin's out-of-cycle
      window. Proposed mechanism, to be measured first: the lane file adds
      only that origin's pattern, and lists every other pending package in
      `Unattended-Upgrade::Package-Blacklist`. So it uses the same
      `unattended-upgrade` command, and leaves no hold to release. The
      alternatives:
      - holding everything else, which leaves holds behind on an abort;
      - `apt-get install --only-upgrade`, which is another code path;
      - pointing `Dir::Etc::Parts` at an empty directory, which drops the
        host's needrestart hook with the rest.
    - **The probe reports Tailscale's own auto-update** (`tailscale set
      --auto-update`). Under `scheduled`, it's an update channel outside the
      window, and on a node the cohort's bus rides, it's an unscheduled bus
      interruption. Measured first, on a node with tailscaled running.

    *Done when* stub tests prove the one-origin lane takes that origin's
    pending packages alone, and the probe reports auto-update on and off;
    and a live run on noble confirms the mechanism.

    **Done 2026-10-03:** the blacklist mechanism, measured on noble with
    unattended-upgrade 2.9.1: with `site=pkgs.tailscale.com` added and the
    other 7 pending packages skipped, the dry run took `tailscale` alone. The
    list is matched with `re.match`, so each name is anchored and its `.` and
    `+` escaped; apt keeps the backslashes. `apt-get -s` names the origin as
    `Tailscale:pkgs.tailscale.com`, and `apt-cache policy` maps a site to its
    `o=`. `tailscale debug prefs` reads `AutoUpdate.Apply` without root
    (true, false, or null when nothing ever set it on the node; the
    tailnet's setting configures a device only as it joins, and never
    changes an existing one, per Tailscale's KB 1067): true is a
    deviation and null an unknown, under either posture, with exception
    `tailscale:auto-update`.

    **Since its review (CR 160, 168–170, 2026-10-04):**
    - **the lane must take its origin, or fail.** unattended-upgrade passes
      over an upgrade it can't take and still exits 0, so the gate refuses
      a dry run that counted nothing or would leave any of the origin's
      upgrades. The bulk fails before any hold when nothing from the origin
      is pending, and after each step apt must no longer list what the
      step was to take.
    - **the daemon's version is read apart from the CLI's.** Plain
      `tailscale version` never shows a stale tailscaled; `--daemon` does,
      and the probe reports it as `daemon_version`.

6e. **Scope a followed origin to its packages (#344; after step 7, before
    8b).** The processor's NodeSource prototype (2026-09-30) found that a
    followed origin, named by its site, selects every upgradable package
    that site serves: NodeSource also serves `nsolid`. At apt's default
    priority, 500, which ties Ubuntu's, a third-party package with an
    Ubuntu name and a higher version would win. The maintenance lane and the
    one-origin lane both take such a package. Its points 1 and 3 already
    hold: the knob names an origin by its site (6c), and the bulk refreshes
    the host's lists first (6).
    - **`policy.md`:** a *follow* origin is scoped to the packages it was
      added for, by an apt pin. A `Package: *` pin for the site goes below
      500, and each package it was added for goes above.
    - **`probe.sh`:** a finding for a followed origin with no catch-all pin
      below 500, and one for an installed package whose candidate comes
      from a followed origin that no package pin names. Both are read from
      `apt-cache policy`.
    - **NodeSource's class (point 4):** a third-party apt origin, policy
      *follow*, since apt is how it updates. The "repo-owned component"
      class is for what updates outside apt. Proposed 2026-10-04, for the
      owner to confirm.
    - The processor's pins are the measured example: `nodejs` at 600 and
      `nsolid` at 100, and the `site=` dry run took `nodejs` alone.

    *Done when* stub tests prove both findings and their absence under the
    processor's pins, and `policy.md` and `knob.md` say how to scope a
    followed origin.

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
    - Each host commits its `.skills/patching-hosts` knob in this run,
      including its `image-owner` line.
    - A Mayfly channel is optional: the skill carries what the round's
      briefs did.

    *Done when* every exe.dev host has had one run under the skill, and each
    rough-edge issue is closed or deferred with a reason.
9. **Follow-ups, drafted and filed only on your go-ahead per repo:**
   - in this repo, a once-a-day `SessionStart` hook that prints the probe's
     one-line status;
   - in the image repo (step 0b), the cohort base image and the
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
     provisioning gets its own design process** in the image repo, not in
     this plan;
   - **a cohort backup pattern**, in the image repo. Three hosts have no
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
  component came with the image, the fix is the base image (the image repo).
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
    the image repo, private (created 2026-09-29).
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
- **The image repo's bootstrap** runs in its own session. Until
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
