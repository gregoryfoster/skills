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

Land exactly one marker-delimited block in `AGENTS.md`, applying these steps in
order so a repo in any prior state converges to a single marked block:

1. If a `<!-- BEGIN socraticode-policy -->` / `<!-- END socraticode-policy -->`
   pair already exists, **replace the content between the markers**. Otherwise
   append the marked block below. (If no `AGENTS.md` exists, create one and add
   the block.)
2. **Then, unconditionally,** delete any *other* `## Code Exploration Policy`
   section **not** enclosed by the marker pair (its heading through the line
   before the next `##`, or end of file if none follows). This clears the
   duplicate on repos bootstrapped before the markers existed (e.g. by
   `init-project-fastapi`) — including repos where an earlier `init-socraticode`
   run already appended a marked block beside the original unmarked one, so step 1
   alone would leave the unmarked copy behind.

Never leave more than one policy section.

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

## 2. SessionStart hook (script file + `.claude/settings.json`)

Re-emits the prefetch instruction each session so a fresh Claude Code session
loads the deferred `codebase_*` schemas without the operator remembering to.
The hook prints to stdout; Claude Code injects SessionStart stdout as session
context.

The org convention (archiver, power-map, usa-wa, observo) is a **script-file
hook**: the echo lives in `.claude/hooks/socraticode-reminder.sh`, referenced
from settings.json. This keeps the ~600-char `select:` string out of
JSON-escaping and makes later edits a plain shell-file change. Standardize on
this form.

**Step A — write the reminder script** at `.claude/hooks/socraticode-reminder.sh`
(create if absent; overwrite in place if present — it carries no per-project
state):

```bash
#!/usr/bin/env bash
# socraticode-prefetch
echo 'socraticode-prefetch: SocratiCode codebase_* tools are deferred. Before broad code exploration, run ToolSearch "select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search" to load their schemas. Prefer codebase_search over grep for semantic questions.'
```

**Step B — merge the hook into `.claude/settings.json`** (create if absent).
If a `hooks.SessionStart` array already exists, append this entry to it;
preserve any existing `permissions`/other keys. **Never clobber the file.**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-reminder.sh\" # socraticode-prefetch"
          }
        ]
      }
    ]
  }
}
```

Two deliberate details in that command string:

- **`${CLAUDE_PROJECT_DIR:-.}`** — a best-effort fallback (cwd is the launch
  directory, normally the project root) for any environment that fires the hook
  without `CLAUDE_PROJECT_DIR` set. Without it, an unset variable degrades to
  `bash "/.claude/hooks/..."` and errors on every session start; with it, the
  worst case resolves relative to the launch dir instead of erroring outright.
- **trailing `# socraticode-prefetch`** — puts the dedupe marker in the
  *command string itself*, not just inside the script file, so the merge check
  below can recognize the entry by scanning settings.json alone.

**Dedupe (idempotent re-runs).** Before appending, scan the existing
`hooks.SessionStart` command strings and skip the append if any already contains
`socraticode-prefetch` **or** `socraticode-reminder`. The second alias matches
legacy installs whose command references `socraticode-reminder.sh` without the
trailing marker comment; a verbatim single-echo inline install (older canonical
form) is recognized by the `socraticode-prefetch` marker. Either way, do not add
a second entry.

**Upgrade the matched entry in place.** If the matched command string is not
already the canonical command from Step B — e.g. a fallback-less
`bash "$CLAUDE_PROJECT_DIR/…"`, or the legacy inline echo — replace **just that
one command string** with the canonical form, leaving all other entries and keys
untouched. If **more than one** matching entry exists (a duplicate left by a
prior verbatim re-run), remove the extras and keep a single canonical entry.
This is a targeted upgrade, not a clobber: it propagates the
`${CLAUDE_PROJECT_DIR:-.}` fallback to existing sibling installs on re-run — and
collapses any prior duplication — which a skip-only dedupe would leave stranded
on the old, erroring command. (Step A has already written the script the
canonical command points at.)

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
