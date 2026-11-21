# Attesting the local gate

With `.skills/attest-local-gate` committed as `on`, `push.sh` says on GitHub
that the local gate passed: the commit status `gate/local` = `success` on the
SHA it pushed ([#688](https://github.com/gregoryfoster/skills/issues/688)). CI
may then skip its heavy tier for that commit.

It pays only in a private, duration-shaped repo whose PRs come from people who
ran the gate; `auditing-ci-cost` says
[when](../../auditing-ci-cost/references/non-levers.md#local-gate-attestation-where-it-is-live),
and its census measures the saving. Without the knob nothing changes: the same
commands, the same output, no `gh` call.

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
   config hides. Then the gate is asked
   about it: the project's `scripts/pre-ship.sh`, else the skill's, as Step 1
   resolved it. Its exit code is the whole answer.
2. **Push.**
3. **Write, then read back.** `gh` posts the status to `origin`'s repository,
   and the combined status, the endpoint CI reads, must show it.

| Exit | Meaning | Do |
|---|---|---|
| 0, `Attestation: gate/local = success posted on <sha>` | pushed and attested | carry on |
| 0, `ATTESTATION NOT POSTED` or `NOT CONFIRMED` on stderr | pushed; the write was refused or didn't read back | carry on, and say so in the Step 7 report. Running `push.sh` again retries it |
| 1 | uncommitted changes, the gate failed, or the gate changed the tree. Nothing was pushed | fix, commit, run it again |
| 2 | the knob is unusable, or the gate could not run. Nothing was pushed | fix what it names |

**Never post the status by hand.** It is written only after the gate exited 0
on the exact tree, and a hand-posted `success` is the false pass this step
exists to rule out.

## Why it works this way

- **A reused pass attests.** The gate records a pass against the exact tree
  and its tools, only for a clean tree, and answers 0 for that tree again
  without running ([gate-topology.md](gate-topology.md)). That is the same
  evidence a fresh run gives, so the step takes it. `GATE_STAMP=off` still
  forces a run.
- **A repo whose own `scripts/pre-ship.sh` is the gate** is asked through that
  script. If it records no pass, it runs a second time at the push; have it
  record one (`gate-stamp.sh`) or accept the second run.
- **The gate is asked before the push,** so a tree it fails is never pushed,
  and the write follows the push by seconds. A runner that push starts reads
  the status after it exists.
- **A refused write doesn't fail the ship.** The push has landed by then, and
  a missing status fails safe: CI runs everything. Failing here would only
  add pressure to post it by hand.
- **`gate/local` is fixed.** CI keys on the name, so it isn't configurable.

## The token

The write uses the operator's own `gh` login, which needs push access to the
repository. A classic token's `repo` scope covers it; a fine-grained token
needs **Commit statuses: Read and write**. No workflow permission is involved
on this side.

## The CI side

Copy the `permissions` lines, the `attest` step and the `if:` into the
workflow that runs the heavy tier. Cheap tiers (lint, format, guards) keep
running on every commit.

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
          # The combined status keeps each context's latest state; /statuses
          # lists every status ever posted, so a later failure would still
          # count. A page is 30 contexts unless more are asked for. A refused
          # read fails this step: loud, never a silent skip.
          n=$(gh api "repos/${{ github.repository }}/commits/$HEAD/status?per_page=100" \
                --jq '[.statuses[] | select(.context == "gate/local" and .state == "success")] | length')
          echo "attested=$([ "$n" -gt 0 ] && echo yes || echo no)" >>"$GITHUB_OUTPUT"
      - name: Heavy tier
        # Runs unless attested, and always for a bot's PR or a fork's:
        # neither came from a local gate.
        if: >-
          steps.attest.outputs.attested != 'yes'
          || (github.event_name == 'pull_request'
              && (github.event.pull_request.user.type == 'Bot'
                  || github.event.pull_request.head.repo.full_name != github.repository))
        run: uv run pytest
```

## What the status is not

- **Trust, not proof.** Anyone with push access can post `gate/local` without
  running anything, and the combined status doesn't say who posted it. Never
  make it a required status by itself: it proves nothing alone, and a bot's
  PR never gets one, so it could never merge. Require the runner job, which
  reads it.
- **Not the merge.** It speaks for the head commit. A `pull_request` run tests
  the merge with the base, which only a runner builds, and a merge commit made
  on GitHub carries no status.
- **Not a clean machine.** Unpinned tools, a dirty venv or local-only data can
  pass locally and fail on a runner.
- **Not retracted.** A later failing run on the same commit posts nothing, so
  an earlier `success` stands.
