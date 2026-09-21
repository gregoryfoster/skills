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

## Installing the doctor: twice, and from the first vendor that can

The hook installs `.skills/doctor.sh` through `install-doctor.sh` — a no-op when the content already matches — from **two** call sites:

- **Every session, ahead of the lock and the `main` gate.** This is the working-tree repair: a deleted doctor self-heals at the next session start, on any branch. Committing it stays behind both gates ([#86](https://github.com/gregoryfoster/skills/issues/86)).
- **Again after a successful submodule update, ahead of the commit** ([#299](https://github.com/gregoryfoster/skills/issues/299)). The first call ran the *pre*-bump installer against the *pre*-bump doctor, so without the second, the session that advanced the pointer committed the old doctor beside the new pointer, and the refreshed one waited for the next session to reach the first call. Measured in CannObserv/observo: a committed doctor ten days stale, missing `check_unpushed()` entirely, so the "main is ahead of its upstream" sensor did not exist there.

Neither call fires in a checkout whose `skills-vendor/*` are empty gitlinks — every fresh linked worktree, until something initializes them. The glob finds no installer, and there is no vendored doctor to install from anyway; the hook itself, a symlink into that same tree, does not start there either (`SKILL.md` covers that first session). So "every session" means every session in a checkout with its submodules populated.

**The first installer that succeeds wins**, in glob order ([#300](https://github.com/gregoryfoster/skills/issues/300)). The glob spans every vendored repo, so a second one shipping `managing-skills` is the fallback when the first fails; the loop used to stop after the first attempt either way. Each failure is logged, naming the installer, and when every one fails the session hears it on stderr — the channel every other failure here uses — once per run, although the install runs twice. A failing install otherwise leaves a stale doctor with one log line as its only trace.

## Pushing what it commits ([#293](https://github.com/gregoryfoster/skills/issues/293))

The hook commits pointer bumps **and pushes them**. It used to only commit.

A commit that lands locally and is never pushed is functionally untracked for every consumer but the machine that wrote it: CI, fresh worktrees and every other clone see nothing, and the consumer's `main` silently diverges from `origin/main` until something reads it. Most repos never notice. A repo with a deployed service reading the checkout notices all at once, at the worst possible moment — `CannObserv/replicator`'s `systemd` unit refuses to start a checkout carrying unpushed commits, and a one-line bump from this hook stranded that service twice in two weeks: 13 hours on 2026-09-03, 56 minutes on 2026-09-16, neither recoverable without an operator.

Committing to `main` was never the problem. A sibling workflow commits `chore: weekly context measurement` to `main` and pushes it, and it surfaces as a routine rebase.

This is [#86](https://github.com/gregoryfoster/skills/issues/86)'s defect one level up. #86 made the hook commit the `.skills/doctor.sh` it installs, because without that it wrote a file nothing ever tracked: **four of twelve audited consumers had been reinstalling an untracked doctor for weeks**, so their fresh worktrees and CI clones had none and the Phase 1 preflight silently short-circuited. #86 stopped the doctor being untracked; this stops the commit being unshared.

### The shape: reconcile, not commit-then-push

The retry is a **reconcile pass that runs at every session start, ahead of the once-per-day lock and the `main` gate** — not a `git push` bolted onto the commit step. Three things a bolted-on push does not cover:

- The lock is stamped *before* the work, deliberately, so a push that failed on the commit path would wait a whole UTC day to retry.
- The harness can kill this hook between commit and push — a `timeout` SIGKILL, which the ERR-trap backstop cannot catch — leaving exactly the state the fix exists to prevent. A separate pass heals it at the next session.
- Consumers stranded by an older vendored copy of the hook are healed with nobody visiting the machine.

### The guards

- **A refusal blocks the commit too.** Whenever the reconcile declines to push — for any of the reasons below — the run also commits nothing. A run that has concluded it cannot share a commit and then makes one has manufactured the stranding this step exists to prevent, and the second call site would only refuse it again. Nothing is lost by waiting: the refreshed content is already in the working tree.
- **It reads the whole range or refuses.** The subject read is `git log --no-show-signature --format=%s '@{u}..HEAD'`, and the number of subjects it returns must equal the number `git rev-list --count` gave. The `|| true` that keeps a failed git non-fatal would otherwise turn an unreadable range into zero unrecognised subjects — the authorship check below concluding "every one of them is mine" on no evidence at all, in the one direction that publishes an operator's work. `--no-show-signature` is part of the same guard: with `log.showSignature = true` and signed commits, git's verification lines inflate the count and the check refuses every session forever.
- **It only ever touches commits it wrote.** Before pushing, every commit in `@{u}..HEAD` must carry one of the three subjects the hook authors. Anything else and it pushes nothing *and commits nothing that run*: a push is a push of the whole branch, so it would publish work the operator chose not to share — a larger overreach than the stranding being fixed. A mix of theirs and ours says so on stderr; purely operator commits are logged and pass in silence, because unpushed work on a local `main` is normal in plenty of repos and a session-start warning there would train the reader to ignore the channel.
- **A failed push is rolled back**, so the checkout never diverges: `git reset --soft` plus an unstage scoped to the paths those commits touched, matching what the commit step already does on a failed commit. **Never `--hard`**, which the issue originally proposed: `--hard` is whole-tree, is *not* bounded by this hook's add scope — that discipline is a property of `git add` — and discards uncommitted edits anywhere in the checkout. Measured, it also deleted the `.skills/doctor.sh` the same run had just installed, undoing #86's self-heal.
- **It resets to `HEAD~N`, not to `@{u}`.** On a *diverged* `main` — ours ahead, origin also ahead — resetting to `@{u}` moves HEAD onto the remote's tree while the working tree stays on ours, so every file the remote added reads as deleted-by-us. `HEAD~N` stays on this checkout's own history; the completeness, authorship and merge-commit refusals above are what make that arithmetic sound — a range this hook cannot fully read, or does not fully own, is a range it does not touch.
- **One refusal per run.** The block above is set once and read for the rest of the run. A rollback leaves the refreshed content dirty, so the commit step would otherwise re-stage it, re-commit it and re-attempt the push just refused — two network waits inside a 120s ceiling, and the same warning twice.
- **It never pulls.** Landing a bump on a checkout that is behind would mean advancing local `main`, and on a deployed VM `main` *is* the running code; a SessionStart hook updating deployed application code is a far larger authority than moving a submodule pointer. A stale consumer gets no bump, loudly, until a human syncs.
- **The commit is scoped to a pathspec**, not left to sweep the index. `SKILL.md`'s "matches diff scope to add scope" was true of the *add* and of unstaged dirty work, but `git commit` with no pathspec commits the whole index — so anything the operator had staged before the session began went into the hook's commit under the hook's own message. A local wart while the hook only committed; a published one now that it pushes. The pathspec is what is actually staged under the hook's paths, not the path list itself: `git commit -- <path>` fails outright on a path git does not know, and `.skills/doctor.sh` is exactly that where a consumer gitignores `.skills/`, so passing the list verbatim fails the whole commit there and strands the submodule bump too.
- **It never force-pushes**, in any spelling, and uses an explicit refspec rather than a bare `git push` — under `push.default=matching` that pushes every matching branch.

A rollback reverts only the *recorded pointer*. The refreshed submodule content stays in the working tree, so the skills themselves keep working and the next session retries. That is why the rollback is the fix here and the push is the optimization: the service was stranded by `ahead 1`, not by a stale skills pin.

### What to expect where it cannot push

Where `main` is protected, or the hook has no push credentials, every push is rejected and rolled back, so the pointer never advances and the skills freeze at the vendored commit — loudly, on stderr, every session. That is the intended degradation: a consumer that cannot share a bump should not be silently accumulating them.

`.skills/doctor.sh` warns whenever `main` is ahead of its upstream, which is the only cohort-wide sensor that can exist for this — an unpushed commit lives on exactly one machine, so nothing reachable through the GitHub API can see it.

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
