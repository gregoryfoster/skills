# Code Exploration Policy — AGENTS.md block + SessionStart hook

Two artifacts the skill installs into the target project (SKILL.md Phase 3):

1. A **Code Exploration Policy** section in the project's `AGENTS.md`, wrapped in
   idempotency markers so re-runs never duplicate it.
2. A **SessionStart hook** in `.claude/settings.json` that re-emits the
   `ToolSearch` prefetch instruction each session (the `codebase_*` MCP tools
   are *deferred* — their schemas load only after the prefetch).

Both must be **project-adapted, not copied verbatim** (acceptance criterion).
The block below is canonical wording lifted from `init-project-fastapi`'s
`agents-md-template.md`; keep the negative rule and the tool table, but tailor
the last table row and any path examples to the project's actual layout.

---

## 1. AGENTS.md block (marker-delimited — idempotent)

Insert this into `AGENTS.md`. If a `<!-- BEGIN socraticode-policy -->` /
`<!-- END socraticode-policy -->` pair already exists, **replace the content
between the markers** rather than appending a second copy. If no `AGENTS.md`
exists, create one and add the block.

```markdown
<!-- BEGIN socraticode-policy -->
## Code Exploration Policy

SocratiCode is the preferred semantic-search tool for this repo (once indexed;
the artifact manifest lives in `.socraticodecontextartifacts.json`, and the
index itself lives in the local Qdrant store + on-disk graph once
`codebase_index` has run). Its MCP tools are **deferred** — schemas load only
after a `ToolSearch` prefetch.

**Negative rule.** For broad semantic questions ("where is X", "how does Y
work", "what depends on Z"), use SocratiCode MCP tools first. Reach for
`grep`/`ripgrep` only on exact strings (error messages, log lines, known
symbols). Reserve the Explore subagent for path-pattern walks (e.g. "all
`*.py` under `src/api/routes/`"), not semantic search.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what files touch Z | `codebase_search` |
| Exact string/regex match (errors, log lines, known symbols) | `grep` / `rg` |
| Blast radius of changing/deleting a file or function | `codebase_impact` |
| What does an entry point actually do? | `codebase_flow` |
| Callers and callees of a function | `codebase_symbol` |
| Imports/dependents of a file | `codebase_graph_query` |
| DB schemas, deployment topology, runbook context | `codebase_context` / `codebase_context_search` |

Prefetch query — run via `ToolSearch` at session start:

`select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search`
<!-- END socraticode-policy -->
```

## 2. SessionStart hook (`.claude/settings.json`)

Re-emits the prefetch instruction each session so a fresh Claude Code session
loads the deferred `codebase_*` schemas without the operator remembering to.
The hook prints to stdout; Claude Code injects SessionStart stdout as session
context.

**Merge, do not clobber.** If `.claude/settings.json` already has a
`hooks.SessionStart` array, append this entry to it (dedupe by the marker string
`socraticode-prefetch` so re-runs are idempotent). If the file doesn't exist,
create it with just this block. Preserve any existing `permissions`/other keys.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo 'socraticode-prefetch: SocratiCode codebase_* tools are deferred. Before broad code exploration, run ToolSearch \"select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search\" to load their schemas. Prefer codebase_search over grep for semantic questions.'"
          }
        ]
      }
    ]
  }
}
```

> **Duplicate-config trap.** If a session shows BOTH
> `mcp__plugin_socraticode_socraticode__*` and a standalone
> `mcp__socraticode__*`, the user has a duplicate MCP registration. Remove the
> standalone (the plugin already provides the server):
> `claude mcp remove socraticode`.

## Adaptation checklist (per project)

- [ ] Last tool-table row (`codebase_context …`) names the project's real
      non-code knowledge (schemas, OpenAPI, Terraform) — see
      [`context-artifacts.md`](context-artifacts.md).
- [ ] Any path examples in the negative rule match the project's tree
      (`src/api/routes/` is FastAPI-shaped; change for CLI/PHP/etc.).
- [ ] `AGENTS.md` vs `CLAUDE.md`: this org standardizes on `AGENTS.md` with a
      one-line `CLAUDE.md` that reads `@AGENTS.md`. If the project only has
      `CLAUDE.md`, put the block there instead.
