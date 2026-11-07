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
- **The entry carries an explicit `timeout`, and a re-run keeps whatever is already there** ([#259](https://github.com/gregoryfoster/skills/issues/259)). Each hook's figure lives in its `<hook>.install` manifest — 120 for this one and for `socraticode-health.sh`, both of which reach the network; 5 for `socraticode-reminder.sh`, which is one `echo` — so the constants stay beside the hook they configure rather than in a branch inside the installer. Without a `timeout` the harness default applies, and for a hook that stamps a once-per-UTC-day lock *before* doing its work — `socraticode-health.sh` does, and this one did until [#555](#a-run-killed-part-way-555) — a kill consumes the day's attempt and reports nothing: silent-when-clean becomes indistinguishable from silent-when-killed, with no retry until tomorrow. And because the merge is dedupe-then-append, it used to rebuild the entry from constants and *discard* a `timeout` a consumer had added by hand — the repair silently undone by the tool that prescribed it. A value already on the entry now wins over the flag; the run names both numbers, and `--check` reports the disagreement without failing on it.

</details>

## Installing the doctor: at each step, and from the first vendor that can

The hook installs `.skills/doctor.sh` through `install-doctor.sh` — a no-op when the content already matches — from **three** call sites:

- **Every session, ahead of the lock and the `main` gate.** This is the working-tree repair: a deleted doctor self-heals at the next session start, on any branch. Committing it stays behind both gates ([#86](https://github.com/gregoryfoster/skills/issues/86)).
- **Again after a successful submodule update, ahead of the commit** ([#299](https://github.com/gregoryfoster/skills/issues/299)). The first call ran the *pre*-bump installer against the *pre*-bump doctor, so without the second, the session that advanced the pointer committed the old doctor beside the new pointer, and the refreshed one waited for the next session to reach the first call. Measured in CannObserv/observo: a committed doctor ten days stale, missing `check_unpushed()` entirely, so the "main is ahead of its upstream" sensor did not exist there.
- **After every restore of the content** ([#550](#a-rollback-undoes-the-whole-bump-550)): the heal, a rolled-back push, a failed commit or update, and every [`pr`-mode](auto-refresh-hook/pr-mode.md) refresh, where it is always the run's last install.

No call fires in a checkout whose `skills-vendor/*` are empty gitlinks — every fresh linked worktree, until something initializes them. The glob finds no installer, and there is no vendored doctor to install from anyway; the hook itself, a symlink into that same tree, does not start there either (`SKILL.md` covers that first session). So "every session" means every session in a checkout with its submodules populated.

**The first installer that succeeds wins**, in glob order ([#300](https://github.com/gregoryfoster/skills/issues/300)). The glob spans every vendored repo, so a second one shipping `managing-skills` is the fallback when the first fails; the loop used to stop after the first attempt either way. Each failure is logged, naming the installer; when every one fails, stderr says so once per run, although a run can install several times (three call sites, the third once per restore), and only when the run's *last* install failed, so the report is that install's. A broken pre-bump installer that the bump replaces with a working one is not reported: the second call installed and committed a fresh doctor, which "left as it was" would deny. When the last install was a restore's, the report says instead that the doctor may not be the version the restored pointer ships: the second call may already have replaced it from the bump's installer. A failing install otherwise leaves a stale doctor with one log line as its only trace.

## Why the whole script is one `{ … }` block ([#306](https://github.com/gregoryfoster/skills/issues/306))

The hook is normally a symlink into the submodule its own `git submodule update` rewrites, and bash reads a script incrementally, resuming by byte offset. Were the file's bytes to change under a running hook, everything after the update would resume at an old offset into new content — mid-statement, on the path that commits and pushes. So the script is one brace group ending in `exit`: bash parses it to the closing brace before running any of it, and never reads past that brace. **Nothing may follow the brace, and the block must end in `exit`.** An edit that breaks either fails `tests/structural/test_hook_self_replacement.py`, which rewrites the running hook in place at the update and requires the rest of the run to commit and push as written.

That is defence in depth rather than the fix for a measured corruption. Git's checkout unlinks a file and creates a new one instead of rewriting it in place (measured on git 2.39.3), so the running hook keeps the inode it opened and git's update alone cannot garble it — the same test file pins that, by putting an unprotected copy through a real update. The braces cover the writers that do write in place — `cp` onto an existing file, a shell redirect — and a git that ever starts to. (`install` is not one: BSD's and GNU's both give the path a new inode.) Braces rather than a `main()` function, because they change nothing else about how the script runs.

`.skills/doctor.sh` is replaced under a running doctor too, by its own self-sync, and needs no braces: `install-doctor.sh` writes a temp file and renames it into place, so the running doctor keeps its inode — the reason a refresh applies from the doctor's *next* run.

## Pushing what it commits ([#293](https://github.com/gregoryfoster/skills/issues/293))

The hook commits pointer bumps **and pushes them**. It used to only commit.

A commit that lands locally and is never pushed is functionally untracked for every consumer but the machine that wrote it: CI, fresh worktrees and every other clone see nothing, and the consumer's `main` silently diverges from `origin/main` until something reads it. Most repos never notice. A repo with a deployed service reading the checkout notices all at once, at the worst possible moment — `CannObserv/replicator`'s `systemd` unit refuses to start a checkout carrying unpushed commits, and a one-line bump from this hook stranded that service twice in two weeks: 13 hours on 2026-09-03, 56 minutes on 2026-09-16, neither recoverable without an operator.

Committing to `main` was never the problem. A sibling workflow commits `chore: weekly context measurement` to `main` and pushes it, and it surfaces as a routine rebase.

This is [#86](https://github.com/gregoryfoster/skills/issues/86)'s defect one level up. #86 made the hook commit the `.skills/doctor.sh` it installs, because without that it wrote a file nothing ever tracked: **four of twelve audited consumers had been reinstalling an untracked doctor for weeks**, so their fresh worktrees and CI clones had none and the Phase 1 preflight silently short-circuited. #86 stopped the doctor being untracked; this stops the commit being unshared.

### The shape: reconcile, not commit-then-push

The retry is a **reconcile pass that runs at every session start, ahead of the once-per-day lock and the `main` gate** — not a `git push` bolted onto the commit step. Three things a bolted-on push does not cover:

- Any run that ends spends the day's lock, failure included, so a push that failed on the commit path would wait a whole UTC day to retry.
- The hook can be killed at any point by a signal no trap can answer — the harness's `timeout`, or the VS Code extension's shutdown about 2 s in ([#555](#a-run-killed-part-way-555)). A kill between commit and push leaves exactly the state the fix exists to prevent, and a separate pass heals it at the next session.
- Consumers stranded by an older vendored copy of the hook are healed with nobody visiting the machine.

### The guards

- **A refusal blocks the commit too.** Whenever the reconcile declines to push — for any of the reasons below — the run also commits nothing. A run that has concluded it cannot share a commit and then makes one has manufactured the stranding this step exists to prevent, and the second call site would only refuse it again. It refreshes nothing either ([#550](#a-rollback-undoes-the-whole-bump-550)): a refresh it cannot commit would leave the content ahead of the pointer.
- **It reads the whole range or refuses.** The subject read is `git log --no-show-signature --format=%s '@{u}..HEAD'`, and the number of subjects it returns must equal the number `git rev-list --count` gave. The `|| true` that keeps a failed git non-fatal would otherwise turn an unreadable range into zero unrecognised subjects — the authorship check below concluding "every one of them is mine" on no evidence at all, in the one direction that publishes an operator's work. `--no-show-signature` is part of the same guard: with `log.showSignature = true` and signed commits, git's verification lines inflate the count and the check refuses every session forever.
- **It only ever touches commits it wrote.** Before pushing, every commit in `@{u}..HEAD` must carry one of the three subjects the hook authors. Anything else and it pushes nothing *and commits nothing that run*: a push is a push of the whole branch, so it would publish work the operator chose not to share — a larger overreach than the stranding being fixed. A mix of theirs and ours says so on stderr; purely operator commits are logged and pass in silence, because unpushed work on a local `main` is normal in plenty of repos and a session-start warning there would train the reader to ignore the channel.
- **A failed push is rolled back**, so the checkout never diverges: HEAD moves as `git reset --soft` moves it, plus an unstage scoped to the paths those commits touched, matching what the commit step already does on a failed commit, and then the vendored content and the doctor go back with the pointer ([below](#a-rollback-undoes-the-whole-bump-550)). **Never `--hard`**: it is whole-tree, is *not* bounded by this hook's add scope — that discipline is a property of `git add` — and discards uncommitted edits anywhere in the checkout. Measured, it also deleted the doctor the run had just installed.
- **It rolls back to `HEAD~N`, not to `@{u}`.** On a *diverged* `main` — ours ahead, origin also ahead — resetting to `@{u}` moves HEAD onto the remote's tree while the working tree stays on ours, so every file the remote added reads as deleted-by-us. `HEAD~N` stays on this checkout's own history; the refusals above make that arithmetic sound.
- **Once, by compare-and-swap** ([#566](https://github.com/gregoryfoster/skills/issues/566)). Two sessions can be in this pass at once, and a `reset --soft HEAD~N` run by each rolled back commits that were not the hook's. HEAD is read once, before the guards; they, the push and `git update-ref HEAD <target> <head>` all use that commit. A second swap fails and is said, never as a rollback, and nothing is unstaged or restored. A push refused because the other session's push of the same commit landed first rolls nothing back: the hook checks `@{u}`, then `git ls-remote`, for the commit before the swap (CR 1896) — the remote only if it refused the ref itself, so a push that never reached it does not wait twice (CR 1907).
- **One refusal per run.** The block above is set once and read for the rest of the run. Without it, the refresh after a rollback would fetch, re-stage, re-commit and re-push what was just refused — two network waits inside a 120s ceiling, and the same warning twice.
- **It never pulls.** Landing a bump on a checkout that is behind would mean advancing local `main`, and on a deployed VM `main` *is* the running code; a SessionStart hook updating deployed application code is a far larger authority than moving a submodule pointer. A stale consumer gets no bump, loudly, until a human syncs.
- **The commit is scoped to a pathspec**, not left to sweep the index. `SKILL.md`'s "matches diff scope to add scope" was true of the *add* and of unstaged dirty work, but `git commit` with no pathspec commits the whole index — so anything the operator had staged before the session began went into the hook's commit under the hook's own message. A local wart while the hook only committed; a published one now that it pushes. The pathspec is what is actually staged under the hook's paths, not the path list itself: `git commit -- <path>` fails outright on a path git does not know, and `.skills/doctor.sh` is exactly that where a consumer gitignores `.skills/`, so passing the list verbatim fails the whole commit there and strands the submodule bump too.
- **It never force-pushes `main`**, in any spelling (in [`pr` mode](auto-refresh-hook/pr-mode.md) it replaces only its own branch, under a lease), and uses an explicit refspec rather than a bare `git push` — under `push.default=matching` that pushes every matching branch.

The rollback is the fix here and the push is the optimization: the service was stranded by `ahead 1`, not by a stale skills pin.

### A rollback undoes the whole bump ([#550](https://github.com/gregoryfoster/skills/issues/550))

A rollback used to revert only the recorded pointer, leaving the refreshed content checked out so "the skills keep working either way". That holds only while an update is backward-compatible with the consumer's repo-side config. On 2026-10-29 CannObserv/wslcb-licensing-tracker's rollback left content carrying [#480](https://github.com/gregoryfoster/skills/issues/480), which refuses a knob grammar that repo's committed config still used. Until a human synced, its vendored `patching-hosts` refused the repo's own knob.

- **Content, pointer and doctor go back together.** After the unstage, each registered `skills-vendor/` submodule among the rolled-back paths is checked out at the recorded pointer, and `.skills/doctor.sh` is reinstalled from the restored vendored installer. A doctor tracked before the bump matches its committed copy again. One untracked before it stays untracked, at the version the restored pointer ships.
- **`--checkout --no-fetch`, never `--remote`, `--merge` or `-f`.** A plain `git submodule update -- <path>` honours a configured `submodule.<name>.update`. Under merge, rebase or none it exits 0 and restores nothing, because the older commit is already contained in the newer checkout (measured, git 2.54). The recorded commit was checked out here before the bump, so nothing needs fetching.
- **Bounded, never forced.** Only the rolled-back paths are touched. A local edit inside the vendored checkout is carried across where git can carry it. Where git refuses, stderr says the content is still ahead of the recorded pointer, with the command that syncs it.
- **A run that cannot push does not refresh.** It used to refresh and skip only the commit, which moved the content ahead again: in the same run, after a session-start rollback, and every day on a `main` carrying an operator's unpushed commit.
- **So does a failed commit or a failed update.** A commit the consumer's pre-commit hook refuses used to be unstaged and nothing more, leaving the content ahead and stderr silent; now it is undone whole, and stderr says so. An update that fails part way puts back what it moved, in either mode.
- **A killed refresh's leftovers go back the same way.** When the session-start heal ([#555](#a-run-killed-part-way-555)) finds its marker, it restores the content as well as the staging, so a session that cannot redo the bump leaves a checkout that agrees with its pointer. Where someone's work staged beside the hook's keeps the staging in place, the content still goes back, onto the pointer the index records: for a gitlink the killed run staged, that is its bump.

A stale consumer keeps the older skills until a session that can share the bump makes it. That is "a stale consumer gets no bump", applied to the content as well as the pointer.

### What to expect where it cannot push

Where `main` is protected, or the hook has no push credentials, every push is rejected and rolled back, so the pointer never advances and the skills freeze at the vendored commit — loudly, on stderr, once a day. That is the intended degradation: a consumer that cannot share a bump should not be silently accumulating them. When a repository rule or branch protection refused it (`GH013`, `GH006`), the stderr line names the rule and the remedy: [`pr` mode](auto-refresh-hook/pr-mode.md).

`.skills/doctor.sh` warns whenever `main` is ahead of its upstream, which is the only cohort-wide sensor that can exist for this — an unpushed commit lives on exactly one machine, so nothing reachable through the GitHub API can see it.

## In `pr` mode ([#560](https://github.com/gregoryfoster/skills/issues/560))

With `.skills/merge_mode` `pr` the hook never pushes to `main`: it proposes the bump as one pull request from `skills/submodule-refresh`, which later sessions update, and the checkout's content stays on its recorded pointer. How, and what it does when `gh` or a rule stands in the way: [auto-refresh-hook/pr-mode.md](auto-refresh-hook/pr-mode.md).

## The timeout budget ([#572](https://github.com/gregoryfoster/skills/issues/572))

The hook commits and pushes through the consumer's pre-commit and pre-push hooks, inside its 120 s `timeout`. A suite too slow for that is skipped on the hook's own commit and pushes with `.skills/refresh-skip-hooks`. The budget, the knob, keeping the vendored-tree tests, and the per-phase timing in the log: [auto-refresh-hook/timeout-budget.md](auto-refresh-hook/timeout-budget.md).

## A run killed part way ([#555](https://github.com/gregoryfoster/skills/issues/555))

The VS Code extension starts a short-lived "config cache" CLI process at every window (re)connect. It runs the SessionStart hooks and shuts down about 2–3 s later, killing what is still running; the real session runs them again about a second after. A refresh that fetches a hundred upstream commits and then commits through a consumer's pre-commit framework does not fit. CannObserv/address-validator was killed there twice: after `git add`, leaving `.skills/doctor.sh` and the gitlink staged, and after the submodule update, leaving the content ahead of the pointer. Both times the killed run had already stamped the day's lock, so the real session's run exited at the guard, and the next try fell in the same window a day later.

- **The lock is spent when a run ends, not when it starts.** Every way out of the update-and-commit block stamps it, failures included, so a network blip still does not retry at every same-day session. A run killed part way leaves it, and the next session, usually the real one a second later, redoes the refresh.
- **A killed run's staging is undone at the next session**, on `main`, ahead of the lock and the reconcile pass. It is unstaged rather than committed: the same session redoes the bump, and nothing is committed that the run did not just verify. The vendored content goes back to the recorded pointer with it, [as a rollback's does](#a-rollback-undoes-the-whole-bump-550), whether or not the kill got as far as `git add`.
- **Only what the hook staged is touched.** A human's manual bump (`git add skills-vendor/<v>`) stages exactly the hook's paths, so the paths alone cannot tell the two apart. Before the update the hook writes `.git/skills-update.staging`, naming every path the run may stage, and removes it once the commit block ends with none of them left staged. The heal unstages only when that marker exists and every staged path is one it names. Anything else staged beside them is someone's work, so the whole index is left alone. The content still goes back, since `git submodule update --checkout` writes no index. Any of the hook's paths still staged is said on stderr with the `git reset` that drops it, once per killed run (the marker gets a `noted` line), not at every session while the human's work stays staged. With no marker, a staged hook path is logged and left alone. That includes a checkout left staged by a hook from before #555. In `direct` mode the first refresh this version completes on `main` commits it through its own pathspec. In `pr` mode, which never commits in the checkout, the refresh names it on stderr once a day with the `git reset` that clears it, since otherwise the next `git commit` on `main` absorbs it.
- **The marker names a live owner, and a live owner is left alone.** The old up-front lock was also the hook's mutual exclusion: a session starting mid-refresh exited at the once-per-day guard. With the day spent at the end, two sessions starting together in one checkout (agent sessions sharing it, two VS Code windows reconnecting) both ran the refresh, and the second's heal took the first's live marker for a killed run's, unstaging under it. So the marker's first line is `pid <PID> <epoch seconds>`, and the refresh claims it with `noclobber`, so of two runs exactly one owns it. The content is built before the file is opened and written by one builtin `printf`, and a marker with no parseable `pid` line is believed live for its first 2 s by mtime: a claim forking `date` inside the redirect once left the file empty long enough for a second run to read it as dead and refresh too (CR 1808). A run that finds the owner alive (`kill -0` reaches it) exits at once, before the doctor install, the heal, the reconcile or the refresh, and without spending the day. The heal acts only on a marker whose owner is gone, which is what a SIGKILL or SIGTERM leaves. It takes that marker by rename, so of two sessions that judged it dead only one heals, and claims it under its own PID until the heal ends, so a session starting meanwhile leaves (CR 1897). A heal killed part way leaves a marker the next session heals: its own, or, killed between rename and claim, `.git/skills-update.staging.heal.<pid>.<epoch>`, which, with no marker there, becomes it again once that PID is gone or 300 s old; any other goes when the marker superseding it is dropped (CR 1906). A marker older than 300 s (the hook's 120 s ceiling plus margin) is stale even with a live PID: a reused one, or another PID namespace's. **Known limit:** an installer re-run keeps a consumer's own larger `timeout`, and a run over 300 s has its live marker read as stale, so a session starting then can heal under it. The bound is not derived from the entry (the harness does not pass a hook its timeout, and parsing `.claude/settings.json` does not fit a path that must finish in about 2 s), so a `timeout` above 300 s needs `MARKER_MAX_AGE` raised with it.
- **The second kill in a row inside the commit backs off a day** ([#575](https://github.com/gregoryfoster/skills/issues/575)), or a pre-commit suite slower than 120 s is killed at every session. A heal finding the hook's paths staged counts the kill in `.git/skills-update.commit-kills`, once per marker, before undoing anything (CR 1899). The second stamps the day's lock and names [`.skills/refresh-skip-hooks`](auto-refresh-hook/timeout-budget.md) on stderr. A commit that returns resets the count, landed or refused, and marks the marker `done`, so a refused commit's failed unstage is not counted (CR 1900); a kill before `git add`, where the extension's kill nearly always lands, neither counts nor resets it.
- **A kill that strands git's own `index.lock`** (SIGKILL inside `git commit`) is not cleared: the hook cannot tell it from a live git process's lock. The unstage fails, and stderr names what is still staged and the `git reset` that clears it, as [below](#an-unstage-is-checked-not-assumed-311).

## An unstage is checked, not assumed ([#311](https://github.com/gregoryfoster/skills/issues/311))

Both failure paths, a failed commit and a rolled-back push, end by unstaging the hook's paths, and each used a `git reset` whose exit status was discarded. CannObserv/power-map was found on 2026-09-18 with both paths still staged beneath the hook's own "unstaging" line, cause unproven: #306's in-place rewrite was measured and ruled out, an `index.lock` held by another git process reproduces it (the reset exits 128), and a kill inside the reset might ([#555](#a-run-killed-part-way-555)). So the hook checks the outcome: after the reset it reads the index back and names on stderr anything still staged under its paths, with the `git reset` that clears it. A hook or framework that re-stages later is past the check; git's reason lands in the log after "commit failed".

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

You may also want to delete the hook's files in `.git/` if you don't plan to reinstall. All but the lock, the log and the kill count (`commit-kills`) are transient files the hook removes itself (the `pr-index` pair in `pr` mode only), so they survive only a run or heal that died mid-flight:

```bash
rm -f .git/skills-update.lock .git/skills-update.log .git/skills-status.err .git/skills-update.staging \
  .git/skills-update.commit-kills .git/skills-update.commit-kills.tmp .git/skills-update.log.tmp .git/skills-update.pr-index .git/skills-update.pr-index.lock
find .git -maxdepth 1 -name 'skills-update.staging.heal.*' -delete
```
