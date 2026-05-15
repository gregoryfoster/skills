---
name: writing-plans
description: A discipline for writing a short, reviewed plan before any non-trivial implementation. Plans live under a configurable plans directory (default `docs/plans/`) and follow a prescribed shape — problem, approach, tradeoffs, steps, open questions. Use when the user says "write a plan", "plan this", or "let's plan".
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git for plan-directory resolution; no other runtime dependencies.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: write a plan, plan this, let's plan
---

# Writing Plans

A discipline for writing a short, reviewed plan before non-trivial implementation. Plans capture problem, approach, tradeoffs, steps, and open questions in a prescribed structure so reviewers can react to a concrete artifact instead of an intent.

**Activation triggers:** "write a plan", "plan this", "let's plan".

## The Iron Law

```
NO NON-TRIVIAL IMPLEMENTATION WITHOUT A WRITTEN, REVIEWED PLAN
```

If the work is non-trivial (see Phase 1) and there is no plan committed to the plans directory and acknowledged by the user, you cannot start implementing. Write the plan first.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "I'll plan as I go — the structure will emerge" | Mid-stream replanning is more expensive than upfront planning, and the user can't review what isn't written. Write the plan first. |
| "The GitHub issue description is the plan" | Issues capture *what* and *why*; plans capture *how*, *tradeoffs considered*, and *steps*. They are not interchangeable — write the plan even when the issue is detailed. |
| "This is small enough to skip" | Phase 1 exists to make that call deliberately. If you're tempted to skip because typing the plan feels slow, you're skipping for the wrong reason. |

## Parameterized invocation

Trigger phrases may include the plan topic inline — e.g., `write a plan for auth rotation`, `plan this migration`, `let's plan the index rebuild`. Apply the appended topic as the explicit subject; skip the "what should we plan?" fallback.

## Plans directory resolution

Every plan write resolves the target directory in this order (first match wins):

1. **`PLANS_DIR` env var** (highest priority) — explicit override for one-off invocations
2. **`.skills/plans_dir` file** — single-line file under the repo root; project's persistent default
3. **`<repo-root>/docs/plans/`** — fallback when neither of the above is set

Invoke `bash scripts/resolve-plans-dir.sh` to print the resolved directory. The plan filename is `YYYY-MM-DD-<topic-slug>.md`, where `<topic-slug>` is the topic lowercased with non-alphanumerics replaced by `-`.

## Procedure

### Phase 1 — Decide whether a plan is appropriate

A plan is appropriate when at least one applies:

- The work spans multiple files or modules, or won't fit in one sitting
- Two or more reasonable approaches exist and the user should choose
- The change touches shared state (DB schema, public API, deploy config, auth)
- The operation is hard to reverse (migrations, deletions, force-pushes, third-party calls)
- The change crosses a stack boundary the user has not yet inspected (e.g., backend touching frontend assumptions)

A plan is **not** required for:

- One-file bug fixes with obvious causes
- Mechanical renames, formatting passes, doc typo fixes
- Following an existing plan's prescribed steps (the plan itself is the plan)

If none apply, stop. Just do the work. Don't write a plan because the trigger phrase fired.

### Phase 2 — Draft the plan

Copy [`assets/plan-template.md`](assets/plan-template.md) to `<plans-dir>/YYYY-MM-DD-<topic-slug>.md` and fill in:

- **Problem** — what is broken / missing / unclear, and why it matters. One short paragraph. Not how you'll fix it.
- **Approach** — the chosen path, in one paragraph. Concrete enough that a reviewer can disagree.
- **Tradeoffs / alternatives** — the realistic alternatives considered, each with one line on why it was rejected. If there are no alternatives, say so explicitly and explain why this is the only path.
- **Steps** — a numbered list. Each step independently verifiable (a reader should be able to tell, mid-execution, whether step N is done). Aim for 3–10 steps; if you have 20, the plan is too granular or the work is too large.
- **Open questions / risks** — anything the user must decide before or during execution. Empty is fine; pretending none exist is not.

Keep the plan short. A reader should consume it in under 5 minutes. If it doesn't fit, split the work.

### Phase 3 — Request review

Commit the plan (don't wait for implementation), then surface it to the user with a one-line pointer (amend the commit if review demands changes; new plan only on pivot — see Phase 4):

```
Plan written: <plans-dir>/YYYY-MM-DD-<topic-slug>.md — review before I start.
```

Wait for explicit acknowledgment. "Looks good", "proceed", or directed edits all count. Silence does not.

### Phase 4 — Execute against the plan

Work through the steps in order. If a step reveals the plan is wrong:

- **Small revision** (one step's mechanics changed, no scope change): edit the plan inline, commit the edit, mention it in the next response.
- **Pivot** (approach or scope changed): stop. Write a new plan with a `Supersedes: <old-plan-path>` line in the frontmatter. The old plan stays in the directory as a record.

Never silently diverge from a plan the user reviewed. Either revise it or replace it.

## When the user pushes back on the plan itself

Treat plan-review feedback as first-class. The plan is the artifact under review in Phase 3 — not the code that follows. Edits requested at this phase are cheap; the same edits after implementation are not.

## Notes

- Plans are commit-able artifacts. They survive the work that follows them and form a record of *why* the codebase looks the way it does.
- The plans directory is project-configurable precisely because some projects keep plans alongside other design docs (`docs/plans/`), others under a tooling-vendored path. Use the resolution order; don't hardcode.
- `Supersedes:` chains let a topic's planning history be reconstructed without git archaeology. Use them on pivot, not on every minor edit. The template's frontmatter exposes this as a lowercase YAML key — set `supersedes: <relative path to prior plan>` on the new plan.
