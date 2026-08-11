---
name: managing-skills
description: "Manages external skill repos in a project using the git submodule + symlink pattern: adds skill repos as submodules under skills-vendor/, symlinks individual skills into the project's skills/ directory and .claude/skills/ for Claude Code discovery, handles updates and removal, and can install an optional once-per-day auto-refresh hook. Use when the user says 'add skill repo', 'add external skills', 'manage skills', 'update vendor skills', 'install skills hook', or 'enable auto-refresh'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git CLI.
metadata:
  author: gregoryfoster
  version: "1.7"
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

`.claude/hooks/` is in the heal scope because skill installers link hooks there into the same vendor chain ([#99](https://github.com/gregoryfoster/skills/issues/99)). A dangling `skills/<name>` surfaces only when that skill is invoked; a dangling hook symlink surfaces on **every** `Edit|Write|MultiEdit` as exit 127 naming a path `ls` plainly shows exists. One heal path covers both, and any future hook a skill installs. Regular files there — a project's own hook scripts — are not symlinks and are ignored.

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
git submodule update --remote --merge
git add skills-vendor/
git commit -m "chore: update skill submodules"
```

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

#### Step 0 — Skip if already installed

Re-runs of `/managing-skills` must never double-wire the hook. Bail out of the procedure if **both** of these are already true:

- The symlink at `.claude/hooks/skills-submodule-update.sh` exists and resolves to the vendored script (`../../skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/skills-submodule-update.sh`).
- `.claude/settings.json` contains the string `.claude/hooks/skills-submodule-update.sh` at least once. Match the script path, not the whole command — an install written before the `$CLAUDE_PROJECT_DIR` form ([#110](https://github.com/gregoryfoster/skills/issues/110)) uses a cwd-relative command and must still be recognised.

Otherwise — fresh install or partial install — continue. Steps 1 and 2 are individually idempotent (`ln -sf` and a jq merge that dedupes the entry first), so they repair partial state without creating duplicates.

#### Step 1 — Symlink the hook script

Install via **symlink**, not copy, so upstream fixes to the script propagate via the normal submodule refresh. Use `-f` so a re-run replaces an existing symlink rather than failing:

```bash
mkdir -p .claude/hooks
ln -sf ../../skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/skills-submodule-update.sh \
   .claude/hooks/skills-submodule-update.sh
```

The `../../` prefix resolves from `.claude/hooks/` back to the project root, then into the vendored script path.

#### Step 2 — Merge the hook into `.claude/settings.json`

**Merge, don't overwrite.** If `.claude/settings.json` already has `hooks.SessionStart` entries, append to that array — never clobber the file. The jq expression below is defensive in two ways: it creates `.hooks` and `.hooks.SessionStart` if they don't exist, and it **strips any pre-existing entry for this hook before appending** so re-runs never produce duplicates. It works against an empty `{}`, a partial settings.json without a `hooks` block, a populated one with other hooks, and one where this hook is already present:

```bash
jq '(.hooks //= {}) |
    (.hooks.SessionStart //= []) |
    .hooks.SessionStart |= map(select(((.hooks // [])[0].command // "") | tostring | contains("skills-submodule-update.sh") | not)) |
    .hooks.SessionStart += [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh\""
      }]
    }]' .claude/settings.json > .claude/settings.json.tmp \
  && mv .claude/settings.json.tmp .claude/settings.json
```

Two details in that expression are load-bearing:

- **The command is anchored on `$CLAUDE_PROJECT_DIR`**, not on the hook process's cwd ([#110](https://github.com/gregoryfoster/skills/issues/110)). Claude Code normally runs hooks from the project dir, so the older `bash .claude/hooks/…` form works today — but it is an undocumented assumption, and a repo whose `settings.json` mixes both styles is what made this visible in review. The `${CLAUDE_PROJECT_DIR:-.}` fallback is the same one `init-socraticode` uses: with the variable unset, a bare `"$CLAUDE_PROJECT_DIR/…"` degrades to `bash "/.claude/hooks/…"` and errors on every session start, where `.` degrades to exactly the old behaviour.
- **The strip matches the script path, not the whole command string.** An equality test against the current command would skip an entry written in the older form — duplicating the hook here, and leaving it unremovable by the uninstall filter below.

If `.claude/settings.json` does not exist yet, create it with `echo '{}' > .claude/settings.json` before running the jq command.

The merged result should look like:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh\""
          }
        ]
      }
    ]
  }
}
```

#### Step 3 — Commit

```bash
git add .claude/hooks/skills-submodule-update.sh .claude/settings.json
git commit -m "chore: enable skills auto-refresh hook"
```

### Uninstalling the auto-refresh hook

Remove the symlink:

```bash
git rm .claude/hooks/skills-submodule-update.sh
```

Strip the matching entry from `.claude/settings.json`, preserving any other `SessionStart` entries. The `if .hooks.SessionStart then ... else . end` guard makes this safe to run against an already-uninstalled file or one that never had a `hooks` block, and the `contains` test — rather than string equality — removes an entry written in either command form, so an install predating [#110](https://github.com/gregoryfoster/skills/issues/110) is still removable:

```bash
jq 'if .hooks.SessionStart then
      .hooks.SessionStart |= map(select(((.hooks // [])[0].command // "") | tostring | contains("skills-submodule-update.sh") | not))
    else . end' \
   .claude/settings.json > .claude/settings.json.tmp \
  && mv .claude/settings.json.tmp .claude/settings.json
```

Stage and commit:

```bash
git add .claude/settings.json
git commit -m "chore: disable skills auto-refresh hook"
```

You may also want to delete the hook's files in `.git/` if you don't plan to reinstall. `skills-status.err` is a transient stderr scratch file the hook removes itself — it only survives a run that died mid-flight:

```bash
rm -f .git/skills-update.lock .git/skills-update.log .git/skills-status.err
```

### Holding one submodule at a commit

Use this when a repo must stay on a specific vendored version — an experiment's
control arm, a known-good release pending a breaking change — while its sibling
submodules keep refreshing. Uninstalling the auto-refresh hook also works, but
it is blunt: it stops every other submodule's refresh and the `.skills/doctor.sh`
self-heal too.

Write `.skills/skills-pin`, one `<submodule-path> <commit-ish>` per line. Blank
lines and `#` comments are ignored:

```
# held for the curating-context cohort experiment (wave A control arm)
skills-vendor/gregoryfoster-skills 3fc7b71
```

Commit it. The file is deliberately committed rather than an env var or a
settings key: a hold has to survive across sessions and machines, and be
greppable and reviewable by whoever inherits it.

What the hook does with it:

- Pinned paths are excluded from the submodule update **and** from the
  auto-commit. Excluding only the update is not enough — staging
  `skills-vendor/` wholesale would commit a pinned submodule whose checkout had
  already drifted, ending the hold the update step just honoured.
- Every honoured pin is logged by name in `.git/skills-update.log`, so a hold
  that outlived its reason is visible rather than silent.
- A pin naming a submodule git has no record of, or a line that is not
  `<path> <commit-ish>`, **refuses the whole refresh for that run** and reports
  to stderr. A typo'd path leaves the intended submodule unpinned, which is the
  exact silent bump the pin was written to stop; moving nothing is the only
  safe response.
- If the recorded gitlink is not the pinned commit — the pin was written after
  the pointer had already moved — the hook reports **drift** and still holds the
  pointer still. It will not rewrite the pointer back; reset it by hand and
  commit.

For a one-off hold without committing a file, point `SKILLS_PIN_FILE` at another
path. Resolution is the usual three steps: `$SKILLS_PIN_FILE`, then
`.skills/skills-pin`, then no pins.

`.skills/doctor.sh` needs no pin awareness, but it does not substitute for one:
its `--init --recursive` restores the *recorded* pointer, so it can never move a
submodule past a pin — and equally can never restore a pointer that was already
committed past one.

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

The doctor distinguishes two failure modes; the remediation differs by mode.

#### For auth failures (`Permission denied (…)` / `Authentication failed for 'https://…'`)

Walk the rungs top-down — most reports trace to one of the first three:

1. **Agent not reachable.** `ssh-add -l` returns "Error connecting to authentication agent" → start the agent and re-add keys. On macOS this usually happens after a reboot or a fresh shell session.
2. **Agent reachable but empty.** `ssh-add --apple-use-keychain ~/.ssh/id_ed25519` once, then add a `Host github.com` block to `~/.ssh/config` with `AddKeysToAgent yes` and `UseKeychain yes` so the key auto-loads on every shell.
3. **Agent works interactively but not from a wrapper script.** A `dev.sh` (or similar) in the call chain is scrubbing `SSH_AUTH_SOCK`. Test from the same shell with `ssh -T git@github.com`: if it works there but the wrapper's subshell fails, the fix lives in the wrapper.
4. **Public submodule, no credentials needed.** The global HTTPS rewrite (`git config --global url."https://github.com/".insteadOf "git@github.com:"`) lets git clone without auth — note it affects every repo on that machine. **In CI, ephemeral containers, or any non-interactive runner**, prefer the runner's native credential mechanism (deploy key, `GITHUB_TOKEN`, app token) over the global rewrite — those are scoped to the run and don't bleed across repos.

#### For host-key failures (`Host key verification failed`)

The pre-flight runs `ssh -T` with `StrictHostKeyChecking=yes` so unknown hosts are rejected loudly instead of silently appended to your `known_hosts`. The doctor prints a separate, smaller block pointing at `ssh-keyscan`:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

Verify the forge's [published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints) against the `ssh-keyscan` output **before** appending — `ssh-keyscan` will happily echo whatever a man-in-the-middle answers.

#### Skipping the pre-flight

Pass `--no-preflight` to skip the SSH ping if the operator already knows the agent state and wants to skip the 3-second `ConnectTimeout` per invocation. The submodule-init classification still runs after a failure either way.

## Notes

- Always use relative symlink paths so they work regardless of where the repo is cloned
- If a symlink is broken (target missing), run `bash .skills/doctor.sh` — it auto-runs `git submodule update --init --recursive` and reports an actionable error if self-healing fails
- `bash .skills/doctor.sh --version` prints the installed copy's stamp — worth including in a bug report, since the installed doctor and the vendored one can differ for one run after a submodule bump
- The `skills-vendor/` directory should be treated as read-only — make changes upstream
- The two-level chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/…`) means any local override created in `skills/` automatically shadows the vendor version in Claude Code too — no changes to `.claude/skills/` needed
