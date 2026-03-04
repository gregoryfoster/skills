---
name: reviewing-architecture-claude
description: Performs a high-level architectural review evaluating structural health, design principles, and long-term maintainability. Use when the user says "AR", "architecture review", or "architectural review". Distinct from line-level code review. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements approved refactors.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: AR, architecture review, architectural review
---

# Architectural Review

A high-level review of application architecture: structural health, design principles, and long-term maintainability. Distinct from line-level code review.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — apps, modules, layers, or areas of concern specified by the user
2. **Conversation context** — if recent work touched a subsystem, review that subsystem
3. **Full project** — if no scope is given or implied, review the entire project
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

```bash
bash scripts/gather-context.sh
```

Also:
- Read AGENTS.md, README.md, and project layout documentation
- Survey the full directory tree; identify all modules, apps, and layers
- Read key files: settings, routing, models, entry points, service configs
- Note dependency graph between modules (imports, shared state, coupling)
- Check file sizes (`wc -l`) across all source files to flag oversized modules
- Review dependency manifest (`pyproject.toml`, `package.json`, etc.) for health

### Phase 2 — Analyze

Evaluate against these dimensions. See [references/dimensions.md](references/dimensions.md) for detail on each.

- DRY — duplicated logic, parallel structures that should be unified
- Module size & cohesion — files mixing unrelated concerns; >300 lines deserves scrutiny, >500 is a strong signal to split
- Separation of concerns — business logic leaking into handlers or templates
- Coupling & dependency direction — circular imports, layering violations
- Efficiency & performance — N+1 queries, missing indexes, unoptimized loops
- Configuration & environment — secrets management, hardcoded values
- Error handling patterns — inconsistent strategies, bare excepts, swallowed errors
- Naming & discoverability — module names that obscure purpose
- Schema & data model health — missing constraints, orphaned tables
- Scalability — patterns that break at 10×, missing pagination, sync work that should be async
- Test architecture — isolation, fixture reuse, coverage gaps by layer

### Phase 3 — Present findings

See [references/findings-format.md](references/findings-format.md) for the exact report structure.

Key rules:
- Title: `## Architectural Review — [scope]`
- **Architecture summary** — 2–4 sentence description of current architecture (shared context for findings)
- **What's solid** — genuine architectural strengths worth preserving
- **Numbered findings** — sequential across ALL severity groups, never reset
- Group by severity: 🔴 Structural problems → 🟡 Design improvements → 💭 Observations & opportunities
- **Summary** — 1–2 sentences on overall architectural health and highest-priority items

### Phase 4 — Wait for feedback

**Stop. Do not make changes until the user responds.**

Accept terse directives referencing item numbers. See [references/directives.md](references/directives.md).

After directives, implement all requested changes, commit, and present a summary table.

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If the review leads to structural changes:
- AGENTS.md project layout and architecture sections
- README.md if module boundaries or service topology changed
- Module-level docstrings affected by refactoring

## Parameterized invocation

Triggers may include scope inline — e.g., `AR services/`, `architecture review routers/`. Apply the appended context as the explicit scope (step 1 of scope detection).
