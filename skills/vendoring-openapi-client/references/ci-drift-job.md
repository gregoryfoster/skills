# CI drift gate — regenerate-from-snapshot and diff

The hermetic, PR-blocking gate: regenerate the client from the committed
snapshot into a temp dir and fail on any diff vs the committed generated
tree. It catches the two local failure modes — a hand-edited `generated/`
tree, and a refreshed snapshot committed without regenerating — and its
remediation output tells the developer which fix applies.

What it can NOT catch: the snapshot itself going stale vs the live producer
(a skipped refresh leaves snapshot and tree *consistently* stale, and this
gate passes). That gap is the live-drift guard's job — see
[live-drift.md](live-drift.md).

## `sdk-package` layout

Copy `assets/check_client_drift.py` into the consumer repo as
`scripts/check_client_drift.py` and fill in its `CLIENTS` registry (one entry
per vendored SDK). The script regenerates inside each SDK's own `uv`
environment, so the generator + ruff versions come from that SDK's lockfile —
byte-stable across machines. It also serves as the local remediation tool
(`--write` regenerates the committed tree from the snapshot in place).

For a filtered SDK (`FILTER_SPEC=yes`), set `filter_keep_prefix` on its
`Client` entry and point `spec_path` at the committed **raw** snapshot: the
checker then filters raw → surface before generating (via the Phase 2
`scripts/filter_openapi_spec.py`), so the one gate proves the whole
raw → filtered → tree chain — a stale filtered spec or a changed keep-prefix
is caught, matching the generated-tree layout's coverage.

Add a job to the consumer's CI workflow:

```yaml
  client-drift:
    name: client-drift
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install Python
        run: uv python install 3.12

      # Regenerate each vendored client from its committed OpenAPI snapshot
      # and fail on any diff vs the committed generated/ tree — turns a stale
      # client into a red build. Stdlib-only driver (--no-project skips the
      # root sync); the per-SDK regen syncs that SDK's own lockfile, pinning
      # its openapi-python-client + ruff versions.
      - name: detect generated-client drift vs committed OpenAPI snapshot
        run: uv run --no-project --python 3.12 python scripts/check_client_drift.py
```

## `generated-tree` layout

Same principle, simpler mechanics: run the repo's regen command against the
committed snapshot and `git diff --exit-code` the generated tree.

```yaml
  client-drift:
    name: client-drift
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          python-version: "3.12"
      - run: uv sync --frozen --group dev   # dev group carries the pinned generator
      - name: regenerate from committed snapshot and diff
        # Diff the generated tree, plus — only when FILTER_SPEC=yes — the
        # committed filtered spec the regen target rewrites. For the default
        # (FILTER_SPEC=no) there is no filtered file; diff the raw snapshot the
        # target reads instead. Use ONE pathspec set, matching FILTER_SPEC.
        run: |
          make regenerate-<PRODUCER_NAME>-client
          # FILTER_SPEC=no (default):
          git diff --exit-code -- \
            src/<CONSUMER_PACKAGE>/shared/<PRODUCER_UNDERSCORE>_generated \
            vendor/<PRODUCER_NAME>/openapi.json
          # FILTER_SPEC=yes — replace the pathspec above with:
          #   src/<CONSUMER_PACKAGE>/shared/<PRODUCER_UNDERSCORE>_generated \
          #   vendor/<PRODUCER_NAME>/openapi.filtered.json
```

`--frozen` matters: it resolves the generator to the exact locked version, so
the regen in CI is byte-identical to the regen that produced the committed
tree.

## Producer-in-same-repo bonus check

When the consumer repo also *hosts* a service whose own spec is vendored by
others (or by itself), add an offline freshness test to the main suite:
re-derive the canonical spec from the app (`app.openapi()`), canonicalize
identically to the refresh script, and diff against the committed snapshot.
That closes the snapshot-staleness gap without any network dependency — no
live-drift guard needed for that client.
