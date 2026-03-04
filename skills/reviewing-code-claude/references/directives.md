# Review Directives

After the findings report is presented, the user responds with terse directives referencing item numbers.

## Directive syntax

| Directive | Meaning |
|---|---|
| `1: fix` | Implement the suggested fix |
| `3: stet` | Leave as-is (acknowledged, no action) |
| `5: fix, but use X approach` | Fix with user's preferred approach |
| `2: document as TODO` | Add a code comment or AGENTS.md note instead of fixing |
| `7: investigate further` | Gather more information before deciding |
| `10: GH` | Create or update a corresponding GitHub issue |

## After receiving directives

1. Implement all requested changes
2. Commit with an appropriate message
3. Present a summary table:

| Item | Action | Result |
|---|---|---|
| 1 | Fixed | `services/parser.py:42 — added bounds check` |
| 3 | Stet | — |
| 10 | GH | Issue #22 created |
