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

Each artifact is `{ "name", "path", "description" }` — all three **required
non-empty strings**. The server (`dist/services/context-artifacts.js`) validates
this on the first `codebase_context_index` call and rejects anything else, so
Phase 4 fails outright if the shape is wrong.

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
- **A directory artifact is pruned only of `node_modules`/`.git`.** The artifact
  walk uses its own hardcoded ignore — it does **not** honor `.socraticodeignore`
  or `.gitignore` (those govern the *code* index, not artifacts). So the
  `.socraticodeignore` you add in Phase 4 won't shrink an over-broad artifact
  dir; keep each artifact path scoped to the subtree you actually want embedded.
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

## Two failure modes — shape aborts, a bad path skips

The server treats these differently, and the fix differs:

- **Shape errors abort the whole run.** A `paths` array, an empty/missing/
  non-string `path`, or a duplicate `name` throws at manifest-parse time — nothing
  indexes, `codebase_context_index` fails outright. This is the #76 bug.
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
