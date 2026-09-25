---
title: patching-hosts — a generic OS-patching skill with a reference policy, a read-only probe and learned environment profiles
date: 2026-09-25
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

## Approach

A new generic skill, `skills/patching-hosts/`, built to #313 §2 with these
decisions folded in:

- **Built-in reference policy.** Security-only automatic upgrades, no
  automatic reboot, needrestart set to list restarts rather than perform them.
  This is Ubuntu's stock unattended-upgrades posture plus one needrestart
  setting, so it is a generic default, not a cohort one.
- **Host-config knob, `.skills/patching-hosts`.** Holds only what the owner
  knows: host class, window, runbook services, health checks, and where records
  go. It declares exceptions to the policy, each with a reason and a
  review-by date. One file describes every host a repo deploys to, because
  the cohort already has both shapes: production, staging and dev hosts in one
  repo, and a primary plus throwaway workers in another. Lines outside any
  section apply to all hosts, and a `[host <glob>]` section overrides them for
  the hosts it matches. The class is one of `production`, `staging`, `dev` or
  `ephemeral`. An ephemeral host is patched by rebuilding its image, so it
  gets a report and never an apply.
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
- **A gated `apply.sh`.** Needs an explicit approval flag. It records the
  package versions before applying, applies security updates through
  `unattended-upgrade` with `NEEDRESTART_MODE=l`, then re-probes.
- **One profile, `exe-dev-exeuntu`.** Every fact in it is dated and sourced.
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

