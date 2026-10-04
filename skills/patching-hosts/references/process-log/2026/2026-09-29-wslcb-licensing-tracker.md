## Session 2026-09-29 — wslcb-licensing-tracker

Host 10, the last of the round. CannObserv/wslcb-licensing-tracker#184 closed 2026-09-29T19:26Z. It was the first host whose window was set by its **own scheduled ingest**, and the first with an **in-host automatic restarter**. Patch only.

### Environment

exe.dev, on a Feb-2026 image (7.7 months old). Its lists hadn't been refreshed since March. The journal is volatile, the third Feb-2026 host with that.

### Readings

- **257 security updates:** a bulk of 250 plus 2 auto-removed (21:33, 266 MiB), PostgreSQL 16 (17.8 s), and Docker (30.3 s). The dry run took 8:52.
- A health timer restarts the web app on any non-200. With it stopped for the Postgres step, the outage was 1.46 s, with two 503s, both inside it.
- The web unit had only `After=network.target`: its first start after boot succeeded **by luck.** It was fixed in-run with `After=postgresql.service`. A review dropped the `Wants=`, which would have started a cluster an operator had stopped on purpose. A second reboot proved the order.
- The reboot chain ran as a detached 0700 root script. **Its transient timer fired 41 s late** under the default `AccuracySec=1min`, and on time with `1s`.
- `pro security-status`: 546 universe packages, and **29 esm-apps security updates pending**, which `noble-security` doesn't cover.
- `/tmp` was emptied at boot, so a staged binary was copied to `/var/tmp`.

### What the profile lacked

- On a volatile journal, shutdown evidence is **a journal copy taken last in the chain**, read back with `journalctl -D`.
- The maintainer-script table gained journald and timesyncd. dockerd stayed put on 4 of 4 hosts, and containerd restarted itself on 3 of 4.

### Decisions

- **Find every in-host automatic restarter, stop it for a data-store restart, and prove it's running again.**
- **Poll health every second through a data-store step,** logging each code with its time.
- **The post-boot check asks whether the order is configured,** reading `critical-chain` and `After=`, not just whether the first start worked.
- **ESM is a class of its own,** next to security, `-updates`, third-party and outside apt.
- **`Persistent=` catches up a missed run, not a killed one,** so the in-flight gate runs inside the chain.

### Surprises

Round 1 quoted earlyoom's arguments from the first journal block, from before the daemon was restarted. **Read `/proc/<pid>/cmdline`.**
