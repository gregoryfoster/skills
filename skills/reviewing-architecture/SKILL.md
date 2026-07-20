---
name: reviewing-architecture
description: Performs a high-level architectural review evaluating structural health, design principles, and long-term maintainability. Use when the user says "AR", "architecture review", or "architectural review". Distinct from line-level code review. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements approved refactors.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git.
metadata:
  author: gregoryfoster
  version: "1.2"
  triggers: AR, architecture review, architectural review
---

# Architectural Review

A high-level review of application architecture: structural health, design principles, and long-term maintainability. Distinct from line-level code review.

**Activation triggers:** AR (shorthand for architecture review), "architecture review", "architectural review".

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
```

If you haven't run `gather-context.sh` and surveyed the actual current architecture, you have not completed Phase 1.
If the user hasn't responded with directives, you cannot implement anything.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "This is a strategic review, no need for detailed evidence" | Without specific code/structure citations, findings are opinions. Cite the modules that triggered each finding. |
| "I already understand this architecture" | Familiarity bias. Re-survey the actual current state, not your remembered version — directory trees and dependency graphs change. |
| "Tests pass, that's the architecture" | Tests verify behavior, not coupling, cohesion, layering, or scalability. |
| "I'll suggest a refactor as I go" | Phase 4 exists. Present findings first; user picks which refactors warrant doing. |
| "This module wasn't in the diff" | Architecture review crosses boundaries — call graphs, dependency direction, layering. The diff is the trigger, not the scope. |
| "The user seems in a hurry" | A fast bad architecture pivot is slower than a thorough correct one. |

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `AR services/`, `architecture review routers/`, `AR #22`. Apply the appended context as the explicit scope (step 1 of Scope detection); skip the conversation-context and full-project fallbacks.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — apps, modules, layers, or areas of concern specified by the user
2. **Conversation context** — if recent work touched a subsystem, review that subsystem
3. **Full project** — if no scope is given or implied, review the entire project
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

```bash
N=reviewing-architecture S=gather-context.sh SD=
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `gather-context.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

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

Required report structure:
- `## Architectural Review — [scope]`
- `### Architecture summary` — 2–4 sentence description of current architecture (shared context for findings)
- `### What's solid` — genuine architectural strengths worth preserving
- `### Findings` — numbered findings grouped by severity
- Group by severity: 🔴 Structural problems → 🟡 Design improvements → 💭 Observations & opportunities
- Numbered findings are **sequential across ALL severity groups** — never reset
- Sub-items under a single finding use `2a.`, `2b.` etc.
- `### Summary` — 1–2 sentences on overall architectural health and top priorities

Each finding within `### Findings` must follow this format:

> N. **[module/file]** What: \<precise description with file/module reference\>. Why it matters: \<architectural impact: maintainability? performance? correctness?\>. Suggested approach: \<concrete refactoring direction — name new modules, describe the split, sketch the pattern\>.

All three labels (`What:`, `Why it matters:`, `Suggested approach:`) are required in every finding, verbatim.

### Phase 3.5 — Verify before reporting

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION
```

- Each finding must cite a specific module, file, or directory — not a generic claim about "the architecture"
- If any refactor was prototyped in this conversation, re-run the test suite and report failures as 🔴 findings regardless of cause
- Do NOT claim a structural problem exists unless you have output from this session (file listing, dependency trace, line count) confirming it

### Phase 4 — Wait for feedback

**Stop. Do not make changes until the user responds.**

Accept terse directives referencing item numbers:

| Directive | Meaning |
|---|---|
| `1: fix` | Implement the suggested refactoring |
| `3: stet` | Leave as-is (acknowledged, no action) |
| `5: fix, but use X approach` | Refactor with the user's preferred approach |
| `2: document as TODO` | Add a code comment or AGENTS.md note instead of fixing |
| `7: investigate further` | Gather more information before deciding |
| `10: GH` | Create or update a corresponding GitHub issue |

After directives, implement all requested changes. Before committing, run the test suite and confirm it passes — report any failures before committing. Then commit and present a summary table:

| Item | Action | Result |
|---|---|---|
| 1 | Fixed | `Split services/parser.py → parser.py + recovery.py` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If the review leads to structural changes:
- AGENTS.md project layout and architecture sections
- README.md if module boundaries or service topology changed
- Module-level docstrings affected by refactoring
