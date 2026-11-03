# Worktrees in `pr` mode

`.skills/merge_mode` set to `pr` means a branch reaches the default branch
through a pull request merged on GitHub, never through a local merge
([#342](https://github.com/gregoryfoster/skills/issues/342)). Absent, or
`direct`, Phase 4 merges locally as written. The knob is one word, read from
the primary checkout, like `.skills/worktree_root`. `bash "<merge-mode.sh>"`
prints it, and its exit 2 means the file is unusable: fix it, and never read
it as `direct`.

## Phase 4: push and open the PR

1. Commit inside the worktree.
2. Push the branch: `git push -u origin <branch>`.
3. Open the PR, or hand the whole ship to `shipping-work`, whose `pr` mode
   runs the gate, pushes, and opens or updates the PR. By hand: `gh pr view
   --json number,state,url` first. An `OPEN` PR was updated by the push; a
   `MERGED` or `CLOSED` one was not, since `gh pr view` finds a branch's PR in
   any state. With none, `gh pr create --base <default> --head <branch>`.
4. Nothing merges here. The main checkout stays where it is: don't `git
   switch` it, and don't merge into it.

Once the PR shows as merged, update the main checkout with `git switch
<default>` and `git pull --ff-only`, then destroy the worktree (Phase 5).
`shipping-work`'s post-merge pass does all three, and deploys between the
pull and the destroy.

## Phase 5: what `worktree-destroy.sh` accepts

A GitHub squash or rebase merge writes new commits, so a branch merged that
way is not an ancestor of `origin/<base>`, and the Iron Law's ancestry check
refuses it. In `pr` mode the script also:

- **Fetches first.** `git fetch origin` runs before the check, because
  `origin/<base>` moves only on GitHub. If the fetch fails, the script warns
  with git's own message and checks the refs it has: a stale ref can miss a
  merge, never invent one.
- **Accepts a merged PR** when ancestry fails. `gh pr list --head <branch>
  --base <base> --state merged` must list a PR whose head is the branch tip,
  or a descendant of it that this clone has. A matching name is not enough:
  `--head` matches by branch name, so a branch reused after its PR merged
  would otherwise read as merged with its new commits unmerged.

The three cases where gh isn't the answer:

| Case | Result |
|---|---|
| gh missing, unauthenticated (gh exits 4), or failing | exit 2, gh's own stderr shown, nothing destroyed. The verdict wasn't reached, which never reads as merged. Exit 1 would say "merge it first", which is wrong advice for a branch that may be squash-merged |
| `--base <ref>` | ancestry against the ref as given, and gh is never asked: the ref is a local integration branch such as `batch/<x>`, which no PR targets. For a PR into a non-default branch, set `.skills/default_branch` |
| `--descoped <reason>` | no check, so no fetch and no gh |

`--dry-run` fetches too, which moves remote-tracking refs only, and its
`merge:` line names the PR it accepted. It exits with the real run's code,
including 2 when gh fails.

The branch ref survives the destroy, as always. After a squash or rebase
merge, `git branch -d` deletes it only while its pushed upstream ref is still
here (with a warning), and refuses it once that ref is gone: `git branch -D`
is the instrument once destroy has accepted the PR.
