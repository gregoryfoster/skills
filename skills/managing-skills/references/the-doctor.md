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

## Silent forks: the shape a symlink scan cannot see

Two vendoring shapes are in cohort use, and from a shell they look identical — `ls skills/` shows the same names either way:

- **A whole-directory symlink.** `skills/<name>` is one tree entry, mode `120000`, pointing at `../skills-vendor/<owner>-<repo>/skills/<name>`. Everything beneath it is upstream by construction; nothing can drift.
- **A directory of per-file symlinks.** `skills/<name>/` is a real directory (`040000`) holding `SKILL.md` and `scripts/`, each entry individually `120000`. A change reaches it file by file — so **any one file committed as `100644`/`100755` silently opts out of every future update**, permanently.

Nothing detected the second case until [#256](https://github.com/gregoryfoster/skills/issues/256): the dangling scans skip regular files by construction, the refresh hook moves a submodule pointer that a forked file never reads, and the drift check ([#238](https://github.com/gregoryfoster/skills/issues/238)) looks only at declared overrides. It cost measurably. One member carried `skills/shipping-work-php/scripts/doc-check.sh` as a regular file among five symlinked siblings, still running the pre-[#252](https://github.com/gregoryfoster/skills/issues/252) matcher — so its own carefully tailored path list had matched nothing since it was written, which is the exact bug #252 fixed. Three others forked `SKILL.md` while symlinking every script beneath it: the scripts update, the instructions describing them do not, and an agent following those instructions misreads the new verdict. All four were found by hand-reading a trees API listing.

The check walks each real `skills/<name>/` against the vendored skill of the same name and reports any path present in both where the consumer's copy is a regular file. Three things are deliberately **not** forks: a whole-directory symlink (it *is* the vendor tree), a file the consumer does not carry (using less of a skill is not diverging from it), and a **declared override** — local by definition, and its staleness is the drift check's business, so reporting every file in one would bury the real finding.

Reported, never healed — a project-local divergence is sometimes the right answer, so the operator decides. Two ways to say so: `pre-ship.sh` is exempt by name (upstream ships a stub for the bare variant, and [docs/STYLE.md](https://github.com/gregoryfoster/skills/blob/main/docs/STYLE.md) blesses a project-supplied wrapper), and anything else goes in `.skills/forked-ok`, one repo-relative path per line, `#`-comments and blank lines ignored. Advisory in every mode including `--check-only`: a fork is sync debt an operator pays down on their schedule, and a probe that failed on it would push consumers toward deleting the local file rather than declaring it. The named remedy is the one from `docs/STYLE.md` — **wrap, don't fork**: a project that needs different behaviour keeps a thin local script that `exec`s the vendored one through the `skills/…` symlink.

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

## Gating on the wiring: `--check-only` vs a per-hook `--check` loop

An unregistered hook is a defect in the repo's **tooling wiring**, not in the
diff under review, so the default invocation warns and exits 0 — flipping that
exit code would hard-block every review in every consumer running the Phase 1
preflight, the same absent-vs-unusable failure
[#140](https://github.com/gregoryfoster/skills/issues/140) removed from the
shellcheck gate. The audience splits rather than the severity
([#231](https://github.com/gregoryfoster/skills/issues/231)):

- `bash .skills/doctor.sh` — warns, exits 0. Review preflights stay advisory.
- `bash .skills/doctor.sh --check-only` — exits 1 for the unregistered-hook
  state, alongside the damage it already gated on (dangling symlinks, unheld
  uninitialized submodules). Already the non-mutating mode — no submodule init,
  no self-re-sync — so it stays safe against a CI job's clean-working-tree
  assertion, which is what makes it the natural home for a probe that is
  *supposed* to fail. Caveat: without `jq` the registration check is skipped
  entirely (a wrong warning in every jq-less consumer would train readers to
  ignore it), so a jq-less runner cannot see wiring gaps.

The finer-grained alternative is `install-hook.sh --check`, which probes ONE
hook's two artifacts and exits 3 when either is missing, duplicated, or in a
repairable form — and reports UNKNOWN rather than guessing when `jq` is absent.
A consumer that wants per-hook gating loops it over its manifests, feeding each
hook the same argument line the doctor would print as its repair:

```bash
rc=0
for m in skills-vendor/*/skills/*/scripts/*.install; do
  [ -f "$m" ] || continue
  args=$(grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$m" | head -n 1)
  # shellcheck disable=SC2086 — the line is a documented argument list
  bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-hook.sh \
    --check --allow-unresolved $args || rc=$?
done
exit "$rc"
```

`--allow-unresolved` is what keeps the loop honest in CI and fresh worktrees,
where a correct install's symlink does not resolve because the vendor content
is not checked out
([#227](https://github.com/gregoryfoster/skills/issues/227)); it relaxes
resolution and nothing else. Use the loop when different hooks warrant
different responses; use `--check-only` when "any wiring gap fails the probe"
is the right granularity.
