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
gh pr comment <N> --body "@dependabot rebase"            # only if main moved
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
  before `--watch`.
- **Fast-forward only.** The commit CI tested is the commit that lands, and its
  subject already takes the repo's form through `commit-message.prefix`.
- **One at a time.** Each landing puts the next PR behind `main`, so expect one
  rebase per PR: about 4–5 minutes each on watcher, mostly CI.
- **Restart** the service only when the diff touches something it runs. An
  action bump never does; a runtime dependency bump does, through the repo's
  own deploy.

`shipping-work*` Step 3 can point here for a PR it didn't author.

## Red auth on a Dependabot PR

Not the bump's fault. Triage by the auth action's own error:
[credential-context.md](credential-context.md#red-auth-triage-by-the-auth-actions-own-error).

## Generated workflows

Dependabot bumps `uses:` in every file under `.github/workflows/`, generated
ones included (`inventory.sh`'s `workflows[].generated`). The next re-render
writes the generator's older pin back, quietly: a one-line diff in a file whose
header says not to hand-edit it, so it reads as part of the regeneration.
`curating-context`'s `install-cadence.sh` was the first generator found doing
this ([#373](https://github.com/gregoryfoster/skills/issues/373)).

Until the generator never writes an older pin than the one installed:

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
