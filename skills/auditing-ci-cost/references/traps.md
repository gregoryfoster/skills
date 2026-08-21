# Traps

Every one of these was hit for real during the two source audits
([#212](https://github.com/gregoryfoster/skills/issues/212)). Several were
nearly shipped bugs. They share one property, which is the reason they are
collected rather than scattered: **each is a GitHub behaviour that differs from
the natural reading of GitHub's documentation**, and each was settled by
running a probe.

That is the stance. When the docs and a probe disagree about what Actions will
do, the probe wins and the probe's result gets written down next to the rule it
justifies — otherwise the next reviewer "corrects" the working version back to
the documented one. That happened.

## 1. `paths-ignore` on `pull_request` sees the whole PR diff

Not the incremental push. A docs-only commit pushed into an open PR whose diff
already touches `ci.yml` **runs the workflow**. Predicted otherwise; probed;
wrong.

Consequence for the audit: a saving estimated from "how many pushes were
docs-only" is wrong. Estimate from **whole-PR file lists**, which is what the
replay in [path-filter-replay.md](path-filter-replay.md) already does.

## 2. A path-filter probe must run from the branch carrying the filter

Basing the probe on the default branch proves nothing. `pull_request` runs the
workflow **from the merge commit**, so the base branch's filter-less version is
what is in effect. A probe PR that opens against a main without the filter is
testing the old workflow and will happily report "it ran" for a filter that
would have skipped.

## 3. `workflow_call` inherits the **caller's** `github` context

In `cannobserv`, `publish.yml` calls `ci.yml` on a tag push. Inside the called
workflow:

- `github.event_name` is still `push`
- `github.event.head_commit.message` is still `release: vX.Y.Z`

A job condition matching only on the commit message would have **silently
disabled the release gate** — the job would evaluate false in exactly the
situation it exists for, and nothing would fail. A `github.ref` guard is what
makes such a condition safe.

**Rule:** any commit-message-based job condition inside a workflow that is ever
`workflow_call`-ed needs a `github.ref` guard beside it and a comment saying
why.

## 4. Blanket `**.md` can be a bug, not a saving

All four `cannobserv` packages declare `readme = "README.md"` in their
`pyproject.toml`, which makes package READMEs **build inputs**. Ignoring `**.md`
would have let the exact packaging regression the build smoke-test exists to
catch through unvalidated.

Markdown is the most tempting ignore pattern and the one most likely to be
wrong, because "documentation" is a statement about intent and "build input" is
a statement about the packaging config.

## 5. A repo-metadata file can be a build input

Root `.gitignore` looks like pure metadata. Hatchling's file selection is
VCS-aware, and the probe was unambiguous: appending a module path to the
**root** `.gitignore` **dropped that module from the sdist** — 199 entries down
to 198.

Ignoring it would have shipped source-dropping sdists silently, because the
release workflow asserts artifact **count**, not contents.

**Rule:** enumerate the real build inputs by *building and inspecting the
artifact*, never by intuition about what a file "is". See
[path-filter-replay.md](path-filter-replay.md#enumerating-build-inputs).

## 6. GitHub's filter globs are more lenient than the docs read

Probe PR #728 on `cannabis.observer-wordpress` established that **a leading
`**/` matches zero directories**, so `**/composer.json` *does* match the root
`composer.json`.

This one earned its place twice: a review round had already "corrected" the
committed filter on the stricter reading before the probe ran. The probe result
now lives inline next to the pattern, because a correct rule with no evidence
attached gets re-broken by the next careful reader.

## 7. YAML folded scalars (`>-`) preserve newlines on indented continuations

A more-indented continuation line inside a `>-` block keeps its newline, which
embeds a literal `\n` **inside a `${{ }}` expression**. The expression then
does not evaluate as written and the job condition silently misbehaves.

**Rule:** keep job conditions on one line.

## 8. A two-dot diff on a stacked PR shows phantom reverts

GitHub's PR view is **three-dot** (against the merge base). Reviewing a stacked
branch with a two-dot diff shows the parent branch's changes as reversions that
do not exist. Verify with a trial merge before "fixing" anything.

This is a review trap rather than a cost one, but it belongs here: it is how a
correct CI change gets reverted during the review of the PR that introduces it.

## The general form

Six of the eight above are the same mistake in different clothes: **a belief
about what GitHub will do, held confidently, sourced from prose.** The audit
procedure that survives them is the one in Phase 5 — anything the docs do not
settle gets a probe PR, and the probe's result is recorded where the rule
lives, not in the PR that produced it.
