## Session 2026-09-29 — address-validator

Host 9. CannObserv/address-validator#235 closed 2026-09-29T12:37Z. It was the first host other services call **synchronously**, and the first with Docker in the production path. Patch only.

### Environment

exe.dev, on a Feb-2026 image about 7.3 months old. exe-init hands off to systemd, and nothing consumes a setup script. The journal was **volatile**, despite `Storage=persistent`.

### Readings

- **236 security updates:** a bulk of 231 (20 m 05 s, 274 MB max RSS), PostgreSQL 16 (3 packages) and Docker (2). A health probe answered 241 of 241.
- **The needrestart proof was read in the source:** `needrestart -m u -b -r l` proves the drop-in loaded and stays list-only. Without `-r`, a file that failed to load would restart everything.
- While Postgres was down, the app **failed open:** callers got the provider's real verdict. So it stayed up through the Postgres step. One 503 came 2 s after ready, from a stale pooled connection, and 0 audit rows were lost.
- `docker.io` again didn't restart dockerd, and `containerd` restarted itself.
- The app's first start after boot **failed** while a dependency warmed up, and `Restart=on-failure` recovered it in 6 s.
- The apply **auto-removed** two packages the upgrade had left unused.
- The reboot ran 7h20m after the apply, outside the window, and nothing failed.

### What the profile lacked

- The 51 days of journal read in round 1 were gone after the reboot: **read where the journal is**, not its setting.
- "Does anything consume a setup script?" is the question, not "is exe-init running?".

### Decisions

- **The callers' notice names the class "the caller's degraded path is permanent",** and asks what the host returns while degraded.
- **A fail-open app needs a recovery check:** a real request, a new row, a cache hit on the repeat, and the fail-open warnings back to flat.
- **"Dependency active" isn't "dependency ready":** the post-boot check reads `NRestarts` and the first start's result.
- **Removals are recorded apart from upgrades.** Recovery points get a stated retention, and a dump with PII is flagged.
- **A reboot outside the window is recorded as such,** with the quiet-hour check re-run before it.

### Surprises

It was the first run to record what's left pending by class: security 0, `-updates` 64, third-party 1 (NodeSource), and 9 outside apt.
