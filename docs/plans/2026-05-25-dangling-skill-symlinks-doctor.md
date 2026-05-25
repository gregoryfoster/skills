---
title: skills-doctor + optional post-checkout hook to fix dangling skill symlinks (GH #46)
date: 2026-05-25
status: draft
---

# skills-doctor + optional post-checkout hook to fix dangling skill symlinks

## Problem

When a project vendors this repo via git submodule + symlink chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/<owner>-<repo>/skills/<name>`), any consumer checkout that hasn't initialized the submodule leaves the entire chain dangling. The canonical `bash scripts/gather-context.sh` pattern documented in every `reviewing-*` / `shipping-*` SKILL.md then fails with a confusing `No such file or directory`, even though the symlinks themselves exist. This bites fresh `git worktree add` checkouts, shallow CI clones without `--recurse-submodules`, and fresh clones generally. Each downstream consumer rediscovers and patches this independently (see [CannObserv/cannabis.observer-wordpress#285](https://github.com/CannObserv/cannabis.observer-wordpress/issues/285)). Filed as [#46](https://github.com/gregoryfoster/skills/issues/46).

## Approach

Ship a single small `skills-doctor.sh` from `managing-skills` and **copy** (not symlink) it into the consumer's `scripts/` directory on `add skill repo`. The doctor walks `skills/*` symlinks; if any dangle and a `.git` dir exists, it runs `git submodule update --init --recursive` and re-checks; if still broken, it prints an actionable error naming the missing skill. Update Phase 1 of every `reviewing-*` and `shipping-*` SKILL.md to prepend `bash scripts/skills-doctor.sh` before the existing gather/pre-ship script. As a separate, optional addition, also ship a `post-checkout`/`post-merge` git hook that auto-inits the `skills-vendor/` submodule — installable from `managing-skills` via the same symlink + settings-merge pattern as the existing auto-refresh hook. Defer the archive-download / non-git case (issue's Approach C) — fundamentally incompatible with the submodule model; revisit if an actual archive consumer asks.

## Tradeoffs / alternatives

- **Per-skill wrapper at the symlink target (issue's Approach A)** — rejected. The wrapper would live inside the symlinked skill directory and have the same bootstrap problem: a broken symlink chain can't reach it any more than it reaches `gather-context.sh`.
- **Bootstrap copy of all scripts (issue's Approach B)** — rejected. Trades dangling symlinks for silent drift; stale copies pass instead of failing loudly, which is the worse failure mode.
- **Distributable per-skill bundle / release asset (issue's Approach C)** — deferred. Correct long-term answer if non-git consumers become real, but big scope (release pipeline, version pinning, harness fetcher). No concrete consumer asking yet.
- **Skip the doctor; rely on `post-checkout` hook alone** — rejected. Git hooks aren't copied into new worktrees, aren't run for `gh pr checkout`, and CI environments often don't execute them. The doctor is the universal safety net; the hook is convenience on top.
- **Symlink the doctor instead of copying** — rejected. The whole point is that symlinks into the vendor don't resolve when the submodule is un-init'd. Drift is mitigated by a version stamp in the script that the doctor itself checks against the vendor copy when reachable.

## Steps

1. **Comment on [#46](https://github.com/gregoryfoster/skills/issues/46)** with the chosen approach and a link to this plan; mark the issue's Approach A recommendation as superseded.
2. **Write `skills/managing-skills/scripts/skills-doctor.sh`** — idempotent, exits 0 silently when healthy. On dangling symlink: if `.git` exists, run `git submodule update --init --recursive` and re-check; if still broken (or no `.git`), print actionable error with the unreachable path and remediation hint. Include a `VERSION="YYYY-MM-DD-N"` constant for drift detection.
3. **Write `skills/managing-skills/scripts/install-doctor.sh`** — copies `skills-doctor.sh` into `<consumer-root>/scripts/skills-doctor.sh`, creating `scripts/` if needed. Idempotent (overwrites if vendor version is newer; reports no-op if identical). Refuses to clobber a non-doctor file at the target path.
4. **Update `skills/managing-skills/SKILL.md`** — insert a "Step 2c — install the doctor script" in the Add procedure (between current Step 2b and Step 3); document re-running `install-doctor.sh` as part of the "Updating a skill repo" procedure; replace the existing single-line tip in Notes ("If a symlink is broken… run `git submodule update --init`") with a pointer to the doctor.
5. **Update Phase 1 of consumer SKILL.md files** (7 files: `reviewing-code`, `reviewing-code-php`, `reviewing-code-python-click`, `reviewing-code-python-fastapi`, `reviewing-architecture`, `shipping-work`, `shipping-work-php`, `shipping-work-python-click`, `shipping-work-python-fastapi` — that's 9 actually; verify count) to prepend `bash scripts/skills-doctor.sh` before the existing gather/pre-ship invocation, with a one-line "ensures vendor symlinks resolve" note.
6. **Manually verify** against a fresh `git worktree add` of a consuming project: confirm the doctor self-heals the un-init'd submodule and that the reviewing-code Phase 1 instructions then succeed end-to-end. Document the verification in the PR description.
7. **(Optional, separable)** Add `skills/managing-skills/scripts/skills-post-checkout-init.sh` and a new "Installing the post-checkout hook" subsection in `managing-skills/SKILL.md` parallel to the auto-refresh hook section. Install via symlink + settings.json merge using the same idempotency pattern (Step 0 skip-if-installed). Can ship as a follow-up PR if step 6 reveals friction.

## Open questions / risks

- **Doctor install location** — proposed `scripts/skills-doctor.sh` at consumer root. Risk: collides with consumer-owned `scripts/` content (most projects already have one). Alternatives: `.skills/doctor.sh`, `.claude/skills-doctor.sh`. Need to pick one before step 3.
- **Backport to existing consumers** — `install-doctor.sh` only runs on new `add skill repo`. Existing consumers (cannabis.observer-wordpress et al.) won't get the doctor unless they explicitly run `bash skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/install-doctor.sh`. Should the auto-refresh hook also opportunistically install/update the doctor? Leans yes, but adds scope to the hook.
- **Drift detection** — the `VERSION` stamp idea only helps when the submodule *is* reachable. If the doctor file is stale and the vendor is unreachable, the user gets the stale error message. Probably acceptable — the failure mode is still "doctor told you to init the submodule," which is the right action.
- **Should the doctor auto-init or just report?** — proposed auto-init (safe, idempotent, fast). Could be made opt-in via `--check-only` flag if any consumer objects to implicit network/disk activity from a "doctor" script.
- **Post-checkout hook portability** — `core.hooksPath` configuration varies; some projects use Husky/Lefthook. The proposed approach uses raw `.git/hooks/` which won't compose with those. May need to detect and warn, or document opt-out.
