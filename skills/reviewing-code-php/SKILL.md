---
name: reviewing-code-php
description: "For PHP/WordPress projects (Bedrock + Sage 11): performs a structured code and documentation review using a severity-tiered findings format. Use when the user says \"CR\", \"code review\", or \"perform a review\" and the project is a Composer-managed PHP/WordPress monorepo. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements and commits approved changes."
compatibility: Designed for PHP 8.4 WordPress/Bedrock/Sage 11 monorepos with Composer. Requires git, gh, composer, php.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: CR, code review, perform a review
---

# Code & Documentation Review — PHP

A systematic review workflow for PHP/WordPress/Bedrock/Sage 11 monorepos. Produces a numbered findings report, waits for directives, then implements approved changes.

**Activation triggers:** CR (shorthand for code review), "code review", "perform a review".

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
```

If you haven't run `gather-context.sh` and confirmed it passed, you have not completed Phase 1.
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

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `CR #14`, `code review web/app/themes/sage/app/Providers/ThemeServiceProvider.php`, `CR <commit-range>`. Apply the appended context as the explicit scope (step 1 of Scope detection); skip the conversation-context and uncommitted-work fallbacks.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — files, branch, commit range, or issue number specified by the user
2. **Conversation context** — changes implemented in this conversation
3. **Uncommitted work** — `git diff` and `git diff --staged`
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

```bash
bash scripts/gather-context.sh
```

The script runs `composer validate --no-check-publish` at root and at every auto-discovered composer directory under `themes/` and `plugins/`, plus `php -l` on changed PHP files.

Also:
- Read AGENTS.md conventions relevant to changed files
- Identify all files touched and their roles (theme vs plugin vs `web/app/` infra)
- Check the live site if UI changes are involved (browser screenshot)
- Run the app to catch runtime errors (e.g., `wp acorn view:clear` after Blade changes)

### Phase 2 — Analyze

Evaluate against these dimensions:

- **Correctness** — bugs, logic errors, edge cases, off-by-ones
- **Data integrity** — schema constraints, migration safety, ACF field-group integrity
- **Convention compliance** — AGENTS.md patterns (logging, naming, style), `composer.lock` integrity, PSR-12
- **Documentation** — do AGENTS.md, README.md, and PHPDoc reflect changes?
- **Robustness** — error handling, idempotency, graceful degradation
- **Bedrock conventions** — `web/app/` only; `.env`-only secrets; no edits to WP core
- **Sage 11 patterns** — service providers in `app/Providers/`, View composers in `app/View/Composers/`, Blade templates in `resources/views/`
- **ACF JSON sync drift** — flag missing pulls/pushes for `acf-json/` changes
- **WP hooks** — actions/filters/registration sanity (priority, accepted args, hook timing)
- **SQL safety** — `$wpdb->prepare()` required for any interpolated SQL; flag raw `$wpdb->query()` with concatenation
- **Formatting** — `pint` violations are findings
- **Asset build** — remind about `yarn bud build` when `resources/assets/` changes
- **Security** — no hardcoded credentials; output escaping (`esc_html`, `esc_attr`, `esc_url`); nonce checks on form handlers

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
  - `vendor/bin/pint --test` (skip with a note if `vendor/bin/pint` is not installed)
- Lint/format violations are 🟡 by default, 🔴 if they signal a real bug (e.g., undefined name, unreachable code)

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
| 1 | Fixed | `app/Providers/AssetsServiceProvider.php:42 — added bounds check` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If changes affect schema, new APIs, user-facing behavior, deployment, or theme/plugin inventory — flag missing documentation updates as numbered findings. Spot-check AGENTS.md and README for drift: file paths still valid, conventions still match the code, skill inventory still complete.
