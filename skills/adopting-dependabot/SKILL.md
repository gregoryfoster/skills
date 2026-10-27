---
name: adopting-dependabot
description: Adopts Dependabot in a GitHub repo so it goes green on its first PR and stays audible when it breaks. It maps CI's credential surface and what the bot can and can't move (private indexes, git-sourced and lockstep pins, generated workflows, frozen action tags), sweeps stale declarations test-first, writes the smallest honest config with each key's silent failure commented, pins it with a derived guard test, writes the merge path for the repo's merge model, treats the first batch as the test, and checks that the bot is working (PRs opening, PR-limit headroom, update runs green, every lockfile in the dependency graph, alerts and security updates on). Use when the user says "adopt Dependabot", "set up Dependabot", "dependabot.yml", "Dependabot isn't opening PRs", "is Dependabot working", "Dependabot security updates", or "land the Dependabot PRs".
compatibility: Designed for Claude Code or a similar harness with a Bash tool. Requires git, gh (authenticated), and python3 3.11+ with PyYAML, or uv to supply it. Stack-agnostic for github-actions; the package-ecosystem guards and the stale-declaration sweep are written for uv and pip.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: adopt Dependabot, set up Dependabot, dependabot.yml, Dependabot isn't opening PRs, is Dependabot working, Dependabot security updates, land the Dependabot PRs
---

# Adopting Dependabot

