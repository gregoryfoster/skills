# Process Log — orchestrating-issue-backlog

Session-specific institutional memory for the [`orchestrating-issue-backlog`](../SKILL.md) skill. Each entry captures: project, interview answers, batch shape, non-obvious decisions, and tactical lessons. New sessions are appended chronologically; stable patterns get promoted into the SKILL.md body and (optionally) summarized here.

**This file is the root of the index.** Each session is its own entry file under
`process-log/<year>/`, named `<date>-<project>.md`, and each year's rows live in
that year's own index, `process-log/<year>/index.md`. Journaling a session means
two things: write the entry file, and add one row to that year's index — see
"Adding an entry" at the foot of this file.

## Years

- **2026** — [session index](process-log/2026/index.md)

---

## Adding an entry

1. Write `process-log/<year>/<date>-<project>.md`, opening with a
   `## Session <date>` heading. Use the year the session ran; create the
   directory for a new year.
2. Add one row to `process-log/<year>/index.md`, linking the date cell at the
   entry as a bare filename — the index sits beside its entries. For a new year,
   create that index from the previous year's and add it to the Years list above.
   An index nothing links is an unreachable file the suite fails on.

Never grow an index with an entry body. An index is bounded by one row per
session; the ledger it indexes is not, which is why they are separate files
([#152](https://github.com/gregoryfoster/skills/issues/152)). Keep the row to a
headline — an index is the artifact an agent loads to orient, and it stops
working the moment it is dense enough that finding a session means opening
entries speculatively.

**Row length is the budget.** Every file here, a year index included, is bound by
the repo's 10,000-token per-doc budget, and a year index is the one doc every
session of that year appends to. Splitting by year (#183/#197) bounded the file;
it did not create headroom, because 2026's first five months already fill it. At
~7 sessions a month the affordable row is about **400 bytes** — the length of the
shortest rows in the 2026 index, not the 1,500-byte rows further down it. Write
the row that size, and put the rest in the entry file, which is what the entry
file is for.
