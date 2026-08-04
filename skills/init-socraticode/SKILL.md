---
name: init-socraticode
description: Installs, configures, and indexes SocratiCode semantic code search on a project — Docker/Node preflight, plugin enablement, a project-adapted Code Exploration Policy + SessionStart prefetch hook, a context-artifacts manifest, and a full blocking index that waits for embeddings, graph, and artifacts to all complete. Use when adding semantic code search to a repo.
compatibility: Designed for Claude Code (SocratiCode ships as the socraticode@socraticode plugin). Requires Docker running, Node >=18 <26, and npx. Run from the target repo's root.
metadata:
  author: gregoryfoster
  version: "1.2"
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

1. **Policy block** → land exactly one marker-delimited `## Code Exploration
   Policy` section in `<POLICY_FILE>`. Apply in order, so a repo in any prior
   state converges to a single marked block, in place where one already exists:
   a. **Write the block, preferring the existing position:**
      - marker pair (`<!-- BEGIN socraticode-policy -->` … `<!-- END
        socraticode-policy -->`) already exists → **replace between the markers**;
      - else an unmarked `## Code Exploration Policy` section exists → **replace
        that section in place** (its heading through the line before the next
        `##`, or end of file if none follows) with the marked block;
      - else → **append** a fresh marked block.
   b. **Then, unconditionally,** delete any *other* `## Code Exploration Policy`
      section **not** enclosed by the marker pair (same heading-to-next-`##`
      span). Step (a) fixes at most one location; this sweeps any remaining stray
      copy — e.g. a repo where an earlier `init-socraticode` run appended a marked
      block beside the original unmarked one, where step (a) takes the marker-pair
      branch and would otherwise leave the unmarked copy behind.
   Never leave more than one policy section. Adapt the last tool-table row and any
   path examples to this project's real layout.
2. **SessionStart hook** (when `INSTALL_HOOK=yes`) → write the reminder script
   (`.claude/hooks/socraticode-reminder.sh`) and **merge** its hook entry into
   `.claude/settings.json` (create if absent). Dedupe by scanning existing
   command strings for `socraticode-prefetch` **or** `socraticode-reminder` (the
   latter matches legacy script-file installs); when a match isn't already the
   canonical command, upgrade that one command string in place (propagates the
   `${CLAUDE_PROJECT_DIR:-.}` fallback to legacy installs). Preserve existing
   `hooks`/`permissions`/other keys. Never clobber the file.
3. **Linked projects** (when `LINKED_PROJECTS` is set) → write
   `SOCRATICODE_LINKED_PROJECTS=<comma-separated abs paths>` into the `env` block
   of `.claude/settings.local.json` (create the file if absent, merge if present).
   Enables cross-repo `codebase_search` over sibling service checkouts — archiver
   links watcher + notifier this way. Each linked project must itself be indexed
   to contribute results.
   These are absolute paths to one VM's checkouts, so the file must stay out of
   version control. Don't assume an upstream template ignored it: if
   `git check-ignore -q .claude/settings.local.json` fails, append a
   newline-safe block to `.gitignore` (create it if absent) — matching the
   `init-project-fastapi` template's header:

   ```gitignore
   # Machine-specific Claude Code settings (local permissions, env, linked projects)
   .claude/settings.local.json
   ```

   Ensure a preceding blank line so the block can't fuse onto a
   trailing-newline-less last rule (e.g. `printf '\n%s\n%s\n' '# Machine-specific
   Claude Code settings (local permissions, env, linked projects)'
   '.claude/settings.local.json' >> .gitignore`). Repos bootstrapped by
   `init-project-fastapi` already carry this rule; the guard covers repos indexed
   standalone.

### Phase 4 — Configure context artifacts

Author `.socraticodecontextartifacts.json` at the repo root from
[`references/context-artifacts.md`](references/context-artifacts.md). Point it at
the project's **non-code** knowledge (SQL schemas, OpenAPI/Protobuf, Terraform/k8s,
architecture docs, env *examples*). **Adapt paths per project — do not copy the
template verbatim.** Each artifact is `{name, path, description}` with `path` a
single **literal file or directory** (globs do **not** work — the server `stat()`s
the value; a directory indexes recursively). Verify each path resolves
(`test -e '<path>'`) and drop categories the project lacks.

**Also write `.socraticodeignore` (repo root).** It's layered on the built-in
defaults + `.gitignore` (gitignore syntax) and is essentially mandatory for any
repo that vendors skills via `managing-skills` — the submodule trees dominate the
index otherwise (on replicator: 301 files/1038 chunks → 28 files/42 chunks, ~70
min → 84 s once excluded). Every repo bootstrapped by `init-project-fastapi`
(Phase 9 adds those submodules) needs this. Mirror the `extend-exclude` that
`ruff`/`ty` already carry:

```gitignore
# .socraticodeignore — semantic-index exclusions (layered on defaults + .gitignore)
skills-vendor/
skills/
.claude/skills/
```

