# `skills/` and `.claude/skills/` symlinks (Phases 10–11)

Literal loops, commands, and where former overrides' content goes, for the `init-project-fastapi` skill's Phases 10 and 11. The invariants these encode — relative paths, `ln -sfn` over bare `ln -s`, `-python-fastapi` review variant and the one `shipping-work`, and the load-bearing doctor install — stay in `SKILL.md`.

## Phase 10 — vendor symlinks

**Vendor symlinks:** Symlink every skill from each submodule, except the review workflow, where only the `-python-fastapi` stack variant belongs in a FastAPI project, and the retired `shipping-work-*` variants, which `shipping-work` replaces ([#537](https://github.com/gregoryfoster/skills/issues/537)). Create from within the repo root — paths must be relative from `skills/`:

```bash
mkdir -p skills
# ln -sfn: later vendor in loop overrides earlier (gregoryfoster overrides obra defaults).
# Bare `ln -s` would recurse into an existing directory-symlink and deposit a dangling
# link inside the obra submodule on name collisions (e.g. using-git-worktrees, writing-plans).
for repo in skills-vendor/obra-superpowers skills-vendor/gregoryfoster-skills; do
  for skill_dir in "$repo"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    # The review workflow ships as stack variants upstream: a FastAPI
    # project wants ONLY the -python-fastapi one, so skip the stack-neutral
    # name and any other stack variant. shipping-work is one skill that
    # detects the stack; its shipping-work-* variants are retired (#537).
    # Pattern-based so future stack variants get filtered automatically.
    case "$skill_name" in
      reviewing-code|reviewing-code-*)
        [ "$skill_name" = reviewing-code-python-fastapi ] || continue
        ;;
      shipping-work-*) continue ;;
    esac
    ln -sfn "../$repo/skills/$skill_name" "skills/$skill_name"
  done
done
```

## Phase 10 — install the symlink doctor

**Install the symlink doctor.** The `reviewing-*` / `shipping-*` skills preflight via `.skills/doctor.sh` (self-heals dangling vendor symlinks); without this step that preflight is a silent no-op ([#65](https://github.com/gregoryfoster/skills/issues/65) found it missing in all four consumer repos):

```bash
bash skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/install-doctor.sh
```

## Phase 10 — no local overrides

**No local override.** The scaffold uses symlinks plus configuration, not overrides: an override stops receiving upstream's changes without saying so (#537 step 9, [#540](https://github.com/gregoryfoster/skills/issues/540)). The vendor loop above already links everything a FastAPI project uses, including obra's `brainstorming`, `writing-plans`, `reviewing-code-python-fastapi` and `shipping-work`, which detects the stack itself.

What each former override carried goes here instead:

| Was | Now |
|---|---|
| `skills/brainstorming/`, a copy of power-map's with its header renamed | obra's `brainstorming`, linked. Its project deltas are in the scaffolded AGENTS.md's **Design & Planning** section (`agents-md-template.md`). Every session loads AGENTS.md (`CLAUDE.md` is `@AGENTS.md`), and obra's skill reads the project before it asks, so it sees them first |
| a thin `writing-plans` fork for project narrative | the same AGENTS.md section. The plans directory is `.skills/plans_dir`; never fork to repoint it |
| a forked `shipping-work/SKILL.md` Step 2.5 for a worktree deploy layout | `.skills/deploy_command` ([#345](https://github.com/gregoryfoster/skills/issues/345)): `shipping-work` offers to run the project's own deploy command, from the primary checkout, after the push |
| `skills/shipping-work/scripts/pre-ship.sh` | never fork it. A project that needs `/etc/<project>/.env` loaded before tests (e.g., archiver, notifier, watcher) commits a project-root `scripts/pre-ship.sh` wrapper that parses the env files and `exec`s the vendored gate; the wrapper recipe is in `skills/shipping-work/scripts/pre-ship.sh`'s header. A wrapper isn't a skill, so it needs no override frontmatter |

If a project later needs an override anyway, the frontmatter rules and the re-sync procedure are `managing-skills`' (its `references/local-overrides.md`).

### Retiring an existing `skills/brainstorming/` override

For a repo this skill scaffolded before #540. #537's step-9 issues point here.

1. **Move the narrative first.** The override's `override-reason:` lists its project deltas. Write each one that still holds into AGENTS.md's **Design & Planning** section, as a project preference: obra's skill lets the human partner's preferences override its defaults. A delta upstream now covers, or one the repo no longer follows, is dropped, and the commit says which.
2. **Replace the directory with the link**, from the repo root. `.claude/skills/brainstorming` already points at `../../skills/brainstorming`, so it follows:

```bash
git rm -r -q skills/brainstorming
mkdir -p skills # git rm removes skills/ if that was its last entry
ln -sfn ../skills-vendor/obra-superpowers/skills/brainstorming skills/brainstorming
git add skills/brainstorming
```

3. **Check.** Drop any `.skills/forked-ok` entry for it, and run `.skills/doctor.sh`: `brainstorming` is a link now, not an override, so its drift findings no longer name it. Commit both changes together, as `#<n> chore: retire the brainstorming override (#540)`.

## Phase 11 — `.claude/skills/` discovery symlinks

Mirror every entry in `skills/` into `.claude/skills/` so Claude Code discovers them. Create from repo root — paths must be relative from `.claude/skills/`:

```bash
mkdir -p .claude/skills
# ln -sfn: same atomic-replace policy as Phase 10 — keeps the loop idempotent on re-runs.
for skill_dir in skills/*/; do
  skill_name=$(basename "$skill_dir")
  ln -sfn "../../skills/$skill_name" ".claude/skills/$skill_name"
done
```
