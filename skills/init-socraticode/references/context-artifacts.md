# Context artifacts — `.socraticodecontextartifacts.json`

SocratiCode indexes **code** by default. Context artifacts point it at a
project's **non-code knowledge** so `codebase_context` / `codebase_context_search`
can answer questions about schemas, API contracts, infra topology, and runbooks
— the things grep-over-source can't surface.

The manifest lives at the **repo root** as `.socraticodecontextartifacts.json`.
After `codebase_index` finishes embeddings + graph, run `codebase_context_index`
(or let the driver do it) to embed the artifacts (SKILL.md Phase 4 + Phase 5).

> **Adapt, do not copy.** The acceptance criteria require the manifest to name
> the project's *actual* files. The template below is a starting menu — delete
> the categories the project doesn't have, fix every path, and verify each glob
> matches at least one file before indexing.

## Template

```json
{
  "artifacts": [
    {
      "name": "Database schema",
      "description": "SQL DDL / migrations — table shapes, columns, constraints",
      "paths": ["alembic/versions/**/*.py", "**/*.sql", "schema/**"]
    },
    {
      "name": "API contracts",
      "description": "OpenAPI / Protobuf / GraphQL service definitions",
      "paths": ["openapi.yaml", "openapi/**", "**/*.proto", "**/*.graphql"]
    },
    {
      "name": "Infrastructure",
      "description": "Terraform / Kubernetes / systemd — deployment topology",
      "paths": ["deploy/**", "terraform/**/*.tf", "k8s/**/*.yaml", "**/*.service"]
    },
    {
      "name": "Architecture & runbooks",
      "description": "Design docs, ADRs, agent guidelines, operational docs",
      "paths": ["AGENTS.md", "README.md", "docs/**/*.md"]
    },
    {
      "name": "Environment config",
      "description": "Env var contracts and example configs (never real secrets)",
      "paths": [".env.example", "config/**", "pyproject.toml"]
    }
  ]
}
```

## Field notes

- **`paths`** accepts globs. Prefer specific subtrees over `**/*` — over-broad
  globs pull vendored deps and inflate index time.
- **Never point at real secrets.** Include `.env.example`, never `.env`. If the
  project keeps secrets in a tracked file, exclude it explicitly.
- **Exact schema shape may drift** between SocratiCode versions. If
  `codebase_context_index` rejects the manifest, run `codebase_status` — it
  reports how many artifacts it parsed — and reconcile against the installed
  version's docs. Keep the field names above unless the server complains.

## Per-stack starting points

| Stack | Likely artifact sources |
|---|---|
| FastAPI (this org) | `alembic/versions/**`, `AGENTS.md`, `docs/**`, `deploy/*.service`, `pyproject.toml` |
| Click CLI | `AGENTS.md`, `docs/**`, `pyproject.toml`, any `*.toml`/`*.yaml` config schema |
| PHP / WordPress (Bedrock) | `composer.json`, `config/**`, `*.sql` dumps, `docs/**`, theme `*.blade.php` layouts |

## Verify a glob before committing it

```bash
# Each artifact path should match at least one real file:
git ls-files 'alembic/versions/**' 'docs/**' 'deploy/**' | head
```

Empty output for a category → drop that category from the manifest rather than
shipping a glob that matches nothing (it makes `artifacts N/N` misleading).
