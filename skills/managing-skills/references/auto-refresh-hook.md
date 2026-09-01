# The auto-refresh hook's mechanics

Read this when debugging the hook or removing it by hand. Installing it needs
only `install-refresh.sh`, which `SKILL.md` covers.

<details>
<summary>What the installer does — read this when debugging it, not to execute it</summary>

1. **Symlinks** rather than copies, so upstream fixes propagate through the normal submodule refresh. The target is relative and derived from the vendor directory actually found, not from a hand-substituted `<owner>-<repo>` — that substitution is how a symlink ends up pointing at a plausible path that does not exist.
2. **Merges** `.claude/settings.json` with jq, dedupe-then-append: it creates `.hooks`/`.hooks.SessionStart` when absent, preserves every other hook and key, and strips any pre-existing entry for this hook first so a re-run cannot duplicate it.

The mechanism itself is `scripts/install-hook.sh`, which takes the hook's constants as arguments so all three hooks a consumer ends up with — this one and `init-socraticode`'s two — inherit one implementation and one set of hardening rounds ([#200](https://github.com/gregoryfoster/skills/issues/200)). `install-refresh.sh` is the wrapper that supplies this hook's; run it, not the generic one.

Two details in that merge are load-bearing, and `install-hook.sh` carries the full reasoning inline:

- **The command is anchored on `$CLAUDE_PROJECT_DIR`**, not the hook process's cwd ([#110](https://github.com/gregoryfoster/skills/issues/110)). The `${CLAUDE_PROJECT_DIR:-.}` fallback matters: unset, a bare `"$CLAUDE_PROJECT_DIR/…"` becomes `bash "/.claude/hooks/…"` and errors on every session start, where `.` degrades to exactly the old behaviour.
- **The strip matches the script path, not the whole command.** An equality test would skip an entry written in the older cwd-relative form — duplicating the hook, and leaving the original unremovable by the uninstall filter.
- **The entry carries an explicit `timeout`, and a re-run keeps whatever is already there** ([#259](https://github.com/gregoryfoster/skills/issues/259)). Each hook's figure lives in its `<hook>.install` manifest — 120 for this one and for `socraticode-health.sh`, both of which reach the network; 5 for `socraticode-reminder.sh`, which is one `echo` — so the constants stay beside the hook they configure rather than in a branch inside the installer. Without a `timeout` the harness default applies, and for a hook that stamps a once-per-UTC-day lock *before* doing its work, a kill consumes the day's attempt and reports nothing: silent-when-clean becomes indistinguishable from silent-when-killed, with no retry until tomorrow. And because the merge is dedupe-then-append, it used to rebuild the entry from constants and *discard* a `timeout` a consumer had added by hand — the repair silently undone by the tool that prescribed it. A value already on the entry now wins over the flag; the run names both numbers, and `--check` reports the disagreement without failing on it.

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
