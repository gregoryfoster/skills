---
name: init-socraticode
description: Installs, configures, and indexes SocratiCode semantic code search on a project — Docker-or-shared-store/Node preflight, plugin enablement, a project-adapted Code Exploration Policy + docs/SOCRATICODE.md, SessionStart prefetch and once-per-day health hooks, a context-artifacts manifest, and a full blocking index verified by edge yield rather than graph status. Use when adding semantic code search to a repo.
compatibility: Designed for Claude Code (SocratiCode ships as the socraticode@socraticode plugin). Requires Docker running (or an external Qdrant and Ollama), Node >=18.17, and npx. Run from the target repo's root.
metadata:
  author: gregoryfoster
  version: "1.7"
  triggers: init socraticode, set up code search, index this project, socraticode setup
---

# Initialize SocratiCode — Semantic Code Search

Takes a project from "no semantic search" to a fully indexed SocratiCode setup:
host preflight → plugin enabled → Code Exploration Policy + `docs/SOCRATICODE.md`
+ hooks written → context-artifacts manifest authored → full index run and
**verified green** (embeddings 100%, graph READY *and clearing the edge-yield
floor*, artifacts N/N, no failed last operation, sample `codebase_search`
returns hits).

SocratiCode gives agents `codebase_search` / `codebase_impact` / `codebase_flow`
/ `codebase_symbol` / `codebase_graph_*` / `codebase_context_*` MCP tools backed
by a Qdrant vector store (local, or shared: `STORE=external`) + Ollama
embeddings + an AST dependency/symbol graph. It's a Claude Code **plugin**
(`socraticode@socraticode`) whose MCP server also ships the management tools
this skill drives (`codebase_index`, `codebase_status`, `codebase_health`,
`codebase_watch`, …).

<HARD-GATE>
Do NOT write files into the target project or start a (slow, one-time) index
until you have (1) collected and confirmed the parameters below and (2) passed
preflight (Phase 1). The first index can take an hour or more on the default CPU
backend — get the backend choice and artifact paths right before you start it.
Except, for `STORE=external`, the tracked ignore rule and then the API key in
`.claude/settings.local.json`: preflight reads the key
([`references/external-store.md`](references/external-store.md)).
</HARD-GATE>

## Parameters to collect

Ask the user; each has a default they can accept silently.

| Parameter | Default | Choices | Drives |
|---|---|---|---|
| `PROJECT_PATH` | repo root (`git rev-parse --show-toplevel`) | any abs path | what gets indexed; passed to every `codebase_*` call |
| `STORE` | `managed` | `managed` \| `external` | Phase 1 gates, Phase 3 steps 4–5 — `external`: a Qdrant reached by URL, not a container ([`references/external-store.md`](references/external-store.md)) |
| `EMBEDDING_BACKEND` | `ollama-docker` | `ollama-docker` \| `ollama-native` \| `openai` \| `google` | Phase 1 backend env, index speed — see [`references/embedding-backends.md`](references/embedding-backends.md); `STORE=external` uses the store's instead |
| `POLICY_FILE` | `AGENTS.md` | `AGENTS.md` \| `CLAUDE.md` | Phase 3 — where the Code Exploration Policy block lands |
| `INSTALL_HOOK` | `yes` | `yes` \| `no` | Phase 3 — install the two SessionStart hooks (prefetch reminder + once-per-day health check) |
| `LINKED_PROJECTS` | none | comma-separated sibling paths | Phase 3 — cross-repo search: relative `linkedProjects` in `.socraticode.json` |

**Backend note (do not silently default for large repos).** `ollama-docker` is
keyless but **CPU-only and slow** (`usa-wa`: ~75 min); steer large repos, or a
user with a key/GPU, to `openai` / `google` / `ollama-native`, and for a cloud
backend collect the key and confirm the env var the installed server expects.

Confirm all parameters before Phase 1.

## Procedure

### Phase 0 — Acquire skill source (only if running detached from the repo)

