# Output layouts — sdk-package and generated-tree

Two layouts, one invariant: the committed snapshot is the contract-of-record,
and the generated tree is always produced FROM the snapshot (never directly
from the live producer), so snapshot and tree move in lockstep and the CI
drift gate can prove their consistency hermetically.

## `sdk-package` (default)

A standalone SDK directory with its own `pyproject.toml` + `uv.lock`, wired
into the consumer as an editable path dependency (or a uv workspace member if
the repo already uses a workspace). The SDK's own lockfile pins
`openapi-python-client` and `ruff`, so every regen — local or CI — uses
identical toolchain versions. This is what makes the drift gate byte-stable.

```
clients/<PRODUCER_NAME>-python/
  pyproject.toml            # hand-authored shell: deps, pins, build config
  uv.lock
  README.md                 # what this is + the regen command
  <PRODUCER_NAME>-openapi.json      # committed snapshot (contract-of-record)
  <SPEC_DIR>/openapi.meta.json      # provenance sidecar (same dir as snapshot)
  scripts/regen.sh
  src/<CLIENT_PACKAGE>/
    __init__.py             # curated re-exports from generated/
    generated/              # openapi-python-client output (--meta none); never hand-edited
  tests/                    # optional: import/export smoke tests
```

### SDK `pyproject.toml` template

```toml
[project]
name = "<PRODUCER_NAME>-client"
version = "0.1.0"
description = "Python SDK for the <PRODUCER_NAME> service. Generated from its OpenAPI schema."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.28.0,<1",
    "attrs>=24",                   # required by openapi-python-client output
    "python-dateutil>=2.9",        # required by openapi-python-client output
]

[dependency-groups]
dev = [
    # Generator + formatter pinned HERE (resolved exactly by this SDK's own
    # uv.lock) so regen diffs reflect spec changes, not toolchain changes —
    # a bump is an explicit decision.
    "openapi-python-client~=<GENERATOR_MINOR>",
    "ruff>=0.9,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/<CLIENT_PACKAGE>"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Wire into the consumer root `pyproject.toml`:

```toml
[tool.uv.sources]
<PRODUCER_NAME>-client = { path = "clients/<PRODUCER_NAME>-python", editable = true }
```

(or `{ workspace = true }` + a `[tool.uv.workspace] members` entry when the
repo is already a workspace.)

### `scripts/regen.sh` template

```bash
#!/usr/bin/env bash
# Regenerate the <CLIENT_PACKAGE> SDK from the committed OpenAPI snapshot.
# Refresh the snapshot first (scripts/refresh-<PRODUCER_NAME>-spec.sh) when
# picking up a producer-side change — this consumes the snapshot, not live.
# Idempotent; afterwards the CI drift gate is a no-op.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SDK_DIR="${REPO_ROOT}/clients/<PRODUCER_NAME>-python"
GEN_DIR="${SDK_DIR}/src/<CLIENT_PACKAGE>/generated"
SNAPSHOT="${SDK_DIR}/<PRODUCER_NAME>-openapi.json"
# When FILTER_SPEC=yes, filter the snapshot to the consumed surface first and
# generate from the filtered file:
#   uv run python "${REPO_ROOT}/scripts/filter_openapi_spec.py" \
#       "${SNAPSHOT}" "${SDK_DIR}/<PRODUCER_NAME>-openapi.filtered.json" \
#       --keep-prefix "<KEEP_PREFIX>"
#   SNAPSHOT="${SDK_DIR}/<PRODUCER_NAME>-openapi.filtered.json"

cd "${SDK_DIR}"
rm -rf "${GEN_DIR}"
uv run openapi-python-client generate \
    --path "${SNAPSHOT}" \
    --meta none \
    --output-path "${GEN_DIR}" \
    --overwrite

uv run ruff format "${GEN_DIR}" || true   # cosmetic; don't fail regen on format diffs
echo "Regenerated: ${GEN_DIR}"
```

## `generated-tree` (minimal-footprint alternative)

No package shell: spec + sidecar live under `vendor/<PRODUCER_NAME>/`, and the
generated tree lands inside the consumer's own source package. Fewer moving
parts, but the generator pin lives in the consumer's root dev dependency
group, and the generated tree needs explicit carve-outs at every tool that
walks `src/` (see [carve-outs.md](carve-outs.md)).

```
vendor/<PRODUCER_NAME>/
  openapi.json              # raw committed snapshot
  openapi.filtered.json     # when FILTER_SPEC=yes: filter output, the generator input
  openapi.meta.json         # provenance sidecar
src/<CONSUMER_PACKAGE>/shared/<PRODUCER_UNDERSCORE>_generated/   # never hand-edited
```

Pin the generator in the consumer root `pyproject.toml` dev group with the
same comment discipline as the SDK layout (`~=<GENERATOR_MINOR>`, bump =
explicit decision). Set the emitted package name via an
`openapi-python-client.yaml` config:

```yaml
package_name_override: <PRODUCER_UNDERSCORE>_generated
```

Regen command (Makefile target or script — match the repo's idiom):

```make
regenerate-<PRODUCER_NAME>-client:
	uv run python scripts/filter_openapi_spec.py \
		vendor/<PRODUCER_NAME>/openapi.json \
		vendor/<PRODUCER_NAME>/openapi.filtered.json \
		--keep-prefix "<KEEP_PREFIX>"
	uv run openapi-python-client generate \
		--path vendor/<PRODUCER_NAME>/openapi.filtered.json \
		--output-path src/<CONSUMER_PACKAGE>/shared/<PRODUCER_UNDERSCORE>_generated \
		--meta none \
		--overwrite \
		--config openapi-python-client.yaml
```

(When `FILTER_SPEC=no`, drop the filter step and generate from
`openapi.json` directly.)

## Canonicalization — one rule

Whatever transform sits between the fetched spec and the generator input
(pretty-print for the raw snapshot; the filter script for filtered flows)
must be byte-deterministic and identical across the refresh script, the regen
command, and every drift guard. The raw snapshot is canonicalized
order-preserving (NOT `sort_keys` — the generator emits model fields in spec
property order, so sorting reshapes the generated tree). The filter script's
output is `sort_keys` + 2-space indent, which is fine because it is applied
identically everywhere. Never mix canonicalizations between the local flow
and CI.
