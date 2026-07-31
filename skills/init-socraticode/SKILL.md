---
name: init-socraticode
description: Installs, configures, and indexes SocratiCode semantic code search on a project — Docker/Node preflight, plugin enablement, a project-adapted Code Exploration Policy + SessionStart prefetch hook, a context-artifacts manifest, and a full blocking index that waits for embeddings, graph, and artifacts to all complete. Use when adding semantic code search to a repo.
compatibility: Designed for Claude Code (SocratiCode ships as the socraticode@socraticode plugin). Requires Docker running, Node >=18 <26, and npx. Run from the target repo's root.
metadata:
  author: gregoryfoster
  version: "1.1"
  triggers: init socraticode, set up code search, index this project, socraticode setup
---

# Initialize SocratiCode — Semantic Code Search

Takes a project from "no semantic search" to a fully indexed SocratiCode setup:
host preflight → plugin enabled → Code Exploration Policy + prefetch hook written
→ context-artifacts manifest authored → full index run and **verified green**
(embeddings 100%, graph READY, artifacts N/N, sample `codebase_search` returns
hits).

SocratiCode gives agents `codebase_search` / `codebase_impact` / `codebase_flow`
/ `codebase_symbol` / `codebase_graph_*` / `codebase_context_*` MCP tools backed
by a local Qdrant vector store + Ollama embeddings + an AST dependency/symbol
graph. It's a Claude Code **plugin** (`socraticode@socraticode`) whose MCP server
also ships the management tools this skill drives (`codebase_index`,
`codebase_status`, `codebase_health`, `codebase_watch`, …).

<HARD-GATE>
Do NOT write files into the target project or start a (slow, one-time) index
until you have (1) collected and confirmed the parameters below and (2) passed
preflight (Phase 1). The first index can take an hour or more on the default CPU
backend — get the backend choice and artifact paths right before you start it.
</HARD-GATE>

## Parameters to collect

Ask the user; each has a default they can accept silently.

| Parameter | Default | Choices | Drives |
|---|---|---|---|
| `PROJECT_PATH` | repo root (`git rev-parse --show-toplevel`) | any abs path | what gets indexed; passed to every `codebase_*` call |
| `EMBEDDING_BACKEND` | `ollama-docker` | `ollama-docker` \| `ollama-native` \| `openai` \| `google` | Phase 1 backend env, index speed — see [`references/embedding-backends.md`](references/embedding-backends.md) |
| `POLICY_FILE` | `AGENTS.md` | `AGENTS.md` \| `CLAUDE.md` | Phase 3 — where the Code Exploration Policy block lands |
| `INSTALL_HOOK` | `yes` | `yes` \| `no` | Phase 3 — install the SessionStart prefetch hook |
| `LINKED_PROJECTS` | none | comma-separated abs paths | Phase 3 — cross-repo search over sibling checkouts via `SOCRATICODE_LINKED_PROJECTS` |

**Backend note (do not silently default for large repos).** `ollama-docker` needs
no key but is **CPU-only and slow** (`usa-wa`: ~1105 files / 6019 chunks / ~75
min). For large repos or when a key/GPU is available, steer the user to `openai`
/ `google` / `ollama-native`. If they pick a cloud backend, collect the API key
and confirm which env var the installed server version expects.

Confirm all parameters before Phase 1.

## Procedure

### Phase 0 — Acquire skill source (only if running detached from the repo)

This skill's scripts (`preflight.sh`, `mcp-driver.mjs`) live in *this* skill
directory. If you're running inside a project that already vendors
`gregoryfoster/skills` (submodule + symlink), reference them at
`skills/init-socraticode/scripts/…` and skip this phase. Otherwise clone once to
a scratch dir and reference scripts through the captured path:

```bash
set -euo pipefail
SKILL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/init-socraticode.XXXXXX")
git clone --depth 1 https://github.com/gregoryfoster/skills.git "$SKILL_TMP/gregoryfoster-skills"
SKILL_DIR="$SKILL_TMP/gregoryfoster-skills/skills/init-socraticode"
test -f "$SKILL_DIR/scripts/preflight.sh" || { echo "Phase 0 clone failed"; exit 1; }
echo "SKILL_DIR=$SKILL_DIR"; echo "SKILL_TMP=$SKILL_TMP"
```

