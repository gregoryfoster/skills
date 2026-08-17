# Linked projects — cross-repo `codebase_search`

Phase 3 item 4. Read this only when `LINKED_PROJECTS` is set; the parameter
defaults to none, so most installs skip it entirely.

## What it does

`SOCRATICODE_LINKED_PROJECTS` points one indexed project at sibling checkouts so
`codebase_search` spans them — archiver links watcher + notifier this way. Each
linked project must **itself be indexed** to contribute results; a linked path
that was never indexed contributes nothing and says nothing about it.

## Write it into `.claude/settings.local.json`

Write `SOCRATICODE_LINKED_PROJECTS=<comma-separated abs paths>` into the `env`
block of `.claude/settings.local.json` — create the file if absent, merge if
present, and preserve every other key.

## Then make sure that file is git-ignored

These are absolute paths to one VM's checkouts, so the file must stay out of
version control. Don't assume an upstream template ignored it: if
`git check-ignore -q .claude/settings.local.json` fails, append a newline-safe
block to `.gitignore` (create it if absent) — matching the
`init-project-fastapi` template's header:

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
