---
title: skills-doctor + optional post-checkout hook to fix dangling skill symlinks (GH #46)
date: 2026-05-25
status: draft
---

# skills-doctor + optional post-checkout hook to fix dangling skill symlinks

## Problem

When a project vendors this repo via git submodule + symlink chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/<owner>-<repo>/skills/<name>`), any consumer checkout that hasn't initialized the submodule leaves the entire chain dangling. The canonical `bash scripts/gather-context.sh` pattern documented in every `reviewing-*` / `shipping-*` SKILL.md then fails with a confusing `No such file or directory`, even though the symlinks themselves exist. This bites fresh `git worktree add` checkouts, shallow CI clones without `--recurse-submodules`, and fresh clones generally. Each downstream consumer rediscovers and patches this independently (see [CannObserv/cannabis.observer-wordpress#285](https://github.com/CannObserv/cannabis.observer-wordpress/issues/285)). Filed as [#46](https://github.com/gregoryfoster/skills/issues/46).

## Approach

Ship a single small `doctor.sh` from `managing-skills` and **copy** (not symlink) it into the consumer's `.skills/` directory on `add skill repo`. The doctor walks `skills/*` symlinks; if any dangle and a `.git` dir exists, it runs `git submodule update --init --recursive` and re-checks; if still broken, it prints an actionable error naming the missing skill. Update Phase 1 of every `reviewing-*` and `shipping-*` SKILL.md to prepend `bash .skills/doctor.sh` before the existing gather/pre-ship script. Also extend the existing auto-refresh hook to opportunistically install/update the doctor on every run, so existing consumers (cannabis.observer-wordpress et al.) pick it up without a manual command. As a separate, optional addition, ship a `post-checkout`/`post-merge` git hook that auto-inits the `skills-vendor/` submodule — installable from `managing-skills` via the same symlink + settings-merge pattern as the existing auto-refresh hook. Defer the archive-download / non-git case (issue's Approach C) — fundamentally incompatible with the submodule model; revisit if an actual archive consumer asks.

## Tradeoffs / alternatives

- **Per-skill wrapper at the symlink target (issue's Approach A)** — rejected. The wrapper would live inside the symlinked skill directory and have the same bootstrap problem: a broken symlink chain can't reach it any more than it reaches `gather-context.sh`.
- **Bootstrap copy of all scripts (issue's Approach B)** — rejected. Trades dangling symlinks for silent drift; stale copies pass instead of failing loudly, which is the worse failure mode.
- **Distributable per-skill bundle / release asset (issue's Approach C)** — deferred. Correct long-term answer if non-git consumers become real, but big scope (release pipeline, version pinning, harness fetcher). No concrete consumer asking yet.
- **Skip the doctor; rely on `post-checkout` hook alone** — rejected. Git hooks aren't copied into new worktrees, aren't run for `gh pr checkout`, and CI environments often don't execute them. The doctor is the universal safety net; the hook is convenience on top.
- **Symlink the doctor instead of copying** — rejected. The whole point is that symlinks into the vendor don't resolve when the submodule is un-init'd. Drift is mitigated by a version stamp in the script that the doctor itself checks against the vendor copy when reachable.

## Steps

1. **Comment on [#46](https://github.com/gregoryfoster/skills/issues/46)** with the chosen approach and a link to this plan; mark the issue's Approach A recommendation as superseded.
2. **Write `skills/managing-skills/scripts/doctor.sh`** — idempotent, exits 0 silently when healthy. On dangling symlink: if `.git` exists, run `git submodule update --init --recursive` and re-check; if still broken (or no `.git`), print actionable error with the unreachable path and remediation hint. Include a `VERSION="YYYY-MM-DD-N"` constant for drift detection.
3. **Write `skills/managing-skills/scripts/install-doctor.sh`** — copies `doctor.sh` into `<consumer-root>/.skills/doctor.sh`, creating `.skills/` if needed. Idempotent (overwrites if vendor version is newer; reports no-op if identical). Refuses to clobber a non-doctor file at the target path. Used by both the `add skill repo` procedure (one-time) and the auto-refresh hook (every run).
4. **Extend `skills/managing-skills/scripts/skills-submodule-update.sh`** — after the existing submodule pointer-bump logic, opportunistically invoke `install-doctor.sh` from the vendor copy. Silent on no-op; logs to existing `.git/skills-update.log` when it actually writes/updates. Never blocks the hook (existing exit-0-on-error semantics preserved). This is the backport path for existing consumers.
5. **Update `skills/managing-skills/SKILL.md`** — insert "Step 2c — install the doctor script" in the Add procedure (between current Step 2b and Step 3); add a "Doctor script" note in the auto-refresh hook section documenting the opportunistic install; document re-running `install-doctor.sh` as part of "Updating a skill repo"; replace the existing single-line tip in Notes ("If a symlink is broken… run `git submodule update --init`") with a pointer to the doctor.
6. **Update Phase 1 of consumer SKILL.md files** to prepend `bash .skills/doctor.sh` before the existing gather/pre-ship invocation, with a one-line "ensures vendor symlinks resolve" note. Verify exact file count (`reviewing-code`, `reviewing-code-php`, `reviewing-code-python-click`, `reviewing-code-python-fastapi`, `reviewing-architecture`, `shipping-work`, `shipping-work-php`, `shipping-work-python-click`, `shipping-work-python-fastapi` = 9 files) by grepping for the current invocation pattern.
7. **Manually verify** against a fresh `git worktree add` of a consuming project: confirm the doctor self-heals the un-init'd submodule and that the reviewing-code Phase 1 instructions then succeed end-to-end. Document the verification in the PR description.
8. **(Optional, separable)** Add `skills/managing-skills/scripts/skills-post-checkout-init.sh` and a new "Installing the post-checkout hook" subsection in `managing-skills/SKILL.md` parallel to the auto-refresh hook section. Install via symlink + settings.json merge using the same idempotency pattern (Step 0 skip-if-installed). Can ship as a follow-up PR if step 7 reveals friction.

## Open questions / risks

- **Doctor install location** — resolved: `.skills/doctor.sh` (coexists with `.skills/plans_dir` from `writing-plans`; `.skills/` becomes the standard tool-config dir).
- **Backport to existing consumers** — resolved: the auto-refresh hook opportunistically installs/updates the doctor on every run (step 4). Existing consumers pick it up automatically the next time the hook fires on `main`.
- **Drift detection** — the `VERSION` stamp only helps when the submodule is reachable. If the doctor file is stale and the vendor is unreachable, the user gets the stale error message. Acceptable — the failure mode is still "doctor told you to init the submodule," which is the right action.
- **Should the doctor auto-init or just report?** — proposed auto-init (safe, idempotent, fast). Could be made opt-in via `--check-only` flag if any consumer objects to implicit network/disk activity from a "doctor" script.
- **Post-checkout hook portability** — `core.hooksPath` configuration varies; some projects use Husky/Lefthook. The proposed approach uses raw `.git/hooks/` which won't compose with those. May need to detect and warn, or document opt-out. (Only relevant to optional step 8.)
