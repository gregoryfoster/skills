# `skills/` and `.claude/skills/` symlinks (Phases 10–11)

Literal loops, commands, and the local-override inventory for the `init-project-fastapi` skill's Phases 10 and 11. The invariants these encode — relative paths, `ln -sfn` over bare `ln -s`, `-python-fastapi` variants only, the load-bearing doctor install, and the required override frontmatter — stay in `SKILL.md`.

## Phase 10 — vendor symlinks

**Vendor symlinks:** Symlink every skill from each submodule, except the cross-cutting review/ship workflows where only the `-python-fastapi` stack variant belongs in a FastAPI project. Create from within the repo root — paths must be relative from `skills/`:

```bash
mkdir -p skills
# ln -sfn: later vendor in loop overrides earlier (gregoryfoster overrides obra defaults).
# Bare `ln -s` would recurse into an existing directory-symlink and deposit a dangling
# link inside the obra submodule on name collisions (e.g. using-git-worktrees, writing-plans).
for repo in skills-vendor/obra-superpowers skills-vendor/gregoryfoster-skills; do
  for skill_dir in "$repo"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    # Cross-cutting review/ship workflows ship as stack variants upstream.
    # A FastAPI project wants ONLY the -python-fastapi variant of each; skip
    # the stack-neutral name and any other stack variants. Pattern-based so
    # future stack variants added upstream get filtered automatically.
    case "$skill_name" in
      reviewing-code|reviewing-code-*|shipping-work|shipping-work-*)
        case "$skill_name" in
          reviewing-code-python-fastapi|shipping-work-python-fastapi) ;;
          *) continue ;;
        esac
        ;;
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

## Phase 10 — local overrides

**Local overrides (1):** The cross-cutting review and ship workflows now ship as Python/FastAPI stack variants upstream (`reviewing-code-python-fastapi`, `shipping-work-python-fastapi`). Symlink those alongside the other vendor skills (Phase 10's vendor loop above selects only the `-python-fastapi` variants of these workflows) — no full-copy override needed for either workflow. The variant's `pre-ship.sh` auto-derives its per-SHA stamp prefix from the git toplevel basename, so no project-name substitution is required.

The remaining local override is the project-narrative skill that genuinely varies per-project:

| Override | Files |
|---|---|
| `skills/brainstorming/` | `SKILL.md` |

Substitutions in local overrides:
- Skill headers: `— power-map` → `— <PROJECT_NAME>`
- All other content: verbatim

> **Override frontmatter is required.** Every local override `SKILL.md` (both the row above and any thin overrides below) must declare `overrides: <vendor>/<upstream-skill-name>` and `override-reason: <one-line rationale>` in its frontmatter `metadata` block. The `<vendor>` token matches the submodule directory name under `skills-vendor/` (e.g. `gregoryfoster-skills`, `obra-superpowers`). See AGENTS.md § Required override frontmatter in the upstream `gregoryfoster/skills` repo for the canonical wording.

**Optional thin overrides** (only when the project genuinely needs them):
- `skills/writing-plans/` — fork only if the project ships project-specific narrative content (e.g., `plan-document-reviewer-prompt.md`). The plans directory itself is configurable via `.skills/plans_dir`; do not fork just to repoint it. The forked `SKILL.md` needs `overrides: gregoryfoster-skills/writing-plans` + `override-reason:`.
- `skills/shipping-work-python-fastapi/scripts/pre-ship.sh` — fork only if the project requires `/etc/<project>/.env` loading before tests (e.g., archiver, notifier, watcher). Keep the auto-derived stamp prefix. The forked `SKILL.md` needs `overrides: gregoryfoster-skills/shipping-work-python-fastapi` + `override-reason:` (e.g., `"Adds /etc/<project>/.env loading before pytest"`).
- Step 2.5 worktree-aware merge path — fork the relevant `shipping-work-python-fastapi/SKILL.md` step if the project deploys via a worktree layout that needs a specific `cd /home/.../<project>` step. Same frontmatter requirement.

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
