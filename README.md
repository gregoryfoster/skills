# gregoryfoster/skills

A shared library of [Agent Skills](https://agentskills.io) for use across projects.

Skills are folders of instructions, scripts, and references that agents can discover and use to perform better at specific tasks.

## Skills

| Skill | Triggers | Description |
|---|---|---|
| [`reviewing-code-claude`](skills/reviewing-code-claude/) | CR, code review, perform a review | Structured code & documentation review with severity-tiered findings |
| [`reviewing-architecture-claude`](skills/reviewing-architecture-claude/) | AR, architecture review, architectural review | High-level architectural review across 11 structural dimensions |
| [`shipping-work-claude`](skills/shipping-work-claude/) | ship it, push GH, close GH, wrap up | Commit, push, comment, and close GitHub issues |

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
skills-ref to-prompt skills/reviewing-code-claude skills/reviewing-architecture-claude skills/shipping-work-claude
```

## Project-level overrides

Projects can supersede any skill by placing a directory with the same name under their local `/skills/` folder. The local version is a complete replacement — see [AGENTS.md](AGENTS.md) for details.

## Spec

Follows the [Agent Skills specification](https://agentskills.io/specification). Validated with [`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref).

## License

MIT
