# Linked projects — cross-repo `codebase_search`

Phase 3 item 4. Read this when `LINKED_PROJECTS` is set (it defaults to none),
when a re-run finds an older install's `SOCRATICODE_LINKED_PROJECTS`, or for the
`.claude/settings.local.json` ignore rule an external store's key depends on.

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
upstream template ignored it, and don't settle for any rule that happens to
match: only a rule in a file the repo tracks protects every clone. A global
excludes file, or `.git/info/exclude`, protects one machine — which is how
`CannObserv/broker`, a public repo, came one `git add -A` from the cohort's
key. So the rule goes into the root `.gitignore` and into the index, whatever
else already matches. Run this from the repo root, and relay any `STOP` line
to the operator rather than working around it:

```bash
f=.claude/settings.local.json
if git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
  echo "STOP: $f is tracked — git rm --cached it, and check its history, before any key goes in" >&2
else
  if ! grep -qxF -- "$f" .gitignore 2>/dev/null \
    || { ! git check-ignore -q -- "$f" && [ "$(tail -n 1 .gitignore)" != "$f" ]; }; then
    printf '\n%s\n%s\n' \
      '# Machine-specific Claude Code settings (local permissions, env, linked projects)' \
      "$f" >> .gitignore
  fi
  git show :.gitignore 2>/dev/null | grep -qxF -- "$f" || git add -- .gitignore
  git check-ignore -q -- "$f" \
    || echo "STOP: $f is still not ignored — a .gitignore below the root re-includes it" >&2
fi
```

Each line answers a way the check used to pass while the key sat exposed
([#287](https://github.com/gregoryfoster/skills/issues/287)):

- **A tracked file stops it first.** `git check-ignore` reports a tracked path
  as not ignored, and no rule untracks it.
- **The rule is appended unless the root `.gitignore` holds it *and* it is in
  force.** `git check-ignore -q` exits 1 on a negated match, so `.claude/*`
  followed by `!.claude/*.json` gets the line appended after the negation,
  where it wins. `-v` is no test: it names a `!` rule too, and exits 0.
- **It is staged until the index holds it**, so a re-run finds the rule and
  appends nothing. Commit `.gitignore` with `.socraticode.json` in Phase 3.
- **It ends on the check that matters**, the file ignored. A `.gitignore` in
  `.claude/` that re-includes the file outranks the root's, and appending
  again cannot fix that, so that case stops for the operator too.

The leading `\n` keeps the block from fusing onto a trailing-newline-less last
rule; the header matches the `init-project-fastapi` template's. Repos
bootstrapped by `init-project-fastapi` already carry this rule; the guard
covers repos indexed standalone.
