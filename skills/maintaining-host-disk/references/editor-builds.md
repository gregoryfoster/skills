# Editor builds

VS Code's remote server builds accumulate under each home, about 640–700M each, and the editor doesn't bound them: two writers share one leaky `lru.json`, and `code tunnel prune` on 1.140.0 deletes nothing (microsoft/vscode#337944). On co-broker, seven builds reached 4.5 GB and pushed `/` to 90% on 2026-10-24 (CannObserv/broker#126, [#482](https://github.com/gregoryfoster/skills/issues/482)).

The canonical GC already prunes this scope, so this skill owns it, and patching-hosts doesn't get a class of its own: its [pruning reference](../../patching-hosts/references/pruning.md) points here. A second implementation would be two sources for the same deletions.

## The GC's two tiers

| Tier | Covers |
|---|---|
| `vscode-servers` | `~/.vscode-server/cli/servers/Stable-*` |
| `vscode-clis` | `~/.vscode-server/code-*` |

`vscode-servers` keeps:

- anything in use;
- every build newer than the newest live one;
- with nothing live, the newest.

"Newer" is by `server/product.json`'s `version`, never by the `Stable-<commit>` name, mtime (VS Code restores the archive's, usa-wa#512) or ctime (a re-download resets it). A build whose version can't be read as `<major>.<minor>.<patch>` is kept (`version unread: …`), and when builds are live but none of their versions can be read, every idle build is. Live is the `/proc` evidence alone: a build that's only settling doesn't count. Older builds are judged as below.

`vscode-clis` keeps anything in use.

Both:

- judge use from `/proc` (exe, cwd, maps, fd), not from `lru.json`, which omitted the live build on three hosts and named builds no longer on disk;
- withhold a tree with any entry touched within `grace_minutes` (60);
- remove only trees the home's owner owns, and remove them **as root**, by file descriptor;
- never touch `lru.json`.

## Where they differ from #482's ask

Read from the VERSION 3 layer ([#510](https://github.com/gregoryfoster/skills/issues/510)), pulled through this skill on 2026-10-28. Rows 1 and 2 differed up to VERSION 2 and now match. Each row says who can change it.

| # | The GC | #482 asked | Who controls it |
|---|---|---|---|
| 1 | keeps a **staged newer build**: every build newer than the newest live one, by version. Matches #482. VERSION 2 removed it, and the CLI's agent host staged it again within hours: 5 h 25 min on co-replicator ([#504](https://github.com/gregoryfoster/skills/issues/504)), and after every daily run from 2026-10-23 to 10-26 on the image repo's VM. That cost 641M of download per host per day, and the host's disk cycled with it, so a host still on VERSION 2 sets its headroom lines for the peak, not the post-GC level | keep anything newer than the newest running build | Provisioner |
| 2 | with nothing running, **keeps the newest**, by version. Matches #482 | with nothing running, keep the newest | Provisioner |
| 3 | prunes the **VSIX cache**, as its own `vsix-cache` tier | leave it: the server prunes `CachedExtensionVSIXs` itself on restart | **the host:** drop `vsix-cache` from `tiers` |
| 4 | matches **Stable only**; Insiders builds aren't matched. Kept in VERSION 3, its reason recorded in Provisioner's README (decided in CannObserv/provisioner#96, a private repo) | any quality | Provisioner |
| 5 | has **no Cursor or Windsurf** (`~/.cursor-server`, `~/.windsurf-server`) until a host runs one; #482 hadn't verified their layout either. Kept in VERSION 3, its reason in the README (provisioner#96) | maybe both | Provisioner |
| 6 | removes **as root**, by descriptor, only what the owner owns: `--prune` needs every process's `/proc` entries to judge liveness. Kept in VERSION 3, its reason in the README (provisioner#96) | as the user, never root | Provisioner |
| 7 | prunes **on its timer**, daily | a dry run first, and each removal approved | **the host**, in part: read the report-only `gc` run before enabling the timer, or leave `vscode-servers` and `vscode-clis` out of `tiers` and keep its own pruning |

A host that needs one of Provisioner's kept differently files it there, with the owner's approval.

## broker's script

broker's `scripts/prune_editor_builds.sh` is on the retire list ([retiring.md](retiring.md)). As #482 described it (observed 2026-10-25, not re-verified: `gh api repos/CannObserv/broker/contents/scripts/prune_editor_builds.sh`), it kept a staged newer build and the running CLI binary, and its first run that day removed only two idle CLI binaries (69,110,208 bytes). Since VERSION 3 the GC keeps a staged newer build too, so retiring the script gives up nothing there. When a build is staged, the next GC report shows it kept: `kept vscode-servers … Stable-<commit> (<v>, newer than the live <v>)`.
