# Attesting the local gate

With `.skills/attest-local-gate` committed as `on`, `push.sh` says on GitHub
that the local gate passed: the commit status `gate/local` = `success` on the
SHA it pushed ([#688](https://github.com/gregoryfoster/skills/issues/688)). CI
may then skip its heavy tier for that commit.

It pays only in a private, duration-shaped repo whose PRs come from people who
ran the gate; `auditing-ci-cost` says
[when](../../auditing-ci-cost/references/non-levers.md#local-gate-attestation-where-it-is-live),
and its census measures the saving. Without the knob nothing changes: the same
push, the same output, no `gh` call and no gate run.

## The knob

One word, `on` or `off`. Blank lines and whole-line `#` comments are ignored,
and `off` is the same as no file.

It is read from **the commit being shipped**, not the work tree. Only a
committed knob turns the write on, and a branch that removes it stops
attesting with that commit. Anything else (another word, two words, an empty
file, a symlink, a file that is only in the work tree) is exit 2 before the
push: never `on`, and never silently `off`.

## What `push.sh` does with it on

Both shipping paths run `push.sh`, so both attest: a direct ship pushes the
default branch, and `pr` mode pushes the PR's head, the SHA its CI reads.

1. **Verify, before the push.** The tree must be clean, by a stricter test
   than `git status`: an untracked file, an edit inside a submodule and a
   skip-worktree or assume-unchanged path all count, whatever the repo's
   config hides. So a sparse checkout can't attest; ship from a full one.
   Then the gate is asked about it: the project's
   `scripts/pre-ship.sh`, else the one beside `push.sh`. Its exit code is the
   whole answer.
2. **Push.**
3. **Write, then read back.** `gh` posts the status to the repository
   `origin` pushes to, and the combined status, the endpoint CI reads, must
   show it. That repository is read from `origin`'s configured push URL, else
   its URL, as written: an `insteadOf` or `pushInsteadOf` rewrite that sends
   pushes to another repository isn't followed.

| Exit | Meaning | Do |
|---|---|---|
| 0, `Attestation: gate/local = success posted on <sha>` | pushed and attested | carry on |
| 0, `ATTESTATION NOT POSTED` or `NOT CONFIRMED` on stderr | pushed; the write was refused or didn't read back | carry on, and say so in the Step 7 report. Running `push.sh` again retries it |
| 1, `Nothing was pushed` | uncommitted changes, the gate failed, or the tree changed under the gate | fix, commit, run it again |
| 2, `Nothing was pushed` | the knob is unusable, `_attest-gate.sh` or `pre-ship.sh` wasn't found, the gate could not run, or git failed | fix what it names |
| any other, after `Pushing <branch> to origin...` | `git push` itself failed, with git's own code (a rejected push is 1) | as without the knob: resolve it, then push |

**Never post the status by hand.** It is written only after the gate exited 0
on the exact tree, and a hand-posted `success` is the false pass this step
exists to rule out.

## Why it works this way

- **A reused pass attests.** The gate records a pass against the exact tree
  and its tools, only for a clean tree, and answers 0 for that tree again
  without running ([gate-topology.md](gate-topology.md)). For everything
  that key covers it is the evidence a fresh run gives, so the step takes it.
  `GATE_STAMP=off` still forces a run.
- **The gate often runs in full at the push.** A pass is recorded only for a
  clean tree. When Step 1 ran on uncommitted work, or a merge made a new
  tree, the commit has none, so `push.sh` runs the whole gate: give that
  Bash call the gate's time.
- **A repo whose own `scripts/pre-ship.sh` is the gate** is asked through that
  script. If it records no pass, it runs a second time at the push; have it
  record one (`gate-stamp.sh`) or accept the second run.
- **The gate is asked before the push,** so a tree it fails is never pushed,
  and the write follows the push by seconds. A runner that push starts
  usually finds the status; one that doesn't runs the full tier.
- **A refused write doesn't fail the ship.** The push has landed by then, and
  a missing status fails safe: CI runs everything. Failing here would only
  add pressure to post it by hand.
- **`gate/local` is fixed.** CI keys on the name, so it isn't configurable.

## The token

The write uses the operator's own `gh` token, which needs push access to the
repository. A classic token's `repo` scope covers it; a fine-grained token
needs **Commit statuses: Read and write**. No workflow permission is involved
on this side. To confirm the grant without writing anything, post to a SHA
that doesn't exist (`gh api -X POST repos/<owner>/<repo>/statuses/<40 zeros>
-f state=success`): 403 means no grant, 422 "No commit found for SHA" means
the grant is there.

`gh` takes the token from its stored login, or from `GH_TOKEN` (or
`GITHUB_TOKEN`) in its environment. On a host with no stored login, the
variable must be **exported** into the shell that runs `push.sh`. If it's set
but not exported, or kept in a file nobody loaded, the push lands and the
write says `ATTESTATION NOT POSTED`. With the export in effect, `gh auth
status` names it (`(GH_TOKEN)`): check that before the first push. git needs
the token too, for the push itself. With no credential helper, an HTTPS push
fails before anything is pushed or posted. This environment hands git the
same token through `gh`. The empty first value clears any helper already
configured:

```bash
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=
export GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1='!gh auth git-credential'
```

## The CI side

Add `statuses: read` to the `permissions` of the workflow that runs the heavy
tier, beside what it already grants, and copy the `attest` step and the `if:`.
Cheap tiers (lint, format, guards) keep running on every commit. The grant
must also reach the step past two things that narrow it:
- **A job that declares its own `permissions`** replaces the workflow's, so
  put the grant on that job.
- **A workflow that calls this one through `workflow_call`** caps its token.
  The calling job must grant `statuses: read` too. Otherwise GitHub rejects
  the caller at startup with zero jobs, even when the calling job would be
  skipped.

```yaml
permissions:
  contents: read
  statuses: read # the attest step reads the combined status; unlisted keys are none

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      # ... checkout, setup and the cheap tiers, as today ...
      - id: attest
        env:
          GH_TOKEN: ${{ github.token }}
          # The PR's head. On pull_request, github.sha is the merge commit,
          # which nobody gated.
          HEAD: ${{ github.event.pull_request.head.sha || github.sha }}
        run: |
          # The combined status keeps the latest state of each context, while
          # /statuses lists every status ever posted, so a later failure would
          # still count. A page is 30 contexts unless more are asked for. A
          # refused read fails this step: loud, never a silent skip.
          n=$(gh api "repos/${{ github.repository }}/commits/$HEAD/status?per_page=100" \
                --jq '[.statuses[] | select(.context == "gate/local" and .state == "success")] | length')
          v=$([ "$n" -gt 0 ] && echo yes || echo no)
          echo "attested=$v" >>"$GITHUB_OUTPUT"
          # The verdict where a reviewer looks: the log and the run summary.
          echo "gate/local on $HEAD: attested=$v" | tee -a "$GITHUB_STEP_SUMMARY"
      - name: Heavy tier
        # Skipped only for an attested commit, on a branch push or a pull
        # request, and never for a bot's PR or a fork's: neither came from a
        # local gate. Everything else (a schedule, a manual run, a tag's
        # release, pull_request_target) always runs it. Every line of the
        # `>-` block sits at one indent, so it folds to one line.
        if: >-
          steps.attest.outputs.attested != 'yes'
          || (github.event_name != 'push' && github.event_name != 'pull_request')
          || startsWith(github.ref, 'refs/tags/')
          || (github.event_name == 'pull_request' && github.event.pull_request.user.type == 'Bot')
          || (github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != github.repository)
        run: uv run pytest
```

Keep a scheduled run of that workflow. It always runs the heavy tier, as a
tag's release run does, and it is the only clean-runner run a directly
shipped commit gets.

To check the `if:`s over every trigger, attested and not, copy rather than
reason: CannObserv/processor's `tests/test_ci.py` evaluates them with a small
evaluator for GitHub's expression syntax (search `_evaluate`).

### What to skip

**Skip only what the gate ran.** The stock gate deselects
`integration`-marked tests, runs without a coverage floor (`--no-cov`), and
runs nothing CI adds on its own, such as a migration check. A heavy tier that
holds any of these has two choices:
- **The gate runs them too.** A project `scripts/pre-ship.sh` that wraps the
  stock gate and runs the rest makes the attestation cover them.
- **CI keeps them on an attested commit.** A second step runs them, under the
  heavy tier's `if:` wrapped in `!( … )` (in a `>-` block a leading `!` is not
  a YAML tag), for example `uv run pytest -m integration`.

A test the gate's environment skips is one the attestation skips too, so the
environments must match first ([Adopting it](#adopting-it), step 2).

### A skipped step leaves the job `success`

Anything that reads the job's conclusion as "tests passed", such as a deploy
gate, release reuse or a required check, can't tell an attested skip from a
full run. For the default branch's push run, what to do depends on how
commits reach it:

| Commits reach the default branch by | Its push run, under the `if:` above | Do |
|---|---|---|
| a merge made on GitHub (merge or squash) | runs everything: the new commit carries no status | nothing |
| a fast-forward from a PR, or a rebase that keeps the SHA | **skips**: the PR's head is the commit, status and all | read the status on `pull_request` only: `if: github.event_name == 'pull_request'` on the `attest` step. An unset output reads as not attested. `\|\| github.ref == 'refs/heads/<default>'` on the heavy tier's `if:` does the same from the other side |
| a direct ship | **skips**: that run is the one the attestation saves | have the reader check `attested` instead of the job's conclusion, or make the heavy tier [its own job](#the-heavy-tier-as-its-own-job) |

#### The heavy tier as its own job

Move the heavy tier into its own job. It `needs:` the job that holds the
attest step, which exports `attested` as a job output, and it carries the
same `if:` at job level, reading `needs.<that job>.outputs.attested` in place
of `steps.attest.outputs.attested`. An attested skip is then that job's
conclusion, `skipped`, not `success`. A reader that requires every job to be
`success` refuses it, which is the loud outcome. Start that `if:` with
`!cancelled() &&`. A job-level `if:` without a status function implies
`success()`, so a failed status read would skip the heavy tier instead of
running it.

## What the status is not

- **Trust, not proof.** Anyone with push access can post `gate/local` without
  running anything, and the combined status doesn't say who posted it. Never
  make it a required status by itself: it proves nothing alone, and a bot's
  PR never gets one, so it could never merge. Require the runner job, which
  reads it.
- **Not the merge.** It speaks for the head commit. A `pull_request` run tests
  the merge with the base, which only a runner builds, and a merge commit made
  on GitHub carries no status. A fast-forward merge, or a rebase that
  keeps the SHA, is the exception: the head itself lands on the default
  branch, status and all ([the table](#a-skipped-step-leaves-the-job-success)).
- **Not the same run.** CI may run the tests differently from the gate
  (another order, shards, other flags). On an attested PR those differences
  surface only on the default branch's next full run, after the merge.
- **Not a clean machine.** Unpinned tools, a dirty venv or local-only data can
  pass locally and fail on a runner.
- **Not retracted.** A later failing run on the same commit posts nothing, so
  an earlier `success` stands.

## Adopting it

In order. The first adopters' reports are on
[#688](https://github.com/gregoryfoster/skills/issues/688).

1. **Update the vendored skills.** If `skills/shipping-work/scripts/` is a
   directory of per-file symlinks, add one for `_attest-gate.sh` beside
   `push.sh`'s. A whole-directory link needs nothing.
2. **Make the gate's environment match the heavy tier's.** A test the gate's
   environment skips (an `importorskip` of an extra the venv lacks) passes
   locally, and the attestation then skips it in CI. A bare `uv run` doesn't
   install the workspace extras CI may sync, so commit
   `.skills/pre-ship-uv-args` with CI's flags (for example
   `--all-packages --all-extras`). Then settle [What to skip](#what-to-skip).
3. **Check the token** ([The token](#the-token)).
4. **Add the CI step** ([The CI side](#the-ci-side)), and check the
   default branch's readers against
   [the table](#a-skipped-step-leaves-the-job-success).
5. **Commit the knob**, `on`. Gitignore any machine-local `.skills/` file
   first: an untracked one makes every attested push refuse the tree.
   **The adoption PR attests itself** if it's shipped through `push.sh`. The
   knob is read from `HEAD`, and a `pull_request` run uses the PR's own
   workflow, so the PR that adds the skip skips its own tests. Push it with
   plain `git push` to have it run in full, or expect it attested.
6. **Measure it.** Run `auditing-ci-cost`'s census before and about 30 days
   after. A saving quoted without that is an estimate.
