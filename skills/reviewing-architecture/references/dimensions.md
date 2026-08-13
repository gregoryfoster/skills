# Architectural Review Dimensions

Detailed guidance for each dimension evaluated during an architectural review.

**Altitude test — the single rule that keeps this distinct from code review:** *Could a reviewer find this by reading one file?* If yes, it belongs to [`reviewing-code`](../../reviewing-code/SKILL.md), not here. Architecture findings are about relationships *between* units — boundaries, direction, contracts, blast radius — not defects *within* one. A bare `except` is CR's; two modules that both own authentication is AR's. When a dimension below sounds code-level, it is because the same word (DRY, error handling) names a structural cousin — always report the structural one.

Each dimension carries **Look for / How to find it / Example finding** so the analysis phase produces evidence-backed findings, not opinions. The **Example finding** lines illustrate the *What* phrasing for that dimension only — they are not full findings; the required report envelope (`What:` / `Evidence:` / `Why it matters:` / `Suggested approach:` / `Effort/Blast radius:`, all five verbatim) lives in [SKILL.md](../SKILL.md) Phase 3.

**"How to find it" is the finding's `Evidence:`.** Whatever command, graph query, or gather-context section actually surfaced the problem is what the finding records — as run, so the implementer can re-run it rather than re-derive the citation from a line table that has since moved.

---

## Separation of concerns & boundaries
Clear boundaries between layers (models, services, handlers, serialization) and between domains. Business logic must not leak into request handlers or templates; a handler that computes is a boundary violation.
- **Look for:** domain logic inside routers/views/templates; a single module that both talks to the DB and renders output; "god" modules that everything imports; missing seams where a bounded context should exist.
- **How to find it:** grep handlers/routers for query calls or business arithmetic; from the fan-in list (gather-context / `codebase_graph_query`), the module every other module imports is a boundary smell.
- **Example finding:** *`routers/report.py` builds the aggregate query, applies the pricing rules, and formats the CSV. The pricing rules belong in a `services/pricing.py` the router calls; today the same rules are re-implemented in `jobs/nightly.py`.*

## Coupling & dependency direction
Circular imports, layering violations (lower layers importing higher ones), and modules that should be independent but aren't. Direction matters more than count: dependencies should point toward stable abstractions.
- **Look for:** import cycles; `models/` importing `services/`; two "sibling" services that import each other; a change in one module forcing edits across many (poor evolvability).
- **How to find it:** `codebase_graph_circular` for cycles and `codebase_impact` for blast radius when SocratiCode is indexed; otherwise the `=== Internal import fan-in ===` blocks (Python and JS/TS) from gather-context. Fan-in/fan-out ratios flag instability.
- **Example finding:** *`services/billing.py` ↔ `services/accounts.py` form an import cycle (gather-context, Internal import fan-in). Extract the shared `Invoice` type into `models/invoice.py` so both depend on it and neither on each other.*

## Service contracts & interface stability
For multi-service repos: the API/schema surface other services depend on, its versioning, and backward compatibility. A breaking change at a boundary is an architectural event, not a code change.
- **Look for:** breaking changes to public request/response shapes without a version bump; a vendored client ([`vendoring-openapi-client`](../../vendoring-openapi-client)) drifting from its producer spec; unversioned endpoints; internal DB columns leaking into API responses.
- **How to find it:** diff the OpenAPI/schema surface against the last release tag; check for `v1`/`v2` routing and deprecation markers; look for response models that are ORM objects serialized directly.
- **Example finding:** *`GET /observations` returns the ORM row verbatim, so adding the internal `_ingest_batch_id` column silently changed the public contract. Introduce a response schema decoupled from the model.*

