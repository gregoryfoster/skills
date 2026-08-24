# The doctor's design

Why `.skills/doctor.sh` is shaped the way it is. `SKILL.md` Step 2c covers
installing it; this covers the decisions behind it, which matter when you are
changing the doctor or wondering why it did something.

## Why `.claude/hooks/` is in the heal scope

`.claude/hooks/` is in the heal scope because skill installers link hooks there into the same vendor chain ([#99](https://github.com/gregoryfoster/skills/issues/99)). A dangling `skills/<name>` surfaces only when that skill is invoked; a dangling hook symlink surfaces on **every** `Edit|Write|MultiEdit` as exit 127 naming a path `ls` plainly shows exists. One heal path covers both, and any future hook a skill installs. Regular files there — a project's own hook scripts — are not symlinks and are ignored.

The same 127 also hits `SessionStart` hooks for a whole first session, which is
why `SKILL.md` states that cost inline rather than here — a consumer who
installed one hook should not have to reach a reference doc to learn its first
run fails ([#228](https://github.com/gregoryfoster/skills/issues/228)). Stated
once, there; this section is about the heal scope only.

## Why the doctor is a copy, not a symlink

**The doctor is a copy, not a symlink** — deliberately. A symlink into `skills-vendor/` would itself dangle in exactly the uninitialized-submodule state the doctor exists to repair. The copy stays reachable there; the price is that upstream fixes don't arrive by submodule bump alone. Three things close that gap, in order of how much they ask of the consumer:

- **The doctor re-syncs itself.** On every mutating run it compares `.skills/doctor.sh` against the vendored `doctor.sh` and re-installs when they differ ([#84](https://github.com/gregoryfoster/skills/issues/84)). Since Phase 1 of every `reviewing-*` / `shipping-*` skill invokes the doctor, this reaches consumers that declined the auto-refresh hook. Content decides, not mtime — git stamps checkout times, so an mtime comparison would misread both a fresh init and a deliberate rollback. The re-sync is best-effort and never changes the doctor's exit code; failures surface only under `--verbose`.
- **The auto-refresh hook re-installs it** on every session, outside the once-per-day lock.
- **A manual `install-doctor.sh`** run, for consumers with neither.

Three consequences worth knowing. A refresh applies from the *next* run — the running instance keeps reading the copy it started from. `--check-only` skips the re-sync entirely, so that mode stays safe for a CI health probe that asserts a clean working tree. And a consumer running a doctor predating this behaviour doesn't self-heal into it: getting the self-syncing doctor takes one pass through the hook or one manual install, after which it is permanent.

## The `<hook>.install` manifest format

The doctor checks every resolving hook symlink for its `SessionStart` registration and prints a repair line; the arguments in that line come from this file, so a skill adding a hook adds a manifest rather than an edit to `doctor.sh` ([#224](https://github.com/gregoryfoster/skills/issues/224)). The first line that is neither blank nor a comment is the argument list, appended to a resolved `install-hook.sh`, and is bounded to `[A-Za-z0-9._-]` and spaces because an operator is invited to paste it. A hook with no manifest still gets named as a defect — only the exact command is withheld.

The manifest is located from the symlink's own target, so whichever vendor tree
a given link points into is the one whose constants apply. The registration
scope follows from the manifest too: a hook *with* one was installed by
`install-hook.sh`, which writes `SessionStart` and nothing else, so that is the
only event checked; a hook *without* one is checked against every event, because
nothing declares which event it wants.
