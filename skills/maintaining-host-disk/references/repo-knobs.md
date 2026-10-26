# Repo-side disk knobs

Some disk costs belong to a repo, and a host-level tool shouldn't guess at them: only the repo knows what its tests leave behind, what its data is worth, and which of its trees must survive a prune. Each knob here is a measured, per-repo decision, made and recorded in that repo. None is a `.skills/` file of this skill.

## pytest basetemps

```toml
[tool.pytest.ini_options]
tmp_path_retention_count = 1
tmp_path_retention_policy = "failed"
```

This solves *growth*, not the *swing*. The newest run's tree is always on disk (about 0.5G on power-map, in `/tmp/pytest-of-<user>/pytest-N`), and pytest prunes at exit, so a failing run's residue survives the green runs after it (CannObserv/power-map#665). A repo near its host's line crosses it twice per commit: once when the run writes its tree, once when the next run prunes it.

**Size the host's `alert_at_percent` from the baseline plus one gate's basetemp,** not from the baseline alone ([turning-on.md](turning-on.md#picking-the-lines)).

## Worktree cost

Each worktree carries its own `.venv` and `node_modules`, about 0.2–0.8G each. That's a repo's cost while the worktree is live; a host tool can't tell a parked worktree from an abandoned one.

Orphaned worktree directories, ones git no longer registers, are the GC's `worktrees` tier. It runs only when the host's config lists `worktrees` in `tiers` **and** names the repo in `worktree_repos`; the template does neither. Then it removes only unregistered directories older than 30 minutes.

## App data tiers

An app's own data (caches, exports, scraped archives) is a retention contract the repo states: what it keeps, for how long, and who may delete it. Never automatic, and never the GC's (cf. CannObserv/usa-wa#396).

## `npx_spec_files`

The GC's `_npx` prune keeps the npx trees that pinned specs resolve to. A repo that pins SocratiCode names its `.claude/settings.json` in the host's `npx_spec_files`, so the pinned tree is kept (the init-socraticode pin work: [#295](https://github.com/gregoryfoster/skills/issues/295), [#327](https://github.com/gregoryfoster/skills/issues/327), [#332](https://github.com/gregoryfoster/skills/issues/332)). The GC reads VS Code's machine setting too. An unreadable spec source skips the `_npx` prune entirely, with a warning, rather than exempting nothing.