## Module size & cohesion
Files too large or mixing unrelated concerns. Size is a proxy, not the finding — a 600-line module doing one thing well may be fine; a 200-line module doing three things is not. Over ~300 lines deserves scrutiny, over ~500 is a strong split signal.
- **Look for:** the top entries of gather-context's file-size list; modules whose name implies one job but whose contents span several; `utils.py`/`helpers.py` grab-bags.
- **How to find it:** the `=== File sizes ===` block; then read the largest to judge whether size tracks a single responsibility.
- **Example finding:** *`services/parser.py` (612 lines) holds tokenizing, error recovery, and AST emission. Split into `parser.py` + `recovery.py`; recovery has no callers outside parsing and can be tested in isolation.*

## Resilience & failure architecture
How the system behaves when a dependency is slow, down, or returns garbage — the structural cousin of "error handling," raised from the try/except to the boundary. Blast radius of a single failure.
- **Look for:** external calls with no timeout; retries without backoff or idempotency; no circuit breaker/bulkhead around a flaky dependency; one failure taking down unrelated features; swallowed errors that hide partial failure.
- **How to find it:** grep for HTTP/DB client construction and check for timeout/retry config; trace what happens to a request when a downstream returns 503.
- **Example finding:** *Every request to `/dashboard` calls the pricing API synchronously with no timeout; one slow upstream stalls the whole page. Add a timeout + cached fallback so pricing degrades independently.*

## Scalability & data-access patterns
Patterns that break at 10× or 100× current scale. The *pattern*, not the individual site — an N+1 in one endpoint is CR's; an ORM-lazy-load pattern repeated across every list view is AR's.
- **Look for:** list endpoints without pagination; synchronous work that should be queued (email, report generation, external calls in the request path); unbounded in-memory accumulation; per-item queries in a shared serialization layer.
- **How to find it:** grep list/index handlers for pagination params; look for `for … in …: session.query(...)` shapes; identify work done inline that has no latency budget.
- **Example finding:** *All three list routers serialize via `to_dict()` which lazy-loads relations per row — an N+1 baked into the serialization layer, so every list view inherits it. Add eager-load at the query layer or a `selectinload` policy.*

## Observability
Can this system be understood and debugged in production? Treated as a structural property, not a logging nicety.
- **Look for:** no correlation/request IDs threaded through logs; unstructured `print`/string logs at boundaries; no metrics on the paths that matter; errors logged without context to locate them; no tracing across service hops.
- **How to find it:** check the logging setup module and whether request context is injected; grep boundary calls for surrounding log/metric emission.
- **Example finding:** *Cross-service calls carry no correlation ID, so a failed observation ingest can't be traced from the API log to the worker log. Thread a request ID through the client and log it on both sides.*

## Trust boundaries & security architecture
Structural security only — where authz decisions live, tenant isolation, secrets *flow*, data classification. Line-level checks (injection, a specific missing validation) are the `security-review` skill's; the seam between the two is: *AR asks where the boundary is drawn, security-review checks each crossing.*
- **Look for:** authz decisions scattered across handlers instead of a single enforced layer; multi-tenant queries that can omit the tenant filter; secrets read far from where configured; PII crossing a boundary without classification.
- **How to find it:** grep for the auth decorator/dependency and find handlers that lack it; check whether tenant scoping is enforced centrally or per-query.
- **Example finding:** *Tenant scoping is applied per-query in each router, so a new endpoint that forgets the filter leaks across tenants. Enforce tenant scope in a shared query dependency instead.*

## Configuration & environment
Secrets management, environment-specific settings, and hardcoded values that should be configurable — at the level of *how config flows through the system*.
- **Look for:** secrets in code or committed files; config read ad hoc across modules instead of a single settings object; environment assumptions (paths, URLs) hardcoded; 12-factor violations (config not from environment).
- **How to find it:** grep for likely secret patterns and hardcoded URLs/paths; check for a central settings module vs scattered `os.environ` reads.
- **Example finding:** *The DB URL is read via `os.environ` in four modules with four different fallbacks. Centralize in `settings.py` so environments can't diverge silently.*

