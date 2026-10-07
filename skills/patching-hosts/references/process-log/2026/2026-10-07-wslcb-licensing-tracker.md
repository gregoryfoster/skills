## Session 2026-10-07 — wslcb-licensing-tracker

The second run under the scripts, and this host's first (#313 step 8b; CannObserv/wslcb-licensing-tracker#192). A FastAPI app over Postgres 16, with a Docker-hosted search index. It was also the host's maintenance-lane catch-up.

### Environment

exe.dev, `exe-dev-exeuntu`, generation `feb-2026`, 7 days since the last boot. The journal is volatile (`systemd-journal-flush` masked; 7 days' reach), so the chain copied it. The apt timers are masked, and needrestart is at `restart=l` from a tracked drop-in. The session's path runs through `sshd-session` at -1000 (CannObserv/wslcb-licensing-tracker#182).

### Readings

- **The knob** declares:
  - one service;
  - one restarter: a health-check timer whose service restarts the web unit;
  - one Postgres datastore with two databases;
  - an `inflight` count of the oneshot ingest tasks. knob.md's `--state=active` example missed them, since a running oneshot is `activating` (#359).
- **The restarter scan returned `[]`.** The health-check service is a 0600 root unit file, and the scan reads as the user. The knob's own declaration covered it (#360).
- **The dry run exited 1 on `fwupd`.** The image masks it and deleted its motd conffile, so unattended-upgrade blacklists it at the conffile prompt. The probe said only `exit 1` (#361). The owner holds it (`exception held:fwupd`, review 2026-11-10), and the dry run then exited 0: 90 packages, 161 s.
- **Recovery point:** two `pg_dump -Fc` dumps (33.8 MB in 6 s; 1 s), each passing all three gates at mode 600 and flagged personal. The owner copied them off the node, and the sha256s matched. They were deleted at the stated retention.
- **The bulk took 90 packages in 410 s** against the dry run's 161 s, with max RSS 257 MiB: 14 security, 76 `-updates`, nothing auto-removed. No hold group was pending.
  - Security families: OpenSSL, FreeType, libheif, librsvg, libXpm, sg3-utils, Authen::SASL.
  - `-updates` families: Kerberos, audit, AppArmor, procps, iproute2, nftables, binutils, initramfs-tools, Mesa and Intel media, apport, python-apt, plymouth, open-vm-tools, snapd, runc, Docker buildx and compose, dnsmasq, and others.
- **The reboot was called for:** AppArmor set `reboot-required`, PID 1 mapped 15 deleted libraries, and needrestart listed Postgres, the web app, docker and the systemd manager.
  - The bulk ended at 23:18Z. The chain's 720 s span would have run 25 s past the window's 23:30 close, so the chain refused (#362).
  - It ran the next morning under a one-off window line.
- **The chain:** it stopped the restarter timer, then the web unit, then ran a CHECKPOINT and stopped the cluster, then copied the journal and rebooted.
  - Postgres shut down clean, with no redo, and there was no orphan recovery.
  - The web unit's first start succeeded, ordered `After=` its cluster. One real DB-backed request answered.
  - **Downtime: 14 s,** from the web stop to the first 200.
- **The post-boot probe passed 12 of 14.** The two misses: the session adj (known), and the health-check timer read as "not scheduled" while firing every 5 minutes. It's monotonic, and the check reads only `NextElapseUSecRealtime` (#363).

### What the skill got wrong or lacked

- **knob.md's `inflight` example misses a running oneshot** (#359).
- **The restarter scan reads 0600 unit files as the user,** and reports `[]` as clean, not unknown (#360).
- **A conffile-prompt blacklist surfaces only as `dry-run: exit 1`,** and the class counts include what the dry run skipped (#361).
- **No gate checks that the reboot fits after the bulk.** A late bulk slipped the reboot a day, with PID 1 on deleted libraries meanwhile (#362).
- **The post-boot timer check misreads monotonic timers** (#363).

Each is filed as its own issue, #359 to #363, to be fixed before the next host's run.

### Decisions

- `fwupd` is the owner's hold, with a review date, not something fixed in the run: it does nothing on a VM with no firmware of its own, and is a prune candidate.
- The reboot ran the next morning under a one-off window line, removed after the run.

### Surprises

The bulk ran 2.5× its dry run, the second host in a row at more than twice. That, not the dump or the copy, is what pushed the reboot out of the window.
