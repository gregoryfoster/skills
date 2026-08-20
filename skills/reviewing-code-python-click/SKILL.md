---
name: reviewing-code-python-click
description: "For Python/Click CLI projects (uv + ruff + pytest + Pydantic v2): performs a structured code and documentation review using a severity-tiered findings format. Use when the user says \"CR\", \"code review\", or \"perform a review\" and the project is a Click-based CLI. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements and commits approved changes."
compatibility: Designed for Python Click CLI projects using uv, ruff, pytest, and Pydantic v2. Requires git, gh, uv.
metadata:
  author: gregoryfoster
  version: "1.1"
  triggers: CR, code review, perform a review
---

# Code & Documentation Review — Python/Click

A systematic review workflow for Python Click CLI projects (uv + ruff + pytest + Pydantic v2). Produces a numbered findings report, waits for directives, then implements approved changes.

**Activation triggers:** CR (shorthand for code review), "code review", "perform a review".

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
```

If you haven't run `gather-context.sh` and confirmed ruff and the import check pass (and tests, if a suite exists), you have not completed Phase 1.
If the user hasn't responded with directives, you cannot implement anything.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's a small change, no need for a full review" | Size doesn't determine risk. Run the review. |
| "I just implemented this, I know it's correct" | Familiarity bias. A fresh pass finds what implementation blindness missed. |
| "Tests are passing, that's the review" | Tests verify behavior, not convention compliance or docs. |
| "The user seems in a hurry" | A fast broken change is slower than a thorough correct one. |
| "I'll fix things as I find them" | Phase 4 exists. Present first, implement after directives. |
| "This file wasn't in the diff" | Related files need review too. Check call sites, tests, AGENTS.md. |
| "The new command works locally" | Verify it's registered on the project's Click entrypoint — an unregistered command never reaches a user. |
| "It's just a decorator order tweak" | Click decorator order changes parameter binding semantics. Treat ordering changes as behavior changes. |
| "Naive datetime is close enough" | ISO 8601 UTC only. Naive datetimes cause silent timezone drift in production. |

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `CR #14`, `code review src/cli/commands/run.py`, `CR <commit-range>`. Apply the appended context as the explicit scope (step 1 of Scope detection); skip the conversation-context and uncommitted-work fallbacks.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — files, branch, commit range, or issue number specified by the user
2. **Conversation context** — changes implemented in this conversation
3. **Uncommitted work** — `git diff` and `git diff --staged`
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

```bash
N=reviewing-code-python-click S=gather-context.sh SD=
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `gather-context.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

The script runs the variant's review-time checks informationally (output captured; failures become Phase 3 findings, not gather-context errors) alongside the standard git diff/status output:

- `uv run ruff check .`
- `uv run python -c "import <PACKAGE>"` — the import target is auto-detected from `pyproject.toml` (`[project] name`, hyphens normalized to underscores). Auto-detection is a heuristic; if it picks the wrong package, the project should commit a `.skills/import-targets` file at the repo root (one package per line) which the script consumes instead.
- `uv run pytest <dirs>` — test directories resolved via the same helper as pre-ship (`tests/` first, then every existing entry in `pyproject.toml [tool.pytest.ini_options].testpaths`). A missing test suite is a warning, not an error (the cannobserv shared-library case has no test suite).

**Pytest in gather-context (variant-specific):** Click CLI test suites are typically fast enough that running them at review time materially shortens the feedback loop — the audit found existing downstream consumers already do this. This differs from the FastAPI variant, which defers pytest to ship time. The divergence is deliberate.

Also:
- Read AGENTS.md conventions relevant to changed files
- Identify all files touched and their roles (Click command vs core lib vs test)
- Run targeted imports/scripts to catch obvious syntax errors before reporting
- If the script printed a **Context budget** block, treat an OVER row on `AGENTS.md` as a documentation finding when this branch is what pushed it over — the fix is usually to move the addition into a `docs/` reference doc rather than to shorten it. It is informational, never a blocker, and it prints nothing when the diff touches no context-surface file.

### Phase 2 — Analyze

Evaluate against these dimensions:

