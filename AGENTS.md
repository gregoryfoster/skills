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

- Skill directories use **gerund form, no suffix**: `reviewing-code`, `shipping-work`, `init-project-fastapi`.
- Names must be lowercase, hyphens only, no consecutive hyphens, max 64 chars (spec requirement).
- In practice all current skills run identically across agent providers, so the bare name is the default.

### When to add a suffix

Two situations warrant a suffix:

- **Agent-specific variant** when a skill genuinely needs to diverge for one provider (e.g. provider-specific tool invocation, prompt-style tuning that materially affects behavior). Allowed suffixes: `-claude`, `-cursor`, `-copilot`, `-gemini`.
- **Stack-specific variant** when a skill diverges along a technology axis (e.g. `reviewing-code-php`, `shipping-work-python-fastapi`). Use the language or framework as the suffix; when a single language hosts multiple genuinely-different workflows (e.g. Python FastAPI vs Python Click), include the framework in the suffix and skip the bare-language variant.

Without a sibling variant, do not add a suffix prophylactically — it adds noise without information.

## Variant strategy

When a skill needs a variant, each variant lives in its own directory:

```
skills/
  reviewing-code/                  # baseline (used when no variant matches)
  reviewing-code-php/              # PHP/WordPress stack variant
  reviewing-code-python-fastapi/   # Python/FastAPI stack variant
  reviewing-code-cursor/           # Cursor-specific agent variant (hypothetical)
  shipping-work/                   # baseline
  shipping-work-php/               # PHP/WordPress stack variant
  shipping-work-python-fastapi/    # Python/FastAPI stack variant
```

Variants share the same trigger phrases (documented in `metadata.triggers`). The runtime selects the appropriate variant. Each variant is a **complete, self-contained skill** — no inheritance between variants.

## Project-level superseding

Projects may define a local `/skills/` directory with the **same skill name**. The local version is a **complete replacement** — not an extension. There is no partial override or inheritance.

Resolution order (most specific wins):
1. Project-level skill (e.g., `my-project/skills/reviewing-code/`)
2. Global skill (this repo, e.g., `gregoryfoster/skills/skills/reviewing-code/`)

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

### Required override frontmatter

Every project-level override **must** declare two fields in its `metadata` block:

- `overrides: <upstream-skill-name>` — the upstream skill being replaced
- `override-reason: <one-line rationale>` — why a full replacement was needed

```yaml
metadata:
  author: gregoryfoster
  version: "1.0"
  overrides: reviewing-code
  override-reason: Adds project-specific commit convention and systemctl restart step
```

These keys make it possible to audit divergence across downstream repos (e.g. "which overrides have drifted from upstream") without inspecting every SKILL.md by hand. Upstream skills in this repo do not carry these keys — they aren't overrides.

### Project-name suffix on the H1

When an override is active, suffix the `SKILL.md` body's top-level heading with the project name so users can tell at a glance which version is loaded:

```markdown
# Code & Documentation Review — Address Validator
```

The suffix is recommended (not required) and applies to the H1 only — not the skill `name` field (which must continue to match the directory name).

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

1. Add this repo as a submodule at `skills-vendor/gregoryfoster-skills/`
2. Symlink individual skills into the project's `skills/` directory using relative paths
3. The agent framework auto-discovers skills by scanning `skills/` — symlinks make them visible

Key rules:
- Submodule path convention: `skills-vendor/<owner>-<repo>/` (e.g., `skills-vendor/gregoryfoster-skills/`)
- Symlink paths must be relative: `../../skills-vendor/gregoryfoster-skills/skills/<skill-name>`
- Local overrides (committed directories in `skills/`) always win over symlinks
- The `skills-vendor/` directory is read-only from the consuming project's perspective

The [`managing-skills`](skills/managing-skills/) skill teaches agents how to perform these operations.

### Self-discovery (`.claude/skills` in this repo)

This repo's own `.claude/skills` is a symlink to `../skills`, so Claude Code auto-discovers the skills under `skills/` when this repo is opened as the working directory. Recreate with:

```bash
ln -sfn ../skills .claude/skills
```

The target must be `../skills` (one `..`), not `../../skills` — the latter resolves back to the repo root because the repo itself is named `skills`, which silently breaks discovery.

## Dev setup

Create a venv, install dependencies, and activate local git hooks (run once after cloning):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
pre-commit install                       # structural tests run on every commit
pre-commit install --hook-type pre-push  # integration tests run on every push
```

Hooks use `.venv/` directly, so the venv must be at the repo root.

Tests run automatically from that point on. To run them manually:

```bash
pytest tests/structural/ -v              # fast, no API key needed
pytest tests/integration/ -v -m integration  # requires ANTHROPIC_API_KEY
```

## Adding a new skill

1. Create `skills/<skill-name>/SKILL.md` with valid frontmatter
2. Add `scripts/` and `references/` as needed
3. Validate: `skills-ref validate skills/<skill-name>`
4. Commit and push
5. Update project AGENTS.md files that reference this repo to include the new skill in their `<available_skills>` block (if applicable)
6. If the skill should be listed in this repo's README.md skills table, add it there too

## Adding a variant

When an agent-specific or stack-specific divergence is needed (see "Variant strategy"):

1. Copy the baseline: `cp -r skills/reviewing-code skills/reviewing-code-<suffix>` (e.g. `-php`, `-python`, `-cursor`)
2. Update the `name` field in `SKILL.md` to match the directory name
3. Tune instructions, scripts, and references for the target stack or agent
4. Validate and commit
