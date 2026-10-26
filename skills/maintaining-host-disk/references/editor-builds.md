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
- remove only trees the home's owner owns, and run as that owner;
- never touch `lru.json`.

## Where they differ from #482's ask

Read from the VERSION 2 layer at the #485 gate. The skill states these; changing any of them is Provisioner's to do.

1. **A staged newer build is removed** once it's past the grace window. The CLI's agent host pre-downloads every Stable release, and #482 keeps a build newer than the newest running one. The likely cost is a re-download per release, which is unmeasured.
2. **The VSIX cache is pruned.** #482 left it, since the server prunes `CachedExtensionVSIXs` itself on restart.
3. **Stable only.** Insiders builds aren't matched.
4. **No Cursor or Windsurf** (`~/.cursor-server`, `~/.windsurf-server`). #482 hadn't verified their layout either.

A host that needs any of these kept differently files it on Provisioner, with the owner's approval.

## broker's script

broker's `scripts/prune_editor_builds.sh` is on the retire list ([retiring.md](retiring.md)). It keeps a staged newer build and the running CLI binary, and its first run removed only two idle CLI binaries (69,110,208 bytes). Retiring it trades difference 1 above for one GC: check the next GC report for a staged build before retiring it.
