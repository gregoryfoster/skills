# Shared backing services as the ceiling

Loaded from [`SKILL.md`](../SKILL.md) when Q5's second sub-question finds a
service the worktrees do not clone — a shared test database above all. Q and
Step numbers refer to `SKILL.md`, so "item 2" below is its Step 5 item 2
(procedure in [`shared-files.md`](shared-files.md));
Worker-step numbers refer to [`execution.md`](execution.md).

## Before accepting a ceiling (Q5)

For a shared test database specifically: read the suite's session-scoped fixture and its DSN guard before accepting any ceiling.
- If the fixture is destructive (`DROP SCHEMA … CASCADE`, `drop_all`, truncate-all), concurrent runs corrupt each other and the ceiling is 1 until slots are provisioned.
- **Read the guard before accepting serialization.** If it validates a *base* DB name before a worker suffix is appended, per-agent databases pass it and the ceiling reverts to the host's CPU/RAM limit (process-log 2026-08-09: `observo_a1_test` passed the `endswith("_test")` assert *and* stayed xdist-compatible as `observo_a1_test_gw0`). **Then check the role can create the slots** — `SELECT rolcreatedb, rolsuper FROM pg_roles WHERE rolname = current_user`. A permissive guard plus a non-CREATEDB role reads as "rung 1 available" until provisioning fails; usually the role has neither, making rung 1 a one-time superuser step (2026-08-07, 2026-08-17 watcher, 2026-08-28 power-map).

Three resolutions, in preference order:
1. **Provision N slots up front** (N = desired ceiling). The only option preserving both parallelism *and* worker self-verification (Worker steps 7–9 run before the completion signal). Verify with one real run, then put the per-agent DSN in every worker prompt.
2. **Serialize the verification gate** — workers implement in parallel, the orchestrator runs the suite. Cheap, but workers can no longer self-verify before signalling.
3. **Cap agents at 1 per batch.** Always available, wastes all disjointness.

**Naming gotcha:** provisioned slot names must satisfy the suite's own safety guard. A guard like usa-wa's `assert_test_url_safety()`, requiring a `_test` *suffix*, means the obvious `db_test_1 … _4` aborts at conftest import; the slots have to be `db_1_test … db_4_test` (process-log 2026-08-07).

## The escape grep (Step 5, item 3)

3. **Where a shared backing service sets the ceiling (Q5), grep for the helpers that *escape* the isolation fixture.** A helper that opens its own engine/connection and destroys shared state is a *hard* conflict zone — not the **soft** fixture dependency item 2 ends by naming: it does not degrade other agents, it corrupts them mid-run, and the failure presents as an unrelated worker's mysterious red. It forces its issue solo on a database property with no file-overlap footprint at all (process-log 2026-08-11 usa-wa: a `reset_migration_schemas` helper documented as deliberately bypassing the savepointed `db_session` fixture forced a three-line test fix into its own batch). One grep, run alongside the contested-file grep:
```bash
grep -rnE 'DROP (SCHEMA|DATABASE)|TRUNCATE|create_async_engine|create_engine' --include='*.py' <test trees> <testing helper modules>
```
