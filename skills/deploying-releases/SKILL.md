---
name: deploying-releases
description: Installs and configures the cohort's one release-deploy core in a Python service repo, so its systemd units run a root-owned, read-only release under /srv/<project> instead of the development checkout. The core builds releases/<sha12> from a pushed, CI-green commit (git archive, uv sync --locked, REVISION last), switches a link atomically, installs the units that differ, restarts and verifies what changed, and switches back on failure; the repo supplies only scripts/deploy_hooks.sh. The core is copied in with a version and sha256 marker, never run from skills-vendor/, so an upgrade is a reviewable diff. Use when the user says "deploy from releases", "release deploy", "install the deploy core", "update the deploy core", "deploy hooks", or "retrofit the deploy".
compatibility: Designed for Claude Code or a similar harness with a Bash tool. The core runs on a Linux host with systemd, bash 4+, GNU coreutils, util-linux flock, git, jq, curl (or gh) and uv, as a deploy user with sudo. install.sh runs anywhere with bash and git.
metadata:
  author: gregoryfoster
  version: "0.1"
  triggers: deploy from releases, release deploy, install the deploy core, update the deploy core, deploy hooks, retrofit the deploy
---

# Deploying Releases

Moves a repo's systemd units off its checkout and onto releases, through one core shared by the cohort. Built from [#372](https://github.com/gregoryfoster/skills/issues/372) to the plan in [docs/plans/2026-11-13-deploying-releases.md](../../docs/plans/2026-11-13-deploying-releases.md). The core is extracted from CannObserv/broker's `scripts/deploy.sh` at `bbf1c72f`, the newest of the six copies that each pilot ran on its own.

