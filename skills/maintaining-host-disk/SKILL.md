---
name: maintaining-host-disk
description: Adopts Provisioner's canonical disk GC and headroom sensor on a CannObserv cohort host, and keeps it current. It pulls the GC's one layer from a digest-pinned co-image-base release anonymously and without docker, refusing on any failed check, then installs or updates it from MANIFEST and turns it on per host (config, a report-only run, the co-status monitor, the timers). It retires the host's own disk tooling only after checking what that removed, states where the GC's VS Code tiers differ from a host's own editor-build pruning, and carries the repo-side disk knobs no host tool should own. Use when the user says "disk GC", "root disk is full", "disk headroom", "install the disk GC", "update the disk GC", "retire disk hygiene", or "VS Code server builds".
compatibility: Designed for Claude Code or a similar harness with a Bash tool, on a Linux host with systemd (Debian or Ubuntu), reached as a user with sudo. Pulling needs curl, tar, sha256sum and python3, and network to ghcr.io and the host its blobs redirect to (pkg-containers.githubusercontent.com).
metadata:
  author: gregoryfoster
  version: "0.1"
  triggers: disk GC, root disk is full, disk headroom, install the disk GC, update the disk GC, retire disk hygiene, VS Code server builds
---

# Maintaining Host Disk

Gets a host onto the cohort's one disk GC and headroom sensor, and off its own. The GC is Provisioner's (CannObserv/provisioner#61): it ships in the public image `ghcr.io/cannobserv/co-image-base` as one dedicated layer, so a new VM has it at birth, off. Every other host adopts the same files through this skill. Built from [#425](https://github.com/gregoryfoster/skills/issues/425), with [#482](https://github.com/gregoryfoster/skills/issues/482)'s editor builds bundled in.

**Status: new.** No host has adopted it through this skill yet.

**Activation triggers:** "disk GC", "root disk is full", "disk headroom", "install the disk GC", "update the disk GC", "retire disk hygiene", "VS Code server builds".

## The Iron Law

<!-- skill:required id=iron-law -->
```
NO INSTALL FROM ANYTHING BUT THE PINNED RELEASE, CHECKED; NEVER FROM :latest
NO RETIREMENT BEFORE THE RETIRE CHECK HAS READ WHAT THE OLD TOOL REMOVED
NO INSTALL, ENABLE, RETIREMENT OR REMOVAL WITHOUT THE OWNER'S APPROVAL, GIVEN IN THE HOST'S OWN SESSION
```

The GC's tiers, keep rules and sensor are Provisioner's. Where the GC does something a host wants done differently, the change is raised there, never patched into the installed copy: at the same `VERSION`, `install-disk-gc.sh` refuses a copy that no longer matches its MANIFEST, and an update overwrites it.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "`:latest` is the newest release, so pull that" | `:latest` only says which release is newest. Install from the pin, whose manifest digest the puller checks first. |
| "The digests matched, so the layer is safe to extract" | The digests prove the bytes are the release's. Members are checked separately, before extracting: no link, no `..`, nothing outside `usr/local/lib/`. |
| "The GC prunes the same things, so the old script can go" | Read what the old one removed that the GC keeps: containers, volumes, unused tagged images, tiers that are off. [retiring.md](references/retiring.md). |
| "`journalctl -p err` shows no alerts" | It does for the GC, whose lines carry priorities. A host's own script logs plain stderr at `info`. [verifying.md](references/verifying.md). |
| "Weekly is enough for VS Code builds" | Two ~640M server builds shipped in one week on power-map. Keep the GC daily. |
| "The update only changed the GC script, so restart journald anyway" | Only when its drop-in changed: the installer compares the bytes and says. |

## Script path resolution

The skill's `scripts/` directory ships inside the skill, not at the project root. Resolve each script once, and substitute the printed path wherever `<name.sh>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63), [#301](https://github.com/gregoryfoster/skills/issues/301)):

<!-- skill:required id=skill-scripts -->
```bash
N=maintaining-host-disk
for S in pull-disk-gc.sh install-disk-gc.sh retire-check.sh remove-disk-gc.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

## The release pin

The release this skill installs is pinned in `scripts/_pin.sh`, and only there: a 40-hex tag and its manifest's sha256, the `VERSION` that tag's layer holds, and the sha256 of the layer's own MANIFEST, which binds every file it lists to the release. There is no `.skills/` knob for it. A new GC release is a commit to this skill, and reaches a host through its repo's skills-vendor bump. `VERSION` is an integer that goes up with every change to the layer's files; a host updates when the pin's is higher than its own.

## The run

1. **Pull**, as any user: `bash "<pull-disk-gc.sh>" --into <scratch>/staging`. It takes the anonymous token, checks the manifest against the pin (an index refuses), the config, the one `COPY disk-gc/ / # buildkit` layer by `.history`, the blob and its diff_id, every member before extracting, and MANIFEST's exact file set with `sha256sum --strict -c`. Any failure refuses, exits 3, says which step, and leaves no staging directory. The layer holds only `/usr/local/lib`: the GC and its `VERSION`, `MANIFEST` and `disk-gc.conf.example`, both services and timers, and the journald drop-in (`SystemMaxUse=512M`).
2. **Install or update**: `bash "<install-disk-gc.sh>" --staging <dir>` prints the plan: `install`, `update`, `current` or a refusal, which files land, which the new MANIFEST dropped, and whether journald restarts. With the owner's approval, `sudo bash "<install-disk-gc.sh>" --staging <dir> --approve`. It never trusts the staging tree as it stands: it copies it into a root-owned private directory, and checks that copy's MANIFEST against the pin and every mode (files 0644 or 0755, directories 0755) before installing from it. An update removes only what the new MANIFEST dropped, and MANIFEST itself is written last, as the commit marker: a run that fails part-way leaves the old one in place, and a re-run finishes the job. It never touches `/etc/cannobserv/disk-gc/` or a timer: an enabled timer stays enabled, and a first install leaves both off.
3. **Turn it on**, per host: the config from the example, a report-only run, the co-status monitor, the key, both timers, and a rehearsal page. Each step, the lines and the cadence: [turning-on.md](references/turning-on.md).
4. **Retire the host's own tooling** in the same change that enables the timers, never before its check. `sudo bash "<retire-check.sh>" --run-gc-report`, once the config exists, lists what on this host runs a retire-list implementation, and whether it's enabled, beside the GC's report-only run. It can't read a script and say what that removed; the checklist is by hand: [retiring.md](references/retiring.md).
5. **Verify** the first runs, then turn the monitor on: [verifying.md](references/verifying.md).
6. **Record** what was installed (the pin's `VERSION`), the config's lines and tiers, what was retired and why it was safe to, on the host's adoption issue.

**Removing it:** `bash "<remove-disk-gc.sh>"` prints the plan; with `--approve`, as root, it disables both timers, removes MANIFEST's files and MANIFEST, reloads, and restarts journald. It keeps the host's config and key, the GC's state, and anything MANIFEST doesn't list. Ask for the monitor to be disabled with it, or it pages *has stopped reporting*.

## Beyond the host

Some disk costs belong to a repo, not to a host tool: pytest basetemps, each worktree's own environment, app data tiers, and the SocratiCode pin the GC must keep. Each is a measured, per-repo decision: [repo-knobs.md](references/repo-knobs.md).

The GC's VS Code tiers prune editor server builds under each home, and differ from a host's own editor-build pruning in four stated ways: [editor-builds.md](references/editor-builds.md).

## What the skill never does on its own

It never installs from an unpinned tag, edits the installed GC, writes the host's `disk-gc.conf` or key without the owner, enables a timer before the report-only run has been read, retires a host's tool before its retire check, or files an issue or a monitor request in another repo without approval.

## Detail Docs

- [references/turning-on.md](references/turning-on.md) — the config, the report-only run, the monitor, the key, the timers, the rehearsal, picking the lines, the cadence
- [references/retiring.md](references/retiring.md) — the retire list, what the check automates, and the by-hand checklist against the nine rules
- [references/repo-knobs.md](references/repo-knobs.md) — the repo-side disk knobs no host tool should own
- [references/editor-builds.md](references/editor-builds.md) — the VS Code tiers, and where they differ from #482's ask
- [references/verifying.md](references/verifying.md) — reading the GC's and the sensor's runs, and a host's own scripts

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by `tests/structural/test_skill_self_budget.py`; both readings must clear it. Each `references/` doc is held to the 10,000-token per-doc budget.
