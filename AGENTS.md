# Agent Guidance — gregoryfoster/skills

## What this repo is

A shared library of [Agent Skills](https://agentskills.io) (agentskills.io spec) used across multiple projects.
Skills are generic and project-agnostic. Project-specific overrides live in a `/skills/` directory within each project repo.

## Repository structure

```
skills/
  <skill-name>/          # One directory per skill variant
    SKILL.md             # Required. Frontmatter + instructions.
    scripts/             # Executable scripts (bash, Python, etc.)
    references/          # Supplementary docs loaded on demand
    assets/              # Static resources (templates, schemas, etc.)
```

All active skills live under `skills/`. No other top-level layout is required by the spec.

## Naming conventions

- Skill directories use **gerund form + agent suffix**: `reviewing-code-claude`, `shipping-work-cursor`, etc.
- Agent suffixes: `-claude`, `-cursor`, `-copilot`, `-gemini` (add more as needed)
- When a skill works identically across all agents, omit the suffix and document `compatibility: All agents`
- Names must be lowercase, hyphens only, no consecutive hyphens, max 64 chars (spec requirement)

## Variant strategy (per-agent tuning)

Each skill may have multiple agent-specific variants as separate directories:

```
skills/
  reviewing-code-claude/
  reviewing-code-cursor/
  reviewing-code-gemini/
```

Variants share the same trigger phrases (documented in `metadata.triggers`). The agent's runtime selects the appropriate variant. Each variant is a **complete, self-contained skill** — no inheritance between variants.

## Project-level superseding

Projects may define a local `/skills/` directory with the **same skill name**. The local version is a **complete replacement** — not an extension. There is no partial override or inheritance.

Resolution order (most specific wins):
1. Project-level skill (e.g., `my-project/skills/reviewing-code-claude/`)
2. Global skill (this repo, e.g., `gregoryfoster/skills/skills/reviewing-code-claude/`)

Consequences:
- Global skills must be fully general and project-agnostic
- Project skills must be fully self-contained (they cannot assume the global version exists)
- When creating a project override, copy the global skill as a starting point

### Signal that a project override is needed

A project-level override is appropriate when the global skill would require project-specific knowledge to function correctly, such as:
- Commit message format conventions
- Deployment commands (`systemctl restart`, `fly deploy`, etc.)
- Test runner invocation (`uv run pytest`, `go test ./...`, etc.)
- Project-specific CI/CD steps
- Custom severity criteria for that codebase

Document the override rationale in the project skill's `metadata` block:
```yaml
metadata:
  author: gregoryfoster
  version: "1.0"
  overrides: reviewing-code-claude
  override-reason: Adds project-specific commit convention and systemctl restart step
```

## Spec compliance

Validate skills with `skills-ref validate skills/<name>`.

### Installing `skills-ref`

Use `uv tool install` (recommended — isolated, no `--break-system-packages` needed):

```bash
uv tool install "git+https://github.com/agentskills/agentskills#subdirectory=skills-ref"
```

Or with pip in a venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "git+https://github.com/agentskills/agentskills#subdirectory=skills-ref"
```

### Spec rules

- Required frontmatter: `name`, `description`
- `name` must match the directory name exactly
- `description` max 1024 chars; write in third person; include what and when
- `SKILL.md` body recommended under 500 lines; move detail to `references/`

## Writing effective skills

- **Be concise.** Claude already knows how to use git, read Python, etc. Only add context it doesn't have.
- **Match freedom to fragility.** Exact scripts for dangerous/stateful ops; high-level instructions for judgment calls.
- **Descriptions drive discovery.** The description is how Claude decides which skill to activate from 100+ candidates. Make it specific and include trigger keywords.
- **Progressive disclosure.** `SKILL.md` is the overview. `references/` files are loaded only when needed. `scripts/` are executed, not loaded into context.
- **Test across models.** Skills tuned for Opus may need more detail for Haiku.

## Scripts

- All scripts must be self-contained or document dependencies clearly
- Support `--help` with usage + flag descriptions
- No interactive prompts — agents run in non-interactive shells
- Use structured output (JSON, TSV) on stdout; diagnostics to stderr
- Use `set -euo pipefail` in bash scripts
- Pin versions when invoking tools (e.g., `uvx ruff@0.8.0`)

## Commit conventions

Conventional Commits style:
```
<type>: <description>
```
Common types: `feat`, `fix`, `docs`, `refactor`, `chore`

Example: `feat: add reviewing-architecture-cursor variant`

## How downstream projects consume this repo

Projects use the **git submodule + symlink** pattern:

1. Add this repo as a submodule at `vendor/gregoryfoster-skills/`
2. Symlink individual skills into the project's `skills/` directory using relative paths
3. The agent framework auto-discovers skills by scanning `skills/` — symlinks make them visible

Key rules:
- Submodule path convention: `vendor/<owner>-<repo>/` (e.g., `vendor/gregoryfoster-skills/`)
- Symlink paths must be relative: `../../vendor/gregoryfoster-skills/skills/<skill-name>`
- Local overrides (committed directories in `skills/`) always win over symlinks
- The `vendor/` directory is read-only from the consuming project's perspective

The [`managing-skills-claude`](skills/managing-skills-claude/) skill teaches agents how to perform these operations.

## Adding a new skill

1. Create `skills/<skill-name>/SKILL.md` with valid frontmatter
2. Add `scripts/` and `references/` as needed
3. Validate: `skills-ref validate skills/<skill-name>`
4. Commit and push
5. Update project AGENTS.md files that reference this repo to include the new skill in their `<available_skills>` block (if applicable)
6. If the skill should be listed in this repo's README.md skills table, add it there too

## Adding a new agent variant

1. Copy an existing variant: `cp -r skills/reviewing-code-claude skills/reviewing-code-<agent>`
2. Update the `name` field in `SKILL.md` to match the directory name
3. Tune instructions, scripts, and references for the target agent
4. Validate and commit
