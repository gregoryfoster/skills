# The auto-refresh hook's mechanics

Read this when debugging the hook or removing it by hand. Installing it needs
only `install-refresh.sh`, which `SKILL.md` covers.

## What the installer does

<details>
<summary>What the installer does — read this when debugging it, not to execute it</summary>

1. **Symlinks** rather than copies, so upstream fixes propagate through the normal submodule refresh. The target is relative and derived from the vendor directory actually found, not from a hand-substituted `<owner>-<repo>` — that substitution is how a symlink ends up pointing at a plausible path that does not exist.
2. **Merges** `.claude/settings.json` with jq, dedupe-then-append: it creates `.hooks`/`.hooks.SessionStart` when absent, preserves every other hook and key, and strips any pre-existing entry for this hook first so a re-run cannot duplicate it.

The mechanism itself is `scripts/install-hook.sh`, which takes the hook's constants as arguments so all three hooks a consumer ends up with — this one and `init-socraticode`'s two — inherit one implementation and one set of hardening rounds ([#200](https://github.com/gregoryfoster/skills/issues/200)). `install-refresh.sh` is the wrapper that supplies this hook's; run it, not the generic one.

Two details in that merge are load-bearing, and `install-hook.sh` carries the full reasoning inline:

- **The command is anchored on `$CLAUDE_PROJECT_DIR`**, not the hook process's cwd ([#110](https://github.com/gregoryfoster/skills/issues/110)). The `${CLAUDE_PROJECT_DIR:-.}` fallback matters: unset, a bare `"$CLAUDE_PROJECT_DIR/…"` becomes `bash "/.claude/hooks/…"` and errors on every session start, where `.` degrades to exactly the old behaviour.
- **The strip matches the script path, not the whole command.** An equality test would skip an entry written in the older cwd-relative form — duplicating the hook, and leaving the original unremovable by the uninstall filter.

</details>

## Uninstalling by hand

`install-refresh.sh --uninstall` does both halves. The manual equivalent:

Remove the symlink:

```bash
git rm .claude/hooks/skills-submodule-update.sh
```

Strip the matching entry from `.claude/settings.json`, preserving any other `SessionStart` entries. The `if .hooks.SessionStart then ... else . end` guard makes this safe to run against an already-uninstalled file or one that never had a `hooks` block, and the `contains` test — rather than string equality — removes an entry written in either command form, so an install predating [#110](https://github.com/gregoryfoster/skills/issues/110) is still removable. It strips matching **hooks** and drops only a group it emptied, never a whole matcher group — a group can hold several hooks, and dropping it silently deletes its group-mates' registrations ([#222](https://github.com/gregoryfoster/skills/issues/222)).

```bash
jq 'if .hooks.SessionStart then
      .hooks.SessionStart |= map(
        if (.hooks | type) == "array"
        then (.hooks | length) as $n
           | (.hooks |= map(select((.command? // "") | tostring
               | contains("skills-submodule-update.sh") | not)))
           | select($n == 0 or (.hooks | length) > 0)
        else . end)
    else . end' \
   .claude/settings.json > .claude/settings.json.tmp \
  && mv .claude/settings.json.tmp .claude/settings.json
```

Stage and commit:

```bash
git add .claude/settings.json
git commit -m "chore: disable skills auto-refresh hook"
```

You may also want to delete the hook's files in `.git/` if you don't plan to reinstall. `skills-status.err` is a transient stderr scratch file the hook removes itself — it only survives a run that died mid-flight:

```bash
rm -f .git/skills-update.lock .git/skills-update.log .git/skills-status.err
```
