---
name: managing-skills
description: "Manages external skill repos in a project using the git submodule + symlink pattern: adds skill repos as submodules under skills-vendor/, symlinks individual skills into the project's skills/ directory and .claude/skills/ for Claude Code discovery, handles updates and removal, and can install an optional once-per-day auto-refresh hook. Use when the user says 'add skill repo', 'add external skills', 'manage skills', 'update vendor skills', 'install skills hook', or 'enable auto-refresh'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git CLI.
metadata:
  author: gregoryfoster
  version: "1.8"
  triggers: add skill repo, add external skills, manage skills, update vendor skills, install skills hook, enable auto-refresh
---

# Managing External Skills

Adds, updates, and removes external skill repos in a project using git submodules and symlinks.

## Pattern overview

- Skill repos are added as **git submodules** at `skills-vendor/<owner>-<repo>/`
- Individual skills are **symlinked** from the submodule into the project's `skills/` directory
- A second symlink from `.claude/skills/<name>` → `../../skills/<name>` wires each skill into Claude Code's native discovery path
- Local overrides (committed directories in `skills/`, not symlinks) always take precedence in **both** discovery systems — no changes to `.claude/skills/` needed when creating an override
- The agentskills.io framework auto-discovers skills by scanning `skills/`; Claude Code discovers them from `.claude/skills/`

## Procedure

### Adding a skill repo

#### Step 1 — Add the submodule

Use the `<owner>-<repo>` naming convention for the vendor path:

```bash
git submodule add https://github.com/<owner>/<repo>.git skills-vendor/<owner>-<repo>
```

Example:
```bash
git submodule add https://github.com/gregoryfoster/skills.git skills-vendor/gregoryfoster-skills
```

#### Step 2 — Symlink desired skills

Create relative symlinks from the project's `skills/` directory to the submodule:

```bash
mkdir -p skills
ln -s ../skills-vendor/<owner>-<repo>/skills/<skill-name> skills/<skill-name>
```

Example:
```bash
ln -s ../skills-vendor/gregoryfoster-skills/skills/reviewing-code skills/reviewing-code
ln -s ../skills-vendor/gregoryfoster-skills/skills/shipping-work skills/shipping-work
```

The `../` prefix is required because the symlink target is resolved relative to the symlink's parent directory (`skills/`), which is one level below the repo root.

#### Step 2b — Wire to Claude Code's skill discovery path

Claude Code discovers project skills from `.claude/skills/`, not from the project root `skills/`. Create a second symlink pointing through `skills/` rather than directly to vendor — this ensures local overrides in `skills/` automatically shadow vendor skills in both discovery systems without duplication:

```bash
mkdir -p .claude/skills
ln -s ../../skills/<skill-name> .claude/skills/<skill-name>
```

Example:
```bash
ln -s ../../skills/reviewing-code .claude/skills/reviewing-code
ln -s ../../skills/shipping-work .claude/skills/shipping-work
```

The `../../` prefix resolves from `.claude/skills/` back to the project root, then into `skills/<name>`.

#### Step 2c — Install the doctor script

