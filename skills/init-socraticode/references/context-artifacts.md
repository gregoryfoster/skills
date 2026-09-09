# Context artifacts — `.socraticodecontextartifacts.json`

SocratiCode indexes **code** by default. Context artifacts point it at a
project's **non-code knowledge** so `codebase_context` / `codebase_context_search`
can answer questions about schemas, API contracts, infra topology, and runbooks
— the things grep-over-source can't surface.

The manifest lives at the **repo root** as `.socraticodecontextartifacts.json`.
After `codebase_index` finishes embeddings + graph, run `codebase_context_index`
(or let the driver do it) to embed the artifacts (SKILL.md Phase 4 + Phase 5).

> **Adapt, do not copy.** The acceptance criteria require the manifest to name
> the project's *actual* files. The canonical categories below are the taxonomy
> the configured cohort repos converged on (archiver 8 artifacts, power-map 6,
> observo 13, usa-wa 7) — include each category **only when the project has the
> files**, fix every path, and verify each path resolves to a real file or
> directory before indexing.

## Manifest shape — one `path` string per artifact

**The top level must be an object with an `artifacts` array. A bare top-level
array is rejected** — the server throws `.socraticodecontextartifacts.json must
be a JSON object`. Legacy manifests written as a naked `[ … ]` are the common
inherited form, and they fail in the worst possible way (see below); migrate to:

```json
{ "artifacts": [ …the existing array… ] }
```

Each artifact is `{ "name", "path", "description" }` — all three **required
non-empty strings**. The server (`dist/services/context-artifacts.js`) validates
this on the first `codebase_context_index` call and rejects anything else, so
Phase 4 fails outright if the shape is wrong.

Validate before indexing rather than discovering this afterwards:

```bash
node "<SKILL_DIR>/scripts/mcp-driver.mjs" validate-manifest "<PROJECT_PATH>"
```

- **`path` is a single string, not an array.** There is no `paths` field. One
  artifact = one path.
- **`path` must be a literal file or directory that exists.** The server
  `stat()`s it; **globs do not work** — `docs/plans/**/*.md` is `stat()`'d
  verbatim and errors with *"path is neither a file nor a directory."*
- **A directory path indexes every file under it, recursively** (dotfiles,
  `node_modules`, and `.git` skipped). This is how one artifact covers a
  multi-file category — point at `./docs/plans/`, not a glob.
- **One file per artifact otherwise.** To cover two unrelated files (e.g.
  `.env.example` and `pyproject.toml`), write two entries — each then carries a
  description specific to that file instead of a blended one.

## Canonical categories (cohort-converged)

Where a row lists more than one path, they are **alternatives or separate
entries** — pick whichever the project has and give each its own artifact. A
comma never means "combine into one `path`"; there is no multi-path `path`.

| Category | Typical path (file or dir) | Include when |
|---|---|---|
| `agent-guidelines` | `./AGENTS.md` | always (every cohort repo registers it) |
| `commands` | `./docs/COMMANDS.md` | the project keeps a command reference |
| `skills-doc` | `./docs/SKILLS.md` | the project vendors skills |
| `socraticode-doc` | `./docs/SOCRATICODE.md` | always (Phase 3 writes it) |
| `design-plans` | `./docs/plans/` (dir) | plans dir exists (writing-plans default) |
| `design-specs` | `./docs/specs/` and/or `./docs/research/` (dirs; one entry each) | separate spec/research trajectories exist |
| `architecture` | `./docs/ARCHITECTURE.md` and/or `./README.md` (one entry each) | an architecture doc exists |
| `schema-migrations` | `./alembic/versions/` (dir) | DB-backed (whichever is the schema source of truth) |
| `api-contracts` | `./openapi.yaml` or a vendored spec snapshot file | the project consumes/publishes specs |
| `systemd-unit` | `./deploy/` (dir) or a specific `./deploy/app.service` | DEPLOY_TARGET=systemd |
| `infrastructure` | `./terraform/` or `./k8s/` (dirs) | IaC exists |
| `project-config` | `./pyproject.toml` and/or `./.env.example` (one entry each; never real secrets) | dep/tool config or env contract documented |
| `style-guide` | `./docs/STYLE.md` | a style doc exists |

## Template

```json
{
  "artifacts": [
    {
      "name": "agent-guidelines",
      "path": "./AGENTS.md",
      "description": "Agent working agreements, conventions, layout map"
    },
    {
      "name": "commands",
      "path": "./docs/COMMANDS.md",
      "description": "Canonical command reference (setup, test, deploy)"
    },
    {
      "name": "design-plans",
      "path": "./docs/plans/",
      "description": "Implementation plans and design docs (directory, indexed recursively)"
    },
    {
      "name": "schema-migrations",
      "path": "./alembic/versions/",
      "description": "SQL DDL / migrations — table shapes, columns, constraints"
    },
    {
      "name": "systemd-unit",
      "path": "./deploy/app.service",
      "description": "Deployment topology — systemd unit"
    },
    {
      "name": "env-example",
      "path": "./.env.example",
      "description": "Env var contract and example config (never real secrets)"
    },
    {
      "name": "pyproject",
      "path": "./pyproject.toml",
      "description": "Dependency and tool config — project contract"
    }
  ]
}
```

