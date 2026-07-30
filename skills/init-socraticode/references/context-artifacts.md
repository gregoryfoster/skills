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
> files**, fix every path, and verify each glob matches at least one file
> before indexing.

## Canonical categories (cohort-converged)

| Category | Typical paths | Include when |
|---|---|---|
| `agent-guidelines` | `AGENTS.md` | always (every cohort repo registers it) |
| `commands` | `docs/COMMANDS.md` | the project keeps a command reference |
| `skills-doc` | `docs/SKILLS.md` | the project vendors skills |
| `design-plans` | `docs/plans/` | plans dir exists (writing-plans default) |
| `design-specs` | `docs/specs/`, `docs/research/` | separate spec/research trajectories exist |
| `architecture` | `docs/ARCHITECTURE.md`, `README.md` | an architecture doc exists |
| `schema-migrations` | `alembic/versions/` or `**/*.sql` | DB-backed (whichever is the schema source of truth) |
| `api-contracts` | `openapi.yaml`, vendored spec snapshots | the project consumes/publishes specs |
| `systemd-unit` | `deploy/**/*.service`, `deploy/**/*.timer` | DEPLOY_TARGET=systemd |
| `infrastructure` | `terraform/**/*.tf`, `k8s/**/*.yaml` | IaC exists |
| `env-example` | `.env.example`, `pyproject.toml` | env contract documented (never real secrets) |
| `style-guide` | `docs/STYLE.md` | a style doc exists |

## Template

```json
{
  "artifacts": [
    {
      "name": "agent-guidelines",
      "description": "Agent working agreements, conventions, layout map",
      "paths": ["AGENTS.md"]
    },
    {
      "name": "commands",
      "description": "Canonical command reference (setup, test, deploy)",
      "paths": ["docs/COMMANDS.md"]
    },
    {
      "name": "design-plans",
      "description": "Implementation plans and design docs",
      "paths": ["docs/plans/**/*.md"]
    },
    {
      "name": "schema-migrations",
      "description": "SQL DDL / migrations — table shapes, columns, constraints",
      "paths": ["alembic/versions/**/*.py"]
    },
    {
      "name": "systemd-unit",
      "description": "Deployment topology — systemd units and timers",
      "paths": ["deploy/**"]
    },
    {
      "name": "env-example",
      "description": "Env var contracts and example configs (never real secrets)",
      "paths": [".env.example", "pyproject.toml"]
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
