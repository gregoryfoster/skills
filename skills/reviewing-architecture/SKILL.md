---
name: reviewing-architecture
description: Performs a high-level architectural review evaluating structural health, design principles, and long-term maintainability. Use when the user says "AR", "architecture review", or "architectural review". Distinct from line-level code review. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements approved refactors.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git.
metadata:
  author: gregoryfoster
  version: "1.5"
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
| "I listed the exact lines — that's as specific as it gets" | Lines move; the command that found them doesn't. Record the grep beside the conclusion so the reader re-runs it instead of trusting a snapshot. |

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

<!-- skill:required -->
```bash
N=reviewing-architecture S=gather-context.sh SD=
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `gather-context.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

`gather-context.sh` prints more than a file listing: internal import **fan-in** (which modules the system leans on), **churn hotspots**, and **temporal coupling** (files that change together) mined from the git log. Read those sections — they are the coupling and decay evidence the rest of the review cites.

**When SocratiCode is indexed for this project, use its graph tools for real dependency edges the static snapshot cannot give** — `codebase_graph_circular` (import cycles), `codebase_graph_query` (fan-in/fan-out for a module), `codebase_impact` (blast radius of a change), `codebase_graph_visualize` (layering overview). A coupling or dependency-direction finding backed by graph output is evidence; one backed by eyeballing a file tree is an opinion.

Also:
- Read AGENTS.md, README.md, and project layout documentation — note the *documented* architecture so Phase 2 can check the real one against it (drift)
- Survey the full directory tree; identify all modules, apps, and layers
- Read key files: settings, routing, models, entry points, service configs
- Review dependency manifest (`pyproject.toml`, `package.json`, etc.) for health

### Phase 2 — Analyze

Evaluate against these dimensions. See [references/dimensions.md](references/dimensions.md) for the **Look for / How to find it / Example finding** detail on each — use it; it is what keeps findings evidence-backed.

**Altitude rule (what makes this not a code review):** *Could a reviewer find it by reading one file?* If yes, it belongs to [`reviewing-code`](../reviewing-code/SKILL.md), not here. Report the structural cousin — duplicated *responsibility* not duplicated lines, resilience *architecture* not a bare `except`, a data-access *pattern* not a single N+1.

- Separation of concerns & boundaries — logic leaking across layers; missing domain seams
- Coupling & dependency direction — cycles, layering violations, poor evolvability
- Service contracts & interface stability — breaking API/schema changes at boundaries, client/spec drift
- Module size & cohesion — size as a proxy for a module doing too many jobs (>300 scrutinize, >500 split)
- Resilience & failure architecture — timeouts, retries, circuit breakers, blast radius of one failure
- Scalability & data-access patterns — pagination, async offload, patterns that break at 10×/100×
- Observability — correlation IDs, structured logs, metrics/tracing at boundaries
- Trust boundaries & security architecture — where authz lives, tenant isolation, secrets flow (structural slice only; line-level → `security-review`)
- Configuration & environment — secrets management, config flow, 12-factor
- Schema & data-model health — constraints, normalization, migration hygiene
- DRY of responsibility — the same decision owned in two places that must change together
- Naming & discoverability — layout that lets a newcomer predict where things live
- Test architecture — isolation seams, coverage by layer, missing unit tier
- Architecture drift — does the real structure match AGENTS.md's documented one?

Where a coupling/layering/contract finding is accepted, consider whether it can graduate into an **executable fitness function** (import-linter, dependency-cruiser, deptrac, a module-size gate, or an OpenAPI diff gate) so it can't silently regress — see the end of [references/dimensions.md](references/dimensions.md). Surface it as the finding's suggested approach; never adopt one unprompted. When the user opts in (see the `fitness` directives below), delegate the actual generation and wiring to [`enforcing-architecture`](../enforcing-architecture/SKILL.md) via the Skill tool, handing off the finding's rule, scope, and stack.

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

> N. **[module/file]** What: \<precise description with file/module reference\>. Evidence: \<the command, query, or gather-context section that produced the citation, written so the reader can re-run it — `rg -n "is StreamProvider\." src/`, `codebase_graph_circular`, the `=== File sizes ===` block\>. Why it matters: \<architectural impact: maintainability? performance? correctness?\>. Suggested approach: \<concrete refactoring direction — name new modules, describe the split, sketch the pattern\>. Effort/Blast radius: \<rough cost and reach of the fix: how many modules move, and is it reversible or a one-way door\>.

All five labels (`What:`, `Evidence:`, `Why it matters:`, `Suggested approach:`, `Effort/Blast radius:`) are required in every finding, verbatim. The severity marker (🔴/🟡/💭) ranks *how bad the problem is*; `Effort/Blast radius:` is a separate axis for *how expensive and risky the fix is* — a user triaging refactors needs both, because "severe but cheap and reversible" and "severe but a risky migration" warrant different decisions.

`Evidence:` records *how* the citation was obtained, not a second copy of where it points. A finding whose grep travels with it can be **re-run** by whoever implements it, months later, in a second; a finding carrying only the conclusion has to be re-derived, and re-derivation is the step that gets skipped. Where the finding rests on reading rather than on a command, say so — "read `settings.py` end to end" is honest evidence; a grep reconstructed for the report is not.

**Shelf life — lead with the invariant.** A finding's file:line specifics are evidence-of-the-moment, not specification. Findings become issue bodies read *later*, after other findings from the same review have been implemented, so staleness is not random: it is proportional to how deep in the execution order a finding sits, and it is worst exactly where the work is hardest. Phrase `What:` so the durable claim leads and the specifics merely evidence it — "every provider branch is inline at the call site" survives a refactor that "seven `is X` checks, at lines 40, 88, 133…" does not. Keep the specifics, mark them as observed at review time, and treat line numbers as evidence rather than as specification; `Evidence:` is what the implementer re-runs. (Measured: a 13-issue backlog carved from one such review carried a material error in **every** issue body by implementation time — one finding's branch-point table was 5 of 7 stale when its batch ran, because an earlier batch in the same backlog had changed the column type. See [`orchestrating-issue-backlog`](../orchestrating-issue-backlog/references/process-log.md), 2026-08-09.)

### Phase 3.5 — Verify before reporting

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION
```

- Each finding must cite a specific module, file, or directory — not a generic claim about "the architecture" — and its `Evidence:` must be the command you **actually ran** to reach that citation, not one reconstructed afterwards to look rigorous. If you cannot name what produced the citation, you do not have a finding yet
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
| `4: fix + fitness` | Refactor, then graduate the rule into an executable fitness function (delegates to [`enforcing-architecture`](../enforcing-architecture/SKILL.md)) |
| `6: fitness` | Encode the rule as a fitness function without a refactor — the architecture is already correct, just lock it so it can't regress (delegates to `enforcing-architecture`) |
| `2: document as TODO` | Add a code comment or AGENTS.md note instead of fixing |
| `7: investigate further` | Gather more information before deciding |
| `8: ADR` | Record the decision as an Architecture Decision Record (capture the *why*, not just the change) |
| `10: GH` | Create or update a corresponding GitHub issue |

For `fix + fitness` and bare `fitness`, invoke the [`enforcing-architecture`](../enforcing-architecture/SKILL.md) skill (Skill tool) once the tree satisfies the rule, handing off the finding's rule, scope, and stack. For `fix + fitness`, complete the refactor first.

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
- An ADR (if directed) capturing *why* the change was made — the decision, the alternatives, the tradeoff — so the next reviewer inherits the reasoning, not just the result

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
