---
name: managing-skills
description: "Manages external skill repos in a project using the git submodule + symlink pattern: adds skill repos as submodules under skills-vendor/, symlinks individual skills into the project's skills/ directory and .claude/skills/ for Claude Code discovery, handles updates and removal, and can install an optional once-per-day auto-refresh hook. Use when the user says 'add skill repo', 'add external skills', 'manage skills', 'update vendor skills', 'install skills hook', or 'enable auto-refresh'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git CLI.
metadata:
  author: gregoryfoster
  version: "1.3"
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

#### Step 3 — Update the project's AGENTS.md

Add or update the `<available_skills>` block to list the newly available skills. Document which skills are symlinked (global) vs local overrides.

#### Step 4 — Commit

Commit the `.gitmodules` file, the `skills-vendor/` submodule reference, and the new symlinks together:

```bash
git add .gitmodules skills-vendor/<owner>-<repo> skills/ .claude/skills/
git commit -m "feat: add <owner>/<repo> skills submodule"
```

#### Step 5 — Offer to install the auto-refresh hook

After the commit, ask the user:

> Install the once-per-day auto-refresh hook for `skills-vendor/`? Recommended
> for long-lived projects — pulls upstream changes daily on `main` only,
> auto-commits the pointer bump, never blocks a session.

On **yes**, follow the [*Installing the auto-refresh hook*](#installing-the-auto-refresh-hook) procedure below. The hook is **idempotent**: if the symlink already points at the right target and `.claude/settings.json` already contains the command string, skip silently — re-running `/managing-skills` must never double-wire.

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

### Installing the auto-refresh hook

Pulls upstream submodule changes once per calendar day, on `main` only, and auto-commits the pointer bumps. Designed for invocation as a Claude Code `SessionStart` hook — exits `0` on every non-fatal condition so it can never block a session.

**Behaviour:**
- Runs at most once per UTC day (single `.git/skills-update.lock` containing today's UTC date).
- Skips silently on any branch other than `main`.
- Skips silently if the project has no `skills-vendor/` directory.
- Scopes updates to `skills-vendor/` — never touches other submodules a project may have.
- Logs to `.git/skills-update.log` (auto-truncated to the last 200 lines once it crosses 64 KiB).
- Matches diff scope to add scope (`skills-vendor/`), so unrelated dirty work cannot be absorbed and empty commits cannot be created.
- To verify the hook is running, check `.git/skills-update.log` after a session start on `main`.

#### Step 1 — Symlink the hook script

Install via **symlink**, not copy, so upstream fixes to the script propagate via the normal submodule refresh:

```bash
mkdir -p .claude/hooks
ln -s ../../skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/skills-submodule-update.sh \
   .claude/hooks/skills-submodule-update.sh
```

The `../../` prefix resolves from `.claude/hooks/` back to the project root, then into the vendored script path.

#### Step 2 — Merge the hook into `.claude/settings.json`

**Merge, don't overwrite.** If `.claude/settings.json` already has `hooks.SessionStart` entries, append to that array — never clobber the file. The jq expression below is defensive: it creates `.hooks` and `.hooks.SessionStart` if they don't exist, then appends, so it works against an empty `{}`, a partial settings.json without a `hooks` block, and a fully-populated one with other hook entries:

```bash
jq '(.hooks //= {}) | (.hooks.SessionStart //= []) | .hooks.SessionStart += [{
  "matcher": ".*",
  "hooks": [{
    "type": "command",
    "command": "bash .claude/hooks/skills-submodule-update.sh"
  }]
}]' .claude/settings.json > .claude/settings.json.tmp \
  && mv .claude/settings.json.tmp .claude/settings.json
```

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
            "command": "bash .claude/hooks/skills-submodule-update.sh"
          }
        ]
      }
    ]
  }
}
```

#### Step 3 — Idempotency check before committing

Before staging, confirm the hook is not already wired up (re-runs of `/managing-skills` must not double-wire):

- The symlink at `.claude/hooks/skills-submodule-update.sh` resolves to the expected target.
- `.claude/settings.json` contains the string `bash .claude/hooks/skills-submodule-update.sh` exactly once.

If either check shows the hook is already installed, stop — no commit needed.

#### Step 4 — Commit

```bash
git add .claude/hooks/skills-submodule-update.sh .claude/settings.json
git commit -m "chore: enable skills auto-refresh hook"
```

### Uninstalling the auto-refresh hook

```bash
git rm .claude/hooks/skills-submodule-update.sh
```

Then remove the matching `SessionStart` entry from `.claude/settings.json` (preserving any other entries), stage it, and commit:

```bash
git add .claude/settings.json
git commit -m "chore: disable skills auto-refresh hook"
```

You may also want to delete the lock and log files in `.git/` if you don't plan to reinstall:

```bash
rm -f .git/skills-update.lock .git/skills-update.log
```

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

## Notes

- Always use relative symlink paths so they work regardless of where the repo is cloned
- If a symlink is broken (target missing), run `git submodule update --init`
- The `skills-vendor/` directory should be treated as read-only — make changes upstream
- The two-level chain (`.claude/skills/<name>` → `../../skills/<name>` → `../skills-vendor/…`) means any local override created in `skills/` automatically shadows the vendor version in Claude Code too — no changes to `.claude/skills/` needed