**Skip this phase if the project already vendors `gregoryfoster/skills`** — most
do. Reference the scripts at
`skills-vendor/<owner>-<repo>/skills/init-socraticode/scripts/…`, the real path
`skills/…` symlinks to and the one the health hook resolves first
([#177](https://github.com/gregoryfoster/skills/issues/177)).

Otherwise clone once to a scratch dir and capture `SKILL_DIR`/`SKILL_TMP`:
[`references/detached-source.md`](references/detached-source.md). `<SKILL_DIR>`
and `<SKILL_TMP>` below are **placeholders** for the literal paths it prints —
each Bash call runs in a fresh shell, so they are not inherited. Clean up
`<SKILL_TMP>` in Phase 6.

### Phase 1 — Preflight the host (blocking; never mutates the toolchain)

```bash
bash "<SKILL_DIR>/scripts/preflight.sh"
```

Gates: Docker, **only when something will run in it** (a managed Qdrant, or an
Ollama container), never probed on a socket-activated host with the daemon
down; Node `>=18.17` (26+ is checked against the resolved `socraticode@latest`
— [#269](https://github.com/gregoryfoster/skills/issues/269)); `npx`; for
`STORE=external`, the store, the external Ollama, and whether this session
carries the settings `env` block (a first install passes the values inline,
the key already in place). Advisory readings: host memory and `MemoryLow=`,
Docker at boot (gotcha L), the running Claude Code's version and install age,
the `socraticode` marketplace, the plugin MCP server Connected.

**Detect-and-instruct only.** On any ✗ the script prints the exact fix and exits
non-zero. Do **not** auto-install Node/npm or auto-start Docker — relay the fix
and wait. Re-run until it exits 0.
`bash "<SKILL_DIR>/scripts/preflight.sh" --check` is the same gates, the skill's
dry-run.

If `EMBEDDING_BACKEND` is a cloud/native backend, export its env (see
[`references/embedding-backends.md`](references/embedding-backends.md)) in the
environment where the MCP server / driver will run, before Phase 5.

### Phase 2 — Install/enable the plugin

```bash
claude plugin marketplace add giancarloerra/socraticode   # once per host
claude plugin install socraticode@socraticode             # user scope
SOCRATICODE_AUTO_RESUME=off claude mcp list   # read-only (gotcha R); expect: plugin:socraticode:socraticode ✓ Connected
```

**The marketplace step is not optional on a fresh host:** `socraticode@socraticode`
is `plugin@marketplace`, so with none registered the install fails.
`giancarloerra/socraticode` is canonical (per the plugin-hub listing); forks
such as `oltivex/socraticode` and `Flink-JP/socraticode` exist — add one only
deliberately, and the plugin name stays the same. Preflight Gate 4 reports the
marketplace separately from the connection, and flags a redundant standalone
`mcp__socraticode__*` beside the plugin's (`claude mcp remove socraticode`).

**On a small or shared host, pin the server here** — the plugin's command
installs at every launch, 1.2 G against 75 MB pinned — and on a shared one
reserve the production service's memory:
[`host-memory.md`](references/host-memory.md).

### Phase 3 — Author the project's exploration policy (idempotent)

Follow [`references/code-exploration-policy.md`](references/code-exploration-policy.md):

1. **Policy block** → exactly one marker-delimited `## Code Exploration
   Policy` section in `<POLICY_FILE>`, converging from any prior state:
   a. **Write it where one already is:** between an existing
      `<!-- BEGIN socraticode-policy -->` … `<!-- END socraticode-policy -->`
      pair; else in place of an unmarked `## Code Exploration Policy` section
      (its heading to the next `##`, or end of file) — **rescuing first**
      anything in that span the template does not carry, moved unchanged to a
      `## Code Exploration Notes (repo-specific)` section after the END marker
      and named in the report, or the replace deletes it silently
      ([#115](https://github.com/gregoryfoster/skills/issues/115)); else append.
   b. **Then, unconditionally,** delete any *other* `## Code Exploration Policy`
      section outside the markers: (a) fixes one location, and an earlier run
      may have appended a marked block beside the unmarked original.
   Adapt path examples to this project's layout. Write variant **A** (standard)
   on a first install — there is no graph to measure yet — and let Phase 6's
   yield gate send you back for **B** (degraded) on `low`; an audit re-run
   carries the variant Phase 6 last measured.
2. **Detail doc** → write `docs/SOCRATICODE.md` (creating `docs/`) from
   [`references/socraticode-doc.md`](references/socraticode-doc.md): the full
   tool table, per-tool notes, graph-health and index-scope guidance, and a
   **pointer** to the prefetch hook, never a copy of its `select:` query — the
   hook is a vendored symlink, so a copy drifts silently (#209, #234). The
   `AGENTS.md` block links here and keeps only what nearly every task needs.
   Marker-delimited too, each marker unbroken on its own line:
   `<!-- BEGIN socraticode-doc -->` and `<!-- END socraticode-doc -->`.
   Replace between existing markers, leaving every line after `END` untouched;
   an unmarked file (every install before
   [#210](https://github.com/gregoryfoster/skills/issues/210)) gets step 1a's
   **rescue** first, under a `## Repo-specific notes` heading after `END`; else
   write the template. Repo-specific notes live below `END`, never in `AGENTS.md`.
3. **SessionStart hooks** (when `INSTALL_HOOK=yes`) → run
   [`references/code-exploration-policy.md`](references/code-exploration-policy.md)
   Step A and Step C verbatim; neither hook is yours to hand-execute or
   hand-wire. Both call `managing-skills`' `scripts/install-hook.sh`, which
   **symlinks** the hook into `skills-vendor/*/…/scripts/`, merges its
   SessionStart entry into `.claude/settings.json` without clobbering
   `hooks`/`permissions`/other keys, and **copies** only where there is no
   `skills-vendor/` tree (#200) — the worse install, for reasons in Step A
   (#99, #186).
   - `.claude/hooks/socraticode-reminder.sh` — the prefetch reminder; dedupe
     markers `socraticode-prefetch` (written) and `socraticode-reminder`
     (legacy, matched only), so a re-run upgrades an older entry in place.
   - `.claude/hooks/socraticode-health.sh` — the once-per-day infra check,
     symlinked the same way. Its distinct marker `socraticode-health` keeps one
     hook's dedupe from evicting the other's entry. Silent when clean, so a
     stale copy looks healthy; it reports, and never re-indexes.
4. **`.socraticode.json`** (when `STORE=external` or `LINKED_PROJECTS` is set)
   → at the repo root, merged, committed: `projectId` for an external store
   (default: the repo name), and each linked sibling in `linkedProjects` as a
   path **relative to the repo root** — never absolute, which names one host's
   layout. Each linked project must itself be indexed to contribute results.
   Details, and migrating an older install's `SOCRATICODE_LINKED_PROJECTS`:
   [`references/linked-projects.md`](references/linked-projects.md).
5. **Client `env` block** (only `STORE=external`, and only after step 4 wrote
   `projectId`) → merge it into `.claude/settings.json`, per
   [`references/external-store.md`](references/external-store.md) (the key is
   already in git-ignored `.claude/settings.local.json`). Never the block
   alone: without a `projectId`
   a session names its collections by a hash of the checkout path, shared by
   every host with the same layout. Unless this session's Phase 1 already
   showed the `env` block line ✓, restart Claude Code here, trusting the folder
   if asked, and re-run this skill in the new session (Phases 1–4 are
   idempotent); its bare `preflight.sh --check` must show that line ✓ before
   Phase 5. The session that wrote the block cannot index: its server started
   without it.

### Phase 4 — Configure context artifacts

Author `.socraticodecontextartifacts.json` at the repo root from
[`references/context-artifacts.md`](references/context-artifacts.md). Point it at
the project's **non-code** knowledge (SQL schemas, OpenAPI/Protobuf, Terraform/k8s,
architecture docs, env *examples*). **Adapt paths per project — do not copy the
template verbatim.** Each artifact is `{name, path, description}` with `path` a
single **literal file or directory** (globs do **not** work — the server `stat()`s
the value; a directory indexes recursively). Drop categories the project lacks.

**Migrate a legacy top-level array first (idempotent audit).** A manifest whose
first non-whitespace character is `[` is rejected, silently: the repo indexes
"successfully" at `artifacts 0/0` with **no context search at all** (gotcha K).
Rewrite it as `{"artifacts": [ …the existing array… ]}`:
[mechanics](references/context-artifacts.md#migrating-a-legacy-top-level-array).

**Then gate on the validator**, before the expensive index:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" validate-manifest "<PROJECT_PATH>"
```

It checks shape, names and globs, and that **every path resolves**, one line per
problem. A non-resolving path is skipped silently, so `artifacts N/N` never
reaches parity and Phase 5 blocks until `INDEX_TIMEOUT_MS`. Fix every line, or
drop the category, before indexing.

**Also write `.socraticodeignore` (repo root)** — essentially mandatory for any
repo vendoring skills via `managing-skills`, whose submodule trees otherwise
dominate the index. It governs the code index and graph, not a subtree
artifact, so **ask** whether dated prose registered as one (`docs/plans/`)
should leave the code index too. Template, question, and the first-party `skills/` carve-out:
[`references/context-artifacts.md`](references/context-artifacts.md#index-exclusions--socraticodeignore).

### Phase 5 — Run the index and block until *fully* done

**Gate first, on either path:** `node "<SKILL_DIR>/scripts/mcp-driver.mjs"
validate-store "<PROJECT_PATH>"` fails, naming the defect, when a server
launched here would address the wrong store or collections. The driver runs it
before its own launches.

**Preferred (native) path** — when the `codebase_*` tools are callable in this
session (run the `ToolSearch` prefetch from
[`references/code-exploration-policy.md`](references/code-exploration-policy.md)
first):

1. `codebase_index { projectPath: <PROJECT_PATH> }` — returns immediately; work
   runs in the server process.
2. Poll `codebase_status` until the run reports **`Last operation: Full index —
   completed`** with no "in progress" block, **and** `codebase_graph_status` is
   **READY**, **and** context artifacts are **N/N**. "100% embedded" alone is NOT
   done (gotcha C), and don't *wait* to see 100%: a finished run prints no
   percentage at all (gotcha J).
3. If artifacts aren't auto-indexed, run `codebase_context_index { projectPath }`.
4. Confirm the file watcher registered (`codebase_watch` / status); it is
   **ephemeral**, living only while a server runs (gotcha E).

**Fallback path** — when the server is Connected but the tools were never injected
into the session (gotcha A), and a Claude Code **restart** didn't register them
either:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" index "<PROJECT_PATH>"
```

The driver speaks JSON-RPC to the plugin's server directly, keeps it alive while
indexing (gotcha B) and blocks on the same three-signal predicate; it **owns its
child process** — no `pkill -f` (gotcha G).

> **Driver can't find the server?** `mcp-driver.mjs resolve` prints the launch
> command it would use, starting nothing (gotcha I). **Slow first index?** Raise
> `INDEX_TIMEOUT_MS` (default 2h) or switch backends (gotcha D).

### Phase 6 — Verify

Native tools, or `node "<SKILL_DIR>/scripts/mcp-driver.mjs" verify "<PROJECT_PATH>"`:

- A sample `codebase_search` returns hits.
- `codebase_graph_status` is READY **and clears the yield floor** (below).
- `codebase_list_projects` shows the project.
- `STORE=external`: `codebase_health` reports `Qdrant mode: external` and the
  store's endpoint, not a container.
- `codebase_status`: artifacts N/N, and the last operation **completed, not
  FAILED** — a failed one fails verification even with every other light green,
  because the delta that failed is missing from the index.

**Graph yield — READY is a status, not a result** (gotcha N). Measure it:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" health-check "<PROJECT_PATH>" \
  --probe <a file you know has several first-party imports>
```

| Verdict | Meaning | Do |
|---|---|---|
| `ok` | no server advisory, or ≥ 0.1 edges per file | nothing; keep policy **variant A** |
| `low` | server advisory fired, or (absent one) < 0.1 edges per file | **return to Phase 3 and write policy variant B** — route imports/dependents/blast-radius to `grep`; empty graph output is tool failure, not absence. Do **not** fail the install |
| `unknown` | < 20 files, or the status string did not parse | report it; leave variant A |

**A stale or unstamped `Built by:` line is its own defect.** `health-check`
compares the stamp against the session's server rather than waiting for a
`STALE` token, and reports staleness *beside* the verdict, never instead of it
([#297](https://github.com/gregoryfoster/skills/issues/297), #305). Rebuild,
then re-measure before variant B.

Then clean up the Phase 0 scratch clone (if used): `rm -rf "<SKILL_TMP>"`.

Present a completion table:

| Component | Status |
|---|---|
| Preflight | Docker ✓ (boot-enabled: `<yes/n-a>`) or not needed · `external`: store `<url>` ✓, `env` block in session ✓ · Node `<version>` (>=18.17) ✓ · npx ✓ |
| Store config | `validate-store` ✓ · `.socraticode.json`: `projectId` `<id/none>`, `<N>` relative `linkedProjects` |
| Plugin | marketplace `socraticode` registered · `plugin:socraticode:socraticode` Connected |
| Backend | `<EMBEDDING_BACKEND>`, or the store's (`external`: `OLLAMA_URL`, model) |
| Policy | `## Code Exploration Policy` in `<POLICY_FILE>` (marker-delimited, variant `<A/B>`) · `docs/SOCRATICODE.md` written |
| SessionStart hooks | `<INSTALL_HOOK>` — `.claude/hooks/socraticode-reminder.sh` (prefetch, `<symlink/copy>`) · `.claude/hooks/socraticode-health.sh` (once-per-day infra check, `<symlink/copy>`) |
| Context artifacts | `.socraticodecontextartifacts.json` (N artifacts, each `path` resolves) |
| Index exclusions | `.socraticodeignore` (vendored skill trees excluded) |
| Index | index run completed (no FAILED last operation) · graph READY · **yield `<ok/low/unknown>`** · artifacts N/N |
| Sample search | returns hits |

## Re-run on an existing project (audit/repair)

Running this skill on a project that already has SocratiCode is **safe and is
the audit**: every edit is idempotent and Phase 6 re-verifies. Read
[`references/audit-rerun.md`](references/audit-rerun.md) first — what each
phase re-does, what a re-run repairs, and the rescue it must not skip.

## Key invariants

The invariants Phases 4–6 enforce are in
[`references/troubleshooting.md`](references/troubleshooting.md) beside the
gotcha matrix (A–U) and the native-vs-fallback decision tree.

- **All file edits are idempotent.** The AGENTS.md policy block and the
  `docs/SOCRATICODE.md` template are both marker-delimited — a re-run replaces
  between the markers and preserves what follows `END`; the settings.json hook
  is merged and deduped. Re-running the skill, or running it on a project that
  already has these files, must not duplicate blocks or stack hooks.
- **The health hook reports; it never repairs.** No re-index, no `docker`
  command of its own, no file edit from a SessionStart hook — it runs before an agent has
  context and must cost a bounded, silent-when-clean moment.
- **Never mutate the host toolchain.** Preflight detects and instructs. Its
  network reads are bounded GETs, and it runs no docker command that would
  start a socket-activated daemon.
- **The policy block pays rent on every invocation.** It is the one section
  `curating-context` will not edit, so whatever lands in `AGENTS.md` is a fixed
  cost the repo cannot curate away. Keep the block at the negative rule plus the
  two or three highest-traffic rows; everything else goes to
  `docs/SOCRATICODE.md`. Adding a row to the block is a budget decision
  ([#115](https://github.com/gregoryfoster/skills/issues/115)).

**Self-budget:** held to a **9,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py`, a named exception to the repo's
6,000-token standard; how it came down from 10,050 is recorded beside the
figure there.
