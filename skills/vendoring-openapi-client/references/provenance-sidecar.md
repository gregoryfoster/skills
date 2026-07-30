# Provenance sidecar — schema and refresh script

The committed OpenAPI snapshot is the contract-of-record the client is
generated from. The sidecar (`<SPEC_DIR>/openapi.meta.json`, committed beside
the snapshot) records where the snapshot came from and what produced the
generated tree, so refresh mode and drift guards are deterministic.

## Path conventions (per layout)

Two placeholders name the vendored files; substitute both consistently across
the refresh script, the regen command, and every drift guard:

| Placeholder | `sdk-package` (default) | `generated-tree` |
|---|---|---|
| `<SPEC_DIR>` (holds snapshot + sidecar) | `clients/<PRODUCER_NAME>-python` | `vendor/<PRODUCER_NAME>` |
| `<SNAPSHOT_PATH>` (raw committed snapshot) | `<SPEC_DIR>/<PRODUCER_NAME>-openapi.json` | `<SPEC_DIR>/openapi.json` |

The sidecar is always `<SPEC_DIR>/openapi.meta.json`. The snapshot filename
differs by layout because a `generated-tree` `vendor/<PRODUCER_NAME>/` dir is
already producer-scoped by its parent, whereas an `sdk-package` snapshot sits
in the SDK root alongside other files and needs the producer prefix to read
unambiguously — this matches the drift checker's `spec_path`
(`<PRODUCER_NAME>-openapi.json`) and the `regen.sh` `SNAPSHOT` variable.

Filtered spec (when `FILTER_SPEC=yes`) — the two layouts differ on purpose:

- `generated-tree` **commits** it as `openapi.filtered.json` beside the raw
  snapshot; the `make` target rewrites it and the CI `git diff` covers both it
  and the tree, so raw→filtered is gated by the diff.
- `sdk-package` **does not commit** it. Both `regen.sh` and
  `check_client_drift.py` re-filter the raw snapshot transiently (`mktemp` /
  in-tmp) and generate from that, so the raw snapshot is the sole committed
  spec. A committed filtered file here would be an unguarded second source the
  tree-diffing checker never validates — and could let `regen.sh` (remediation)
  and the checker (detection) filter from different bytes.

## Schema

```json
{
  "producer": "<PRODUCER_NAME>",
  "source_url": "https://<producer-host>/openapi.json",
  "captured_at": "2026-07-30T14:00:00Z",
  "sha256": "<sha256 of the committed snapshot bytes>",
  "openapi_version": "3.1.0",
  "spec_info_version": "0.4.2",
  "generator": "openapi-python-client==<exact version from the SDK lockfile>",
  "filter": { "keep_prefix": "/api/v1/" }
}
```

Field notes:

- `source_url` — the endpoint the snapshot was fetched from. When the spec was
  copied from a local producer checkout instead, use `source_path` plus
  `source_commit` (the producer repo commit SHA) instead of `source_url`.
- `sha256` — hash of the committed **raw snapshot** bytes, recomputed on every
  refresh. A sidecar whose hash doesn't match the committed snapshot means the
  snapshot was hand-edited after capture — treat as an error.
- `generator` — informational record of the generator version used at capture.
  The *authoritative* pin lives in the SDK's `pyproject.toml` + lockfile (see
  the layout docs); CI regenerates with that pin, never with this string.
- `filter` — `null` when the spec is consumed unfiltered; otherwise the exact
  arguments passed to `filter_openapi_spec.py`, so a refresh re-filters
  identically.

## Refresh script template

Write to `scripts/refresh-<PRODUCER_NAME>-spec.sh` in the consumer repo,
substituting `<PLACEHOLDERS>`. One command refreshes snapshot + sidecar in
lockstep so the sidecar can never drift from the snapshot (stale
`captured_at`, mismatched `sha256`).

```bash
#!/usr/bin/env bash
# Refresh the vendored <PRODUCER_NAME> OpenAPI snapshot + meta sidecar.
# Usage: scripts/refresh-<PRODUCER_NAME>-spec.sh   # then run the regen command
set -euo pipefail

# Run from the repo root regardless of invocation directory — the vendored
# paths below are relative.
cd "$(git rev-parse --show-toplevel)"

: "${<PRODUCER_BASE_URL_ENV>:?set <PRODUCER_BASE_URL_ENV> to the producer base URL}"
SPEC_URL="${<PRODUCER_BASE_URL_ENV>%/}/openapi.json"
SPEC_PATH="<SNAPSHOT_PATH>"          # see Path conventions above (differs by layout)
META_PATH="<SPEC_DIR>/openapi.meta.json"

mkdir -p "$(dirname "$SPEC_PATH")"

echo "Fetching ${SPEC_URL} ..."
curl --fail --silent --show-error --max-time 30 "${SPEC_URL}" > /tmp/spec-raw.$$.json

# Canonicalize into the committed snapshot: pretty-print, order-preserving.
# NOT sort_keys — openapi-python-client emits model fields in spec property
# order, so sorting would reshape (not just reformat) the generated tree.
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); open(sys.argv[2],'w').write(json.dumps(d, indent=2)+'\n')" \
    /tmp/spec-raw.$$.json "${SPEC_PATH}"
rm -f /tmp/spec-raw.$$.json

CAPTURED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# python3 (not sha256sum) for the hash — sha256sum is GNU coreutils, missing
# on macOS; one interpreter emits hash + sidecar together.
python3 - "${SPEC_PATH}" "${SPEC_URL}" "${CAPTURED_AT}" > "${META_PATH}" <<'PY'
import hashlib, json, pathlib, sys

spec_path, source_url, captured_at = sys.argv[1:4]
content = pathlib.Path(spec_path).read_bytes()
spec = json.loads(content)
meta = {
    "producer": "<PRODUCER_NAME>",
    "source_url": source_url,
    "captured_at": captured_at,
    "sha256": hashlib.sha256(content).hexdigest(),
    "openapi_version": spec.get("openapi"),
    "spec_info_version": spec.get("info", {}).get("version"),
    "generator": "openapi-python-client==<GENERATOR_VERSION>",
    "filter": <FILTER_JSON>,
}
print(json.dumps(meta, indent=2))
PY

echo "Wrote ${SPEC_PATH} and ${META_PATH}"
echo "Next: run the regen command (see the vendored client's README)"
```

Substitutions: `<FILTER_JSON>` is `None` when `FILTER_SPEC=no`, else
`{"keep_prefix": "<KEEP_PREFIX>"}` (Python literal — this heredoc is Python).
`<GENERATOR_VERSION>` is the exact version from the SDK lockfile at wiring
time; update it when the pin is bumped.

For an auth-gated spec endpoint, add the producer's API-key header to the
`curl` call (e.g. `-H "X-API-Key: ${<PRODUCER_API_KEY_ENV>}"`) — never inline
the key.
