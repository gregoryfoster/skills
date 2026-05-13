# gregoryfoster/skills

A shared library of [Agent Skills](https://agentskills.io) for use across projects.

Skills are folders of instructions, scripts, and references that agents can discover and use to perform better at specific tasks.

## Skills

| Skill | Triggers | Description |
|---|---|---|
| [`reviewing-code`](skills/reviewing-code/) | CR, code review, perform a review | Structured code & documentation review with severity-tiered findings |
| [`reviewing-code-php`](skills/reviewing-code-php/) | CR, code review, perform a review | PHP/WordPress/Bedrock/Sage 11 variant of `reviewing-code` |
| [`reviewing-architecture`](skills/reviewing-architecture/) | AR, architecture review, architectural review | High-level architectural review across 11 structural dimensions |
| [`shipping-work`](skills/shipping-work/) | ship it, push GH, close GH, wrap up | Commit, push, comment, and close GitHub issues |
| [`shipping-work-php`](skills/shipping-work-php/) | ship it, push GH, close GH, wrap up | PHP/WordPress/Bedrock/Sage 11 variant of `shipping-work` |
| [`managing-skills`](skills/managing-skills/) | add skill repo, add external skills, manage skills, update skills submodule | Add, update, and remove external skill repos using git submodules + symlinks |
| [`init-project-fastapi`](skills/init-project-fastapi/) | init project, bootstrap project, new fastapi project, set up foundation | Bootstrap a new FastAPI service with SSH deploy key, pyproject.toml, structured logging, TDD scaffold, vendor skill submodules, and GitHub issue tracking |
| [`orchestrating-issue-backlog`](skills/orchestrating-issue-backlog/) | orchestrate backlog, prioritize issues, plan issue execution, clear backlog | Prioritize an open issue backlog, analyze conflict zones, design a parallel-safe batch execution plan using git worktrees, and hand off to an agent team |

## Structure

```
skills/
  <skill-name>/
    SKILL.md          # Required: frontmatter + instructions
    scripts/          # Executable scripts
    references/       # Supplementary docs (loaded on demand)
```

## Usage

Point your agent at this repo's `skills/` directory. For Claude Code and similar tools, add a `<available_skills>` block to your system prompt or AGENTS.md using the [`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref) CLI:

```bash
skills-ref to-prompt skills/reviewing-code skills/reviewing-architecture skills/shipping-work
```

## Consuming this repo

The recommended pattern for using these skills in your project is **git submodule + symlinks**:

```bash
# 1. Add as a submodule
git submodule add https://github.com/gregoryfoster/skills.git skills-vendor/gregoryfoster-skills

# 2. Symlink the skills you want
#    (relative paths assume skills-vendor/ is at the repo root)
mkdir -p skills
ln -s ../../skills-vendor/gregoryfoster-skills/skills/reviewing-code skills/reviewing-code
ln -s ../../skills-vendor/gregoryfoster-skills/skills/shipping-work skills/shipping-work

# 3. Commit
git add .gitmodules skills-vendor/gregoryfoster-skills skills/
git commit -m "feat: add gregoryfoster/skills submodule"
```

Symlinked skills are auto-discovered by the agent framework. To override a global skill with project-specific behavior, replace the symlink with a committed directory of the same name.

See [`managing-skills`](skills/managing-skills/) for the full procedure.

## Project-level overrides

Projects can supersede any skill by placing a directory with the same name under their local `/skills/` folder. The local version is a complete replacement — see [AGENTS.md](AGENTS.md) for details.

## Spec

Follows the [Agent Skills specification](https://agentskills.io/specification). Validated with [`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref).

## License

MIT
