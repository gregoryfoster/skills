# Replaying a path filter against history

A `paths:` / `paths-ignore:` filter is a claim about the future — "these
changes never need CI" — shipped on the strength of an intuition. The replay
turns it into a measurement against the past, and it is what took Finding 3
from an estimate to a measurement in both source audits.

**Do not commit a filter without a replay.**

## The gate

Two numbers come out, and only one of them is a gate:

| Number | Meaning | Gate |
|---|---|---|
| **skips** | commits the filter would have skipped | none — this is the saving |
| **false skips** | commits carrying code the filter would have skipped | **must be zero** |

A **false skip** is a commit that touched a build input, or a file the test
suite covers, and that the candidate filter would have prevented from running.
One is enough to reject the filter. Not "few", not "acceptable" — **zero false
skips**, because the whole value of a filter is that it never has to be
reasoned about again.

Measured results from the two audits:

- `wp#726` — replayed against **45 merged PRs**, zero mismatches.
- `cannobserv#355` — replayed against **104 main-push commits**: 13 skips, **0
  false skips**.

## Procedure

1. **Enumerate the history** the filter would govern. For a `push` filter on
   the default branch, that is the main-push commits in the window. For a
   `pull_request` filter, it is the **whole-PR file lists** of merged PRs — see
   trap 1 in [traps.md](traps.md), the incremental push is not what GitHub
   evaluates.

2. **Get each commit's file list.** For merge commits use
   `git show --first-parent --name-only <sha>`. That is the push range GitHub
   uses for a merge, and the plain `git show` of a merge lists nothing.

3. **Apply the candidate patterns** to each file list, using GitHub's glob
   semantics — including the leniency probed in trap 6, where a leading `**/`
   matches zero directories.

4. **Classify.** A commit is a *skip* if every file matches an ignore pattern.
   A skip is *false* if any of those files is a build input or is covered by a
   test the skipped workflow runs.

5. **Report** skips, false skips, and the estimated saving in billed minutes —
   `skips × (jobs per run) × (mean billed per job)`, taken from the Phase 1
   census rather than from a workflow reading.

6. **Probe** the filter live before trusting it, from a branch that carries the
   filter (trap 2), and record the probe's result inline next to the pattern.

## Enumerating build inputs

Step 4 is only as good as the build-input list, and this is where both audits
nearly shipped a bug. **Build and inspect. Do not reason about what a file
is.**

- Python / hatchling — `uv build`, then `tar -tzf dist/*.tar.gz` and compare
  entry counts before and after touching the candidate file. That probe is what
  caught the root `.gitignore` dropping a module from the sdist (199 → 198
  entries) while the release workflow, which asserts artifact *count*, stayed
  green.
- Node — check `files` in `package.json` and what the bundler actually emits.
- PHP / Composer — check `autoload` roots and any `archive.exclude`.
- Any stack — anything named in packaging metadata is an input regardless of
  its extension. `readme = "README.md"` makes a README a build input, which is
  why a blanket `**.md` ignore is a bug and not a saving (trap 4).

The output of this step is a list, and the list belongs in the finding. It is
also the input `enforcing-architecture` needs to graduate the filter into a
test that discovers build inputs from disk rather than from a hand-kept
constant.

## Duplicated filter blocks

A workflow triggered on both `push` and `pull_request` carries the ignore list
**twice**, and the two copies drift. `cannobserv#356` shipped
`tests/test_ci_workflow.py` — 29 tests — asserting that the two `paths-ignore`
blocks stay identical and that no build input is matched by any pattern, with
the build inputs discovered from disk.

That is the Phase 7 handoff in concrete form: the audit produces the finding,
`enforcing-architecture` graduates it into a contract that fails when someone
adds a package whose README the filter would ignore.
