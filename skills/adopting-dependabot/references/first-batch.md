# The first batch is the test

Pushing the config is outward-facing: on watcher, the config was picked up
seconds after the push and four PRs opened within about a minute, all green
(watcher#354–#357, 2026-10-09). So the first batch *is* the step-1 test of
everything the inventory couldn't read.

**Before the push, list the open Dependabot PRs.** A security PR opened before
the config can't be rebased once it lands, and closing it gives up the fix:
land each first, or by hand
([merge-paths.md](merge-paths.md#security-prs-opened-before-the-config)).

## Watch it land

```bash
gh run list --event dynamic --limit 30 --json displayTitle,conclusion,createdAt -q '.[] | select(.displayTitle | test(" - Update #")) | [.displayTitle, .conclusion, .createdAt] | @tsv'
gh pr list --author app/dependabot --json number,title,headRefName,createdAt
```

- **`Dependabot Updates` runs** are the updater itself, one per ecosystem and
  directory; their titles end ` - Update #<n>`. The same listing holds
  `Configured Graph Update` runs, which refresh the dependency graph and open
  no PR: the filter above leaves them out. A failed updater run opens no PR,
  and reads as "no updates available" everywhere else. Its log names the
  resolution error (a private index, a wrong directory).
- **Each PR's CI**: per job, the actor is `dependabot[bot]`, and the auth steps
  succeeded ([credential-context.md](credential-context.md)).
- **Expect one PR per moved dependency, all at once.** Grouped dev tooling is
  the one that needs work: one PR, many changelogs.

Record the result where the repo keeps state: the issue, the plan, or the
config's own comment.

## Before landing a major bump

Compare the proposed version with upstream's **newest release**
(`bash "<inventory.sh>" --upstream`, or the action's releases page). A gap is
one of two known causes, and **neither is a reason to hold the PR**: land what's
proposed, and file the gap.

| Gap | Cause | Seen |
|---|---|---|
| Proposed `@v7`; upstream at v10.2.0 | The action stopped publishing floating major tags. A major-form pin is proposed no further than the last one (`status: frozen`). Move it to an immutable tag or a SHA pin | `astral-sh/setup-uv`, watcher#360 |
| Proposed `4 → 6`; `v7` existed | A newly floated major isn't proposed at once. `setup-node`'s `v7` was published 2026-10-08, and `@dependabot recreate` on 2026-10-09 still proposed v6. The cause (metadata caching, or a cooldown) is unverified | watcher#355 |

Landing the smaller bump still helps: v6 already fixed the Node 20 deprecation
there.

## Read the changelog, not the diff

The diff of a bump PR is a version string. The value is in the release notes
between the two versions: notifier#45's turned out to be a CWE-400 fix five
minors back. Read every version in between, not just the newest.

## A workflow PR CI never runs

A workflow that runs only on `schedule` or `workflow_dispatch`
(`inventory.sh`'s `workflows[].scheduled_only`) isn't exercised by the PR's CI,
even when the PR bumps it. watcher's `context-cadence.yml` took checkout 5→7,
across v6's persisted-credentials change, untested. **Dispatch it once after
landing**, or read its next scheduled run:

```bash
gh workflow run <file>.yml && gh run list --workflow <file>.yml --limit 1
```

## File what's left

- Each **blocked** ecosystem from phase 2 gets its own issue with its options:
  a `registries:` entry (possibly with OIDC to a registry Dependabot supports),
  the index served over HTTPS, or a scheduled cap-staleness check as a fallback.
  The private index is per-cohort infrastructure, so the skill detects it and
  files it; it doesn't build it.
- Each **generator** that downgrades a pin, upstream ([merge-paths.md](merge-paths.md#generated-workflows)).
- Each **frozen** action that isn't moved in this change.
