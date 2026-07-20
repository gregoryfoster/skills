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

### Signal that a project override is needed

A project-level override is appropriate when the global skill would require project-specific knowledge to function correctly, such as:
- Commit message format conventions
- Deployment commands (`systemctl restart`, `fly deploy`, etc.)
- Test runner invocation (`uv run pytest`, `go test ./...`, etc.)
- Project-specific CI/CD steps
- Custom severity criteria for that codebase

### Required override frontmatter

Every project-level override **must** declare two fields in its `metadata` block:

- `overrides: <vendor>/<upstream-skill-name>` — the upstream skill being replaced, qualified by the vendor it comes from
- `override-reason: <one-line rationale>` — why a full replacement was needed

```yaml
metadata:
  author: gregoryfoster
  version: "1.0"
  overrides: gregoryfoster-skills/reviewing-code
  override-reason: Adds project-specific commit convention and systemctl restart step
```

The `<vendor>` token matches the submodule directory name under `skills-vendor/` (e.g. `gregoryfoster-skills`, `obra-superpowers`). This is the same `<owner>-<repo>` convention documented in [`managing-skills`](skills/managing-skills/). When the same upstream skill name exists in two vendored sources (e.g. both `gregoryfoster-skills/writing-plans` and `obra-superpowers/writing-plans`), the vendor prefix is the only thing that disambiguates which parent the override is replacing — a reader (or audit tool) should never have to consult git history to figure that out.

If the same upstream repo is vendored from two forks, the submodule directory name still disambiguates (e.g. `gregoryfoster-skills` vs `someone-else-skills`); the vendor token is whatever the project actually checked out, not the canonical upstream.

These keys make it possible to audit divergence across downstream repos (e.g. "which overrides have drifted from upstream") without inspecting every SKILL.md by hand. Upstream skills in this repo do not carry these keys — they aren't overrides.

#### Legacy unqualified form

The earlier convention allowed bare `overrides: <skill-name>` without a vendor prefix. That form is **tolerated for existing downstream files** but should be migrated to the qualified form during the next routine touch (e.g., as part of a downstream sweep). New overrides must use the qualified form. Bare entries are ambiguous as soon as a second vendor ships a skill of the same name, so the tolerance window closes once the audited downstreams have been updated.

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

### Invoking a skill's own scripts (`<SKILL_SCRIPTS>`)

**Never write `bash scripts/X.sh` in a SKILL.md.** The agent's cwd is the *project* root, but `scripts/` ships inside the skill directory, so a bare relative path resolves to a file that doesn't exist — the invocation fails with "No such file or directory" in every project that doesn't happen to carry its own `scripts/` copy ([#63](https://github.com/gregoryfoster/skills/issues/63)). [tests/structural/test_content_invariants.py](tests/structural/test_content_invariants.py) (`TestNoBareScriptPaths`) fails the suite if the form reappears.

Instead, resolve once and substitute. Each skill's SKILL.md carries one resolution block — for `reviewing-*` / `shipping-*` this is folded into the Phase 1 / Step 1 doctor preflight; other skills get a standalone "Script path resolution" section. The header, loop, probe, and `done` are common to all 11 skills; the doctor preflight and the final two lines are conditional, as annotated:

