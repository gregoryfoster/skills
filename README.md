# gregoryfoster/skills

A shared library of [Agent Skills](https://agentskills.io) for use across projects.

Skills are folders of instructions, scripts, and references that agents can discover and use to perform better at specific tasks.

## Skills

| Skill | Triggers | Description |
|---|---|---|
| [`reviewing-code`](skills/reviewing-code/) | CR, code review, perform a review | Structured code & documentation review with severity-tiered findings |
| [`reviewing-code-php`](skills/reviewing-code-php/) | CR, code review, perform a review | PHP/WordPress/Bedrock/Sage 11 variant of `reviewing-code` |
| [`reviewing-code-python-fastapi`](skills/reviewing-code-python-fastapi/) | CR, code review, perform a review | Python/FastAPI variant of `reviewing-code` (uv + ruff + pytest + Pydantic v2) |
| [`reviewing-code-python-click`](skills/reviewing-code-python-click/) | CR, code review, perform a review | Python/Click CLI variant of `reviewing-code` (uv + ruff + pytest + Pydantic v2) |
| [`reviewing-architecture`](skills/reviewing-architecture/) | AR, architecture review, architectural review | High-level architectural review across 14 structural dimensions |
| [`enforcing-architecture`](skills/enforcing-architecture/) | add a fitness function, enforce this contract, lock this rule | Graduate an accepted architecture finding into an executable fitness function (import-linter / dependency-cruiser / deptrac / module-size gate / OpenAPI drift guard), add the dev dependency, document it in AGENTS.md, and wire it into the detected check surface as a reviewable diff |
| [`shipping-work`](skills/shipping-work/) | ship it, push GH, close GH, wrap up | Commit, push, comment, and close GitHub issues |
| [`shipping-work-php`](skills/shipping-work-php/) | ship it, push GH, close GH, wrap up | PHP/WordPress/Bedrock/Sage 11 variant of `shipping-work` |
| [`shipping-work-python-fastapi`](skills/shipping-work-python-fastapi/) | ship it, push GH, close GH, wrap up | Python/FastAPI variant of `shipping-work` (uv + ruff + pytest) |
| [`shipping-work-python-click`](skills/shipping-work-python-click/) | ship it, push GH, close GH, wrap up | Python/Click CLI variant of `shipping-work` (uv + ruff + pytest) |
| [`managing-skills`](skills/managing-skills/) | add skill repo, add external skills, manage skills, update vendor skills, install skills hook, enable auto-refresh | Add, update, and remove external skill repos using git submodules + symlinks; optionally install a once-per-day auto-refresh hook |
| [`init-project-fastapi`](skills/init-project-fastapi/) | init project, bootstrap project, new fastapi project, set up foundation | Bootstrap a new FastAPI service with SSH deploy key, pyproject.toml, structured logging, TDD scaffold, vendor skill submodules, and GitHub issue tracking |
| [`vendoring-openapi-client`](skills/vendoring-openapi-client/) | vendor openapi client, vendor api client, generate api client from openapi, refresh vendored client, client drift guard | Vendor a generated Python client for a producer service's OpenAPI: committed spec snapshot + provenance sidecar, optional surface filtering, pinned `openapi-python-client` generation, lint/coverage/diff carve-outs, and tiered drift guards (hermetic CI regen-diff; scheduled or on-VM live-drift) |
| [`init-socraticode`](skills/init-socraticode/) | init socraticode, set up code search, index this project, socraticode setup | Install, configure, and index SocratiCode semantic code search: host preflight (Docker/Node<26/npx), plugin enablement, a project-adapted Code Exploration Policy + prefetch hook, a context-artifacts manifest, and a blocking index verified green (embeddings + graph + artifacts) |
| [`orchestrating-issue-backlog`](skills/orchestrating-issue-backlog/) | orchestrate backlog, prioritize issues, plan issue execution, clear backlog | Prioritize an open issue backlog, analyze conflict zones, design a parallel-safe batch execution plan using git worktrees, and hand off to an agent team |
| [`using-git-worktrees`](skills/using-git-worktrees/) | create worktree, new worktree, destroy worktree, merge worktree, wt | Workflow for parallel branch checkouts via `git worktree`: standardizes creation, lifecycle, port/env separation, and cleanup |
| [`writing-plans`](skills/writing-plans/) | write a plan, plan this, let's plan | Discipline for writing a short, reviewed plan before non-trivial implementation; plans land in a configurable plans directory (default `docs/plans/`) with a prescribed structure |

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

# 3. Install the doctor preflight (self-heals dangling symlinks in fresh
#    worktrees, shallow CI clones, etc.)
bash skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/install-doctor.sh

# 4. Commit
git add .gitmodules skills-vendor/gregoryfoster-skills skills/ .skills/doctor.sh
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
