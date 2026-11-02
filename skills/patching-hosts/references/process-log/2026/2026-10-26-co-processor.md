## Session 2026-10-26 — co-processor

This host's first run under the scripts (CannObserv/processor#77). It's a **bus worker with no data store**: it consumes one stream from the cohort's Redis bus over the tailnet, runs untrusted-document extraction in a contained child process, and writes results to object storage. A scratch `redis-server` on localhost serves the test suite only.

### Environment

- exe.dev, `exe-dev-exeuntu` (Ubuntu 24.04), generation `newer`, `guestd` layout. The journal is persistent.
- Posture `scheduled`, window Mon 23:00–05:00 UTC. The host keeps off the broker's Monday by convention: the knob couldn't say "not the broker's Monday".
- Third-party apt: NodeSource (agent tooling only, already pinned per #344) and Tailscale.
- The apt timers are masked, from the image. Before this run, apt history had only targeted installs: no upgrade had ever been applied.

### Readings

- **The knob**, committed for this run, declares:
  - one `service`;
  - an `inflight` that counts the extraction child (`pgrep -c -u <user> -f '<module>' || true`; `/proc` has no hidepid);
  - two non-root `health` lines: the unit is active, and nothing at `journalctl -p warning` in 6 minutes. The host's records carry their journald priority since a recent change;
  - both origins followed by site, with Tailscale its own `hold`;
  - `owner <release dir> self`: the release is an extract with no git origin, so the language tree's owner read `unknown` without it;
  - no `datastore`, since the scratch Redis holds test data only (0 keys). It stays the default `redis` held step, because its postinst restarts it;
  - no `quiet`: the host's hourly timer is `OnUnitActiveSec`, so its ticks drift.
- **The first probe had 5 findings:**
  - `needrestart:restart`: the drop-in was installed and proven before any apt run;
  - Tailscale unscoped and unpinned ×3: fixed with a tracked pin file;
  - `tailscale:auto-update`: `AutoUpdate.Apply` was true **on the node**, though the tailnet's switch had been off since 2026-10-14. Set false.
  - The re-probe had none.
- **The maintenance lane counted 85:** at least 60 security, 24 `-updates`, 1 NodeSource. The dry run took 170 s, with max RSS 265 MB and a 168 MB download.
- **The service's interpreter links the system OpenSSL** (`ldd`, then `/proc/<pid>/maps` as root), so the OpenSSL fix needed a restart to reach it.
- **ESM:** 25 esm-apps updates visible; Pro isn't attached. **Language:** one `uv.lock`, 0 advisories.

### The run

- **The bulk:** 534 s (3.1× the dry run), 263 MiB, nothing auto-removed, health 2 of 2. No service restarted, so needrestart's `l` held.
- **Held steps:** `redis` 16 s (the scratch server, Ubuntu's security build) and `docker` 14 s (`containerd` alone; Docker is disabled here, so nothing ran to restart).
- **The reboot:** PID 1 mapped 15 deleted files. needrestart listed dbus, logind, journald, timesyncd, polkit, packagekit, the systemd manager and the service.
- **The chain** ran as written: the service stopped cleanly, `Journal stopped`, boot.
- **The bus gap** was about 20 s, from the service's `stopped` to `consuming`. The liveness monitor's first check-in landed with the start: nothing paged.
- **`--post-boot`:** 12 of 12, 0 findings. The after-probe: 0 pending in every apt class, 0 findings.
- **The run was a non-interactive wrapper** under a transient systemd unit, as the invoking user: bulk, held steps, the §4 decision, then `reboot-chain.sh --approve`, all pre-approved, stopping at any non-zero step. The reboot ends an agent session that runs on the same VM, so the post-boot checks were a second session's.

### What the profile got wrong or lacked

- **The kernel moved at the in-guest reboot:** a newer build of the same series after it than before (`journalctl -k -b -1` against `-b`), with the same image (`image.conf` unchanged). The profile says the kernel is the platform's and never decides a reboot, which held. It doesn't say a reboot can **deliver a newer kernel**, which makes any reboot also a kernel update the host didn't choose.
- **The setup script was never delivered** on this VM: `exe-setup.service` was skipped on its condition at all 5 retained boots, the VM's first included. So "re-delivered at every boot" holds only for a VM created with a script.

### Decisions

- **Deploys don't wait for a window** (owner). policy.md's "a deploy that restarts a declared `service` takes a window" (#366) is declared a deviation in the host's runbook. There's no knob directive for it.
- **The first run was moved forward by the owner,** through a temporary `window` line committed and removed in two PRs: windows repeated weekly, and there was no dated window. One has since shipped (#421).

### Surprises

Filed separately:
- the probe escalated through `sudo -n` without asking (#490);
- Docker read as `in-use` from a comment in `deploy/` (#491);
- SKILL.md and run.md sent a no-datastore host to `recovery-point.sh`, which refuses (#492);
- `lists:stale` fired right after a host `apt-get update` (#493).
