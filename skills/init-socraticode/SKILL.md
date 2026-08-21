---
name: init-socraticode
description: Installs, configures, and indexes SocratiCode semantic code search on a project — Docker/Node preflight, plugin enablement, a project-adapted Code Exploration Policy + docs/SOCRATICODE.md, SessionStart prefetch and once-per-day health hooks, a context-artifacts manifest, and a full blocking index verified by edge yield rather than graph status. Use when adding semantic code search to a repo.
compatibility: Designed for Claude Code (SocratiCode ships as the socraticode@socraticode plugin). Requires Docker running, Node >=18 <26, and npx. Run from the target repo's root.
metadata:
  author: gregoryfoster
  version: "1.4"
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
| `INSTALL_HOOK` | `yes` | `yes` \| `no` | Phase 3 — install the two SessionStart hooks (prefetch reminder + once-per-day health check) |
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
`skills-vendor/<owner>-<repo>/skills/init-socraticode/scripts/…` — the real
path that `skills/…` symlinks to, and the one the health hook resolves first
([#177](https://github.com/gregoryfoster/skills/issues/177)) — and skip this
phase. Otherwise clone once to a scratch dir and reference scripts through the
captured path:

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
reachable; and advisory checks that Docker starts at boot, the `socraticode`
marketplace is registered, and the plugin MCP server is Connected.

The boot-persistence advisory is the one whose absence bites later rather than
now: on a systemd host where `systemctl is-enabled docker` is `disabled`, the
index works today and vanishes after the next reboot — the daemon never comes
back, so Qdrant never starts and `codebase_search` quietly returns nothing
(gotcha L).

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
claude plugin marketplace add giancarloerra/socraticode   # once per host
claude plugin install socraticode@socraticode             # user scope
claude mcp list                                            # expect: plugin:socraticode:socraticode ✓ Connected
```

**The marketplace step is not optional on a fresh host.** `socraticode@socraticode`
is `plugin@marketplace`; with no marketplace registered the install has nothing to
resolve against and fails. `giancarloerra/socraticode` is the canonical source
(per the plugin-hub listing). Forks exist — `oltivex/socraticode` and
`Flink-JP/socraticode` among them — so if a project has standardized on one, add
that instead, deliberately rather than by accident; the plugin name stays
`socraticode@socraticode` either way. Preflight Gate 4 reports whether the
marketplace is registered, separately from whether the server is Connected.

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
   Never leave more than one policy section. Adapt any path examples to this
   project's real layout. **Variant:** write **A** (standard) on a first install
   — the graph does not exist yet, so there is nothing to measure — and let
   Phase 6's yield gate send you back here to write **B** (degraded) if it
   returns `low`. On an audit re-run, carry the variant Phase 6 last measured.
   **Rescue before replacing on the unmarked branch:** anything in that span the
   template does not itself carry is repo-authored. Move it, unchanged, to a
   `## Code Exploration Notes (repo-specific)` section after the END marker and
   name every moved block in the report — a whole-span replace deletes it
   otherwise, silently ([#115](https://github.com/gregoryfoster/skills/issues/115)).
2. **Detail doc** → write `docs/SOCRATICODE.md` from
   [`references/socraticode-doc.md`](references/socraticode-doc.md): the full
   tool table, the `ToolSearch` prefetch string, per-tool notes, graph-health
   and index-scope guidance. The `AGENTS.md` block links to it and carries only
   what an agent needs on nearly every task; everything read once lives here.
   Create `docs/` if absent. **Marker-delimited, like the policy block**, by a
   pair kept unbroken on one line each: `<!-- BEGIN socraticode-doc -->` and
   `<!-- END socraticode-doc -->`.
   - marker pair already present → **replace between the markers** and leave
     every line after `END` untouched;
   - else the file exists but is unmarked (every install predating
     [#210](https://github.com/gregoryfoster/skills/issues/210)) → **rescue
     before replacing**, exactly as step 1a does for an unmarked policy
     section: anything the template does not itself carry is repo-authored.
     Move it, unchanged, under a `## Repo-specific notes` heading *after* the
     END marker, and name every moved block in the report.
   - else → write the marked template.
   Repo-specific notes live here, below `END`, never in `AGENTS.md` — see the
   policy-block invariant below for why.
3. **SessionStart hooks** (when `INSTALL_HOOK=yes`) → install **two** vendored
   scripts and register them in `.claude/settings.json`. One command each, and
   neither is yours to hand-execute: both run `managing-skills`'
   `scripts/install-hook.sh`, which **symlinks** into `skills-vendor/*/…/scripts/`
   merges the SessionStart entry without clobbering existing
   `hooks`/`permissions`/other keys, and **copies** only where there is no
   `skills-vendor/` tree (#200).
   Run [`references/code-exploration-policy.md`](references/code-exploration-policy.md)
   Step A and Step C verbatim; the flags are the only difference between them.
   - `.claude/hooks/socraticode-reminder.sh` — the prefetch reminder. Dedupe
     markers `socraticode-prefetch` (canonical, written) and
     `socraticode-reminder` (legacy, matched but never written), so a re-run
     upgrades an older entry in place instead of duplicating it.
   - `.claude/hooks/socraticode-health.sh` — the once-per-day infra check,
     symlinked exactly the same way. Its dedupe marker `socraticode-health` is
     deliberately distinct, so one hook's strip cannot evict the other's entry
     from the array they share. It is silent when clean, so a stale copy is
     indistinguishable from a healthy one. It reports; it never re-indexes.
   A copy freezes at install day and `.skills/doctor.sh` sees only *dangling*
   symlinks, so the drift reads as a healthy install; retyping a hook from prose
   is worse still (#186).
4. **Linked projects** (only when `LINKED_PROJECTS` is set — it defaults to
   none, so most installs skip this) → follow
   [`references/linked-projects.md`](references/linked-projects.md): write
   `SOCRATICODE_LINKED_PROJECTS=<comma-separated abs paths>` into the `env` block
   of `.claude/settings.local.json` (merge, never clobber), then make sure that
   file is git-ignored — it holds one VM's absolute paths. Enables cross-repo
   `codebase_search` over sibling checkouts; each linked project must itself be
   indexed to contribute results.

### Phase 4 — Configure context artifacts

Author `.socraticodecontextartifacts.json` at the repo root from
[`references/context-artifacts.md`](references/context-artifacts.md). Point it at
the project's **non-code** knowledge (SQL schemas, OpenAPI/Protobuf, Terraform/k8s,
architecture docs, env *examples*). **Adapt paths per project — do not copy the
template verbatim.** Each artifact is `{name, path, description}` with `path` a
single **literal file or directory** (globs do **not** work — the server `stat()`s
the value; a directory indexes recursively). Drop categories the project lacks.

**Migrate a legacy top-level array first (idempotent audit).** The server
requires a top-level **object**; a bare array is rejected outright. If the repo
already carries a manifest whose first non-whitespace character is `[`, rewrite
it as `{"artifacts": [ …the existing array… ]}` before going further, preserving
the entries as-is. This is the same normalize-in-place discipline Phase 3 applies
to the policy block, and it matters more than it looks: when the server rejects a
manifest, `codebase_status` silently omits the artifact line, so the repo indexes
"successfully" and reports `artifacts 0/0` while having **no context search at
all** (gotcha K).

**Then gate on the validator** — cheap, and it runs before the expensive index:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" validate-manifest "<PROJECT_PATH>"
```

It checks the top-level shape, the `{name, path, description}` triple, unique
(case-insensitive) names, the absent-`paths`-plural rule, globs, and that **every
path resolves** — exiting non-zero with one line per problem on stderr and a
`{present, count, valid, errors}` verdict on stdout. A non-resolving path
is not cosmetic: the server skips it silently, so `artifacts N/N` never reaches
parity and Phase 5 blocks until `INDEX_TIMEOUT_MS`. Fix every reported line, or
drop the category, before indexing.

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
- `codebase_graph_status` is READY **and clears the yield floor** (below).
- `codebase_list_projects` shows the project.
- `codebase_status`: artifacts N/N, and the last operation **completed, not
  FAILED**. A failed last operation fails verification even with every other
  light green — the delta that failed is missing from the index. On usa-wa an
  `Incremental update — FAILED (fetch failed)` sat unreported for ~21h behind
  three green lights ([#107](https://github.com/gregoryfoster/skills/issues/107)).

**Graph yield — READY is a status, not a result.** READY is reachable with a
graph that resolved almost nothing: usa-wa reported READY over **3 dependency
edges across 374 files, 81.8% unresolved**, because the resolver cannot follow
the standard `uv`/hatch src layout (dashed distribution dir → `src/` →
underscored module). Measure the yield:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" health-check "<PROJECT_PATH>" \
  --probe <a file you know has several first-party imports>
```

| Verdict | Meaning | Do |
|---|---|---|
| `ok` | ≥ 0.1 edges per file | nothing; keep policy **variant A** |
| `low` | < 0.1 edges per file (the probe confirms `codebase_graph_query` returns *empty*, not an error) | **return to Phase 3 and write policy variant B** — route imports/dependents/blast-radius to `grep`, warn that empty graph output is tool failure, not absence. Do **not** fail the install |
| `unknown` | < 20 files, or the status string did not parse | report it; leave variant A |

A low-yield graph is an upstream SocratiCode defect this skill cannot repair, so
it must not fail the install — a repo left with *no* policy is worse off than one
with a policy that routes around the broken tool. What it must never do is stay
silent: `codebase_graph_query` answers a low-yield graph with the ordinary
sentence "No dependency information found for this file", which an agent reads
as a fact about the code rather than about the tool.

Then clean up the Phase 0 scratch clone (if used): `rm -rf "<SKILL_TMP>"`.

Present a completion table:

| Component | Status |
|---|---|
| Preflight | Docker ✓ (boot-enabled: `<yes/n-a>`) · Node `<version>` (>=18 <26) ✓ · npx ✓ |
| Plugin | marketplace `socraticode` registered · `plugin:socraticode:socraticode` Connected |
| Backend | `<EMBEDDING_BACKEND>` |
| Policy | `## Code Exploration Policy` in `<POLICY_FILE>` (marker-delimited, variant `<A/B>`) · `docs/SOCRATICODE.md` written |
| SessionStart hooks | `<INSTALL_HOOK>` — `.claude/hooks/socraticode-reminder.sh` (prefetch, `<symlink/copy>`) · `.claude/hooks/socraticode-health.sh` (once-per-day infra check, `<symlink/copy>`) |
| Context artifacts | `.socraticodecontextartifacts.json` (N artifacts, each `path` resolves) |
| Index exclusions | `.socraticodeignore` (vendored skill trees excluded) |
| Index | index run completed (no FAILED last operation) · graph READY · **yield `<ok/low/unknown>`** · artifacts N/N |
| Sample search | returns hits |

## Re-run on an existing project (audit/repair)

Running this skill on a project that already has SocratiCode is **safe and is
the audit**: every file edit is idempotent and Phase 6 re-verifies the
completion signals. Before an audit re-run read
[`references/audit-rerun.md`](references/audit-rerun.md) — what each phase
re-does, the partial installs a re-run repairs (including a manifest the server
silently rejected, which has been reporting `artifacts 0/0` as if healthy), and
the one thing a re-run must not do quietly: rescue repo-authored prose out of an
unmarked policy section before Phase 3 replaces the span
([#115](https://github.com/gregoryfoster/skills/issues/115)).

## Key invariants

- **Completion is three signals, not one.** Never declare done at "100%
  embedded" — require the index run reported complete AND graph READY AND
  artifacts N/N (troubleshooting gotcha C). None of the three is a percentage:
  the progress line disappears when the run finishes, so waiting to observe
  "100%" is waiting for something that will never arrive (gotcha J).
- **Gate the graph on yield, not on status.** `READY` says a build finished, not
  that it resolved anything: usa-wa reported READY over 3 edges across 374 files
  (gotcha N). Measure edges per file, and on a `low` verdict write the degraded
  policy rather than failing the install — a policy that points at broken
  tooling is worse than no policy, because empty output reads as "no dependents"
  rather than "tool failed" ([#107](https://github.com/gregoryfoster/skills/issues/107)).
- **A failed last operation is a finding, not a footnote.** `codebase_status`
  records it and nothing used to read it outside an in-flight index run. Phase 6
  fails on it; the once-per-day health hook reports it if it appears later.
- **The health hook reports; it never repairs.** No re-index, no Docker start,
  no file edit from a SessionStart hook — it runs before an agent has context
  and must cost a bounded, silent-when-clean moment.
- **Never mutate the host toolchain.** Preflight detects and instructs; it does
  not install Node/Docker. Node 26+ is a hard refusal, not a "try anyway."
- **All file edits are idempotent.** The AGENTS.md policy block and the
  `docs/SOCRATICODE.md` template are both marker-delimited — a re-run replaces
  between the markers and preserves what follows `END`; the settings.json hook
  is merged and deduped. Re-running the skill, or running it on a project that
  already has these files, must not duplicate blocks or stack hooks.
- **The policy block pays rent on every invocation.** It is the one section
  `curating-context` will not edit, so whatever lands in `AGENTS.md` is a fixed
  cost the repo cannot curate away — 1,247 tokens and 15% of watcher's whole
  curated file before the split. Keep the block at the negative rule plus the
  two or three highest-traffic rows; everything else goes to
  `docs/SOCRATICODE.md`. Adding a row to the block is a budget decision
  ([#115](https://github.com/gregoryfoster/skills/issues/115)).
- **Repo-authored content inside an unmarked policy section is rescued, never
  replaced.** The unmarked branch replaces a whole span, and repos grow real
  content in it. Move anything the template does not carry to
  `## Code Exploration Notes (repo-specific)` outside the markers, and say so.
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
gotcha matrix (A–N) and the native-vs-fallback decision tree.

**Self-budget:** held to a **10,050-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — a named exception to the repo's
6,000-token standard, set at current size so this file cannot grow.
