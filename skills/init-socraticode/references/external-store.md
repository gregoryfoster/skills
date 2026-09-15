# External store — a Qdrant this repo does not host

Read this when `STORE=external`: the project is a client of a Qdrant it does
not run — a store one VM serves to a cohort, or Qdrant Cloud. Upstream calls it
`QDRANT_MODE=external`. Every phase still applies. This one changes what Phase
1 gates, adds Phase 3's client config, and makes Phase 5's `validate-store`
gate load-bearing ([#287](https://github.com/gregoryfoster/skills/issues/287)).

## What to collect

| Value | Where it goes | Why it matters |
|---|---|---|
| `QDRANT_URL` | `.claude/settings.json` `env` | `https://<full host name>:6333`. The full name, because that is what the certificate names — on a tailnet the MagicDNS FQDN `<host>.<tailnet>.ts.net`, never the short name. Never `QDRANT_HOST`: a URL built from a host alone uses `QDRANT_PORT`, whose default is 16333, not Qdrant's 6333, and the mistake reads as a network fault. |
| `QDRANT_API_KEY` | `.claude/settings.local.json` `env` (git-ignored), or user settings | Never the tracked file. With a key, the URL must be https: upstream refuses to send it over plain http to anything but loopback. |
| `OLLAMA_MODE`, `OLLAMA_URL` | `.claude/settings.json` `env` | `external` and the store's Ollama. Left at `auto`, a host with no native Ollama on localhost:11434 starts an Ollama container — Docker after all. |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | `.claude/settings.json` `env` | What every other client of the store uses: a collection holds vectors from one model at one dimension. |
| `PROJECT_ID` | `.socraticode.json` | Default: the repo name, with characters outside `[a-zA-Z0-9_-]` replaced by `-` (upstream throws on them rather than sanitize). Unique in the store. |

## Before Phase 1: the key, and the values preflight needs

The one write `SKILL.md`'s HARD-GATE allows before preflight, in this order:

1. **The ignore rule, first.** `.claude/settings.local.json` must be ignored by
   a rule the repo tracks — a global excludes file protects one machine, not
   the repo, and a secret written before the check is one `git add -A` from a
   commit. The test and the append block are in
   [`linked-projects.md`](linked-projects.md#make-sure-settingslocaljson-is-git-ignored).
2. **Then the key**, into the `env` block of `.claude/settings.local.json` —
   never on a command line, where `ps` and shell history keep it, and never in
   the tracked file. Where the operator delivers it out of band, wait for it
   rather than asking for it in the conversation.

The key alone addresses nothing: no `QDRANT_MODE` travels with it.

Preflight reads each value from the environment, then
`.claude/settings.local.json`, then `.claude/settings.json`. Before Phase 3 has
written the rest, pass them to the Phase 1 run:

```bash
QDRANT_MODE=external QDRANT_URL=https://<full host name>:6333 \
  OLLAMA_MODE=external OLLAMA_URL=http://<host>:11434 \
  bash "<SKILL_DIR>/scripts/preflight.sh"
```

## Phase 3: `projectId` first, the `env` block second, never the block alone

1. **`.socraticode.json`** with `projectId`, and `linkedProjects` if any (step
   4). Commit it.
2. **Only then the `env` block** (step 5), merged into `.claude/settings.json` —
   never clobbered, since the file also carries hooks and permissions:

   ```json
   {
     "env": {
       "QDRANT_MODE": "external",
       "QDRANT_URL": "https://<full host name>:6333",
       "OLLAMA_MODE": "external",
       "OLLAMA_URL": "http://<host>:11434",
       "EMBEDDING_MODEL": "nomic-embed-text",
       "EMBEDDING_DIMENSIONS": "768"
     }
   }
   ```

**Why this order.** With no `projectId`, the id is `sha256(<absolute path>)[:12]`,
and where hosts check repos out at the same path it is not per-host: broker's
VM and notifier's clone of broker both resolved to `d4eab3ecb321`. And a
session writes before anyone asks it to — the server's startup auto-resume
runs an incremental update of its cwd project whenever that project's
collection exists, and status and query calls start the file watcher on the
same condition. So the block alone becomes a two-host write the moment a
session starts, under an index lock that is host-local
(`os.tmpdir()/socraticode-locks`). Nothing stops it and nothing reports it.

`mcp-driver.mjs validate-store` fails on that state, and the driver's `index`,
`status` and `verify` refuse to launch a server into it.

## Confirm trust before the first index

The `env` block reaches the server only in a session Claude Code started in a
**trusted** folder after the block was written. Otherwise `QDRANT_MODE` reverts
to managed and `OLLAMA_MODE` to auto, and the server does not report missing
configuration: it starts a local Docker stack, through the socket if the host
has one.

So the session that wrote the block cannot index; its server started without
it. After step 2, restart Claude Code in the repo, accept the trust prompt, and
from the new session run `preflight.sh --check`. Its line `This session carries
.claude/settings.json's env block` must be ✓. Continue from Phase 4 there.
Phase 6 confirms from the server's side: `codebase_health` reports `Qdrant mode:
external` and the store's endpoint, and no container.

Trust is checked by its effect because it cannot be read reliably from outside:
it is inherited from a parent folder, and IDE and SDK sessions skip the prompt.

## One host per `projectId`

A shared store has no shared lock, so each `projectId` is indexed from one
host — the repo's own. Other hosts reach it through `linkedProjects` and a
one-file stub, never by indexing a clone:

```text
../<sibling>/.socraticode.json    →  {"projectId": "<sibling>"}
```

The linked path only selects which collection to query; no source is read from
it. A stub naming a collection that does not exist yet is skipped by search,
silently.

## Adopting `projectId` on a repo already in the store

It renames the collections, and orphans any set already in the store under
this checkout's path hash (`validate-store` prints it as `pathHash`). The three
remove tools — `codebase_remove`, `codebase_graph_remove`,
`codebase_context_remove` — take only a `projectPath` and resolve the id the way
indexing does, `.socraticode.json` first. So the order decides what they delete:

- **Before** the `projectId` reaches the checkout that wrote the old set, run
  them there, on the host that wrote it: that checkout still resolves to the
  hash.
- **After**, the same calls delete the *new* collections. The old set is then
  reachable only by a server started with `SOCRATICODE_PROJECT_ID=<pathHash>`,
  which outranks the file: export it for one Claude Code session, run the
  three removals there, and end the session. Never persist it.

## Namespace

- `SOCRATICODE_PROJECT_ID` overrides the file for one process. Never persist it.
- `QDRANT_COLLECTION_PREFIX` also prefixes the store-wide
  `socraticode_metadata` collection, so one client setting it splits the
  namespace for all of them.
- `SOCRATICODE_BRANCH_AWARE` suffixes only a path-hash id; a `projectId`
  ignores it.
- With a `projectId`, every checkout of the repo addresses the same
  collections, worktrees included: a session started in a worktree updates
  them from that worktree's files.
- `.claude/settings.local.json` belongs to one checkout. A worktree has none, so
  a session started there carries no key unless user settings hold it.