```bash
N=<skill-name> S=<sentinel-script>.sh SD=

# reviewing-* / shipping-* only — resolution follows the doctor so a freshly
# healed symlink chain is visible to the probe.
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1

for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done

# Only when later steps substitute <SKILL_SCRIPTS> — shipping-*,
# using-git-worktrees, writing-plans. Omit for reviewing-*, which has a
# single call site and no later steps to feed.
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"

# Only when this block also runs the script — reviewing-*, shipping-*. Omit
# for using-git-worktrees and writing-plans, which publish the path but
# invoke their scripts from later steps.
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

Notes on the shape:

- **Probe for the sentinel file, not the directory.** `[ -d "$d" ]` would falsely match any project that has an unrelated root `scripts/` — this repo does.
- **Clear `SD` on the header line.** Without it, a value inherited from the environment — or left by an earlier block in the same shell — survives the loop and defeats `${SD:?…}`, silently reproducing the #63 "No such file or directory" symptom against a misleading path.
- **Guard at the call site, not just once.** Every expansion that feeds a path uses the full `${SD:?…}` form, so no invocation depends on an earlier line having aborted first.
- **Project-local `scripts/` wins.** Preserves consumers that already worked around #63 with their own copy.
- **`$HOME/.claude/skills/…` last** covers user-level and plugin installs.
- **Resolution must run *after* `.skills/doctor.sh`,** so a freshly healed vendor symlink chain is visible to the probe.
- **`<SKILL_SCRIPTS>` is a placeholder, not a shell variable** — same convention as `init-project-fastapi` Phase 0's `<SKILL_DIR>`. Each Bash tool call is a fresh shell, so nothing is inherited between steps; later steps substitute the literal path printed above and are written `bash "<SKILL_SCRIPTS>/X.sh"`.

`TestScriptResolutionBlock` in [tests/structural/test_content_invariants.py](tests/structural/test_content_invariants.py) enforces the four common lines across every skill carrying a block, and fails the suite if a skill uses `<SKILL_SCRIPTS>` without publishing it.

### Gate-script discipline (pre-ship, doc-check)

Scripts whose output drives a control-flow decision (will-we-ship vs. will-we-skip) must never silently swallow stderr from the tool that produces that output. The two-bucket rule:

- **Gate-like commands** — output drives a `for` loop, a "did we find anything?" branch, a "is the tree clean?" check, or a stamp-write. Capture exit code explicitly and treat non-zero as ERROR + exit 2. Use a tempfile when the command runs inside a process substitution (`done < <(...)`), since process-substitution exit codes aren't visible in the parent shell.
- **Reporting-only commands** — output is shown to the user as context (status output, log snippet, diff stat). Silent `2>/dev/null || true` is fine: degraded output is acceptable, false-success on a gate is not.

Reference patterns — search by the named anchor below rather than line number, since line numbers drift. Each bullet calls out which reference script(s) carry the canonical implementation; the two canonical scripts are [skills/shipping-work-php/scripts/pre-ship.sh](skills/shipping-work-php/scripts/pre-ship.sh) and [skills/shipping-work/scripts/doc-check.sh](skills/shipping-work/scripts/doc-check.sh).

All three exit-code-capture patterns below (`LS_RC`, `FIND_RC`, `DIFF_RC`) require an `RC=0` pre-init *before* the capturing line. Under `set -u`, a success path doesn't fire `|| RC=$?`, so any subsequent expansion of `$RC` would abort with `RC: unbound variable`. Don't omit the pre-init when adapting these patterns.

- **Tempfile + exit-code capture for process substitution** — grep for `LS_RC` (pre-ship.sh). Use when a command runs inside `done < <(...)` and you need its exit status: capture stdout to a tempfile, capture `$?` into a scalar, branch on it.
- **Three-case `find` handler** — grep for `FIND_RC` (pre-ship.sh). Non-zero exit → ERROR + exit 2; exit-0 with stderr → WARN + proceed; exit-0 silent → proceed.
- **Command substitution + exit-code capture (simpler variant)** — grep for `DIFF_RC` (doc-check.sh). Use when the output fits in a scalar and there's no process substitution; `$?` is directly observable via `RC=0; OUT=$(cmd) || RC=$?`, no tempfile needed.
- **Consolidated EXIT trap** — grep for `trap '` at the top of the file (pre-ship.sh). Multiple tempfile *scalars* (not an array) in one trap line for bash 3.2 + `set -u` compatibility.
- **`--help` exit-code block** — search the `--help` block (pre-ship.sh, doc-check.sh). Enumerates which infra failures map to exit 2 (vs. silently degrading).

Document any intentional silent fallback (e.g., `git rev-parse --show-toplevel 2>/dev/null || pwd`) with a one-line comment describing what the fallback actually does, not the rationale you assume it has.

This convention is enforced for `shipping-work*/scripts/pre-ship.sh` by [tests/structural/test_content_invariants.py](tests/structural/test_content_invariants.py) (`TestPreShipGateHardening`). Reverting a hardened site to `done < <(...)` form fails the structural suite. If process substitution is genuinely required, tag the loop with `# unhardened: <reason>` either on the `done` line itself or anywhere within the prior 10 lines as an opt-out.

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

## References convention

Skills may carry supplementary `references/*.md` files for content that exceeds the SKILL.md body cap (SKILL.md is recommended to stay under 500 lines). References files are loaded on demand by the agent, not on skill activation.

- **No frontmatter.** Plain markdown, no YAML preamble.
- **Linked from the sibling SKILL.md.** Every `references/<name>.md` must appear as a `[label](references/<name>.md)` link in its sibling SKILL.md body. Orphans are blocked by [tests/structural/test_references.py](tests/structural/test_references.py).
- **Flat directory.** No subdirectories under `references/`. The structural no-orphan check compares link targets against `references/*.md` (non-recursive); nested layouts would be silently missed.
- **No length cap.** The whole point of a references file is escaping the SKILL.md body recommendation — don't reimpose one.
- **Naming:** `lowercase-kebab.md`, matching the broader skill naming convention.

The same conventions apply to `assets/` (templates, schemas, copy-into-place artifacts), with the obvious adjustment that `assets/` files are typically not markdown.

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
- Install `.skills/doctor.sh` via `bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-doctor.sh` — Phase 1 of `reviewing-*` / `shipping-*` skills uses it to self-heal dangling vendor symlinks. The auto-refresh hook re-installs it opportunistically; the manual command is only needed before the first session.

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
