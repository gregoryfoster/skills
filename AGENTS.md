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
  reviewing-code-python-click/     # Python/Click CLI stack variant
  reviewing-code-cursor/           # Cursor-specific agent variant (hypothetical)
  shipping-work/                   # baseline
  shipping-work-php/               # PHP/WordPress stack variant
  shipping-work-python-fastapi/    # Python/FastAPI stack variant
  shipping-work-python-click/      # Python/Click CLI stack variant
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

An override **must** declare `overrides: <vendor>/<upstream-skill-name>` and
`override-reason:` in its `metadata` block — the vendor prefix is what
disambiguates which parent is being replaced when two vendored sources ship the
same skill name. Authoring detail, the legacy unqualified form, and the H1 suffix:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

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
- Must pass `shellcheck --external-sources --source-path=SCRIPTDIR --severity=style`
  (shellcheck's own default floor — no level is exempt). `TestShellcheck` runs it
  over `skills/*/scripts/`, `scripts/` and `.claude/hooks/`, and skips loudly when
  the binary is absent or older than 0.7.0 — the release that added
  `--source-path=SCRIPTDIR`, without which an older build rejects the invocation
  outright instead of linting
  ([#140](https://github.com/gregoryfoster/skills/issues/140)).
  `SHELLCHECK_REQUIRED=1` turns either skip into a failure.
- A `# shellcheck disable=SCxxxx` **must** carry a reason comment on the line
  directly above it. `TestShellcheckSuppressionsCarryReasons` enforces the
  pairing, so a suppression stays a documented decision rather than a silencer
  ([#90](https://github.com/gregoryfoster/skills/issues/90)).

Two conventions here carry a full template and a rationale, and live in
[docs/STYLE.md](docs/STYLE.md):

- **`<SKILL_SCRIPTS>` resolution.** Never write `bash scripts/X.sh` in a SKILL.md —
  the agent's cwd is the *project* root, so a bare relative path resolves to a file
  that does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)).
  `TestNoBareScriptPaths` fails the suite if the form reappears.
- **Gate-script discipline.** A script whose output drives a ship/skip decision
  must never silently swallow the stderr of the tool producing that output.
  `TestPreShipGateHardening` enforces it for `shipping-work*/scripts/pre-ship.sh`.

## Worktree root convention

Skills and project-local scripts that operate on `git worktree`s resolve the worktree root via a three-step lookup (see [`using-git-worktrees`](skills/using-git-worktrees/)):

1. `WORKTREE_ROOT` env var (highest priority — one-off overrides)
2. `.skills/worktree_root` file under the repo root (single-line path; the project's persistent default)
3. `<repo-root>/.worktrees/` (fallback)

The helper `bash skills/using-git-worktrees/scripts/resolve-worktree-root.sh` prints the resolved root. Project-local wrapper scripts (e.g., `dev.sh worktree create`) should invoke the upstream `worktree-*.sh` scripts rather than reimplement them, and may pre-populate env files, allocate ports, or run extra bootstrap — but must not bypass the Iron Law gates.

## Plans directory convention

Skills that read or write plan documents resolve the plans directory via the same three-step lookup pattern (see [`writing-plans`](skills/writing-plans/)):

1. `PLANS_DIR` env var (highest priority — one-off overrides)
2. `.skills/plans_dir` file under the repo root (single-line path; the project's persistent default)
3. `<repo-root>/docs/plans/` (fallback)

The helper `bash skills/writing-plans/scripts/resolve-plans-dir.sh` prints the resolved directory. Downstream projects that previously carried a `writing-plans` override solely to repoint the storage path can drop the override and configure `.skills/plans_dir` instead — the upstream skill's resolution order makes the path a knob rather than a fork.

## Submodule pin convention

The auto-refresh hook resolves per-submodule pins via the same three-step lookup (see [`managing-skills`](skills/managing-skills/)):

1. `SKILLS_PIN_FILE` env var (highest priority — one-off overrides)
2. `.skills/skills-pin` file under the repo root (one `<submodule-path> <commit-ish>` per line; `#` comments ignored)
3. no pins — every `skills-vendor/` submodule refreshes (prior behaviour)

A pinned submodule is excluded from both the update and the auto-commit, and each honoured pin is logged by name. Use it to hold one vendored repo at a known-good commit — an experiment control arm, say — while the rest keep refreshing; before this the only remedy was deleting the hook's `SessionStart` entry, which also stopped the sibling refreshes and the `.skills/doctor.sh` self-heal ([#100](https://github.com/gregoryfoster/skills/issues/100)).

## References convention

Skills may carry supplementary `references/*.md` files for content that exceeds the
SKILL.md body cap. They are loaded on demand, not on activation. Two rules are
enforced by the structural suite:

- **No frontmatter**, and **every `references/<name>.md` must be linked from its
  sibling SKILL.md** — orphans fail [tests/structural/test_references.py](tests/structural/test_references.py).
- **Flat directory**, `lowercase-kebab.md`. No length cap: escaping the body
  recommendation is the point of a reference file.

Conditional-block delimiters and the `assets/` equivalents:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Commit conventions

Conventional Commits style:
```
<type>: <description>
```
Common types: `feat`, `fix`, `docs`, `refactor`, `chore`

Example: `feat: add reviewing-architecture-cursor variant`

## How downstream projects consume this repo

Projects vendor this repo as a git submodule at `skills-vendor/<owner>-<repo>/` and
symlink individual skills into their own `skills/` directory with relative paths.
Local overrides (committed directories) always win over symlinks, and
`skills-vendor/` is read-only from the consuming project's side.

The pattern, the `.skills/doctor.sh` install and self-sync rules, and this repo's
own `.claude/skills` self-discovery symlink: [docs/SKILLS.md](docs/SKILLS.md).

The [`managing-skills`](skills/managing-skills/) skill teaches agents how to perform these operations.

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

**Put a new structural rule in its own `tests/structural/test_<rule>.py`, not at
the end of `test_context_surface.py`.** That file is already ~3,600 lines and is
the obvious default home, which is exactly the problem: when several agents work
the backlog in parallel worktrees, appending to one shared file turns every merge
into a conflict, while a new per-rule file merges clean. It also keeps a rule
findable by filename. Extend an existing file only when the new test belongs to
the rule that file already owns.

`ANTHROPIC_API_KEY` lives in the gitignored `.env` at the repo root. Load it with
`set -a && source .env && set +a`; `run-integration-tests.sh` and
`measure-context.sh --exact` find it themselves.

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

## Detail Docs

- [docs/STYLE.md](docs/STYLE.md) — the `<SKILL_SCRIPTS>` resolution template, and the gate-script rules for `pre-ship.sh` / `doc-check.sh`
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — authoring a project override, and the `references/` conditional-block delimiters
- [docs/SKILLS.md](docs/SKILLS.md) — the submodule + symlink vendoring pattern, `.skills/doctor.sh`, and self-discovery
