# Tailscale on the exeuntu images

Where a host runs Tailscale, a third-party apt channel on the exeuntu images ([the profile](exe-dev-exeuntu.md#update-channels)), this is how it's taken. The profile's rule holds here: every fact carries its source and date, and a measurement stays true of the run that made it.

**Tailscale**, where a host has it, goes in the maintenance lane: `origin pkgs.tailscale.com follow` in the knob, by its site. Upgrading tailscaled drops the host's tailnet path, so it waits for a planned window, unless a security bulletin expedites it into an out-of-cycle one. Tailscale publishes them at `https://tailscale.com/security-bulletins`, with a feed at `https://tailscale.com/security-bulletins/index.xml` (read 2026-10-02; the latest was TS-2026-011, 2026-08-18). Whoever watches it should open one tracking issue per bulletin in the image owner's repo (the knob's `image-owner`), which fans out to the hosts that run Tailscale. Each host takes the fix in an expedited run, `apply.sh --lane origin:pkgs.tailscale.com`. The run isn't done until `tailscale version --daemon` prints a `Daemon:` line that matches its `Client:` line, or the reprobe's `updates.tailscale.daemon_version` matches its `version`: until tailscaled restarts, the old one is what runs. Plain `tailscale version` reads only the client, and never warns ([run.md](../run.md#3-the-apply-in-held-steps)). Tailscale's own auto-update would skip all of that, so the probe reports it ([policy.md](../policy.md)). **Turn it off for the tailnet, not only on the node, and on the node, not only for the tailnet:** an explicit node setting outlives a tailnet default of off. co-status and co-processor each read `AutoUpdate.Apply` true on the node with the tailnet's switch off (2026-10-21, 2026-10-26), and `tailscale set --auto-update=false` held through the reboot. On co-replicator, `tailscale set --auto-update=false` held through tailscaled's own restart in the `tailscale` step. Then, at the reboot that followed, tailscaled logged `using tailnet default auto-update setting: true` and set `Apply` true again (2026-10-06, CannObserv/replicator#131). Whether the boot or the newer daemon triggered it is unmeasured.

**What the drop costs, measured:** about 2 s. The package's postinst restarts `tailscaled` ([the profile](exe-dev-exeuntu.md#packages-that-restart-their-own-services)), and the tailnet was down from the old daemon's stop to the new one's `Starting -> Running`, as each run read it:
- co-provisioner, 2.0 s (1.102.4 → 1.104.1, 2026-10-17) and 2.2 s (1.104.1 → 1.104.2, 2026-10-22) (#432, the public account of CannObserv/provisioner#60 and CannObserv/provisioner#77, a private repo);
- co-processor, 2.3 s (1.102.4 → 1.104.2, 2026-10-22, CannObserv/processor#65);
- co-status, 2.2 s (1.102.4 → 1.104.2, 2026-10-23, CannObserv/status#56);
- co-index, 2.2 s (1.104.1 → 1.104.2, 2026-10-23, #474);
- usa-wa, 2.4 s (1.104.1 → 1.104.2, 2026-10-26, #487).

**Listeners bound to the tailnet address stay bound,** with no restart: on co-provisioner, two APIs on it kept their PIDs and sockets, and answered at the first probe after (#432). **An established connection may survive the gap or time out:** co-provisioner's Redis client to a peer stayed on the same 4-tuple through the first upgrade, and timed out at a blocking read in the second, then reconnected on a new socket in the same process (#432). So a client of a tailnet service needs a reconnect path, and whether a host's own services ride out the gap is the host's to confirm in its run.

**Scope Tailscale's origin with apt pins**, as every followed origin is ([policy.md](../policy.md#two-lanes)): a `Package: *` pin for its site below 500, and a package pin above 500 for `tailscale` and for `tailscale-archive-keyring`, which apt installed with it. In a file under `/etc/apt/preferences.d/`:

```
Package: *
Pin: origin pkgs.tailscale.com
Pin-Priority: 100

Package: tailscale tailscale-archive-keyring
Pin: origin pkgs.tailscale.com
Pin-Priority: 600
```

Measured on noble with apt 2.8.3 against Tailscale's own repository (2026-10-05). Unpinned, the probe reported `unscoped:pkgs.tailscale.com` and both packages as `unpinned:`. With `tailscale` pinned alone, the keyring was still `unpinned:`. With both pinned, it reported neither, and apt still took a pending `tailscale`.
