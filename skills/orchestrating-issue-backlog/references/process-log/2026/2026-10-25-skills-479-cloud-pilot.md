## Session 2026-10-24/25 — gregoryfoster/skills (#479 cloud-worker pilot)

The first cloud-session worker. The scope was not a scored backlog: four
`patching-hosts` restarter-scan issues (#393, #418, #419, #420), run as one
Shape A bundle by one cloud worker, to settle the open questions in #479 before
writing [`cloud-workers.md`](../../cloud-workers.md) from what they showed.
#479's comment thread is the run's full account.

**Answers that differed from a local run:**

| Q | Answer |
|---|---|
| Q4 | Cloud sessions, one worker; launched from claude.ai/code |
| Q5 | Not worktrees or services: the plan's usage. One worker for the pilot |
| Decisions | #419: name every matching line and offer the exception; no docstring skipping. #420: key the exception by template, else by unit |

**Shape:** two smoke-test sessions, then one worker: 8 commits (four red/green
pairs) and a review round of 3 more. The cloud and macOS suites reconciled
exactly, at 7738 and then 7743 collected.

## Lessons

### 1. Creating a worker needs a person; steering one doesn't

`claude --cloud "<brief>"` refuses without an interactive terminal, so an
orchestrator agent can't launch a worker. `claude -p "<msg>" --cloud <id>`
runs without one, and delivered the review round. That makes coordination
one-way push: the orchestrator posts to the issue and points the worker at
the comment, while the worker can only write to GitHub, so the orchestrator
waits on it (`await-report.sh`).

### 2. The CLI launch silently uploaded a bundle

Both CLI launches got a bundle, with no `origin` and the proxy refusing the
repo, although the Claude GitHub App was installed and authorized. Only
`--debug` showed why: `GitHub app is not installed on …` and then `Bundling
(reason: github_preflight_failed)`. The terminal printed nothing about it.
The first run's HEAD was an unpushed local commit, which is how the bundle was
spotted at all. A web launch with the repo selected got a real clone, and
`add_repo` recovered a bundle mid-session. Hence the brief's preflight checks
`git remote -v` and a `gh api` read before anything else.

### 3. A suite-running hook can't pass over known failures, and the brief said it would

The baseline held five shellcheck failures, from a newer shellcheck than the
local one (#481). My brief said green commits go through the hook. They can't:
the hook runs the whole suite, which exits non-zero on every tree. The worker's
first hooked commit was rejected after 780 s, with nothing failing but the
known five. It then committed with the suite hook skipped, after a full manual
run, and said so in each body. It reported the brief as wrong, which is what
the corrections half is for.

### 4. A delta named by cause reconciled across root and macOS

The cloud runs as root, so 35 tests skip there that run on macOS, and it runs
Linux-only tests that macOS skips. The briefed baseline was the measured
bundle count plus one test, named, which a clone passes. The worker measured
it exactly, and every later count reconciled by arithmetic: run 1 → run 2 was
−4 failed, −3 passed, +7 skipped, and the 7 were the root fix's 4 failures and
3 vacuous passes. Running as root also exposed four tests with no root skip of
their own: the first smoke run failed on them, and b6034b39 added their skips
before the second.

### 5. A new way to silence a finding has to be tried against a true positive

#419/#420 let an owner declare `not-restarter:<target>`. Review tried to
silence a **real** restart with it, and succeeded in two ways:
- the scan returned at its first match, so a docstring match in an earlier
  Exec line's script hid a later Exec line's `systemctl restart`;
- a finding named only the first matching line, so its advice ("if the line it
  matched isn't a call") covered a real call further down.

The worker fixed both and found a third: the first matching script hid a later
script's call. All three are one defect, a first-match return that was harmless
until an exception could act on its answer. Neither decision was wrong; the
tests just hadn't asked whether the new exception could hide what the scan
exists to catch.

### 6. A replayed commit sequence needs its ordering checked

The suite reads the files live, so the worker developed in a scratch tree and
replayed its commits afterwards: red and green pairs share a minute. The
ordering held, checked per pair (red fails its new tests, green passes them),
but only the check showed that.

### 7. The environment's own surprises

- The setup script died at a dpkg prompt, because the image ships an
  `/etc/zsh/zshrc` without zsh, and `zsh-common` asked about it.
- Once zsh was installed, the Bash tool ran zsh until `CLAUDE_CODE_SHELL`
  was set.
- `AGENTS.md` loaded on its own in all three sessions.
- The suite took 13 minutes on 4 vCPU.