0. **Coordinate broker's patch run, before the skill exists.** Work with
   broker's own agent over a Mayfly channel. It follows #313 §2(a) steps 1–7
   by hand in broker's restart window, with the owner's approval given in
   broker's session, and holds `redis-server` to its runbook. It measures what
   steps 3, 5 and 6 need to know on a real host:
   - whether needrestart honours `NEEDRESTART_MODE`;
   - whether `unattended-upgrade` runs with the timers masked;
   - whether the guest can see its image digest;
   - what `reboot-required` says afterwards.

   *Done when* broker has no security updates pending, its health checks are
   green, and the before/after readings are on a CannObserv/broker issue.
   Those readings become the first live process-log entry (step 7).

   **Then repeat step 0 across the cohort, one host at a time, before
   step 1.**
   - **Order:** archiver first, since it is closest to broker and checks
     that broker's facts carry over. Then the hosts that differ most:
     usa-wa (an older image), power-map (Docker containers on the host),
     observo (a primary plus ephemeral workers), and notifier (the cohort's
     alert path; co-index moved to its own repo's run, CannObserv/notifier#90).
     Then replicator, watcher, address-validator and
     wslcb. WordPress comes last, as the second environment (DigitalOcean
     plus Lima). cannobserv and cli have no production host.
   - **Each run** gets a coordinating issue in its own repo, modelled on
     CannObserv/broker#65, plus a Mayfly channel.
   - **Each run ends at the patch plus the needrestart drop-in** (decided
     2026-09-26). No host's update posture changes in the round: the timers
     stay masked and `Periodic::Enable` stays 0. Turning a policy on waits for
     D4 (see Open questions). broker#67 is on hold for it.
   - **The policy, when it comes, must set `APT::Periodic::Enable "1"`** in
     a file sorting after `docker-disable-periodic-update`. The Docker base
     image sets that value to 0, which makes the timers no-ops even when they
     are unmasked (found on CannObserv/archiver#278). It is proven by the
     first real run's log, never by a dry run.
   - **From observo on, each run also records its dormant components** (added
     2026-09-27): every installed engine or daemon, with its workload, its
     listeners, whether the repo references it, and whether it is in the
     security set. The remaining briefs collect these as facts only; pruning
     is not part of the round.

   **Step 1 starts after the round**, so the skill is built from every
   host's readings, not broker's alone.
1. **Scaffold.** Create `skills/patching-hosts/SKILL.md`: frontmatter, the
   7-step core from #313 §2(a), the per-script resolution block for `probe.sh`
   and `apply.sh`, and the self-budget line. Add a row to the README skills
   table. *Done when* `skills-ref validate skills/patching-hosts` and the
   naming and self-budget tests pass.
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

   - The `[host <glob>]` sections, and how a host finds its own. It is
     matched by `--host`, or else by `hostname`. An exact name beats a glob.
     Two globs that match equally are a configuration finding, not a silent
     choice. A file with sections and no match is treated as production,
     report-only.

   *Done when* `test_skills_knob_inventory.py` passes, and a parser test
   covers comments, a malformed line, a past review-by date (an expired
   exception is a finding), and section precedence: global, then glob, then
   exact, plus the tie and the no-match cases.
3. **`probe.sh`, read-only.** Flags: `--help`, `--root DIR` (reads a filesystem
   tree instead of `/`), `--config`, `--host NAME` (the output names the
   section that matched), and `--refresh-into DIR` (refreshes apt
   lists into a scratch directory, never `/var/lib/apt/lists`). Masks are read
   from the filesystem so the probe works offline. It reads the effective
   `APT::Periodic::Enable` through `apt-config`, and reports security updates
   held by an exception separately from those pending. It emits JSON on stdout
   and diagnostics on stderr.

   Its `dormant` section is described in `references/dormant-components.md`.
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
   - an argv log showing no installing, removing or list-writing command was
     run.
4. **The `exe-dev-exeuntu` profile.** Add `references/environments/exe-dev-exeuntu.md`:
   - its detection check;
   - each update channel: apt, the platform kernel, and the agent binaries
     `exeuntu update` manages;
   - known places where config and reality disagree: the masked timers, and
     `claude doctor` reporting its defaults as settings;
   - the documented remedy path;
   - what the platform owns.

   Every fact carries its date and source. Also add a generic apt fallback
   section to `SKILL.md` for hosts no profile matches. *Done when* the links
   and references tests pass.
5. **Validate against the real image, offline.** Run `probe.sh` inside the
   exeuntu image, pinned by digest, in a throwaway container. Confirm the
   detection, the masked readings and the needrestart version. Measure two
   things there: whether the guest can see its own image digest, and whether
   needrestart 3.6 honours `NEEDRESTART_MODE`. Write both answers into the
   profile. *Done when* the profile's detection matches the image.
6. **`apply.sh` and steps 5–7 of the core.**
   - `apply.sh` refuses without `--approve`, refuses on a production-class
     host that names no recovery point, and refuses on an `ephemeral` host
     (the remedy is to rebuild its image).
   - It writes the before-versions (`dpkg-query -W`, `apt-mark showhold`) to a
     record file, then applies security updates only, with
     `NEEDRESTART_MODE=l`.
   - It never reboots, unmasks, enables or removes anything, then re-probes and runs
     the knob's health checks.

   *Done when* stub tests prove each refusal, the recorded before-versions,
   the environment variable, and that no `systemctl unmask`, `enable` or
   `reboot`, and no `apt-get remove` or `purge`, was run.

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
7. **Process log.**
   - `references/process-log.md` as the root, with a 2026 index and "Adding
     an entry" rules copied from the orchestrator's: a vendored copy files an
     issue upstream, and a private consumer's entry names no identifier of its
     own.
   - One new rule: **an entry that lists pending security updates lands only
     after they are applied**, and records counts and families, not versions.
   - Seed three entries: the already-public readings in #313 (broker
     2026-09-21 and archiver 2026-09-22), and step 0's broker patch run,
     written after it is applied.

   *Done when* `test_process_log_entries.py` passes.
8. **Gate.** *Done when* `bash scripts/pre-ship.sh` is green (budgets, ruff,
   shellcheck, the full structural suite) and both scripts' `--help` output
   is accurate.
9. **Follow-ups, drafted and filed only on your go-ahead per repo:**
   - in this repo, a once-a-day `SessionStart` hook that prints the probe's
     one-line status;
   - in the new CannObserv infra repo, once it exists, the cohort base image
     and the Terraform hardening;
   - in each host repo, a census and remediation issue after release, broker
     first. It carries that host's dormant components, each as prune or keep.
   - where a dormant component shipped with the image on every host, the
     prune belongs in the cohort base image, not in a removal on each host.
     That keeps provisioning reproducible. **How a prune is promoted into
     provisioning gets its own design process** in the infra repo, not in
     this plan.

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
  component came with the image, the fix is the base image (infra repo).
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

## Open questions / risks

- **D4: scheduled patching of data stores** (owner decision on
  CannObserv/archiver#278, 2026-09-26; extended to broker's Redis). A
  database or Redis host is patched in a scheduled window, not by automatic
  updates with an exception list. The window means a chosen time, a fresh
  backup shipped off the node, a clean stop, the apply, a start and a
  verify, all recorded. archiver measured the bounce itself as cheap (0.30 s
  of Postgres downtime, and archiver recovered in 1.1 s). What needs
  designing is who schedules the window and who is accountable for it. This
  makes the knob's `window` something the skill acts on, and it needs its own
  plan revision after the round.
- **Step 6b makes v1 larger.** It can ship as a v1.1 if v1 runs long; the
  probe's `dormant` section (step 3) doesn't depend on it.
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
- **Step 0 is a live production change** on a Redis node. It needs broker's
  own session and the owner's approval there; nothing said in the channel
  counts as approval. If the probe shows `redis-server` or `libc6` in the
  set, broker's restart window governs when they go in.
- **Self-budget.** `SKILL.md` is held to 6,000 tokens. The procedure stays
  there; the policy, profile and log detail go in `references/`.
