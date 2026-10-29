# Merge paths

Dependabot only opens PRs. Write down how one lands, for the repo's merge
model, before the first one opens. Otherwise PRs pile up, or get merged in a
way that skips the repo's ship gate.

## Which model the repo has

Read `AGENTS.md`, the shipping skill it vendors, and the last few merges
(`git log --merges --first-parent -10 main`). A repo whose `main` moves by
local merges and pushes, with no merged PRs, is local-merge. The
`shipping-work*` variants assume local merges today; a PR-mode knob for them is
[#342](https://github.com/gregoryfoster/skills/issues/342).

## GitHub-merge repos

The usual: wait for every required check on the PR's head, read the changelog,
merge on GitHub. Branch protection does the gating. Turn on "require branches
to be up to date" only knowing that each landing then puts every other open
Dependabot PR behind.

## Local-merge repos

This held for four PRs in a row on watcher (watcher#354–#357, 2026-10-09), and
GitHub marked each one merged:

```bash
# Read the release notes, not just the diff: a major bump can change inputs.
gh pr view <N> --json headRefOid -q .headRefOid          # note the head SHA
gh pr comment <N> --body "@dependabot rebase"            # only if main moved; see below
# if you asked for a rebase, wait until headRefOid changes; then:
gh pr checks <N> --watch                                 # every job, on the new head
git fetch origin "$(gh pr view <N> --json headRefName -q .headRefName)"
git merge --ff-only FETCH_HEAD
<the repo's ship gate>                                   # as for any other change
git push origin main                                     # GitHub marks the PR merged
```

- **The rebase race.** Run `@dependabot rebase`, then read `gh pr checks` at
  once, and you read the *old* commit's green. You then fast-forward a commit
  whose CI you never read (watcher#283 CR 6). Wait for the head SHA to change
  before `--watch`. A PR opened before the config never changes: see
  [Security PRs opened before the config](#security-prs-opened-before-the-config).
- **Fast-forward only.** The commit CI tested is the commit that lands, and its
  subject already takes the repo's form through `commit-message.prefix`.
- **One at a time.** Each landing puts the next PR behind `main`, so expect one
  rebase per PR: about 4–5 minutes each on watcher, mostly CI.
- **Restart** the service only when the diff touches something it runs. An
  action bump never does; a runtime dependency bump does, through the repo's
  own deploy.

`shipping-work*` Step 3 can point here for a PR it didn't author.

## Security PRs opened before the config

With security updates on and no `dependabot.yml`, Dependabot still opens
security PRs. **Every Dependabot PR older than the config's first commit can't
be rebased once the config lands.** Recognise one by its age, or by the bot's
answer to `@dependabot rebase`:

```bash
gh pr list --author app/dependabot --json number,title,createdAt   # before the push: all of them
git log --diff-filter=A --format=%cI -- .github/dependabot.yml | tail -1   # after: older than this
```

> The dependabot.yml entry that created this PR has been deleted so this PR
> can't be rebased. Please close the PR so Dependabot can create a new one with
> the current dependabot.yml.

The head never changes, so the bounded wait above times out.

- **Inventory them before pushing the config,** and land each one first where
  its CI and the ship gate allow.
- **Don't close one to get it re-created,** whatever that message says.
  Closing records an ignore for that version, the bot deletes the branch, and
  no replacement opens. With the branch gone the PR can't be reopened, and
  restoring it means pushing to a bot-owned branch
  (CannObserv/address-validator#357, 2026-10-27).
- **Land the advisory's fixed version, or later, by hand**, through the same
  gate: `uv lock --upgrade-package <pkg>`, `npm update <pkg>`. Taking the
  newest release, not the PR's exact version, is fine: address-validator's
  hand-made fix (CannObserv/address-validator#375) landed a newer `filelock`
  than address-validator#357 proposed, and was accepted (CannObserv/address-validator#361,
  2026-10-28).
- **Then close the PR, with a comment pointing at the commit that landed the
  fix.** The ignore it records no longer matters once `main` is on that
  version or later.

## Red auth on a Dependabot PR

Not the bump's fault. Triage by the auth action's own error:
[credential-context.md](credential-context.md#red-auth-triage-by-the-auth-actions-own-error).

## Generated workflows

Dependabot bumps `uses:` in every file under `.github/workflows/`, generated
ones included (`inventory.sh`'s `workflows[].generated`). The next re-render
writes the generator's older pin back, quietly: a one-line diff in a file whose
header says not to hand-edit it, so it reads as part of the regeneration.
`curating-context`'s `install-cadence.sh` was the first generator found doing
this ([#373](https://github.com/gregoryfoster/skills/issues/373)). It now keeps
an installed SHA pin, or a major at or above its template's, so its bump lands
bare; `--check`'s `checkout pin:` line says what a re-render would write. A
consumer vendoring a skills commit from before that fix still downgrades.

For a generator that still writes its own pin:

- take the bump;
- where the generator is in the same repo and a test holds the file to its
  render, the bump itself fails the gate. Move the generator's pin in a commit
  on top of the PR's head, and land both: the fast-forward still marks the PR
  merged (this repo's #507, 2026-10-27);
- after any regeneration, compare the `uses:` lines with `git diff` and restore
  any that went backwards before committing. With `SHA_PINS` on, the guard test
  fails a re-rendered tag pin, so it can't slip through;
- file the downgrade against the generator, upstream.

The cohort rule to argue for, in every skill that renders a workflow: **a
re-render never writes an older `uses:` pin than the one installed.**
