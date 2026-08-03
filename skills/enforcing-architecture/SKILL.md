---
name: enforcing-architecture
description: Graduates an accepted architecture finding into an executable fitness function — picks the stack's tool (import-linter, dependency-cruiser, deptrac, module-size gate, or an OpenAPI drift guard), encodes the specific rule the finding fixed, adds the dev dependency, documents the contract in AGENTS.md, and wires it into the project's detected check surface as a reviewable diff. Use when the user says "add a fitness function", "enforce this contract", "lock this rule", or when reviewing-architecture accepts a `fitness` directive.
compatibility: Designed for Claude. Requires git. Tooling depends on the target stack (uv/pip, npm, or composer).
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: add a fitness function, enforce this contract, lock this rule, fitness function
---

# Enforcing Architecture — fitness functions from accepted findings

Turns a one-time architectural fix into an **executable check** so it can't silently regress.
Architecture rots *between* reviews; a contract in CI is what closes that loop. The counterpart to
[`reviewing-architecture`](../reviewing-architecture/SKILL.md), which *finds* the coupling/layering/
contract problem — this skill *locks the fix in*.

**Activation triggers:** "add a fitness function", "enforce this contract", "lock this rule", and the
`fitness` directive handed off from `reviewing-architecture` Phase 4.

## The Iron Law

```
NO GATE WIRED WITHOUT A NAMED RULE AND A DETECTED CHECK SURFACE
NO CI EDIT APPLIED SILENTLY — WIRING IS ALWAYS A REVIEWABLE DIFF
```

A fitness function encodes **one specific rule** (e.g. "`models` may not import `services`", "no cycles
in `services/`"). If you can't state the rule in one sentence, you don't have a fitness function yet —
go back to the finding. And the CI/pre-commit wiring is never applied unannounced: generate it, show
it, let it land through the user's normal commit gate.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "I'll write the config from memory" | import-linter / dependency-cruiser / deptrac schemas are fiddly; a wrong key ships a green check that enforces nothing. Fill in the vetted snippet in [references/fitness-functions.md](references/fitness-functions.md). |
| "CI is CI — I'll just add a GitHub Action" | Detect the surface. The project may gate on composer scripts, pre-commit, or GrumPHP, not `.github/workflows/`. Wire where it already runs. |
| "I'll build an OpenAPI differ" | The contract case delegates to `vendoring-openapi-client`'s drift guard. Don't reimplement it. |
| "The rule is 'improve coupling'" | That's a finding, not a contract. A fitness function needs a mechanically checkable predicate. |
| "I'll enable the gate and commit" | Wiring is a reviewable diff, always. The user's commit gate approves it. |

## Inputs (from the finding)

Whether invoked directly or handed off from `reviewing-architecture`, establish four things first:

1. **The rule** — one checkable sentence (source → forbidden target, or "no cycles in X", or "≤ N lines").
2. **The scope** — which package/directory/layer the rule governs.
3. **The stack** — from the manifest present (`pyproject.toml` / `package.json` / `composer.json`, or
   an OpenAPI spec for the contract case).
4. **Kind** — layering/no-cycles, module-size, or contract-stability.

## Procedure

### Phase 1 — Detect stack & pick the tool

Read the manifest and select per [references/fitness-functions.md](references/fitness-functions.md):
Python → **import-linter**, JS/TS → **dependency-cruiser**, PHP → **deptrac**, module-size → the
language's native lint rule (eslint `max-lines`, pylint `max-module-lines`) or the portable line-count
gate, contract-stability → **delegate to `vendoring-openapi-client`** (stop here and route the finding
there with the spec location and desired drift tier).

### Phase 2 — Encode the rule

Open the tool's section in the playbook and fill in the snippet from the finding's rule + scope. Add or
extend the tool's config file (`.importlinter`/`pyproject.toml`, `.dependency-cruiser.js`,
`deptrac.yaml`). If a config already exists, **append** a contract rather than replacing it. Confirm the
new check **fails** on the current-or-hypothetical violation and **passes** on the fixed tree — a
fitness function that can't fail is theater.

### Phase 3 — Add the dev dependency

Add the tool as a dev dependency with the project's manager (`uv add --dev`, `npm i -D`,
`composer require --dev`), never globally. Skip for the portable module-size gate (no dependency).

### Phase 4 — Detect the check surface & wire (as a diff)

Detect what the project runs on merge/commit (see the playbook's detection block): `.github/workflows/`,
`.pre-commit-config.yaml`, GrumPHP, composer/npm scripts. Wire the check into **every** surface already
in use. Where none exists, propose adding one CI step. Present all wiring as a **reviewable diff** — do
not enable a gate the user hasn't seen.

### Phase 5 — Document the contract in AGENTS.md

Add the rule to a `## Fitness functions` (or "Enforced contracts") section in the project's AGENTS.md:
the rule in one line, the tool, and the config location. This closes the loop — the **architecture
drift** dimension checks the documented contract against reality on the next review.

### Phase 6 — Verify

Run the check locally and confirm it passes on the current tree; report the command and its output. If
it fails, the fix isn't complete or the rule is mis-encoded — surface that, don't wire a red gate.

## Hand-off from `reviewing-architecture`

When `reviewing-architecture` Phase 4 accepts `N: fix + fitness` (refactor, then lock) or bare
`N: fitness` (architecture already correct — encode the invariant, no refactor), it invokes this skill
with the finding's rule, scope, and stack. For `fix + fitness`, the refactor completes first; this skill
only runs once the tree already satisfies the rule (Phase 6 would otherwise fail).

## Commit & summary

After wiring, commit the config + dev-dependency + AGENTS.md changes together. The commit boundary
depends on how the skill was invoked: **standalone** (user asked directly) — commit all of it,
including the CI wiring, here. **Mid-review** (handed off from `reviewing-architecture` Phase 4) — do
**not** open a separate commit; leave the changes staged so they land through the review's own commit
gate (or the user's `shipping-work`/CR flow), keeping one reviewed boundary for the whole session.
Present a summary:

| Rule | Tool | Config | Wired into |
|---|---|---|---|
| `models` ⊄ `services` | import-linter | `pyproject.toml` | CI lint job + pre-commit |
