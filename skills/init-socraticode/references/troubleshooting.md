# Troubleshooting matrix — SocratiCode setup gotchas

The expensive-to-learn failure modes from the `usa-wa` rollout. Each row: the
symptom you'll see, why it happens, and the fix the skill bakes in.

| # | Symptom | Cause | Fix / where handled |
|---|---|---|---|
| **A** | `claude mcp list` shows `plugin:socraticode:socraticode ✓ Connected`, but the `codebase_*` tools are absent from the session and `ToolSearch "select:…codebase_search…"` returns nothing — so `codebase_index` can't be called normally. | The MCP server connected, but the session never injected the deferred tool schemas into the toolset. | **Primary:** restart Claude Code — a fresh session usually registers the deferred tools; then the `ToolSearch` prefetch works. **Fallback:** drive the server directly with [`scripts/mcp-driver.mjs`](../scripts/mcp-driver.mjs) (SKILL.md Phase 5, fallback path). |
| **B** | Indexing stops partway; `codebase_status` stops advancing. | Indexing runs *inside* the MCP server process. If that process dies, indexing dies with it. | Keep the process alive and poll — never fire-and-forget. The driver holds the child open and polls; the plugin's own daemon does this in a normal interactive session. |
| **C** | Driver/loop exits at "100% embedded" but `codebase_search` returns nothing / graph queries fail. | "100% embedded" is **not** "done." The code graph is still building and context artifacts are still unindexed at 100% embeddings. | Gate completion on **all three**: embeddings 100% → `codebase_graph_status` READY → context artifacts N/N. The driver's poll loop enforces exactly this. |
| **D** | First index takes an hour+ and pulls gigabytes. | One-time: pulls the Qdrant image, the Ollama image, and `nomic-embed-text` (~277 MB) before indexing; CPU Ollama is slow. `usa-wa`: ~1105 files → 6019 chunks → ~75 min (graph build itself was seconds). | Set generous timeouts (`INDEX_TIMEOUT_MS`, default 2h). Surface progress each poll. Consider a cloud/native-GPU backend for large repos — see [`embedding-backends.md`](embedding-backends.md). |
| **E** | `codebase_watch` shows "active" during setup, then auto-update stops later. | The file watcher is **ephemeral** — it auto-registers on connect and dies with the server process. | Persistent auto-update relies on the **plugin daemon being live in an interactive session**, not a one-shot script. Documented, not scripted — don't leave an orphaned node process to fake it. |
| **F** | (Not a failure) re-index/search is fast after the first run. | `socraticode-qdrant` + `socraticode-ollama` containers persist across runs and are reused; index data lives in Qdrant + on-disk graph, durable regardless of which server process built it. | Expected. Only the *first* index pays the full cost. |
| **G** | A cleanup step exits 143/144 and kills the wrong thing. | `pkill -f "socraticode/dist/index.js"` matches the killing shell's own argv → it kills itself. | Never `pkill -f`. The driver **owns its child** and kills by `child.pid`; nothing pattern-matches a cmdline. |
| **H** | Status parsing breaks between runs. | The `Context artifacts:` line changes shape: `2/7 indexed` vs `7 artifacts indexed (131 chunks)`. | Parse loosely (regex both shapes). The driver's `parseArtifacts()` handles both and treats "no line" as 0-expected. |
| **I** | `mcp-driver.mjs` exits `Could not resolve the socraticode server entrypoint` on a host where the plugin is installed and Connected. | The plugin launches the server as `npx -y socraticode`, which unpacks to `~/.npm/_npx/<hash>/node_modules/socraticode/` — reachable by neither `require.resolve()` nor `npm root [-g]`, the driver's only two search paths before [#85](https://github.com/gregoryfoster/skills/issues/85). | `resolveServerLaunch()` now follows the plugin's own chain: `SOCRATICODE_ENTRY` → the plugin's `mcp.json` (authoritative — it carries the exact command, args, and PATH the session uses) → `require.resolve` → `npm root` → the npx cache → `npx -y socraticode`. Diagnose with `node scripts/mcp-driver.mjs resolve`, which prints the launch command without starting anything. |

## Node 26 hard refusal (preflight gate, not a runtime surprise)

`engines.node` for the stack is `>=18.0.0 <26.0.0`. Node 26+ is **hard-refused**:
qdrant-js pins undici v6, incompatible with Node 26's bundled undici — the server
`process.exit(1)`s on start. [`scripts/preflight.sh`](../scripts/preflight.sh)
blocks on this before anything else runs. Fix: `nvm install 22 && nvm use 22`.

## Quick decision tree

```
codebase_* tools callable in this session?
├─ yes → use them natively (preferred). Index via codebase_index, poll codebase_status.
└─ no  → restart Claude Code, retry the ToolSearch prefetch.
         ├─ tools appear → native path.
         └─ still absent → fallback: node scripts/mcp-driver.mjs index <projectPath>
```
