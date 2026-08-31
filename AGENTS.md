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
- A write through a temp file must be checked, and a deliberate exception must
  say so with `# unchecked-write-ok: <reason>` — gated by
  `test_checked_temp_writes.py`, explained in [docs/STYLE.md](docs/STYLE.md)
- Pin versions when invoking tools (e.g., `uvx ruff@0.8.0`)
- Must pass `shellcheck --external-sources --source-path=SCRIPTDIR --severity=style`
  (shellcheck's own default floor — no level is exempt). `TestShellcheck` runs it
  over `skills/*/scripts/`, `scripts/` and `.claude/hooks/`, and skips loudly when
  the binary is absent or older than 0.7.0
  ([#140](https://github.com/gregoryfoster/skills/issues/140)).
  `SHELLCHECK_REQUIRED=1` turns either skip into a failure.
- A `# shellcheck disable=SCxxxx` **must** carry a reason comment on the line
  directly above it. `TestShellcheckSuppressionsCarryReasons` enforces the
  pairing, so a suppression stays a documented decision rather than a silencer
  ([#90](https://github.com/gregoryfoster/skills/issues/90)).

These carry a full template and a rationale in
[docs/STYLE.md](docs/STYLE.md), and each is enforced:

- **A repo-creating git command must scrub `GIT_DIR`** — it overrides `git -C`
  and cwd, and git exports it to every hook, so a fixture's throwaway repo
  writes to the real one ([#189](https://github.com/gregoryfoster/skills/issues/189)).
  `extensions.worktreeConfig` was measured and **refused**.
- **`<SKILL_SCRIPTS>` resolution.** Never write `bash scripts/X.sh` in a
  SKILL.md: the agent's cwd is the *project* root
  ([#63](https://github.com/gregoryfoster/skills/issues/63)). `TestNoBareScriptPaths`.
- **Gate-script discipline.** A script whose output drives a ship/skip decision
  must never silently swallow the stderr of the tool producing that output.
  `TestGateScriptHardening` binds every `shipping-work*` / `reviewing-code*`
  script, each classified gate or reporting (#255); `test_pre_ship_env_override.py`
  holds the wrapper-don't-fork override block across all four variants (#105).

## Resolution knobs

Three skills resolve a path through the same three-step lookup — `<NAME>` env var,
then a `.skills/<name>` file, then a built-in default — so a project configures
them with a knob instead of forking the skill: `WORKTREE_ROOT` /
`.skills/worktree_root` and `PLANS_DIR` / `.skills/plans_dir` (each a single-line
path), and `SKILLS_PIN_FILE` / `.skills/skills-pin` (one `<submodule-path>
<commit-ish>` per line). The per-skill defaults, resolver helpers and what each
one retires: [docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## References convention

Skills may carry supplementary `references/*.md` files for content that exceeds the
SKILL.md body cap. They are loaded on demand, not on activation. Two rules are
enforced by the structural suite:

- **Every `references/<name>.md` must be linked from its sibling SKILL.md** —
  orphans fail [tests/structural/test_references.py](tests/structural/test_references.py),
  which lets an *index* keep entries in a subdirectory it links ([#152](https://github.com/gregoryfoster/skills/issues/152)).
- **Relative links resolve from the file that contains them.** Every rendered
  link in any `skills/**/*.md` — SKILL.md and references alike — must point at a
  real path, or [tests/structural/test_relative_links.py](tests/structural/test_relative_links.py)
  fails. Links inside code fences and inline code spans are skipped: they never
  render as links, which is where illustrative paths belonging to a *consuming*
  repo live. An illustrative link in prose needs an `EXEMPT_LINKS` entry naming
  the file, the target and the reason ([#143](https://github.com/gregoryfoster/skills/issues/143)).

Convention, not enforced: **no frontmatter**, **`lowercase-kebab.md`** names, and
no length cap — escaping that body cap is the point of a reference file.

Conditional-block delimiters and the `assets/` equivalents:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Self-budget

Every `SKILL.md` is held to a **6,000-token ratchet** — the figure
`curating-context` enforces on a consuming repo's `AGENTS.md` — by
[tests/structural/test_skill_self_budget.py](tests/structural/test_skill_self_budget.py),
which also holds every `references/*.md` to the 10,000-token per-doc budget,
with nothing exempt — [#152](https://github.com/gregoryfoster/skills/issues/152)
retired the one exemption by splitting the append-only log rather than excusing
it. Most skills meet it; the rest carry a named exception with
its reason beside it, and every file names its own figure in prose so the gate
and the run read the same number. A ratchet only ever comes down.

Two readings bind it, not one: the offline estimate pre-commit sees, and
`count_tokens` under `SKILL_BUDGET_EXACT=1`. Only the estimate is always on,
which let three ratchets be breached past a green suite. How the two are
reconciled, what pre-commit warns about, and the weekly exact gate:
[docs/STYLE.md](docs/STYLE.md).

`AGENTS.md` itself is gated: the `context-budget-gate` pre-commit hook fails any commit that puts it over `.skills/context-budget` (#88).

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
```

Hooks use `.venv/` at the repo root. A worktree has none; link it, never
re-create: `ln -s <main>/.venv .venv`.

Structural tests are the only gate; integration tests are never wired to
pre-push. Run either by hand:

```bash
pytest tests/structural/ -v              # fast, no API key needed
pytest tests/integration/ -v -m integration  # needs .env, billed ≈$0.16
```

**Put a new structural rule in its own `tests/structural/test_<rule>.py`, not at
the end of `test_context_surface.py`.** That file is already ~4,100 lines and is
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
2. Update `name`, rewrite `description:`, declare in `VARIANT_FAMILIES` — [why](docs/CONVENTIONS.md#variant-selection-surface)
3. Tune instructions, scripts, and references for the target stack or agent
4. Validate and commit

## Detail Docs

- [docs/STYLE.md](docs/STYLE.md) — the `<SKILL_SCRIPTS>` resolution template, the gate-script rules and which scripts they bind, why a repo-creating git command must scrub `GIT_DIR`, and why `extensions.worktreeConfig` is refused
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — authoring a project override, the `references/` conditional-block delimiters, and the three `.skills/` resolution knobs
- [docs/SKILLS.md](docs/SKILLS.md) — the submodule + symlink vendoring pattern, `.skills/doctor.sh`, and self-discovery
