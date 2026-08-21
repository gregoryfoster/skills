# Skills — how downstream projects consume this repo

The vendoring pattern and its rules, for a human or an audit. Agents performing
these operations are taught by [`managing-skills`](../skills/managing-skills/),
which AGENTS.md points at directly.

## The submodule + symlink pattern

Projects use the **git submodule + symlink** pattern:

1. Add this repo as a submodule at `skills-vendor/gregoryfoster-skills/`
2. Symlink individual skills into the project's `skills/` directory using relative paths
3. The agent framework auto-discovers skills by scanning `skills/` — symlinks make them visible

Key rules:
- Submodule path convention: `skills-vendor/<owner>-<repo>/` (e.g., `skills-vendor/gregoryfoster-skills/`)
- Symlink paths must be relative: `../../skills-vendor/gregoryfoster-skills/skills/<skill-name>`
- Local overrides (committed directories in `skills/`) always win over symlinks
- The `skills-vendor/` directory is read-only from the consuming project's perspective
- Install `.skills/doctor.sh` via `bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-doctor.sh` — Phase 1 of `reviewing-*` / `shipping-*` skills uses it to self-heal dangling vendor symlinks. The manual command is only needed before the first session: thereafter the doctor re-syncs itself from the vendored source on every run ([#84](https://github.com/gregoryfoster/skills/issues/84)), and the auto-refresh hook re-installs it opportunistically **and commits it** ([#86](https://github.com/gregoryfoster/skills/issues/86)) — so nobody has to remember to track a file a hook created. Consumers still need `.skills/doctor.sh` committed at least once; until it is, fresh worktrees and CI clones have no doctor and the Phase 1 preflight silently no-ops.
- Install the auto-refresh hook via `bash skills-vendor/<owner>-<repo>/skills/managing-skills/scripts/install-refresh.sh`. It is what advances the submodule pointer; `.skills/doctor.sh` heals symlinks and never bumps anything, so a consumer with a doctor and no hook is frozen at whatever commit it was vendored at. The contract is **two** artifacts — the symlink at `.claude/hooks/skills-submodule-update.sh` *and* a `SessionStart` entry in `.claude/settings.json` — and only the second makes it run, so a symlink alone looks installed to anyone listing `.claude/hooks/` and refreshes nothing. Four of twelve audited consumers were in exactly that state ([#167](https://github.com/gregoryfoster/skills/issues/167)). `install-refresh.sh --check` reports both halves independently (exit 0 both present, 3 either missing — and since [#200](https://github.com/gregoryfoster/skills/issues/200), 3 also when the hook is installed as a *copy* where a symlink is possible, which `.skills/doctor.sh` cannot see by construction), and `.skills/doctor.sh` warns when it sees the half-installed shape.
- The doctor is the one **vendored skill artifact** copied rather than symlinked — a symlink would dangle in the exact state it exists to repair. (One-time scaffolding like `init-project-fastapi`'s is a different thing: it isn't expected to track upstream.) Any future artifact that must be a copy *and* track upstream faces the same drift problem, and gets the same answer: sync from the vendored source at a point guaranteed to run, compare content rather than mtime (git stamps checkout times), keep the sync best-effort so it can never fail a preflight, and skip it in read-only modes so a CI probe can't dirty a tracked file.

## Self-discovery (`.claude/skills` in this repo)

This repo's own `.claude/skills` is a symlink to `../skills`, so Claude Code auto-discovers the skills under `skills/` when this repo is opened as the working directory. Recreate with:

```bash
ln -sfn ../skills .claude/skills
```

The target must be `../skills` (one `..`), not `../../skills` — the latter resolves back to the repo root because the repo itself is named `skills`, which silently breaks discovery.
