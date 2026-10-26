# Retiring a host's own disk tooling

Six hosts built their own GC before the canonical one existed (inventory in CannObserv/provisioner#61). Each retires in the same change that turns the canonical GC on, so the host never runs two GCs or none. **First check what the old one removed that the GC keeps.** A GC that keeps more is a disk that fills again.

## The retire list

| Repo | Implementation | Matched by | Notes |
|---|---|---|---|
| wslcb | `disk_hygiene.py` | `disk_hygiene.py` | |
| address-validator | `disk-hygiene.sh` | `disk-hygiene.sh` | tracked in CannObserv/address-validator#326 |
| address-validator | `docker-prune` | `docker-prune`, `docker-prune.sh` | once the `docker` tier covers it ([below](#docker)) |
| watcher | `cleanup.sh` | `cleanup.sh` | |
| observo | its cache timers | by hand | no fixed name to match |
| usa-wa | `disk-gc.sh` | `disk-gc.sh` | not the canonical `disk-gc`, which has no `.sh` |
| power-map | `prune_disk.py` | `prune_disk.py` | |
| power-map | `check_disk_headroom.py` | `check_disk_headroom.py` | maps to `alert_at_percent = 85` with the default clear line |
| broker | `scripts/prune_editor_builds.sh` | `prune_editor_builds.sh` | from #482; [editor-builds.md](editor-builds.md) |

`scripts/_retire_scan.py` carries the same list, and a test holds the two together.

**power-map's sensor:** its state file (`$STATE_DIRECTORY/state`, `alert`/`ok`) doesn't carry over. If power-map is held in its band when it switches, the canonical sensor starts out not held.

## What the check automates

`retire-check.sh` reads the host and changes nothing:

- **found:** each systemd service (system, or per-user from each `etc/passwd` home's `~/.config/systemd/user` and `~/.local/share/systemd/user`), with every drop-in merged as systemd merges them, its timer (drop-ins included), and each crontab, anacrontab or `cron.<period>` entry that runs a listed implementation. Each says whether it's enabled (a `cron.<period>` entry only when run-parts would run it: executable, and named with letters, digits, `_` and `-` only), the word that matched, and `file:line`. A match is a whole word of a command, inside `sh -c` strings and before a redirect too, or the unit's own name. Commands print redacted (tokens, keys, passwords, Authorization headers, URL paths), so the JSON can go on the adoption issue; still read it before pasting. A basename can collide: `cleanup.sh` on a host that isn't watcher's is a candidate to read, whatever repo the match names.
- **candidates:** host-local units and cron lines whose name or command looks like disk tooling but matches no entry. Read each one: a host may have built more than the list knows. Packaged units under `lib/` are never offered.
- **canonical:** whether the GC is installed, its `VERSION`, and each timer's state.
- **gc_report:** the GC's report-only run (`--run-gc-report`, or `--gc-report FILE` for one you took).

## What stays by hand

The check finds where an old tool runs. It can't read an arbitrary script and say what it removed, so this part is a checklist, read against the old tool's own source and the GC's report:

1. **Which paths did it remove that no GC tier covers,** or that a tier covers but this host's config leaves off (`worktrees` with an empty `worktree_repos`, `docker` off)?
2. **Did it remove anything the GC deliberately keeps?** Containers, volumes, unused tagged images unless `docker_unused_images_days` opts in, a VS Code build still in use or touched within the grace window, a tree with any entry newer than 60 minutes.
3. **Did it keep anything the GC removes?** A staged newer VS Code build and the VSIX cache are the known ones ([editor-builds.md](editor-builds.md)).
4. **Does anything else depend on it?** A monitor reading its journal lines, a state file, a health check calling it.
5. **Is its cadence faster than daily?** Then the canonical timer needs a drop-in, timer first and monitor second ([turning-on.md](turning-on.md#the-cadence)).

Answer each in the host's adoption issue, then disable and remove the old units in the same change that enables the canonical timers.

### The nine rules

address-validator#326's nine rules are implemented in the GC. The skill doesn't re-encode them; they are the checklist's second question, rule by rule:

| # | Rule | The canonical GC |
|---|---|---|
| 1 | `uv cache prune --force` | prunes `--force`, as the cache's owner, with a 600 s timeout; `clean --force` too, above `uv_clean_above_mb` (observo#711) |
| 2 | a bounded run | `TimeoutStartSec=1800` |
| 3 | both SocratiCode pins, per run | the configured repo settings and VS Code's machine setting, `sha512(spec)[:16]` |
| 4 | an unreadable spec source skips `_npx` | yes: it fails toward keeping trees (usa-wa#485) |
| 5 | the grace is the newest entry anywhere, 60 min; a walk error keeps the tree | the mtime or ctime of any entry. npx reinstalls a moved spec into the same directory, so the top level's mtime can be old |
| 6 | warnings at warning priority | sd-daemon `<4>` prefixes |
| 7 | VS Code: the 2 newest by `lru.json`, plus running | **differs:** liveness only. `lru.json` omitted the live build on co-provisioner, observo and co-replicator, and named builds no longer on disk |
| 8 | orphaned worktrees, unregistered, older than 30 min | yes, off unless `worktree_repos` names the repo |
| 9 | the timer's quiet window | daily 05:15 UTC plus up to 30 min; a host overrides `OnCalendar=` with a drop-in |

### Docker

The GC's `docker` tier is off in the template; a host turns it on where Docker builds. Its keys, in `[gc]`:

- `docker_cache_hours` (168): build cache older than this goes, and 0 means all of it. Dangling images go once they're older than `grace_minutes`.
- `docker_builders`: buildx builders whose cache goes too, as `<user>:<builder>`, pruned as that user. buildx keeps a builder in its creator's `~/.docker`; observo's `observo-worker0` is one.
- `docker_unused_images_days` (0, off): tagged images no container uses, older than this. It's opt-in because a pull restores whatever an image was slimmed to drop, as with usa-wa's ollama.

**It never removes a container or a volume.** SocratiCode's qdrant and ollama indexes live in volumes, and some stopped containers are kept on purpose. A host's own `docker-prune` that removed either is doing something the GC won't, and the owner decides whether that stays.
