---
name: reviewing-code-claude
description: Performs a structured code and documentation review using a severity-tiered findings format. Use when the user says "CR", "code review", or "perform a review". Produces a numbered findings report, waits for terse directives (fix/stet/GH), then implements and commits approved changes.
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git and gh CLI.
metadata:
  author: gregoryfoster
  version: "1.1"
  triggers: CR, code review, perform a review
---

# Code & Documentation Review

A systematic review workflow that produces a numbered findings report, waits for directives, then implements approved changes.

## The Iron Law

```
NO FINDINGS REPORT WITHOUT RUNNING THE TEST SUITE FIRST
NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES
```

If you haven't run `gather-context.sh` and confirmed tests pass, you have not completed Phase 1.
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

Also:
- Read AGENTS.md conventions relevant to changed files
- Identify all files touched and their roles
- Check the live app if UI changes are involved (browser screenshot)
- Run the app/imports to catch syntax errors

### Phase 2 — Analyze

Evaluate against these dimensions:
- **Correctness** — bugs, logic errors, edge cases, off-by-ones
- **Data integrity** — schema constraints, migration safety
- **Convention compliance** — AGENTS.md patterns (logging, naming, style)
- **Documentation** — do AGENTS.md, README.md, and comments reflect changes?
- **Robustness** — error handling, idempotency, graceful degradation
- **UX consistency** — if templates changed, do they follow the style guide?

### Phase 3 — Present findings

See [references/findings-format.md](references/findings-format.md) for the exact report structure.

Key rules:
- Title: `## Code & Documentation Review — [scope]`
- **What's solid** — genuine positives, not filler
- **Numbered findings** — sequential across ALL severity groups, never reset
- Group by severity: 🔴 Bugs → 🟡 Issues to fix → 💭 Minor/observations
- **Summary** — 1–2 sentences on overall assessment and top priorities

### Phase 3.5 — Verify before reporting

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION
```

- Re-run tests if any implementation happened in this conversation
- If tests fail: report the failure as a 🔴 finding regardless of cause
- Do NOT claim "tests pass" unless you have output from this session confirming it

### Phase 4 — Wait for feedback

**Stop. Do not make changes until the user responds.**

Accept terse directives referencing item numbers. See [references/directives.md](references/directives.md).

After directives, implement all requested changes. Before committing, run the test suite and confirm it passes — report any failures before committing. Then commit and present a summary table.

## Second review rounds

Continue numbering from where the previous round ended. Never reset.

## Documentation sweep

If changes affect schema, new APIs, user-facing behavior, or deployment — flag missing documentation updates as numbered findings.