`<SKILL_DIR>` / `<SKILL_TMP>` below are **placeholders** for the literal paths
printed here (each Bash call runs in a fresh shell — they are not inherited).
Clean up `<SKILL_TMP>` in Phase 6.

### Phase 1 — Preflight the host (blocking; never mutates the toolchain)

```bash
bash "<SKILL_DIR>/scripts/preflight.sh"
```

Gates: Docker installed + daemon running; Node `>=18 <26` (**26+ hard-refused** —
undici v6 vs Node 26 bundled undici makes the server exit on start); `npx`
reachable; and an advisory check that the plugin MCP server is Connected.

**Detect-and-instruct only.** On any ✗ the script prints the exact fix command
(`nvm install 22`, start Docker, …) and exits non-zero. Do **not** auto-install
Node/npm or auto-start Docker — relay the fix to the user and wait. Re-run
preflight until it exits 0.

> `bash "<SKILL_DIR>/scripts/preflight.sh" --check` is the same gates with no
> mutation — the fast smoke test (use it as the skill's dry-run).

If `EMBEDDING_BACKEND` is a cloud/native backend, export its env (see
[`references/embedding-backends.md`](references/embedding-backends.md)) in the
environment where the MCP server / driver will run, before Phase 5.

### Phase 2 — Install/enable the plugin

```bash
claude plugin install socraticode@socraticode      # user scope
claude mcp list                                     # expect: plugin:socraticode:socraticode ✓ Connected
```

**Duplicate-config trap.** If `claude mcp list` (or the session toolset) shows
BOTH `mcp__plugin_socraticode_socraticode__*` and a standalone
`mcp__socraticode__*`, remove the standalone — the plugin already provides the
server:

```bash
claude mcp remove socraticode
```

### Phase 3 — Author the project's exploration policy (idempotent)

Follow [`references/code-exploration-policy.md`](references/code-exploration-policy.md):

1. **Policy block** → insert the marker-delimited `## Code Exploration Policy`
   section into `<POLICY_FILE>`. If a `<!-- BEGIN socraticode-policy -->` …
   `<!-- END socraticode-policy -->` pair already exists, **replace between the
   markers** — never append a second copy. Adapt the last tool-table row and any
   path examples to this project's real layout.
2. **SessionStart hook** (when `INSTALL_HOOK=yes`) → write the reminder script
   (`.claude/hooks/socraticode-reminder.sh`) and **merge** its hook entry into
   `.claude/settings.json` (create if absent). Dedupe by scanning existing
   command strings for `socraticode-prefetch` **or** `socraticode-reminder` (the
   latter matches legacy script-file installs); preserve existing
   `hooks`/`permissions`/other keys. Never clobber the file.
3. **Linked projects** (when `LINKED_PROJECTS` is set) → write
   `SOCRATICODE_LINKED_PROJECTS=<comma-separated abs paths>` into the `env` block
   of `.claude/settings.local.json` (gitignored — paths are machine-specific;
   create the file if absent, merge if present). Enables cross-repo
   `codebase_search` over sibling service checkouts — archiver links watcher +
   notifier this way. Each linked project must itself be indexed to contribute
   results.

### Phase 4 — Configure context artifacts

Author `.socraticodecontextartifacts.json` at the repo root from
[`references/context-artifacts.md`](references/context-artifacts.md). Point it at
the project's **non-code** knowledge (SQL schemas, OpenAPI/Protobuf, Terraform/k8s,
architecture docs, env *examples*). **Adapt paths per project — do not copy the
template verbatim.** Verify each glob matches at least one tracked file
(`git ls-files '<glob>'`) and drop categories the project lacks.

### Phase 5 — Run the index and block until *fully* done

**Preferred (native) path** — when the `codebase_*` tools are callable in this
session (run the `ToolSearch` prefetch from
[`references/code-exploration-policy.md`](references/code-exploration-policy.md)
first):

1. `codebase_index { projectPath: <PROJECT_PATH> }` — returns immediately; work
   runs in the server process.
2. Poll `codebase_status` until embeddings reach **100%**, **and**
   `codebase_graph_status` is **READY**, **and** context artifacts are **N/N**.
   "100% embedded" alone is NOT done (gotcha C — the graph is still building and
   artifacts are unindexed at 100%).