Skills referenced via the symlink chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/.../skills/<name>`) are unreachable when the submodule isn't initialized — fresh `git worktree add`, shallow CI clones without `--recurse-submodules`, etc. The doctor is a tiny script copied into the consumer's `.skills/` directory that walks `skills/*` **and `.claude/hooks/*`** symlinks, auto-runs `git submodule update --init --recursive` when any dangle, and prints an actionable error otherwise. Phase 1 of every `reviewing-*` / `shipping-*` skill invokes it as a preflight.

`.claude/hooks/` is in the heal scope because skill installers link hooks there into the same vendor chain ([#99](https://github.com/gregoryfoster/skills/issues/99)). A dangling `skills/<name>` surfaces only when that skill is invoked; a dangling hook symlink surfaces on **every** `Edit|Write|MultiEdit` as exit 127 naming a path `ls` plainly shows exists. One heal path covers both, and any future hook a skill installs. Regular files there — a project's own hook scripts — are not symlinks and are ignored. The same 127 hits a vendor-symlinked `SessionStart` hook for a whole session after a fresh clone or worktree, and no ordering avoids it: Claude Code runs an event's matching hooks in [parallel](https://code.claude.com/docs/en/hooks-guide), so the repair lands next session ([#228](https://github.com/gregoryfoster/skills/issues/228)).

Run the installer from the vendor copy:

```bash
bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-doctor.sh
```

This is idempotent — re-running is a no-op when the destination already matches. The installer refuses to clobber a file at `.skills/doctor.sh` that doesn't look like a doctor, so a user-authored file at that path is never silently overwritten.

**The doctor is a copy, not a symlink** — deliberately. A symlink into `skills-vendor/` would itself dangle in exactly the uninitialized-submodule state the doctor exists to repair. The copy stays reachable there; the price is that upstream fixes don't arrive by submodule bump alone. Three things close that gap, in order of how much they ask of the consumer:

- **The doctor re-syncs itself.** On every mutating run it compares `.skills/doctor.sh` against the vendored `doctor.sh` and re-installs when they differ ([#84](https://github.com/gregoryfoster/skills/issues/84)). Since Phase 1 of every `reviewing-*` / `shipping-*` skill invokes the doctor, this reaches consumers that declined the auto-refresh hook. Content decides, not mtime — git stamps checkout times, so an mtime comparison would misread both a fresh init and a deliberate rollback. The re-sync is best-effort and never changes the doctor's exit code; failures surface only under `--verbose`.
- **The auto-refresh hook re-installs it** on every session, outside the once-per-day lock.
- **A manual `install-doctor.sh`** run, for consumers with neither.

Three consequences worth knowing. A refresh applies from the *next* run — the running instance keeps reading the copy it started from. `--check-only` skips the re-sync entirely, so that mode stays safe for a CI health probe that asserts a clean working tree. And a consumer running a doctor predating this behaviour doesn't self-heal into it: getting the self-syncing doctor takes one pass through the hook or one manual install, after which it is permanent.

#### Step 3 — Update the project's AGENTS.md

Add or update the `<available_skills>` block to list the newly available skills. Document which skills are symlinked (global) vs local overrides.

#### Step 4 — Commit

Commit the `.gitmodules` file, the `skills-vendor/` submodule reference, and the new symlinks together:

```bash
git add .gitmodules skills-vendor/<owner>-<repo> skills/ .claude/skills/ .skills/doctor.sh
git commit -m "feat: add <owner>/<repo> skills submodule"
```

#### Step 5 — Offer to install the auto-refresh hook

After the commit, ask the user:

> Install the once-per-day auto-refresh hook for `skills-vendor/`? Recommended
> for long-lived projects — pulls upstream changes daily on `main` only,
> auto-commits the pointer bump, never blocks a session.

On **yes**, follow the [*Installing the auto-refresh hook*](#installing-the-auto-refresh-hook) procedure below — its **Step 0** ensures re-runs never double-wire.

On **no**, leave the user with a pointer to the same procedure so they can opt in later.

### Updating a skill repo

Pull the latest changes from the upstream skills repo:

```bash
cd skills-vendor/<owner>-<repo>
git pull origin main
cd ../..  # return to project root
git add skills-vendor/<owner>-<repo>
git commit -m "chore: update <owner>-<repo> submodule"
```

Or update all submodules at once:

```bash
git submodule update --init --remote --merge
git add skills-vendor/
git commit -m "chore: update skill submodules"
```

`--init` is not optional. Without it, a submodule missing from `.git/config` — vendored content on disk, nothing registered — is skipped in silence and git still exits `0`, so the run reports success with the pointer unmoved ([#176](https://github.com/gregoryfoster/skills/issues/176)).

No follow-up step is needed to refresh `.skills/doctor.sh` — the doctor re-syncs itself from the vendored source on its next run, and the auto-refresh hook re-installs it on session start. Run the installer explicitly only to collapse the one-run lag when iterating on the doctor itself:

```bash
bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-doctor.sh
```

### Installing the auto-refresh hook

Pulls upstream submodule changes once per calendar day, on `main` only, and auto-commits the pointer bumps. Designed for invocation as a Claude Code `SessionStart` hook — exits `0` on every non-fatal condition so it can never block a session.

**Behaviour:**
- Runs at most once per UTC day (single `.git/skills-update.lock` containing today's UTC date).
- Skips silently on any branch other than `main`.
- Skips silently if the project has no `skills-vendor/` directory.
- Scopes updates to `skills-vendor/` — never touches other submodules a project may have.
- Logs to `.git/skills-update.log` (auto-truncated to the last 200 lines once it crosses 64 KiB).
- Matches diff scope to add scope, so unrelated dirty work cannot be absorbed and empty commits cannot be created. Exactly two paths are ever staged: `skills-vendor/` and, when present, `.skills/doctor.sh` — never `.skills/` wholesale, which would sweep in operator config like `.skills/plans_dir` and `.skills/worktree_root`.
- Commit message names what changed: `chore: update skills submodules`, `chore: refresh .skills/doctor.sh`, or both.
- **Opportunistically installs/updates `.skills/doctor.sh`** on every session (not gated by the once-per-day lock) so the doctor self-heals if accidentally deleted, and so consumers added before the doctor existed pick it up automatically on the next session start.
- **Commits the doctor it installed** ([#86](https://github.com/gregoryfoster/skills/issues/86)). The install is a working-tree repair and runs on every branch; the commit stays behind the `main`-only and once-per-day gates. Without this the hook wrote a file nothing ever tracked — four of twelve audited consumers had been reinstalling an untracked doctor for weeks, so their fresh worktrees and CI clones had none and the Phase 1 preflight silently short-circuited.
- To verify the hook is running, check `.git/skills-update.log` after a session start on `main`. Lines beginning `unexpected hook error` come from the ERR-trap backstop and mark an unanticipated failure path; the hook still exits 0.

**Run the installer. Do not hand-execute the steps below.**

```bash
bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-refresh.sh
```

It is idempotent, repairs a partial install, and never commits. Check state without changing anything with `--check` (exit 0 both artifacts present, 3 otherwise); add `--allow-unresolved` where the vendor content is not checked out, so CI can gate on shape alone ([#227](https://github.com/gregoryfoster/skills/issues/227)). Remove both with `--uninstall`.

**The contract is TWO artifacts, and only the second one makes the hook run:**

1. `.claude/hooks/skills-submodule-update.sh` — a symlink into the vendor
2. a `SessionStart` entry in `.claude/settings.json` — the registration

A repo carrying artifact 1 without artifact 2 looks installed to anyone who lists `.claude/hooks/` and refreshes nothing. Four of twelve audited consumers were in exactly that state — symlink present and tracked, registration absent — pinned at one commit for over a week while the rest of the cohort moved through four skill versions ([#167](https://github.com/gregoryfoster/skills/issues/167)). This procedure was prose and `install-doctor.sh` was a script, which is the only difference between them that predicts the failure population. `.skills/doctor.sh` now warns when it sees that half-installed state.

What the installer does with `.claude/settings.json`, the two load-bearing
details of that merge, and the manual uninstall equivalent:
[references/auto-refresh-hook.md](references/auto-refresh-hook.md).

### Uninstalling the auto-refresh hook

`install-refresh.sh --uninstall` does both halves — the symlink and the
registration. Do it by hand only when debugging the installer:
[references/auto-refresh-hook.md](references/auto-refresh-hook.md).

### Holding one submodule at a commit

Pin a repo to a specific vendored version — an experiment's control arm, a
known-good release pending a breaking change — while its sibling submodules keep
refreshing. Write `.skills/skills-pin`, one `<submodule-path> <commit-ish>` per
line, and commit it. Uninstalling the auto-refresh hook also works but is blunt:
it stops every other submodule's refresh and the `.skills/doctor.sh` self-heal
too. Pin-file grammar, the four behaviours the hook applies to it, and the
`SKILLS_PIN_FILE` escape hatch:
[references/pinning-submodules.md](references/pinning-submodules.md).

### Creating a local override

To override a symlinked skill with project-specific behavior:

1. Remove the symlink: `rm skills/<skill-name>` (this removes only the symlink, not the target)
2. Copy the global skill as a starting point: `cp -r skills-vendor/<owner>-<repo>/skills/<skill-name> skills/<skill-name>`
3. Edit `skills/<skill-name>/SKILL.md` — add `overrides` and `override-reason` to metadata
4. Commit the new directory

The local directory is a **complete replacement**, not a partial override.

### Removing a skill

**Remove a single symlink:**
```bash
rm skills/<skill-name>
git add skills/<skill-name>
git commit -m "chore: remove <skill-name> skill"
```

**Remove an entire skill repo submodule:**
```bash
git submodule deinit skills-vendor/<owner>-<repo>
git rm skills-vendor/<owner>-<repo>
rm -rf .git/modules/skills-vendor/<owner>-<repo>
git commit -m "chore: remove <owner>-<repo> submodule"
```

### Cloning a project that uses skill submodules

After cloning, submodules must be initialized:

```bash
git clone <project-url>
cd <project>
git submodule update --init --recursive
```

Or clone with submodules in one step:
```bash
git clone --recurse-submodules <project-url>
```

## Troubleshooting

### `doctor.sh` reports an SSH/HTTPS auth failure

When the doctor runs `git submodule update --init --recursive` and the underlying clone can't authenticate, it prints a targeted remediation block instead of the generic "submodule update failed" line. A second path — the SSH pre-flight ping — surfaces the same block before submodule init when `.gitmodules` references SSH remotes (`git@<host>:…` or `ssh://git@<host>/…`) and the agent isn't reachable from the shell that invoked the doctor.

The doctor distinguishes two failure modes and prints a different remediation
block for each — a rung-by-rung ladder for auth failures, a smaller
`ssh-keyscan` block for host-key failures. Both ladders, and the
`--no-preflight` escape:
[references/auth-troubleshooting.md](references/auth-troubleshooting.md).

## Notes

- Always use relative symlink paths so they work regardless of where the repo is cloned
- If a symlink is broken (target missing), run `bash .skills/doctor.sh` — it auto-runs `git submodule update --init --recursive` and reports an actionable error if self-healing fails
- `bash .skills/doctor.sh --version` prints the installed copy's stamp — worth including in a bug report, since the installed doctor and the vendored one can differ for one run after a submodule bump
- The `skills-vendor/` directory should be treated as read-only — make changes upstream
- The two-level chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/…`) means any local override created in `skills/` automatically shadows the vendor version in Claude Code too — no changes to `.claude/skills/` needed

**Self-budget:** held to a **6,250-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — a named exception to the repo's
6,000-token standard, set at current size so this file cannot grow. Came down
from 8,750 by demoting four units into `references/`. Growing this file means
demoting again, not raising it.
