# 2026 — run index

One row per run; each links its entry file in this directory. The root of the log, and the layout rules, are in [`process-log.md`](../../process-log.md).

| Date | Host | Headline |
|---|---|---|
| [2026-09-21](2026-09-21-broker.md) | broker (reading) | No security update since provisioning: the image masks the apt timers while `20auto-upgrades` says `"1"`. No guest kernel. The finding that opened #313 |
| [2026-09-22](2026-09-22-archiver.md) | archiver (reading) | `claude doctor`'s `enabled` is the default with every key absent: an absent setting is not a reading. The platform's health tool prescribes what the profile forbids |
| [2026-09-26](2026-09-26-broker.md) | broker | 97 applied. The needrestart drop-in only lists; only the list taken after the whole run counts; reboot in-guest, never through the platform; health checks come from the host |
| [2026-09-26](2026-09-26-archiver.md) | archiver | 61 applied; a Postgres restart costs 0.30 s. D4: a database is patched on a schedule, not by an exception list. Accept either journal ending as shutdown evidence |
| [2026-09-26](2026-09-26-usa-wa.md) | usa-wa | 185, counted from the dry run's selection (the grep said 178). An older image, detected. A data store held for the bulk, then upgraded alone |
| [2026-09-27](2026-09-27-power-map.md) | power-map | 232, with a major Docker bump from the security pocket, held. `docker.io` doesn't restart dockerd. Volatile journal. Reboot from the post-run list, never a kernel |
| [2026-09-28](2026-09-28-notifier.md) | notifier | 111 on the alert path. `Persistent=` is OnCalendar-only; a pause covers the apply; a piped dump hides its failure; per-monitor downtime budgets. Session OOM score follows the path in |
| [2026-09-28](2026-09-28-host-6.md) | host 6 (private) | 222. Per-package self-restart table. Rebuilding isn't patching; warm members in the quiesce. Verdict from rc, final line and `dpkg --audit` |
| [2026-09-28](2026-09-28-replicator.md) | replicator | 49 on the youngest image. exe-init re-delivers the creation-time setup script at every boot: revoke the key. A bus worker's drain takes 0–5 s |
| [2026-09-29](2026-09-29-watcher.md) | watcher | 50. Prefer the host's own backup regime. A data store restarts when it maps a patched library. Nothing in flight, inside the chain. A prune must cover groups |
| [2026-09-29](2026-09-29-address-validator.md) | address-validator | 236. The needrestart proof read in source. A fail-open app needs a recovery check. Read where the journal is. Auto-removals; first pending-by-class record |
| [2026-09-29](2026-09-29-wslcb-licensing-tracker.md) | wslcb-licensing-tracker | 257. Stop in-host restarters for a data-store restart. A first start by luck, then ordered. Detached chain with `AccuracySec=1s`. ESM is its own class |
