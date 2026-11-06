# Shipping in `pr` mode

`.skills/merge_mode` set to `pr` means work reaches the default branch
through a pull request merged on GitHub, never through a local merge
([#342](https://github.com/gregoryfoster/skills/issues/342)). Absent, or
`direct`, SKILL.md applies as written. The knob is one word, read from the
primary checkout; `bash "<merge-mode.sh>"` prints it, and its exit 2 means the
file is unusable. Fix it, and never read it as `direct`.

A PR-mode ship is two passes, both started by "ship it":

- **The PR pass** runs while the branch has no PR, or an open one: Steps 1–7,
  ending with the PR open.
- **The post-merge pass** runs once the PR shows as merged: the main checkout
  moves to the merge, and Step 8 runs there.

## Which pass

From the feature branch, after Step 1:

```bash
gh pr view --json number,state,url
```

| Answer | Pass |
|---|---|
| exit 1, `no pull requests found for branch "<branch>"` | the PR pass: none exists yet |
| `"state":"OPEN"` | the PR pass: Step 4's push updates it |
| `"state":"MERGED"` | the post-merge pass |
| `"state":"CLOSED"` | stop and ask. A push to a closed PR's branch neither reopens nor updates it, and a new PR is the user's call |
| any other failure | no answer. Fix gh (`gh auth status`) first |

**A found PR is not proof that a push updates it.** `gh pr view` finds the
branch's PR in any state, merged and closed included: against gh 2.102.0,
`gh pr view <branch>` on a branch whose PR merged exits 0 with
`"state":"MERGED"`. Read `state`, not the exit code.

On the default branch itself there is no PR to look up: that is Step 3's
refusal.

## The PR pass

- **Steps 1, 1.5 and 2** run as written. `doc-check.sh` compares the branch
  against the default branch either way.
- **Step 2.5.** No `using-git-worktrees` Phase 4 merge. Stay on the branch,
  in the worktree or not; every later step of this pass runs there.
- **Step 3.** No merge. Refuse when `git branch --show-current` prints the
  default branch, or nothing (a detached HEAD): there is nothing to open a PR
  from. Stop and ask; moving commits off the default branch is the user's
  call.
- **The HARD-GATE runs here,** before the PR opens, against each in-scope
  issue: re-read the body, confirm each requirement in the commits, and ask
  about anything missing. An issue that fails it gets no `Closes` line.
- **Step 4.** `bash "<push.sh>"` pushes the current branch with `-u`, so the
  branch is what's pushed. Then open or update the PR:
  - an open PR: the push updated it. Edit its body (`gh pr edit
    --body-file <file>`) only if the scope changed, and never to drop a
    `Closes` line alone (below);
  - none: `gh pr create --base <default> --head <branch> --title "<title>"
    --body-file <file>`. The default branch is `.skills/default_branch` when
    the project has one, else `gh repo view --json defaultBranchRef --jq
    .defaultBranchRef.name`.
- **The PR body** summarises the change and carries one `Closes #<n>` line per
  in-scope issue that passed the HARD-GATE. GitHub closes those issues when
  the PR merges into the default branch. These closing keywords are
  deliberate, and only here: the house rule against them in commit and
  comment prose still holds, since a keyword in a commit also closes its
  issue when the commit reaches the default branch.
- **A closing keyword cannot be retracted by editing the body**
  ([#565](https://github.com/gregoryfoster/skills/issues/565)). GitHub kept
  the link of an edited-out `Closes #<n>` and closed the issue at the merge,
  and it parses a checklist line to a human ("Close #<n> once they pass"), a
  negation or `Closes #<n>?` alike. Before `gh pr create` and before any body
  edit, reword every hit in the body file that isn't an intended close (this
  pattern also finds `owner/repo#<n>` and issue URLs, on BSD and GNU grep):

  ```bash
  grep -niE '\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[^[:alnum:]#]{0,3}([[:alnum:]_.-]+/[[:alnum:]_.-]+#|#|https?://[^[:space:]]+/issues/)[0-9]+' <file>
  ```

  Then `gh pr view --json closingIssuesReferences --jq
  '[.closingIssuesReferences[].number]'` lists what the merge will close,
  sidebar links included, and must be exactly the `Closes` issues. To drop
  one still listed, remove it in the PR's Development sidebar; the
  post-merge pass reopens it if the merge closed it anyway.
- **With `.skills/deploy_command` set**, an issue whose requirement concerns
  what production runs gets `Refs #<n>`, not `Closes #<n>`. The merge would
  close it before the deploy ran, which the HARD-GATE's item 4 forbids. The
  post-merge pass closes it once the deploy exits 0.
- **Step 5.** Each issue comment links the PR (`PR #<m>: <url>`) beside the
  usual bullets, above the `Follow-up:`, `Known limits:` and `For #N:`
  sections.
- **Step 6.** Close nothing. The merge closes the `Closes` issues.
- **Step 7.** The Status column reads `PR #<m> open, awaiting review`. A
  `Refs` issue reads `PR #<m> open; closes after the deploy`.
- **Step 8** waits for the post-merge pass. Say so in the report.

## The post-merge pass

Started by "ship it" once `gh pr view` shows `MERGED`:

1. **Move to the main checkout,** the first row of `git worktree list`. Run
   `git switch <default>`, then `git pull --ff-only`. If the pull refuses,
   the local default branch has commits of its own: stop and report. Don't
   merge or rebase them.
2. **Step 8 runs there.** Without `.skills/deploy_command`, a checkout that is
   a unit's `WorkingDirectory=` became production at the pull, so the next
   steps table follows it. With the knob, Step 8's `--check` and offer run
   from there, and `bash "<run-deploy-command.sh>"` deploys. In `pr` mode it
   refuses (exit 2) unless HEAD is the default branch and equals its
   upstream. The deploy runs the merge commit, or a later one on the
   default branch, never the branch tip.
3. **Close the held issues.** Close each `Refs` issue only after the deploy
   exited 0, under the HARD-GATE. For each `Closes` issue, check that the merge
   closed it (`gh issue view <n> --json state`); a PR merged into any other
   base closes nothing. Then check that it closed nothing else: each number
   `gh pr view <m> --json mergedAt,closingIssuesReferences` lists that isn't
   on a `Closes` line, and whose `closedAt` (`gh issue view <n> --json
   state,closedAt`) is the merge's (a second after `mergedAt`, measured),
   was closed by it. Reopen it (`gh issue reopen <n>`) and say why.
4. **Destroy the worktree** with `using-git-worktrees` Phase 5. In `pr` mode
   `worktree-destroy.sh` fetches first, then accepts the merged PR as evidence
   when a squash or rebase merge left no ancestry. To delete the local branch
   afterwards: `git branch -d` deletes a squash-merged branch only while its
   pushed upstream ref is still here (with a warning), and refuses it once
   that ref is gone, so `git branch -D` is the instrument once destroy has
   accepted the PR.
5. **Report** the merge commit, the deploy's exit, and each issue's final
   state.