- **Correctness** — bugs, logic errors, edge cases, off-by-ones
- **Data integrity** — for CLIs that touch storage (archive, ingest, sync flows): schema constraints, migration safety, transactional boundaries, idempotent retries
- **Convention compliance** — AGENTS.md patterns (logging, naming, style); `uv.lock` committed alongside `pyproject.toml`; ruff rule set
- **Documentation** — do AGENTS.md, README.md, docstrings, and `--help` output reflect changes?
- **Robustness** — error handling, idempotency, graceful degradation; user-facing error messages distinguishable from stack traces
- **Click command correctness** — decorator order is meaningful (typical pattern: `@command` → `@pass_context` → custom `@click_option_*` decorators → `@click.option`); `ctx.invoke` used correctly for delegation; `ctx.obj` carries a typed binding (e.g., `ctx_obj: AppContext`) rather than an untyped dict
- **ParamType testability** — `convert()` is a ParamType's only conversion hook, so test a custom ParamType through it and mock what it reaches for (`ctx.obj` and its service accessors) rather than avoiding it; a pure ParamType needs no mocking at all. `callback` is not a ParamType attribute — it belongs to `Parameter`/`Option` (a post-conversion hook) and to `Command` (the decorated function), so it is *command* tests that skip conversion, by calling `command.callback(...)` with pre-built objects instead of going through option parsing.
- **Command registration** — newly added Click commands are registered in the project's entrypoint module (e.g., `src/<project>.py`). An unregistered command compiles, imports, and passes type checks but is invisible to users.
- **Pydantic v2 idioms** — `X | None` syntax over `Optional[X]`; mutable default footgun (use `Field(default_factory=list)` not `= []`); type hints on every signature; `model_config` not `Config` inner class
- **Cross-package boundary** — if a change crosses into a shared library (e.g., `../cannobserv/` consumed from `cli`), flag it for separate review of the library's consumers. Public-API changes in a shared library ripple.
- **Datetime convention** — ISO 8601, UTC only; no naive datetimes; `datetime.now(timezone.utc)` not `datetime.now()`
- **Security** — no hardcoded credentials; secrets via env only; input validation at command boundaries (Click `type=` + a custom ParamType's `convert()`)

### Phase 3 — Present findings

Required report structure:
- `## Code & Documentation Review — [scope]`
- `### What's solid` — genuine positives, not filler
- `### Findings` — numbered findings grouped by severity
- Group by severity: 🔴 Bugs → 🟡 Issues to fix → 💭 Minor/observations
- Numbered findings are **sequential across ALL severity groups** — never reset
- Sub-items under a single finding use `2a.`, `2b.` etc.
- `### Summary` — 1–2 sentences on overall assessment and top priorities

Each finding within `### Findings` must follow this format:

> N. **[file:line]** What: \<precise description\>. Why it matters: \<impact\>. Suggested fix: \<concrete action\>.

All three labels (`What:`, `Why it matters:`, `Suggested fix:`) are required in every finding, verbatim.

### Phase 3.5 — Verify before reporting

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION
```

- Re-run tests if any implementation happened in this conversation and a `tests/` directory exists
- If tests fail: report the failure as a 🔴 finding regardless of cause
- Do NOT claim "tests pass" unless you have output from this session confirming it
- Run the lint/format gate against changed files and report any violations as findings:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
- Lint/format violations are 🟡 by default, 🔴 if they signal a real bug (e.g., undefined name, unreachable code, unused import shadowing intent)

### Phase 4 — Wait for feedback

**Stop. Do not make changes until the user responds.**

Accept terse directives referencing item numbers:

| Directive | Meaning |
|---|---|
| `1: fix` | Implement the suggested fix |
| `3: stet` | Leave as-is (acknowledged, no action) |
| `5: fix, but use X approach` | Fix with the user's preferred approach |
| `2: document as TODO` | Add a code comment or AGENTS.md note instead of fixing |
| `7: investigate further` | Gather more information before deciding |
| `10: GH` | Create or update a corresponding GitHub issue |

After directives, implement all requested changes. Before committing, run the test suite (if present) and confirm it passes — report any failures before committing. Then commit and present a summary table:

| Item | Action | Result |
|---|---|---|
| 1 | Fixed | `src/<project>/commands/foo.py:42 — added bounds check` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If changes affect command surface, new flags, user-facing behavior, deployment, or `--help` output — flag missing documentation updates as numbered findings. Spot-check AGENTS.md and README for drift: file paths still valid, conventions still match the code, command inventory still complete, `--help` output still matches documented behavior.

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
