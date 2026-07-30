---
name: vendoring-openapi-client
description: Vendors a generated Python client for a producer service's OpenAPI into a consumer repo — committed spec snapshot with provenance sidecar, optional surface filtering, pinned openapi-python-client generation, lint/coverage/diff carve-outs, and tiered drift guards (hermetic CI regen-diff; scheduled or on-VM live-drift). Also refreshes an existing vendored client when the producer's spec changes. Use when a Python service needs a typed client for a sibling REST API.
compatibility: Designed for Claude. Requires git, uv, curl, python3. Consumer repo must be a uv-managed Python project; openapi-python-client is pinned per-project, never installed globally.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: vendor openapi client, vendor api client, generate api client from openapi, refresh vendored client, client drift guard
---

# Vendoring an OpenAPI Client — snapshot, generate, guard

Wires a consumer repo to a producer service's REST API through a vendored,
generated Python client. The committed OpenAPI snapshot is the
contract-of-record; the client is always generated FROM the snapshot (never
directly from the live producer), and drift guards keep snapshot, generated
tree, and live producer provably consistent.

Distilled from three CannObserv services that independently built this
lifecycle (archiver, observo, usa-wa — see gregoryfoster/skills#66).

<HARD-GATE>
Do NOT create or modify files in the consumer repo until you have collected
all required parameters and confirmed them with the user. (Phase 0 clones
this skill's source to a scratch dir under `/tmp`; that does not touch the
consumer tree.) Layout and naming choices drive file paths, package names,
and CI config throughout — getting them wrong means manual cleanup.
</HARD-GATE>

## Mode detection (before collecting parameters)

Search the consumer repo for existing provenance sidecars
(`**/openapi.meta.json`) and read each one's `producer` field. A repo can
carry several vendored clients (archiver vendors two), so the presence of
*a* sidecar is not by itself a refresh signal — match on producer:

- **A sidecar whose `producer` matches the requested producer** (or the user
  explicitly asked to refresh that client) → **refresh** run: read that
  sidecar, skip parameter collection (everything needed is recorded), and jump
  to [Refresh mode](#refresh-mode).
- **Sidecars exist but none names the requested producer** (or the user named
  no producer and more than one sidecar exists) → ask which producer this run
  targets before deciding; a new producer is a **bootstrap** run.
- **No sidecar at all** → **bootstrap** run: collect parameters below.

## Parameters to collect

Ask the user (one at a time if not provided upfront).

### Core parameters (required)

| Parameter | Example | Used in |
|---|---|---|
| `PRODUCER_NAME` | `power-map` | directory names, snapshot filename, CI job names |
| `PRODUCER_UNDERSCORE` | `power_map` (derived: hyphens→underscores) | Python package/module names |
| `SPEC_SOURCE` | `https://power-map.example.com/openapi.json` or a path in a local producer checkout | Phase 1 snapshot |
| `PRODUCER_BASE_URL_ENV` | `CO_OBSERVO_POWER_MAP_BASE_URL` | refresh script, live-drift workflow |
| `CLIENT_PACKAGE` | `power_map_client` | sdk-package import/package name |
| `CONSUMER_PACKAGE` | `observo` (the consumer repo's own top-level `src/` package) | generated-tree import path + carve-out paths |

Two more placeholders appear only in the reference templates, both derived
from the generator pin (not asked of the user): `<GENERATOR_MINOR>` is the
`openapi-python-client` minor the pin targets (e.g. `0.29`, used in the
`~=0.29.0` dependency spec), and `<GENERATOR_VERSION>` is the exact version the
lockfile resolves that pin to (e.g. `0.29.1`, recorded in the sidecar's
`generator` field). The minor is the intent; the version is what shipped.

### Branch-point parameters (defaults reflect CannObserv cohort majority)

| Parameter | Default | Choices | Drives |
|---|---|---|---|
| `OUTPUT_LAYOUT` | `sdk-package` | `sdk-package` \| `generated-tree` | Phase 3–5 file layout per [references/layouts.md](references/layouts.md) |
| `FILTER_SPEC` | `no` | `no` \| `yes` (+ `KEEP_PREFIX`, default `/api/v1/`) | Phase 2; refresh + drift flows re-filter identically |
| `DRIFT_GUARD` | `ci` | `none` \| `ci` \| `ci+live` | Phase 6 per [references/ci-drift-job.md](references/ci-drift-job.md) and [references/live-drift.md](references/live-drift.md) |

Cohort context (show when the user asks "why this default?"):

- `OUTPUT_LAYOUT=sdk-package` — archiver (twice: `archiver-client`,
  `watcher-client`) and usa-wa (`powermap-client` workspace member) use a
  standalone package; observo uses `generated-tree`. The SDK's own lockfile
  pinning the generator + ruff is what makes drift checks byte-stable, so
  sdk-package is both majority and mechanically stronger.
- `FILTER_SPEC` — only observo filters (producer exposes an `/admin/*` HTMX
  surface it never calls). Say `yes` when the producer spec carries surface
  the consumer won't touch.
- `DRIFT_GUARD=ci` — every cohort repo runs the hermetic CI gate; only
  archiver adds the live tier (its producer is localhost-only). `ci+live`
  is warranted when a stale snapshot would surface as a runtime incident
  rather than a failing test.

## Procedure — bootstrap

### Phase 0 — Acquire skill source

```bash
SKILL_TMP="$(mktemp -d /tmp/skills-XXXXXX)"
git clone --depth 1 https://github.com/gregoryfoster/skills.git "$SKILL_TMP/gregoryfoster-skills"
SKILL_DIR="$SKILL_TMP/gregoryfoster-skills/skills/vendoring-openapi-client"
test -d "$SKILL_DIR/assets" || { echo "Phase 0 clone failed — $SKILL_DIR/assets missing"; exit 1; }
SKILL_SHA="$(git -C "$SKILL_TMP/gregoryfoster-skills" rev-parse --short HEAD)"
echo "SKILL_DIR=$SKILL_DIR"
```

`<SKILL_DIR>` / `<SKILL_TMP>` below are **placeholders** for the literal
paths printed here (same convention as `<PRODUCER_NAME>`) — each later Bash
invocation runs in a fresh shell, so Phase 0's variables are not inherited.

### Phase 1 — Snapshot the spec + provenance sidecar

Write `scripts/refresh-<PRODUCER_NAME>-spec.sh` from the template in
[references/provenance-sidecar.md](references/provenance-sidecar.md)
(substituting all placeholders), `chmod +x`, and run it once to produce the
committed snapshot and `openapi.meta.json` sidecar. When `SPEC_SOURCE` is a
file path (local producer checkout), copy + canonicalize instead of curl, and
record `source_path` + `source_commit` in the sidecar per the reference.

Snapshot/sidecar location: `clients/<PRODUCER_NAME>-python/` (sdk-package) or
`vendor/<PRODUCER_NAME>/` (generated-tree).

### Phase 2 — Optional surface filter (`FILTER_SPEC=yes` only)

Copy the filter into the consumer repo and run it:

```bash
cp "<SKILL_DIR>/assets/filter_openapi_spec.py" scripts/filter_openapi_spec.py
uv run python scripts/filter_openapi_spec.py <SPEC_PATH> <FILTERED_PATH> --keep-prefix "<KEEP_PREFIX>"
```

The filtered spec is committed beside the raw snapshot and becomes the
generator input; the raw snapshot remains the fetch target of record.

### Phase 3 — Scaffold the output layout + regen entry point

Follow [references/layouts.md](references/layouts.md) for the chosen
`OUTPUT_LAYOUT`:

1. Scaffold the layout: SDK `pyproject.toml` with the generator + ruff pinned
   in its dev group (sdk-package), or the root dev-group pin + generator config
   (generated-tree). Record the resolved exact generator version — it goes in
   the sidecar's `generator` field.
2. Write the regen entry point (`scripts/regen.sh` in the SDK, or a Makefile
   target) from [references/layouts.md](references/layouts.md). It must exist
   before Phase 4 runs it.

### Phase 4 — Generate

Run the regen entry point written in Phase 3 once, then verify the generated
tree imports:

```bash
# sdk-package:
uv run python -c "import <CLIENT_PACKAGE>; print('client imports OK')"
# generated-tree:
uv run python -c "import <CONSUMER_PACKAGE>.shared.<PRODUCER_UNDERSCORE>_generated; print('client imports OK')"
```

### Phase 5 — Carve-outs + document the update flow

1. Apply every applicable exclusion from
   [references/carve-outs.md](references/carve-outs.md): ruff, coverage,
   pre-commit, mypy/ty, `.gitattributes` `linguist-generated`.
2. Document the two-command update flow (refresh script → regen command) in
   the SDK README or the consumer's docs.

### Phase 6 — Drift guards (`DRIFT_GUARD` tier)

- `ci` and `ci+live`: wire the hermetic CI gate per
  [references/ci-drift-job.md](references/ci-drift-job.md). For sdk-package,
  copy the driver: `cp "<SKILL_DIR>/assets/check_client_drift.py"
  scripts/check_client_drift.py` and fill in its `CLIENTS` registry.
- `ci+live`: add the live tier per
  [references/live-drift.md](references/live-drift.md) — flavor A (scheduled
  workflow) when the producer is reachable from GitHub runners, flavor B
  (on-VM systemd timer) when it is localhost-only. Flavor B's deploy wiring
  (users, paths, env files) is project-specific — leave clearly-marked
  placeholders for the project to fill, or defer to a project-level override.
- `none`: state in the SDK README that staleness is unguarded and the regen
  flow is manual-only.

### Phase 7 — Verify

```bash
uv sync && uv run pytest        # consumer suite still green
uv run ruff check .             # carve-outs effective (no generated-tree noise)
```

With `DRIFT_GUARD>=ci`, run the drift check locally — it must be a no-op
immediately after Phase 4:

```bash
uv run --no-project python scripts/check_client_drift.py   # sdk-package
# or: regen command + git diff --exit-code                  # generated-tree
```

### Phase 8 — Commit + report

Commit snapshot, sidecar, generated tree, scripts, carve-outs, and CI changes
together (one reviewable bundle). Clean up: `rm -rf "<SKILL_TMP>"`. Report a
summary table: layout, spec source, filter, drift tier, regen command, and
the sidecar path.

## Refresh mode

When a sidecar already exists:

1. Verify sidecar integrity — recompute the snapshot's sha256; on mismatch,
   stop and report (the snapshot was hand-edited after capture).
2. Run the recorded refresh script (or re-fetch from the sidecar's
   `source_url` / `source_path`) — snapshot + sidecar update together.
3. `git diff` the snapshot. No change → report "no drift" and stop.
4. Re-run the filter with the sidecar's recorded `filter` args (when set),
   then the regen command. The generator version comes from the lockfile pin;
   if the pin has been bumped since capture, update the sidecar's `generator`
   field.
5. Run the consumer suite + drift check; summarize the contract diff (paths /
   schemas touched) for the PR description; commit the bundle.

## Key invariants

- The committed snapshot is the **contract-of-record**: fetch → snapshot →
  generate, never live → generate. Snapshot and generated tree are always
  committed in lockstep.
- Canonicalization (pretty-print, order-preserving, NOT `sort_keys`; filter
  output excepted) must be byte-identical across the refresh script, the
  regen command, and every drift guard — see
  [references/layouts.md](references/layouts.md).
- The generator and ruff are **exactly pinned by a lockfile** the drift check
  resolves (SDK's own `uv.lock` for sdk-package; root lock + `--frozen` for
  generated-tree). A generator bump is an explicit decision, never a drive-by.
- The generated tree is never hand-edited — the CI gate exists to catch it;
  curated exports live in the hand-authored package shell, not in
  `generated/`.
- The hermetic CI gate cannot detect snapshot-vs-live staleness; only the
  live tier (or the producer-in-repo offline test) can. Never claim otherwise
  in the consumer's docs.
- Live-drift guards surface drift on a schedule and are **never merge
  blockers**; flavor B's deploy wiring is project-specific and stays out of
  this global skill.
- Secrets (spec-endpoint API keys, `GH_TOKEN`) come from env/secret stores —
  never committed, never inlined in scripts or workflows.
