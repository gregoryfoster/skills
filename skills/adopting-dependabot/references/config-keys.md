# Config keys: each one's silent failure

Every key below has a default or a typo that produces **no PRs and no
error** anywhere a person looks. Comment each key in the config with the
failure it prevents. The guard test pins each one.

| Key | The silent failure | Evidence |
|---|---|---|
| `version: 2` | Version 1 configs are ignored without an error | |
| `package-ecosystem` | A typo (`github_actions`, `python`) opens nothing, and reads as "no updates available" | notifier#33 |
| `directory` / `directories` | `/` is what scans `.github/workflows/`. `/.github/workflows` is silence. An `action.yml` elsewhere (a composite action) needs its own directory listed | notifier#33 |
| `schedule.interval` | Missing, and Dependabot rejects the block, visibly only in its own tab | notifier#33 |
| `open-pull-requests-limit` | Defaults to **5**. Past the limit Dependabot opens **nothing**, security updates included, and says so nowhere. notifier's dev-tools group and SDK table went silent for **five weeks** | notifier#103 |
| `versioning-strategy` | uv/pip: the default `auto` resolves to `widen` for a library, which uv doesn't support (dependabot-core#15290). Pin `increase-if-necessary`. Even that raised floors on in-range bumps under uv, so read a library's floor before merging | notifier#33, #103 |
| `commit-message.prefix` | The default subject, `Bump x from a to b`, matches no `type:` convention. `prefix: chore` gives `chore: bump …` | watcher#354–#357 |
| `groups` | Without a dev group, dev tooling (ruff alone ships minors about monthly) buries runtime bumps. Runtime dependencies stay individual PRs | notifier#33 |
| `ignore` | Lockstep pins, which move with another repo, need one, or the bot proposes moves nobody should take | watcher#358 |

## The PR limit, derived and not guessed

The limit must exceed what one batch can open at once. The guard test derives
it from the repo, so it stays true as the repo changes:

- `github-actions`: one PR per distinct action (`inventory.sh`'s
  `actions.count`), unless they're grouped.
- uv/pip: every runtime dependency (each is its own PR), plus each group once
  per directory.

## Grouping `github-actions`

Default to **one PR per action**: a major bump changes inputs, and each
deserves its own changelog read. Grouping them all into one PR runs CI once
instead of N times; offer it where CI is expensive (`auditing-ci-cost`), at the
cost of one red check holding back every bump.

## A starting config

```yaml
# Proposes the bumps nothing else does. Each PR is gated by CI like any
# other. Guarded by tests/ci/test_dependabot.py: a mistyped config stops
# producing PRs without erroring anywhere a person looks.
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/" # scans .github/workflows/
    schedule:
      interval: "weekly"
    # The default is 5, and past it Dependabot opens nothing and says so
    # nowhere. One PR per action; the test derives the bound.
    open-pull-requests-limit: 10
    # The PR's commit lands as-is, so it takes the repo's form.
    commit-message:
      prefix: "chore"
```

A `uv` block, once phases 2 and 3 clear it:

```yaml
  - package-ecosystem: "uv"
    directories: ["/"] # one per uv.lock
    schedule:
      interval: "weekly"
    # `auto` resolves to `widen` for a library, unsupported for uv.
    versioning-strategy: increase-if-necessary
    open-pull-requests-limit: 25 # above runtime count + groups × directories
    commit-message:
      prefix: "chore"
    groups:
      dev-tools:
        dependency-type: "development"
    ignore:
      - dependency-name: "<lockstep-pinned package>" # why, and its issue
```