## Field notes

- **`path` is one literal file or directory — never a glob or array.** Point a
  category with many files at its **directory** (`./docs/plans/`); the server
  walks it recursively. Prefer a specific subtree (`./alembic/versions/`) over a
  broad top-level dir — a directory artifact pulls *every* file under it,
  including any vendored deps that live there, and inflates index time.
- **A directory artifact runs the ignore chain — rooted at the ARTIFACT
  directory, not the repo.** Since socraticode **1.13** (`SocratiCode#117`) the
  walk in `dist/services/context-artifacts.js` puts every file through
  `createIgnoreFilter`/`shouldIgnore`: built-in defaults, then `.gitignore`
  (root + nested), then `.socraticodeignore`. The surviving
  `ignore: ["**/node_modules/**", "**/.git/**"]` in the glob is now only a
  subtree-pruning optimisation over two of the chain's own defaults, and the
  source says so. Through **1.12.x** none of this was true — the walk honoured
  no ignore file at all — so which half applies is a version question, and the
  boundary is 1.13.0.
- **Rooted at the artifact directory is the part that surprises.**
  `createIgnoreFilter` is called with the *artifact* path, so it reads
  `<artifact>/.gitignore` and `<artifact>/.socraticodeignore` — **the
  `.socraticodeignore` you add in Phase 4 at the repo root does not reach an
  artifact at `./alembic/versions/`.** Measured on 1.13.2: with `*.sql` in a
  repo-root `.socraticodeignore`, a `versions/` artifact still embedded
  `002_b.sql`; moving the same line into `versions/.socraticodeignore` dropped
  it, and a nested `versions/sub/.gitignore` dropped a file under `sub/` too.
  Rooting it there is deliberate — it also keeps an artifact declared at
  `./build/openapi/` from ignoring *itself*, since the relative paths no longer
  start with `build/`.
- **The built-in defaults now apply INSIDE an artifact, which can drop content
  you wanted.** `__pycache__`, `*.pyc`, `dist`, `build`, `out`, `target`,
  `_build`, `deps`, `obj`, `coverage`, `vendor`, `.tox`, `*.lock`, `*.log`,
  `*.map`, `*.min.js` and the rest of `DEFAULT_IGNORE_PATTERNS`
  (`dist/services/ignore.js`) match at any depth below the artifact root;
  `/venv`, `/env`, `bin/Debug` and `bin/Release` are anchored to it. So an
  artifact pointed at `./docs/` silently loses a Sphinx `docs/build/`, and one
  pointed at a directory of generated `*.lock` fixtures embeds none of them.
  Nothing errors and nothing is logged above debug — the only visible trace is
  a chunk count lower than you expected. **Check the artifact subtree for
  default-ignored names you meant to keep.** To rescue one, negate the
  **directory itself** in an ignore file inside the artifact path — measured on
  1.13.2, `!build` re-includes `build/keep.md`, while `!build/keep.md` and
  `!build/**` do not: gitignore cannot re-include a file whose parent directory
  is excluded, and the `ignore` package enforces that. `node_modules` and
  `.git` cannot be rescued at all — the glob prunes those subtrees before the
  chain ever sees them.
