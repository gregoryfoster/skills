---
name: reviewing-code-python-fastapi
description: "For Python/FastAPI projects (uv + ruff + pytest + Pydantic v2): performs a structured code and documentation review using a severity-tiered findings format. Use when the user says \"CR\", \"code review\", or \"perform a review\" and the project is a FastAPI service. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements and commits approved changes."
compatibility: Designed for Python FastAPI projects using uv, ruff, pytest, Pydantic v2. Requires git, gh, uv.
metadata:
  author: gregoryfoster
  version: "1.1"
  triggers: CR, code review, perform a review
---

# Code & Documentation Review — Python/FastAPI

A systematic review workflow for Python FastAPI projects (uv + ruff + pytest + Pydantic v2). Produces a numbered findings report, waits for directives, then implements approved changes.

**Activation triggers:** CR (shorthand for code review), "code review", "perform a review".

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
```

If you haven't run `gather-context.sh` and confirmed ruff and tests pass, you have not completed Phase 1.
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
| "Pydantic model is internal, breaking changes are fine" | API contract leaks through OpenAPI and consumers. Flag breaking changes explicitly. |
| "Naive datetime is close enough" | ISO 8601 UTC only. Naive datetimes cause silent timezone drift in production. |

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `CR #14`, `code review src/api/routes/v1.py`, `CR <commit-range>`. Apply the appended context as the explicit scope (step 1 of Scope detection); skip the conversation-context and uncommitted-work fallbacks.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — files, branch, commit range, or issue number specified by the user
2. **Conversation context** — changes implemented in this conversation
3. **Uncommitted work** — `git diff` and `git diff --staged`
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

```bash
[ -x .skills/doctor.sh ] && bash .skills/doctor.sh   # heals dangling vendor symlinks; silent if absent
bash scripts/gather-context.sh
```

The script runs `uv run ruff check .` informationally (output captured; lint failures become Phase 3 findings, not gather-context errors) alongside the standard git diff/status output.

**Do not run pytest during a review.** Tests run at ship time via `pre-ship.sh`. If you need targeted test output during review (e.g., to confirm a specific behavior), use `uv run pytest -m "not integration" <specific-test>` — but full-suite runs belong in Phase 1 of `shipping-work-python-fastapi`, not here.

Also:
- Read AGENTS.md conventions relevant to changed files
- Identify all files touched and their roles (route handler vs model vs core infra vs test)
- Check the live app if UI changes are involved (browser screenshot of `/docs` if OpenAPI changed)
- Run targeted imports/scripts to catch obvious syntax errors before reporting

### Phase 2 — Analyze

Evaluate against these dimensions:

- **Correctness** — bugs, logic errors, edge cases, off-by-ones
- **Data integrity** — schema constraints, migration safety, transactional boundaries
- **Convention compliance** — AGENTS.md patterns (logging, naming, style); `uv.lock` committed alongside `pyproject.toml`; ruff rule set
- **Documentation** — do AGENTS.md, README.md, docstrings, and OpenAPI descriptions reflect changes?
- **Robustness** — error handling, idempotency, graceful degradation; FastAPI exception handlers cover new failure modes
- **TDD discipline** — red commit present before green commit (`git log --oneline` evidence of failing-test-first commits); new behavior has corresponding tests
- **API contract** — Pydantic model changes flagged as breaking vs. non-breaking (field renames, removed fields, tightened validation = breaking; added optional fields = non-breaking); field names, types, validation, defaults reviewed for consistency
- **Logging convention** — `get_logger(__name__)` from `src.core.logging`; `configure_logging()` only at entry points (project entrypoint module, never in library code)
- **Datetime convention** — ISO 8601, UTC only; no naive datetimes; `datetime.now(timezone.utc)` not `datetime.now()`
- **Pydantic v2 idioms** — `X | None` syntax over `Optional[X]`; mutable default footgun (use `Field(default_factory=list)` not `= []`); type hints on every signature; `model_config` not `Config` inner class
- **Security** — no hardcoded credentials; secrets via env only; input validation at the route boundary

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

- Re-run tests if any implementation happened in this conversation
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

After directives, implement all requested changes. Before committing, run the test suite and confirm it passes — report any failures before committing. Then commit and present a summary table:

| Item | Action | Result |
|---|---|---|
| 1 | Fixed | `src/api/routes/items.py:42 — added bounds check` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If changes affect schema, new APIs, user-facing behavior, deployment, or route inventory — flag missing documentation updates as numbered findings. Spot-check AGENTS.md and README for drift: file paths still valid, conventions still match the code, route table still complete, OpenAPI descriptions still match field semantics.