Gets Dependabot proposing reviewed, CI-gated diffs, and makes a broken config fail a test instead of going quiet. Built from two cohort adoptions that went very differently ([#376](https://github.com/gregoryfoster/skills/issues/376)):

- **notifier** (notifier#33): CI with no secrets, no cloud auth and no private index, green on the first try. Its problems came later, and quietly: a full PR limit silenced two tables for five weeks (notifier#103), and with the dependency graph off, no security update ever opened (notifier#140).
- **watcher** (watcher#283): CI authenticates to GCP through WIF, two packages resolve only from a private wheelhouse, and the repo merges to `main` locally.

**None of the failures this skill prevents shows up in Dependabot's docs as a failure.** Each one reads as "no updates available".

**Activation triggers:** "adopt Dependabot", "set up Dependabot", "dependabot.yml", "Dependabot isn't opening PRs", "is Dependabot working", "Dependabot security updates", "land the Dependabot PRs".

## The Iron Law

<!-- skill:required id=iron-law -->
```
NO ECOSYSTEM TURNED ON BEFORE ITS RESOLUTION AND CI'S CREDENTIALS ARE READ
NO CONFIG WITHOUT A GUARD TEST THAT FAILS WHEN IT WOULD GO QUIET
NO "IT'S WORKING" WITHOUT THE CHECK: RUNS GREEN, LIMIT HEADROOM, EVERY LOCKFILE IN THE GRAPH
```

Pushing the config is outward-facing: PRs open within a minute. Turning on repository settings (the dependency graph, alerts, security updates) is the owner's action, never the skill's.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "No PRs, so nothing's out of date" | Or the limit is full, the ecosystem is mistyped, the directory is wrong, or the update run fails on a private index. Each reads the same. Run the check. |
| "The defaults are fine" | `open-pull-requests-limit` defaults to 5, then no version update opens. `versioning-strategy: auto` is `widen` for a library, which uv doesn't support. |
| "Version PRs arrive, so security updates work" | They're separate paths. With the dependency graph off, alerts match nothing, and transitive advisories arrive only as a red audit. |
| "`ignore:` the private package and turn uv on" | The updater still has to resolve it, and can't. Every run fails. That ecosystem is blocked; file it. |
| "Dependabot proposed v7, so v7 is newest" | A major-form pin stops at the last floating major tag. `setup-uv` was at v10.2.0. Read upstream's releases. |
| "CI was green" | After `@dependabot rebase`, read checks on the *new* head. The old commit's green reads the same. |
| "The scheduled workflow got the bump too" | Its PR's CI never ran it. Dispatch it once. |

## Script path resolution

The skill's `scripts/` directory ships inside the skill, not at the project root. Resolve each script once, and substitute the printed path wherever `<name.sh>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63), [#301](https://github.com/gregoryfoster/skills/issues/301)):

<!-- skill:required id=skill-scripts -->
```bash
N=adopting-dependabot
for S in inventory.sh check-dependabot.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

The two assets, `test_dependabot.py` and `test_dependency_imports.py`, are in the skill's `assets/`, beside `scripts/`.

## The phases

Phases 1–3 are read-only or test-first, and safe in any session. Phase 7 is outward-facing.

1. **Map CI's credential surface.** `bash "<inventory.sh>" --upstream` reads every workflow, job by job: `needs` is `nothing`, `secret`, `oidc`, or `unknown` for a call to another repo's reusable workflow, with `vars`, write permissions and private-index steps. A Dependabot run gets only Dependabot secrets and a read-only token: [inventory.md](references/inventory.md#phase-1-cis-credential-surface), [credential-context.md](references/credential-context.md).
2. **Inventory what the bot can and can't move.** From the same JSON: ecosystems, private indexes, git-sourced and exact pins, generated and scheduled-only workflows, floating runner labels, and each action's pin form against upstream's tag scheme (`frozen` is a major pin past the last floating major). Give each item a disposition: *bot*, *bot with ignore*, *manual (say why)*, *blocked → issue*: [inventory.md](references/inventory.md#phase-2-what-the-bot-can-and-cant-move).
3. **Sweep stale declarations before turning on a package ecosystem.** Copy `assets/test_dependency_imports.py` to `tests/ci/`, set its ADAPT block, and run it red: every runtime declaration is imported, or allowlisted with a **witness** the test checks. Drop the rest, test-first: [inventory.md](references/inventory.md#phase-3-stale-declarations).
4. **Write the config, smallest honest scope first.** `github-actions` alone, unless the package ecosystem's resolution is solved. Per block: `directory`/`directories`, `schedule.interval`, a **derived** `open-pull-requests-limit`, `commit-message.prefix`, and for uv/pip `versioning-strategy: increase-if-necessary`, a dev group and `ignore:` for lockstep pins. Comment each key with the failure it prevents: [config-keys.md](references/config-keys.md).
5. **Write the guard test.** Copy `assets/test_dependabot.py` to `tests/ci/`, edit only its ADAPT block (`ENABLED`, `HELD_BACK` with each reason, `IGNORED`, `COMMIT_TYPES`, `SHA_PINS`). It pins the version, the ecosystem set, directories, interval, prefix, strategy, groups, and the PR limit derived from the repo. **Mutation-check it**: break the config each way the table in [config-keys.md](references/config-keys.md) lists, and see a guard fail each time.
6. **Write the merge path** for the repo's merge model, in the repo's own docs: GitHub-merge, or local-merge with the rebase race handled, and red-auth triage by the auth action's own errors: [merge-paths.md](references/merge-paths.md).
7. **Push, and treat the first batch as the test.** Watch the `Dependabot Updates` runs and each PR's CI: per job, the actor is `dependabot[bot]` and the auth steps passed. Before landing a major bump, compare it with upstream's newest release; a gap is a frozen tag or a fresh major, and is filed, not a reason to hold the PR. Dispatch each scheduled-only workflow a bump touched: [first-batch.md](references/first-batch.md).
8. **Check, and file what's left.** `bash "<check-dependabot.sh>" --repo OWNER/REPO` reads whether the bot is working: config, PR-limit headroom per ecosystem, the latest update runs, the dependency graph against every committed lockfile, alerts, security updates. A failing graph, alerts or security-updates check is the owner's to switch on, all three together: [security-updates.md](references/security-updates.md). Then file each blocked ecosystem with its options, each generator downgrade upstream, and each frozen action not moved. Record the result where the repo keeps state.

`check-dependabot.sh` is also the standing check: run it whenever "is Dependabot working?" comes up, and on any repo whose lockfile a host's audit found behind.

## Decisions this skill makes by default

- **A private index is detected and filed, not built.** Serving it over HTTPS, or moving to a registry Dependabot supports with OIDC, is per-cohort infrastructure.
- **A scheduled cap-staleness check**, for an ecosystem Dependabot can't resolve, is out of scope: it's one of the options the blocked ecosystem's issue lists.
- **`github-actions` gets one PR per action**, for a changelog read per major. Grouping is an option where CI cost dominates (`auditing-ci-cost`).

## Related skills

- **`patching-hosts`** audits what a host *runs*: its language-dependencies class audits a deployed `uv.lock`, and its record reads the owning repo's update mechanism. This skill is the repo side of that loop: a host audit that finds advisories in a tree whose repo fails `check-dependabot.sh` points here. Neither skill updates the other's side.
- **`shipping-work*`**: Step 3 can point at [merge-paths.md](references/merge-paths.md) for a PR it didn't author.
- **`curating-context`**: `install-cadence.sh` renders a workflow Dependabot bumps, and a re-render downgrades it ([#373](https://github.com/gregoryfoster/skills/issues/373)).
- **`auditing-ci-cost`**: every Dependabot PR runs full CI. Count its weekly volume, and weigh grouping.
- **`init-project-*`**: offer this skill once CI exists.

## Detail Docs

- [references/inventory.md](references/inventory.md) — phases 1–3: credential classes, dispositions, pin forms against upstream's tags, the stale-declaration sweep
- [references/config-keys.md](references/config-keys.md) — each key's silent failure, the derived PR limit, grouping, a starting config
- [references/credential-context.md](references/credential-context.md) — what a Dependabot run gets, verified versus stated, red-auth triage per auth action
- [references/merge-paths.md](references/merge-paths.md) — GitHub-merge and local-merge runbooks, the rebase race, generated workflows
- [references/first-batch.md](references/first-batch.md) — watching the first batch, version gaps, changelogs, scheduled-only workflows, filing what's left
- [references/security-updates.md](references/security-updates.md) — the three switches, what their absence cost, and the check

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by `tests/structural/test_skill_self_budget.py`; both readings must clear it. Each `references/` doc is held to the 10,000-token per-doc budget.
