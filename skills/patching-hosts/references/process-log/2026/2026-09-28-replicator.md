## Session 2026-09-28 — replicator

Host 7. CannObserv/replicator#122 closed 2026-09-28T17:23Z. It was the first host that is **purely a bus worker**: no database, with its state on the broker and in object storage. Patch only.

### Environment

exe.dev, on the youngest image (19 days). The journal persists, and holds the host's whole 17-day life. PID 1's log target is `console`, so its journal lines are sporadic.

### Readings

- **49 security updates,** applied in 3 min 36 s: the fewest of the round, on the youngest image.
- **`exe-setup.service` ran its script on every boot:** 5 of 5 in-guest reboots, and 1 of 1 platform resize. `/exe.dev/setup` is absent between boots and back before the next one.
- The script's key was inline, single-use, and expired, so it was inert.
- The worker drained on SIGTERM in 0.39–4.36 s, with 0 pending and no duplicates. One start was spent from the restart budget.
- The maintainer scripts restarted polkit and started packagekit. PID 1 re-executed itself during the apply.
- The previous boot, a platform resize, was **unclean**: there was no stop line, and the next boot ran EXT4 orphan recovery.

### What the profile lacked

- **exe-init re-delivers the VM's creation-time setup script at every boot.** So shredding the file never sticks.
- Clean-shutdown evidence here is the service's own stop line, `Journal stopped`, and no orphan recovery at the next boot.
- `who -b` was wrong again.

### Decisions

- **The remedy for a re-delivered script is revoking its key.** That covers every copy, the platform's stored one included. Next best is a key-free, idempotent stored script.
- An absent `/exe.dev/setup` is **not evidence of cleanup.**

### Surprises

It refuted this run's first guess, that only platform-initiated boots re-inject the script. The session's path in also changed across the reboot, and its OOM score stayed -1000.
