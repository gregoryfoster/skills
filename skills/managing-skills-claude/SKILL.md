---
name: managing-skills-claude
description: "Manages external skill repos in a project using the git submodule + symlink pattern: adds skill repos as submodules under vendor/, symlinks individual skills into the project's skills/ directory and .claude/skills/ for Claude Code discovery, handles updates and removal. Use when the user says 'add skill repo', 'add external skills', 'manage skills', or 'update vendor skills'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git CLI.
metadata:
  author: gregoryfoster
  version: "1.1"
  triggers: add skill repo, add external skills, manage skills, update vendor skills
---

# Managing External Skills

Adds, updates, and removes external skill repos in a project using git submodules and symlinks.

## Pattern overview

- Skill repos are added as **git submodules** at `vendor/<owner>-<repo>/`
- Individual skills are **symlinked** from the submodule into the project's `skills/` directory
- A second symlink from `.claude/skills/<name>` → `../../skills/<name>` wires each skill into Claude Code's native discovery path
- Local overrides (committed directories in `skills/`, not symlinks) always take precedence in **both** discovery systems — no changes to `.claude/skills/` needed when creating an override
- The agentskills.io framework auto-discovers skills by scanning `skills/`; Claude Code discovers them from `.claude/skills/`

## Procedure

### Adding a skill repo

#### Step 1 — Add the submodule

Use the `<owner>-<repo>` naming convention for the vendor path:

```bash
git submodule add https://github.com/<owner>/<repo>.git vendor/<owner>-<repo>
```

Example:
```bash
git submodule add https://github.com/gregoryfoster/skills.git vendor/gregoryfoster-skills
```

#### Step 2 — Symlink desired skills

Create relative symlinks from the project's `skills/` directory to the submodule:

```bash
mkdir -p skills
ln -s ../vendor/<owner>-<repo>/skills/<skill-name> skills/<skill-name>
```

Example:
```bash
ln -s ../vendor/gregoryfoster-skills/skills/reviewing-code-claude skills/reviewing-code-claude
ln -s ../vendor/gregoryfoster-skills/skills/shipping-work-claude skills/shipping-work-claude
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
ln -s ../../skills/reviewing-code-claude .claude/skills/reviewing-code-claude
ln -s ../../skills/shipping-work-claude .claude/skills/shipping-work-claude
```

The `../../` prefix resolves from `.claude/skills/` back to the project root, then into `skills/<name>`.

#### Step 3 — Update the project's AGENTS.md

Add or update the `<available_skills>` block to list the newly available skills. Document which skills are symlinked (global) vs local overrides.

#### Step 4 — Commit

Commit the `.gitmodules` file, the `vendor/` submodule reference, and the new symlinks together:

```bash
git add .gitmodules vendor/<owner>-<repo> skills/ .claude/skills/
git commit -m "feat: add <owner>/<repo> skills submodule"
```

### Updating a skill repo

Pull the latest changes from the upstream skills repo:

```bash
cd vendor/<owner>-<repo>
git pull origin main
cd ../..  # return to project root
git add vendor/<owner>-<repo>
git commit -m "chore: update <owner>-<repo> submodule"
```

Or update all submodules at once:

```bash
git submodule update --remote --merge
git add vendor/
git commit -m "chore: update skill submodules"
```

### Creating a local override

To override a symlinked skill with project-specific behavior:

1. Remove the symlink: `rm skills/<skill-name>` (this removes only the symlink, not the target)
2. Copy the global skill as a starting point: `cp -r vendor/<owner>-<repo>/skills/<skill-name> skills/<skill-name>`
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
git submodule deinit vendor/<owner>-<repo>
git rm vendor/<owner>-<repo>
rm -rf .git/modules/vendor/<owner>-<repo>
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
- The `vendor/` directory should be treated as read-only — make changes upstream
- The two-level chain (`.claude/skills/<name>` → `../../skills/<name>` → `../vendor/…`) means any local override created in `skills/` automatically shadows the vendor version in Claude Code too — no changes to `.claude/skills/` needed
