# Linked projects — cross-repo `codebase_search`

Phase 3 item 4. Read this only when `LINKED_PROJECTS` is set; the parameter
defaults to none, so most installs skip it entirely.

## What it does

`linkedProjects` points one indexed project at sibling repos so
`codebase_search` spans them — archiver links watcher + notifier this way. Each
linked project must **itself be indexed** to contribute results; a linked path
whose collection was never indexed contributes nothing and says nothing about
it.

Links reach `codebase_search` only, and only when a call passes
`includeLinked: true`. A linked path that does not exist is dropped by the
server without a word, so the daily health check names every configured link
that does not resolve — from `.socraticode.json`'s `linkedProjects` and from
`SOCRATICODE_LINKED_PROJECTS` ([#281](https://github.com/gregoryfoster/skills/issues/281)).
It cannot see whether a link that *does* resolve was ever indexed.

## Write them into `.socraticode.json`, relative to the repo root

Each sibling goes into the `linkedProjects` array of `.socraticode.json` at the
repo root, as a path **relative to the repo root** — `../archiver`, not
`/home/<user>/archiver`. Create the file if absent; merge if present, keeping
`projectId` and every other key. Commit it.

Relative is what lets one committed file work on every host: an entry resolves
against wherever the repo is checked out, where an absolute path names one
host's layout ([#287](https://github.com/gregoryfoster/skills/issues/287)). The
driver reports an absolute entry in the committed file as a note.

The path only selects which collection to query. Upstream resolves each entry
to a directory, reads that directory's own `projectId` (or hashes its path),
and searches the collection it names — no source is read from it. So on an
external store a one-file stub is a complete link
([`external-store.md`](external-store.md#one-host-per-projectid)); on a managed
store the sibling must be a checkout this host indexed, since its collection
lives in this host's Qdrant.

## Migrating an older install

Installs before #287 wrote `SOCRATICODE_LINKED_PROJECTS=<comma-separated
absolute paths>` into the `env` block of `.claude/settings.local.json`. On a
re-run, move each entry into `.socraticode.json`'s `linkedProjects`, rewritten
relative to the repo root, then delete that key from the `env` block and keep
every other key. Upstream reads both sources and de-duplicates by resolved
path, so the file is correct as soon as it is written; deleting the variable
retires the second copy. Name each migrated entry in the report.

## Make sure settings.local.json is git-ignored

Linked projects no longer need the file, but an external store's API key lives
there, and an older install's absolute paths may still. Don't assume an
upstream template ignored it: if `git check-ignore -q
.claude/settings.local.json` fails, append a newline-safe block to `.gitignore`
(create it if absent) — matching the `init-project-fastapi` template's header:

```gitignore
# Machine-specific Claude Code settings (local permissions, env, linked projects)
.claude/settings.local.json
```

Ensure a preceding blank line so the block can't fuse onto a
trailing-newline-less last rule:

```bash
printf '\n%s\n%s\n' \
  '# Machine-specific Claude Code settings (local permissions, env, linked projects)' \
  '.claude/settings.local.json' >> .gitignore
```

Repos bootstrapped by `init-project-fastapi` already carry this rule; the guard
covers repos indexed standalone.
