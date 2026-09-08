---
name: reviewing-code-php
description: "For PHP/WordPress projects (Bedrock + Sage 11): performs a structured code and documentation review using a severity-tiered findings format. Use when the user says \"CR\", \"code review\", or \"perform a review\" and the project is a Composer-managed PHP/WordPress monorepo. Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements and commits approved changes. Also accepts a blanket \"address the findings\" directive that applies them all in one pass."
compatibility: Designed for PHP 8.4 WordPress/Bedrock/Sage 11 monorepos with Composer. Requires git, gh, composer, php.
metadata:
  author: gregoryfoster
  version: "1.2"
  triggers: CR, code review, perform a review
---

# Code & Documentation Review — PHP

A systematic review workflow for PHP/WordPress/Bedrock/Sage 11 monorepos. Produces a numbered findings report, waits for directives, then implements approved changes.

**Activation triggers:** CR (shorthand for code review), "code review", "perform a review".

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
NO BLANKET DIRECTIVE SKIPS THE FINDINGS REPORT
```

If you haven't run `gather-context.sh` and confirmed it passed, you have not completed Phase 1.
If the user hasn't responded with directives, you cannot implement anything.
A directive given up front is a response that arrived early: it satisfies the wait, it never excuses the report.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's a small change, no need for a full review" | Size doesn't determine risk. Run the review. |
| "I just implemented this, I know it's correct" | Familiarity bias. A fresh pass finds what implementation blindness missed. |
| "Tests are passing, that's the review" | Tests verify behavior, not convention compliance or docs. |
| "The user seems in a hurry" | A fast broken change is slower than a thorough correct one. |
| "I'll fix things as I find them" | Phase 4 exists. Present first, implement after directives. |
| "They pre-authorized the fixes, so the report is a formality" | The report is the audit trail for changes nobody reviewed before they landed. Present it in full, then implement. |
| "They said address everything, so this migration is in scope too" | A blanket directive covers findings whose fix you can name. Hold the rest and say why. |
| "This file wasn't in the diff" | Related files need review too. Check call sites, tests, AGENTS.md. |

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `CR #14`, `code review web/app/themes/sage/app/Providers/ThemeServiceProvider.php`, `CR <commit-range>`. Apply the appended context as the explicit scope (step 1 of Scope detection); skip the conversation-context and uncommitted-work fallbacks.

Trailing text may also carry a **blanket directive** that pre-authorizes Phase 4 — `CR --fix`, `CR, address the findings`, `code review src/, address the findings, emphasizing technical correctness`. Parse that as a directive, not as scope, and follow **Blanket directives** in Phase 4. The report is still produced in full; only the wait is satisfied in advance.

## Scope detection

Determine what to review (priority order):
1. **Explicit scope** — files, branch, commit range, or issue number specified by the user
2. **Conversation context** — changes implemented in this conversation
3. **Uncommitted work** — `git diff` and `git diff --staged`
4. **Ask** — if scope is ambiguous, ask before proceeding

## Procedure

### Phase 1 — Gather context

<!-- skill:required id=skill-scripts -->
```bash
N=reviewing-code-php S=gather-context.sh SD=
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `gather-context.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

The script runs `composer validate --no-check-publish` at root and at every auto-discovered composer directory under `themes/` and `plugins/`, plus `php -l` on changed PHP files.

Also:
- Read AGENTS.md conventions relevant to changed files
- Identify all files touched and their roles (theme vs plugin vs `web/app/` infra)
- Check the live site if UI changes are involved (browser screenshot)
- Run the app to catch runtime errors (e.g., `wp acorn view:clear` after Blade changes)
- If the script printed a **Context budget** block, treat an OVER row on `AGENTS.md` as a documentation finding when this branch is what pushed it over — the fix is usually to move the addition into a `docs/` reference doc rather than to shorten it. It is informational, never a blocker, and it prints nothing when the diff touches no context-surface file.

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

Accept terse directives referencing item numbers, or a blanket directive covering all of them at once:

| Directive | Meaning |
|---|---|
| `1: fix` | Implement the suggested fix |
| `3: stet` | Leave as-is (acknowledged, no action) |
| `5: fix, but use X approach` | Fix with the user's preferred approach |
| `2: document as TODO` | Add a code comment or AGENTS.md note instead of fixing |
| `7: investigate further` | Gather more information before deciding |
| `10: GH` | Create or update a corresponding GitHub issue |
| `address the findings` | Blanket: apply every finding — see below |
| `address the findings, emphasizing X` | Blanket, with `X` as the tie-breaker |

After directives, implement all requested changes. Before committing, run the test suite and confirm it passes — report any failures before committing. Then commit and present a summary table:

| Item | Action | Result |
|---|---|---|
| 1 | Fixed | `app/Providers/AssetsServiceProvider.php:42 — added bounds check` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |

#### Blanket directives

`address the findings` answers every finding at once, in all three severity tiers. It may arrive **after** the report or **up front** in the trigger phrase (`CR --fix`, `CR, address the findings, emphasizing technical correctness`); the up-front form is the same explicit directive, simply arrived early. Present the report as its own message before the first edit — the chance to interrupt it is the only review these fixes get.

**Emphasis is not decoration.** Echo it on the Phase 3 title line, after the scope, so a mistyped one cannot silently no-op, then spend it twice: in Phase 2 it reweights which dimensions get scrutiny and can promote severity within the one named; at implementation it breaks ties between viable fixes — `emphasizing technical correctness` takes the fix that provably removes the failure mode over the one that is smaller or tidier.

**Hold, do not apply.** However broad the directive, it reaches only findings whose fix you can *name*:
- `Suggested fix:` is speculative — "consider whether…", "investigate"
- the fix needs a schema migration or a data backfill
- the fix changes a contract that callers outside the reviewed scope depend on

Report each held finding with its reason; a following `4: fix` overrides one.

**Never fire on a red baseline.** A blanket directive makes Phase 3.5's test run **unconditional** — its "if any implementation happened in this conversation" clause does not apply, because the highest-value case for a blanket directive is a branch you did not write, and that is exactly the case where the clause would skip the run and leave this rail consulting nothing. If the branch is already failing its tests or lint as received, present the report and stop: a fix committed on top of a broken baseline cannot be told apart from what broke it.

**One commit per finding**, its number in the message (`fix: CR 3 — bounds check on parse offset`). If the reviewed scope is itself uncommitted, commit it first under its own message: otherwise finding 1's commit sweeps up the whole change under review, every later message misdescribes its contents, and reverting a bad auto-fix reverts the work it was fixing. Nobody reviewed these before they landed, so per-finding commits are what let one bad auto-fix be reverted without unpicking the rest. Run the full gate once after the last fix; if it goes red, that granularity names the offending commit — revert it, re-run, and report the finding as `Reverted`.

Two outcomes only a blanket run produces:

| Item | Action | Result |
|---|---|---|
| 6 | Held | Fix needs a schema migration — outside a blanket directive |
| 9 | Reverted | Gate red after the fix; commit `a1b2c3d` reverted |

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If changes affect schema, new APIs, user-facing behavior, deployment, or theme/plugin inventory — flag missing documentation updates as numbered findings. Spot-check AGENTS.md and README for drift: file paths still valid, conventions still match the code, skill inventory still complete.

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