Here `skills/` and `.claude/skills/` are the `managing-skills` symlink dirs (all
vendored content). **If the project authors first-party skills under `skills/`,
exclude `skills-vendor/` (and `.claude/skills/`) only** — don't drop the project's
own skills from the index. Otherwise adapt to the project's own vendored trees;
add any large generated/data dirs that aren't already in `.gitignore`.

### Phase 5 — Run the index and block until *fully* done

**Preferred (native) path** — when the `codebase_*` tools are callable in this
session (run the `ToolSearch` prefetch from
[`references/code-exploration-policy.md`](references/code-exploration-policy.md)
first):

1. `codebase_index { projectPath: <PROJECT_PATH> }` — returns immediately; work
   runs in the server process.
2. Poll `codebase_status` until the run reports **`Last operation: Full index —
   completed`** with no "in progress" block, **and** `codebase_graph_status` is
   **READY**, **and** context artifacts are **N/N**. "100% embedded" alone is NOT
   done (gotcha C — the graph is still building and artifacts are unindexed at
   100%), and don't *wait* to see 100% either: the server prints its progress
   percentage only while indexing is in flight, so a finished run shows no
   percentage at all (gotcha J).
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

> **If the driver can't find the server**, run `node "<SKILL_DIR>/scripts/mcp-driver.mjs"
> resolve` — it prints the launch command it would use and exits without
> starting anything (no Docker, no network). It reads the plugin's own
> `mcp.json` first, so a plugin-only host resolves to the same `npx -y
> socraticode` the session runs (gotcha I). Override with `SOCRATICODE_ENTRY`
> only if that chain comes up empty.

> **Timeouts.** First index is slow and one-time (gotcha D). The driver's ceiling
> is `INDEX_TIMEOUT_MS` (default 2h). For a large repo on CPU Ollama, raise it or
> switch backends rather than letting it abort a live build.

### Phase 6 — Verify

Native tools, or `node "<SKILL_DIR>/scripts/mcp-driver.mjs" verify "<PROJECT_PATH>"`:

- A sample `codebase_search` returns hits.
- `codebase_graph_status` is READY.
- `codebase_list_projects` shows the project.
- `codebase_status`: last operation completed, artifacts N/N.

Then clean up the Phase 0 scratch clone (if used): `rm -rf "<SKILL_TMP>"`.

Present a completion table:

| Component | Status |
|---|---|
| Preflight | Docker ✓ · Node `<version>` (>=18 <26) ✓ · npx ✓ |
| Plugin | `plugin:socraticode:socraticode` Connected |
| Backend | `<EMBEDDING_BACKEND>` |
| Policy | `## Code Exploration Policy` in `<POLICY_FILE>` (marker-delimited) |
| Prefetch hook | `<INSTALL_HOOK>` — SessionStart in `.claude/settings.json` → `.claude/hooks/socraticode-reminder.sh` |
| Context artifacts | `.socraticodecontextartifacts.json` (N artifacts, each `path` resolves) |
| Index exclusions | `.socraticodeignore` (vendored skill trees excluded) |
| Index | index run completed · graph READY · artifacts N/N |
| Sample search | returns hits |

## Re-run on an existing project (audit/repair)

Running this skill on a project that already has SocratiCode is **safe and is
the audit**: every file edit is idempotent (Phase 3's policy block replaces
between markers, the hook merge dedupes, Phase 4 verifies each artifact path
resolves), and Phase 6
re-verifies the three completion signals. Use a re-run to repair partial
installs — the common drift found across the cohort ([#65](https://github.com/gregoryfoster/skills/issues/65)):
a manifest with **no policy block or prefetch hook** (observo), or hook docs
that drifted from `settings.json` (archiver). Phases 1–2 are read-only when
already satisfied; Phase 5 re-indexes only if the index is missing or stale.

## Key invariants

- **Completion is three signals, not one.** Never declare done at "100%
  embedded" — require the index run reported complete AND graph READY AND
  artifacts N/N (troubleshooting gotcha C). None of the three is a percentage:
  the progress line disappears when the run finishes, so waiting to observe
  "100%" is waiting for something that will never arrive (gotcha J).
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
  Each artifact is `{name, path, description}` — `path` is a **single literal
  file or directory**, never an array and never a glob (the server `stat()`s it;
  a directory indexes recursively).
- **Exclude vendored skill trees.** Any repo that vendors skills via
  `managing-skills` must ship a `.socraticodeignore` (`skills-vendor/`, `skills/`,
  `.claude/skills/`) or the submodule content dominates the index. Every
  `init-project-fastapi` repo qualifies.
- **The file watcher is ephemeral.** Don't promise persistent auto-update from a
  one-shot run; it needs the plugin daemon live in an interactive session
  (gotcha E). Don't leave an orphaned node process to fake it.

See [`references/troubleshooting.md`](references/troubleshooting.md) for the full
gotcha matrix (A–H) and the native-vs-fallback decision tree.
