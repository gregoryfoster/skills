# Architectural Review Dimensions

Detailed guidance for each dimension evaluated during an architectural review.

## DRY (Don't Repeat Yourself)
Duplicated logic, copy-pasted code, constants defined in multiple places, parallel structures that should be unified.

## Module size & cohesion
Files that are too large or mix unrelated concerns. Any source file over ~300 lines deserves scrutiny; over ~500 lines is a strong signal to split. Check with `wc -l **/*.py` (or equivalent).

## Separation of concerns
Clear boundaries between layers (models, views, services, serialization). Business logic must not leak into request handlers or templates. Lower layers must not import from higher ones.

## Coupling & dependency direction
Circular imports, tight coupling between modules that should be independent, violations of layered architecture.

## Efficiency & performance
N+1 query patterns, missing database indexes on filtered/sorted columns, unnecessary eager loading, unoptimized loops over large collections, missing caching opportunities.

## Configuration & environment
Secrets management, environment-specific settings, hardcoded values that should be configurable.

## Error handling patterns
Inconsistent error handling strategies across modules, bare excepts, swallowed errors, missing retry/backoff on external calls.

## Naming & discoverability
Module and package names that obscure purpose, inconsistent naming conventions across apps, files whose role is unclear from name alone.

## Schema & data model health
Missing constraints, denormalization without justification, orphaned tables/columns, migration history cleanliness.

## Scalability concerns
Patterns that will break at 10× or 100× current scale, synchronous work that should be async, missing pagination.

## Test architecture
Test isolation, fixture reuse, test speed bottlenecks, gaps in coverage by layer.