3. If artifacts aren't auto-indexed, run `codebase_context_index { projectPath }`.
4. Confirm the file watcher registered (`codebase_watch` / status). Note it's
   **ephemeral** — it lives only while a server is running (gotcha E); persistent
   auto-update needs the plugin daemon live in an interactive session.

**Fallback path** — when the server is Connected but the tools were never injected
into the session (gotcha A), and a Claude Code **restart** didn't register them
either:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" index "<PROJECT_PATH>"
```

The driver speaks JSON-RPC to the plugin's stdio server directly, keeps it alive
during indexing (gotcha B), and blocks on the same three-signal predicate before
returning. It **owns its child process and kills by PID** — no `pkill -f`
self-match (gotcha G) — and parses status strings loosely (gotcha H).

> **Timeouts.** First index is slow and one-time (gotcha D). The driver's ceiling
> is `INDEX_TIMEOUT_MS` (default 2h). For a large repo on CPU Ollama, raise it or
> switch backends rather than letting it abort a live build.

### Phase 6 — Verify

Native tools, or `node "<SKILL_DIR>/scripts/mcp-driver.mjs" verify "<PROJECT_PATH>"`:

- A sample `codebase_search` returns hits.
- `codebase_graph_status` is READY.
- `codebase_list_projects` shows the project.
- `codebase_status`: embeddings 100%, artifacts N/N.

Then clean up the Phase 0 scratch clone (if used): `rm -rf "<SKILL_TMP>"`.

Present a completion table:

| Component | Status |
|---|---|
| Preflight | Docker ✓ · Node `<version>` (>=18 <26) ✓ · npx ✓ |
| Plugin | `plugin:socraticode:socraticode` Connected |
| Backend | `<EMBEDDING_BACKEND>` |
| Policy | `## Code Exploration Policy` in `<POLICY_FILE>` (marker-delimited) |
| Prefetch hook | `<INSTALL_HOOK>` — SessionStart in `.claude/settings.json` → `.claude/hooks/socraticode-reminder.sh` |
| Context artifacts | `.socraticodecontextartifacts.json` (N artifacts) |
| Index | embeddings 100% · graph READY · artifacts N/N |
| Sample search | returns hits |

## Re-run on an existing project (audit/repair)

Running this skill on a project that already has SocratiCode is **safe and is
the audit**: every file edit is idempotent (Phase 3's policy block replaces
between markers, the hook merge dedupes, Phase 4 verifies globs), and Phase 6
re-verifies the three completion signals. Use a re-run to repair partial
installs — the common drift found across the cohort ([#65](https://github.com/gregoryfoster/skills/issues/65)):
a manifest with **no policy block or prefetch hook** (observo), or hook docs
that drifted from `settings.json` (archiver). Phases 1–2 are read-only when
already satisfied; Phase 5 re-indexes only if the index is missing or stale.

## Key invariants

- **Completion is three signals, not one.** Never declare done at "100%
  embedded" — require embeddings 100% AND graph READY AND artifacts N/N
  (troubleshooting gotcha C).
- **Never mutate the host toolchain.** Preflight detects and instructs; it does
  not install Node/Docker. Node 26+ is a hard refusal, not a "try anyway."
- **All file edits are idempotent.** The AGENTS.md policy block is
  marker-delimited; the settings.json hook is merged and deduped. Re-running the
  skill, or running it on a project that already has these files, must not
  duplicate blocks or stack hooks.
- **The driver is a fenced fallback, not the default.** Prefer native tools;
  reach for `mcp-driver.mjs` only when the session won't expose the tools even
  after a restart. It owns its child process — no `pkill -f`.
- **Artifacts are project-adapted, not verbatim.** Both the policy block and
  `.socraticodecontextartifacts.json` must name this project's real files/paths.
- **The file watcher is ephemeral.** Don't promise persistent auto-update from a
  one-shot run; it needs the plugin daemon live in an interactive session
  (gotcha E). Don't leave an orphaned node process to fake it.

See [`references/troubleshooting.md`](references/troubleshooting.md) for the full
gotcha matrix (A–H) and the native-vs-fallback decision tree.
