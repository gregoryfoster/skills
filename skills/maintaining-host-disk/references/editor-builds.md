# Editor builds

VS Code's remote server builds accumulate under each home, about 640–700M each, and the editor doesn't bound them: two writers share one leaky `lru.json`, and `code tunnel prune` on 1.140.0 deletes nothing (microsoft/vscode#337944). On co-broker, seven builds reached 4.5 GB and pushed `/` to 90% on 2026-10-24 (CannObserv/broker#126, [#482](https://github.com/gregoryfoster/skills/issues/482)).

The canonical GC already prunes this scope, so this skill owns it, and patching-hosts doesn't get a class of its own: its [pruning reference](../../patching-hosts/references/pruning.md) points here. A second implementation would be two sources for the same deletions.

## The GC's two tiers

| Tier | Covers |
|---|---|
| `vscode-servers` | `~/.vscode-server/cli/servers/Stable-*` |
| `vscode-clis` | `~/.vscode-server/code-*` |

Both:

- keep anything in use, judged from `/proc` (exe, cwd, maps, fd), not from `lru.json`, which omitted the live build on three hosts and named builds no longer on disk;
- withhold a tree with any entry touched within `grace_minutes` (60);
- remove only trees the home's owner owns, and remove them **as root**, by file descriptor;
- never touch `lru.json`.

## Where they differ from #482's ask

Read from the VERSION 2 layer, at the #485 gate and in its review. Each says who can change it.

| # | The GC | #482 asked | Who controls it |
|---|---|---|---|
| 1 | removes a **staged newer build** once it's past the grace window. The CLI's agent host pre-downloads every Stable release; the likely cost is a re-download per release, unmeasured | keep anything newer than the newest running build | Provisioner |
| 2 | with nothing running, **keeps none**: there is no keep-newest rule | with nothing running, keep the newest | Provisioner |
| 3 | prunes the **VSIX cache**, as its own `vsix-cache` tier | leave it: the server prunes `CachedExtensionVSIXs` itself on restart | **the host:** drop `vsix-cache` from `tiers` |
| 4 | matches **Stable only**; Insiders builds aren't matched | any quality | Provisioner |
| 5 | has **no Cursor or Windsurf** (`~/.cursor-server`, `~/.windsurf-server`); #482 hadn't verified their layout either | maybe both | Provisioner |
| 6 | removes **as root**, by descriptor, only what the owner owns | as the user, never root | Provisioner |
| 7 | prunes **on its timer**, daily | a dry run first, and each removal approved | **the host**, in part: read the report-only `gc` run before enabling the timer, or leave `vscode-servers` and `vscode-clis` out of `tiers` and keep its own pruning |

A host that needs one of Provisioner's kept differently files it there, with the owner's approval.

## broker's script

broker's `scripts/prune_editor_builds.sh` is on the retire list ([retiring.md](retiring.md)). As #482 described it (observed 2026-10-25, not re-verified: `gh api repos/CannObserv/broker/contents/scripts/prune_editor_builds.sh`), it kept a staged newer build and the running CLI binary, and its first run that day removed only two idle CLI binaries (69,110,208 bytes). Retiring it trades difference 1 above for one GC: check the next GC report for a staged build before retiring it.