## Schema & data-model health
Persistence-layer structure: constraints, normalization, migration hygiene, lifecycle.
- **Look for:** missing FK/unique/not-null constraints that let bad state exist; denormalization without justification; orphaned tables/columns; irreversible or destructive migrations; enums encoded as free strings.
- **How to find it:** read the models/migrations; check for constraints matching the invariants the code assumes; look for columns no code references.
- **Example finding:** *`observations.source_id` has no FK to `sources`, so application code enforces referential integrity the DB should. Add the constraint; a migration can backfill orphans first.*

## DRY of responsibility
Not duplicated *lines* (CR's) — duplicated *ownership*. Two places that must change together because they both encode the same decision.
- **Look for:** the same business rule implemented in a handler and a background job; parallel model hierarchies that mirror each other; a constant meaning re-derived in several modules; two services that both own a slice of the same domain.
- **How to find it:** when a finding elsewhere says "and the same logic exists in X," that's this dimension; grep for a distinctive rule string/number across modules.
- **Example finding:** *The 30-day retention rule lives in `api/cleanup.py` and `jobs/purge.py` as separate literals. Extract a single `RETENTION` policy both import, or they will drift.*

## Naming & discoverability
Structural legibility: can a newcomer predict where a thing lives from the layout? Module/package names, not variable names.
- **Look for:** `utils`/`common`/`misc` modules that hide real responsibilities; inconsistent naming across sibling apps; a module whose role can't be guessed from its name; directory layout that doesn't mirror the domain.
- **How to find it:** scan the directory tree for generic names; check whether sibling services follow the same internal layout.
- **Example finding:** *`core/misc.py` holds rate-limiting, date parsing, and the feature-flag client — three responsibilities behind a name that discloses none. Promote each to a named module.*

## Test architecture
Structure of the test suite, not individual test correctness: what's testable in isolation, where the seams are, coverage *by layer*.
- **Look for:** no unit seam because everything requires the DB/network; fixtures that couple unrelated tests; whole layers (services, migrations) with no tests; slow suites signaling missing isolation; tests asserting implementation not behavior.
- **How to find it:** map test files to source layers and find layers with none; check whether tests can run without external services.
- **Example finding:** *Every test hits Postgres because services take a live session, so there is no fast unit tier. Introduce a repository interface the services depend on to enable isolated tests.*

## Architecture drift (intended vs. actual)
Does the real structure match the documented one? The cheapest high-value check — compares AGENTS.md/README's stated layout and rules against what the tree and imports actually show.
- **Look for:** documented layering rules the imports violate; modules the docs don't mention (or vice versa); a described topology that no longer matches services present.
- **How to find it:** read AGENTS.md's architecture/layout section, then diff each stated rule against gather-context's tree and import edges.
- **Example finding:** *AGENTS.md states "routers never import services directly — always via the container," but `routers/report.py` and `routers/export.py` import `services.pricing` directly. Either restore the rule or update the doc; today it misleads.*

---

## Turning findings into fitness functions
Architecture rots between reviews because nothing enforces the fixes. When a coupling, layering, or contract finding is accepted (`fix`), consider whether it can graduate into an **executable check** so it can't regress:
- **Layering / no-cycles:** an [import-linter](https://import-linter.readthedocs.io/) contract (Python), [dependency-cruiser](https://github.com/sverweij/dependency-cruiser) rule (JS/TS), or [deptrac](https://github.com/qossmic/deptrac) ruleset (PHP) in CI.
- **Contract stability:** an OpenAPI diff gate against the last release (see [`vendoring-openapi-client`](../../vendoring-openapi-client) for the drift-guard pattern).
- **Module size:** a lint threshold that fails the build past an agreed ceiling.

A fitness function is optional, not automatic — surface it as the `Suggested approach` for the relevant finding so the user can opt in. When they do (`fix + fitness` or bare `fitness`), the [`enforcing-architecture`](../../enforcing-architecture/SKILL.md) skill generates the config, adds the dev dependency, documents the contract in AGENTS.md, and wires it into the detected check surface. A one-time refactor fixes today; a fitness function keeps it fixed.