**Status: Part A in development. No repo runs the core yet; CannObserv/replicator (replicator#151) is to adopt it first.**

**Activation triggers:** "deploy from releases", "release deploy", "install the deploy core", "update the deploy core", "deploy hooks", "retrofit the deploy".

## The Iron Law

```
NO UNIT RUNS A CHECKOUT, AND NO DEPLOY RUNS FROM skills-vendor/ OR A SYMLINK: ONLY THE INSTALLED, COMMITTED CORE
NO EDIT TO THE INSTALLED CORE: CONFIGURE scripts/deploy_hooks.sh, OR RAISE IT UPSTREAM
NO FIRST DEPLOY, CUTOVER OR ENABLE WITHOUT THE OPERATOR'S APPROVAL, GIVEN IN THE HOST'S OWN SESSION
```

A copy per repo relearns every lesson: status's alone took five review rounds and 36 findings (#372), and six repos each grew their own. The core is the one place a lesson lands. A difference a repo needs goes in its hooks; one the hooks can't express is raised on this repo, never patched into the installed copy, which `install.sh --check` and the consumer's own marker test both catch.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "Symlink the core from skills-vendor/, so updates are free" | A submodule bump would then change how production deploys, unreviewed. The copy is the point: an upgrade is a diff in the consumer. |
| "One small fix in the installed deploy.sh is quicker" | It is a fork with no signal. The next `install.sh` refuses to overwrite it (`edited`), and the fix never reaches the other repos. |
| "Compare the units, and install them by hand" | Decided (D5): the core installs every unit that differs and keeps each replaced copy for a switch back. A hand install is a step a rollback can't undo. |
| "Enable the new timer in the deploy, it's obviously wanted" | Enabling is a decision, often waiting on a prerequisite. Name it in `ENABLE_NEW`, and it is enabled only after the deploy verifies. |
| "`--skip-ci` on every deploy, our CI is local" | Set `CI=none` once. `--skip-ci` is an emergency, and each use is journaled as one. |

## Script path resolution

<!-- skill:required id=skill-scripts -->
```bash
N=deploying-releases
for S in install.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

`<install.sh>` is a **placeholder** for the literal path printed here, not an inherited shell variable — each Bash invocation runs in a fresh shell. A project-local `scripts/install.sh` wins if one exists ([#301](https://github.com/gregoryfoster/skills/issues/301)).

## What the consumer holds

| File | Whose | What |
|---|---|---|
| `scripts/deploy.sh` | the core, installed | Never edited. Line 2 is its version; line 3 the sha256 of the file with that digest zeroed. |
| `scripts/deploy_hooks.sh` | the repo's | `PROJECT`, `GITHUB_REPO`, the other variables, and up to six hooks. Written once from the template, never overwritten. |
| `deploy/<project>-*.{service,timer}` | the repo's | The units, each on `WorkingDirectory=/srv/<project>/live` (or `/dev`): a unit's target **is** its working directory. |
| `.skills/deploy_command` | the repo's | `scripts/deploy.sh`, so `shipping-work` deploys through it (#345). |

The core's steps, its variables and env knobs, each hook's arguments and exit codes, the verify helpers, and every pilot's hooks filled in: [references/hook-contract.md](references/hook-contract.md).

## Procedure

### Choose the mode

- **Fresh:** a new repo, from `init-project-fastapi` (`DEPLOY_TARGET=releases`) or by hand. Install, fill in the hooks, render the units and copy the tests, as [references/fresh.md](references/fresh.md) lays out.
- **Update:** a repo already on the core. Install or update below, and review the diff.

### Install or update the core

1. `bash "<install.sh>" --check` from the consumer's root. It prints `<state> <installed> <vendored>`: `missing`, `foreign` (the repo's own deploy), `edited`, `drift`, or `current`.
2. `bash "<install.sh>"` installs or updates. It refuses `edited` (move the change into the hooks, or raise it here) and `foreign` without `--replace`. Replace a repo's own deploy only once its behaviour is in the hooks, row by row against [the contract](references/hook-contract.md).
3. Review the diff of `scripts/deploy.sh` as a production change, then commit it with the hooks.

### Configure

Fill in `scripts/deploy_hooks.sh`: `PROJECT` and `GITHUB_REPO` at least. Delete every hook the repo doesn't need. The core refuses an unfilled template, and the decisions behind each default are in the plan:

- **The service user** is dedicated for a new repo and `exedev` for a retrofit, and releases are owned by root in every case (D2, D7). The user is a unit's `User=`; the core refuses a release whose `User=` doesn't exist.
- **`ENABLE_NEW`** is empty unless a unit should start the moment a deploy verifies (D3).
- **`CI=none`** for a repo whose gate is local; `CI_AUTH=gh` for a private repo.
- **`UV_WRAPPER`** names the checkout's co-pypi wrapper when a dependency is private ([#632](https://github.com/gregoryfoster/skills/issues/632)). A lock that resolves from `./.wheelhouse` is refused.

### Deploy

From the checkout, as the deploy user: `scripts/deploy.sh` (every target the release's units run, dev first), `--target dev <branch-commit>`, `--build-only`, or `--no-restart` for a first deploy or a cutover. A rollback is a deploy of the previous build: `scripts/deploy.sh <sha12>`, gated the same way. Exit 0 is verified, 1 refused or switched back to a build that answers, 4 a target left on a build that does not; the journal tag is `<project>-deploy`.

## Notes

- **Linux only.** The core needs GNU coreutils (`mv -T`, `stat -c`) and util-linux `flock`. A Mac runs `install.sh`, not the core.
- **shellcheck 0.11 is the floor** (D8). The core is clean at this repo's pinned 0.11 with `--severity=style`; verdicts from apt's 0.9 or a Mac's 0.8 are not supported, and no `.shellcheckrc` ships with it.
- **The hooks run in the checkout's version.** A rollback to an old build is verified by today's hooks, as broker's deploy always did.

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by `tests/structural/test_skill_self_budget.py`; both readings must clear it. Each `references/` doc is held to the 10,000-token per-doc budget.
