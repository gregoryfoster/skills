---
title: Generate & wire fitness functions from accepted architecture findings (issue #80)
date: 2026-08-02
status: draft
---

# Fitness functions from accepted architecture findings

## Problem

[#78](https://github.com/gregoryfoster/skills/issues/78) added a *fitness-functions* section to
[`reviewing-architecture/references/dimensions.md`](../../skills/reviewing-architecture/references/dimensions.md)
that tells the skill to **suggest** graduating an accepted coupling/layering/contract finding into an
executable check (import-linter, dependency-cruiser, OpenAPI diff). But suggesting is all it does —
there is no scaffolding to actually generate the check, encode the specific rule, add the dev
dependency, or wire it into CI when the user opts in. Architecture rots *between* reviews; a fitness
function in CI is what closes that loop, and leaving it as prose means it rarely happens.
Issue [#80](https://github.com/gregoryfoster/skills/issues/80).

## Approach

Build a **new standalone skill, `enforcing-architecture`**, that `reviewing-architecture` delegates to
when a finding is accepted with a `fitness` directive. Rationale for standalone over inline: the AR
`SKILL.md` is already ~160 dense lines; the capability is reusable off the review path ("add an
import-linter contract that `models` can't import `services`" is a legitimate standalone request); and
delegation is the repo idiom (AR already points at `reviewing-code`, `shipping-work`,
`vendoring-openapi-client`). `reviewing-architecture`'s only new responsibility is Phase 4 directive
recognition and a hand-off of `{stack, the specific rule, scope}`.

The new skill carries a `references/fitness-functions.md` playbook of **vetted per-tool config
snippets** (import-linter contract types, dependency-cruiser `forbidden` rules) — mirroring how
`dimensions.md` and vendoring's `references/` already work — because import-linter and
dependency-cruiser schemas are fiddly enough that inline reconstruction ships checks that silently
pass. Stack detection keys off the manifest (`pyproject.toml` → import-linter; `package.json` →
dependency-cruiser). The **OpenAPI contract case delegates to `vendoring-openapi-client`'s existing
tiered drift guard** rather than reimplementing a differ. Config + dev dependency + an AGENTS.md
contract note are always written; the CI wiring is generated as a **reviewable diff** that lands
through the normal `shipping-work`/CR commit path, never silently applied.

Directive grammar extends the existing terse table with both a compound flag and a bare verb:
`N: fix + fitness` (refactor, then lock it) and bare `N: fitness` (architecture already correct —
encode the invariant without a refactor; common for the drift dimension).

## Tradeoffs / alternatives

- **Grow `reviewing-architecture` in place** — rejected: bloats an already-dense SKILL.md, buries a
  reusable capability behind the review trigger, and breaks the repo's delegation idiom.
- **Bare `fitness` verb only (no `fix + fitness`)** — rejected: loses the "refactor then lock"
  compound that is the headline case; the existing table already models compound directives
  (`fix, but use X`), so both fit the grammar.
- **`fix + fitness` only (no bare verb)** — rejected: can't graduate a rule that is *already*
  satisfied, which is half the value (the drift dimension routinely finds docs and reality agreeing).
- **Generate tool config inline from memory** — rejected: import-linter/dependency-cruiser config
  schemas are error-prone; a hallucinated key yields a green check that enforces nothing. Vetted
  snippets the skill fills in are safer and reviewable.
- **Reimplement an OpenAPI differ inside the new skill** — rejected: `vendoring-openapi-client`
  already ships a tiered drift guard (`DRIFT_GUARD=none|ci|ci+live`); the contract case should route
  into it.
- **Silently wire CI** — rejected: rewriting a workflow unannounced is near a one-way door; generate
  the diff and let the user's commit gate approve it.

## Steps

1. **Scaffold the skill.** Create `skills/enforcing-architecture/SKILL.md` (frontmatter: name,
   description, triggers, compatibility, author, version) with phases: detect stack → select tool →
   fill config from playbook → add dev dep → document in AGENTS.md → generate CI-wiring diff for
   review. Follow the script-path-resolution and doctor-preflight conventions the sibling skills use.
2. **Write the playbook.** `references/fitness-functions.md` with per-tool sections: import-linter
   (layers/forbidden/independence contract types, `.importlinter` config, `pyproject` dep) and
   dependency-cruiser (`forbidden` rule shape, `.dependency-cruiser.js`, `package.json` dep + script).
   Each section: the rule → the exact config snippet → how it wires into the check surface.
3. **Contract-case delegation.** Add a section (or a thin `references/` pointer) routing
   contract-stability findings to `vendoring-openapi-client`'s drift-guard pattern rather than a new
   differ; state the hand-off explicitly.
4. **Wire the AR directive.** In `reviewing-architecture/SKILL.md` Phase 4, add `N: fix + fitness` and
   bare `N: fitness` to the directive table, and a line delegating to `enforcing-architecture` with the
   `{stack, rule, scope}` hand-off. Update the Phase 2 fitness-function paragraph to reference the new
   skill instead of only the dimensions.md prose.
5. **AGENTS.md contract note.** Ensure the skill documents each generated contract in the target
   project's AGENTS.md so the **architecture drift** dimension checks against it on the next review
   (loop closure). Decide format (a "Fitness functions / enforced contracts" subsection).
6. **CI-wiring as reviewable diff.** Confirm the skill generates the pre-commit/CI wiring as a diff
   surfaced to the user (never auto-committed), landing via `shipping-work`/CR — mirror vendoring's
   tiered posture.
7. **Cohort / vendoring downstream.** Note (not in this PR) that adding a skill to the family means the
   vendoring cohort repos need the submodule/symlink update; capture as follow-up per the cohort memo.
8. **Docs & version bumps.** README skill list, `reviewing-architecture` version bump, and any family
   index that enumerates skills.

## Open questions / risks

- **Skill name.** `enforcing-architecture` vs `wiring-fitness-functions` vs `fitness-functions`. Plan
  assumes `enforcing-architecture`; confirm before scaffolding (directory + symlinks are cheap to
  rename now, costly later).
- **Module-size fitness function.** #78's dimensions.md also lists a module-size lint threshold as a
  candidate fitness function. In scope for v1, or defer? (import-linter/dep-cruiser + OpenAPI are the
  three named in #80; module-size is a fourth.)
- **Language coverage for v1.** Python (import-linter) + JS/TS (dependency-cruiser) + OpenAPI covers the
  named cases. Any other stack expected at launch?
- **How prescriptive the CI wiring is.** Do we assume a `.github/workflows/` + pre-commit surface (as
  the CR/shipping skills model), or detect the surface? Detection is more robust but larger.
- **Delegation mechanics.** Does `reviewing-architecture` invoke the new skill via the Skill tool
  mid-Phase-4, or emit an instruction the user re-triggers? First is smoother; second keeps the
  review's commit boundary clean.