- **The binary guard works now, and the bytecode hazard is gone with it.**
  Through 1.12.x the guard was present but could not fire: the server read each
  file with `fsp.readFile(filePath, "utf-8")` inside a `try/catch` commented
  *"skip unreadable files (binary, permissions, etc.)"*, and that call does not
  throw on binary input — it returns U+FFFD replacement characters — so every
  compiled file took the *success* branch. On CannObserv/observo an artifact at
  `./alembic/versions/` picked up the `__pycache__/` every test run drops
  there: **70 `.pyc` files, 32 of the artifact's 86 chunks compiled bytecode**,
  and a `codebase_context_search` for the migration head answered with
  decompiled bytecode as its top hit (filed as `giancarloerra/SocratiCode#116`,
  fixed in #117). On 1.13.x the file is read as a `Buffer` and sniffed with
  `isBinaryContent` before decoding, and `__pycache__`/`*.pyc` are in the
  default ignore list besides — so bytecode is excluded twice over. Measured on
  observo at 1.13.2: 72 `.pyc` under `./alembic/versions/` and the artifact
  indexes **57 chunks** — the without-bytecode figure plus the migrations added
  since, not the 86 that bytecode produced.
  `PYTHONPYCACHEPREFIX` is still worth setting for the *code index* and for a
  tidy tree, but it is no longer load-bearing for artifacts.
- **Staleness parity, and the residual that is left.** `mcp-driver.mjs
  health-check` judges a directory artifact by its **newest descendant** mtime
  (#225). Its walk mirrors the server's exclusions — `dot: false` plus the
  transcribed `DEFAULT_IGNORE_PATTERNS` (#270) — because anything counted that
  the server never embeds reports a byte-identical artifact `stale` with a
  remedy that cannot clear it: re-indexing does not bring in the file whose
  mtime moved (#235). What the driver does **not** mirror is the chain's other
  two layers — artifact-local `.gitignore`/`.socraticodeignore`, and
  virtualenvs found by marker. A file excluded by one of those, inside an
  artifact, can still produce a false `stale`; it is rare, and it is the one
  case where the right response to the finding is to dismiss it.
- **Each `name` must be unique** (case-insensitive) — the server rejects
  duplicates at parse time, aborting the whole run. When you split one category
  into multiple entries, give each a distinct name (as the template's
  `env-example`/`pyproject` do), not the shared category label twice.
- **Never point at real secrets.** Include `.env.example`, never `.env`. If the
  project keeps secrets in a tracked file, don't add it as an artifact.
- **Exact schema shape may drift** between SocratiCode versions. If
  `codebase_context_index` rejects the manifest, run `codebase_status` — it
  reports how many artifacts it parsed — and reconcile against the installed
  version's docs. The `{name, path, description}` shape above matches the server
  resolved by `npx -y socraticode` as of 2026-07.

## Per-stack starting points

| Stack | Likely artifact sources (files / dirs) |
|---|---|
| FastAPI (this org) | `./alembic/versions/`, `./AGENTS.md`, `./docs/`, `./deploy/app.service`, `./pyproject.toml` |
| Click CLI | `./AGENTS.md`, `./docs/`, `./pyproject.toml`, a named config file (e.g. `./ruff.toml`) |
| PHP / WordPress (Bedrock) | `./composer.json`, `./config/`, a named SQL dump (e.g. `./db/schema.sql`), `./docs/`, a named theme layout (e.g. `./resources/views/layouts/app.blade.php`) |

## Three failure modes — shape aborts, shape aborts *silently*, a bad path skips

The server treats these differently, and the fix differs:

- **Shape errors abort the whole run.** A `paths` array, an empty/missing/
  non-string `path`, or a duplicate `name` throws at manifest-parse time — nothing
  indexes, `codebase_context_index` fails outright. This is the #76 bug.
- **…and the abort is invisible from `codebase_status`.** The status handler
  wraps its artifact block in a `try/catch` marked "non-critical", and
  `getArtifactStatusSummary()` returns null whenever `artifacts` is missing or
  empty — which is exactly what a rejected manifest looks like. So the
  `Context artifacts:` line is **omitted entirely**: `codebase_index` completes,
  `codebase_context_index` throws where nobody is looking, and the repo reads as
  a contented `artifacts 0/0` with zero context search. A legacy top-level array
  lands precisely here. Run `validate-manifest` (above) rather than trusting a
  green status — this is #85's gotcha K.
- **A well-formed but non-resolving `path` skips only that artifact.** The server
  `stat()`s each path inside a per-artifact `try/catch`; a path that doesn't exist
  is logged and skipped, and the *other* artifacts still index. It surfaces not as
  a hard error but as a **short count** — `artifacts N/N` reports fewer indexed
  than configured. This is exactly why Phase 5 gates on `artifacts N/N` matching.
  Under the **driver fallback** it's worse than a quiet undercount: the driver
  only completes when `indexed >= configured` and keeps re-nudging context
  indexing while artifacts lag, so a permanently-missing path never satisfies the
  predicate and the run **blocks until `INDEX_TIMEOUT_MS` (2h default)** — another
  reason to verify paths first.

So: get the *shape* right or Phase 4 dies; get every *path* right or Phase 5
quietly comes up short — no error, but `artifacts N/N` never reaches parity.
Verify each path resolves before committing:

```bash
# Each path in the manifest should exist:
for p in ./AGENTS.md ./docs/plans/ ./alembic/versions/; do
  test -e "$p" && echo "ok   $p" || echo "MISS $p"
done
```

Any `MISS` → drop that category from the manifest rather than shipping a path
that skips at index time and leaves `artifacts N/N` short.

## Index exclusions — `.socraticodeignore`

Phase 4 writes this at the repo root, alongside the manifest.

It's layered on the built-in
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

Note this file governs the **code index**, and reaches a directory context
artifact only when the artifact path *is* the repo root: since 1.13 the artifact
walk runs the same chain, but rooted at the artifact directory, so a subtree
artifact reads ignore files inside itself and never this one. The built-in
defaults apply to both. See the Field notes above.

## Migrating a legacy top-level array

Phase 4 does this first, as an idempotent audit. The server
requires a top-level **object**; a bare array is rejected outright. If the repo
already carries a manifest whose first non-whitespace character is `[`, rewrite
it as `{"artifacts": [ …the existing array… ]}` before going further, preserving
the entries as-is. This is the same normalize-in-place discipline Phase 3 applies
to the policy block, and it matters more than it looks: when the server rejects a
manifest, `codebase_status` silently omits the artifact line, so the repo indexes
"successfully" and reports `artifacts 0/0` while having **no context search at
all** (gotcha K).
