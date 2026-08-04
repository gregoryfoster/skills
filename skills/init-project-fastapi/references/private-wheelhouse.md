# Private wheelhouse (`PRIVATE_WHEELHOUSE=find-links`)

Templates for the `init-project-fastapi` skill's private-wheelhouse branch point. Skip this entire reference when `PRIVATE_WHEELHOUSE=no` (the default) — nothing here is emitted and a PyPI-only project renders identically to the base scaffold.

Some CannObserv services resolve their shared libraries (`co-core`, `co-core-aio`) not from PyPI but from a **private package index published to GCS and mirrored into a local `./.wheelhouse`**, wired into uv via `[tool.uv] find-links`. This reference holds the sync script verbatim, the five call sites, and the invariants. Provenance: contributed from `CannObserv/replicator`'s working copy (bootstrapped from `gregoryfoster/skills@37226fb`), generalized to skill placeholders — see [#71](https://github.com/gregoryfoster/skills/issues/71).

**Placeholder legend** (substitute like `<PROJECT_NAME>` elsewhere in the skill):

| Placeholder | Source | Example |
|---|---|---|
| `<WHEELHOUSE_BUCKET>` | sub-parameter | `co-pypi-index` (no `gs://`) |
| `<WHEELHOUSE_PREFIX>` | sub-parameter (default `wheels/`) | `wheels/` (trailing slash required) |
| `<WHEELHOUSE_SA>` | sub-parameter (required only when `GITHUB_CI=yes`) | `co-pypi-reader@<project>.iam.gserviceaccount.com` |
| `<WHEELHOUSE_PACKAGES>` | sub-parameter — the **import lines** for the Phase 12 smoke, not dist names | see (e) below |
| `<PROJECT_UNDERSCORE_UPPER>` | derived (Phase 4) — the project's env-var prefix | `USA_WA` |
| `<PRIVATE_PACKAGE>` | project-supplied private dependency + floor | `co-core[extract]>=0.7,<0.8` |

The script's bucket/prefix env overrides are **namespaced with `<PROJECT_UNDERSCORE_UPPER>`** (e.g. `USA_WA_WHEELHOUSE_BUCKET`) so co-located services on a shared VM cannot collide — reuse the project's existing env prefix rather than inventing a new one. `GCP_WIF_PROVIDER` (CI, gap 1) is a GitHub **org variable**, identical for every repo in the org — it is a prerequisite, not a skill parameter.

---

## `scripts/sync_wheelhouse.py`

Copy verbatim into the project (substituting the two literal fallbacks, the `<PROJECT_UNDERSCORE_UPPER>` env prefix, and `<PROJECT_NAME>` in the docstring). Three properties are load-bearing and must survive any refactor: the **same-size skip** (makes re-runs free, so it is safe as an `ExecStartPre` on every start), the **temp-file + `os.replace`** (an interrupted run never leaves a partial wheel that the size check would then accept forever), and the **broad `except`** (auth, network, and missing-bucket all degrade to the same non-fatal outcome the unit's `-` prefix depends on).

```python
"""Mirror the private package index into the local wheelhouse.

Downloads every object under ``gs://<WHEELHOUSE_BUCKET>/<WHEELHOUSE_PREFIX>``
into ``./.wheelhouse`` (repo root), skipping any file already present with a
matching size. ``uv`` then resolves the private packages from that directory via
the ``[tool.uv] find-links`` entry in ``pyproject.toml``.

Runs standalone, *before* ``uv sync`` — it must not import the project (whose
deps are what the wheelhouse provides), so invoke it in an isolated env:

    uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py

Authentication is Application Default Credentials. On the VM/deploy that is the
service-account key at ``GOOGLE_APPLICATION_CREDENTIALS`` (set in
``/etc/<PROJECT_NAME>/.env``); in CI it is the ADC file written by
``google-github-actions/auth`` (keyless Workload Identity Federation). Either
way the identity needs only ``roles/storage.objectViewer`` on the bucket.

Exit codes: ``0`` success (including a no-op re-run) · ``1`` failure (auth,
network, or a missing bucket). The unit runs this as a non-fatal
``ExecStartPre`` (``-`` prefix): a transient failure is surfaced to the journal,
and if the wheelhouse is already populated the service still starts — only a
genuinely missing wheel surfaces later as a hard ``uv`` resolution error.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# google-cloud-storage is deliberately NOT a project dependency: this script
# runs standalone before `uv sync`, so it must not import anything the
# wheelhouse is what provides. It is supplied at invocation via `uv run --with`.
# Static analysis cannot resolve it — that is expected, not a missing dependency.
from google.cloud import storage  # ty: ignore[unresolved-import]

BUCKET = os.environ.get("<PROJECT_UNDERSCORE_UPPER>_WHEELHOUSE_BUCKET", "<WHEELHOUSE_BUCKET>")
PREFIX = os.environ.get("<PROJECT_UNDERSCORE_UPPER>_WHEELHOUSE_PREFIX", "<WHEELHOUSE_PREFIX>")
DEST = Path(__file__).resolve().parent.parent / ".wheelhouse"


def sync() -> int:
    """Mirror ``gs://{BUCKET}/{PREFIX}`` into ``DEST``; return an exit code."""
    DEST.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = 0
    try:
        client = storage.Client()
        for blob in client.list_blobs(BUCKET, prefix=PREFIX):
            name = blob.name.removeprefix(PREFIX)
            if not name:  # the prefix "directory" placeholder object, if any
                continue
            target = DEST / name
            # Skip when a same-size file is already present. Published artifacts
            # are server-side immutable, so name + size is sufficient; no need
            # to fetch and compare the crc32c.
            if target.exists() and target.stat().st_size == blob.size:
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Download to a sibling temp file then atomically rename, so an
            # interrupted run never leaves a partial wheel in place (which a
            # concurrent reader, or a same-size coincidence, could mistake for
            # a complete one). os.replace is atomic within the same directory.
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part")
            os.close(fd)
            try:
                blob.download_to_filename(tmp)
                os.replace(tmp, target)
            finally:
                Path(tmp).unlink(missing_ok=True)
            downloaded += 1
    except Exception as exc:  # broad by design: auth/network/bucket failures degrade identically
        print(f"error: could not sync gs://{BUCKET}/{PREFIX}: {exc}", file=sys.stderr)
        return 1

    print(f"wheelhouse in sync: {downloaded} downloaded, {skipped} already present -> {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(sync())
```

---

## The five call sites

### (a) `pyproject.toml` — Phase 3

Splice the private package(s) into `dependencies` with plain version floors, and add the `find-links` entry. **No hashes** — `find-links` locks by filename, not hash.

```toml
dependencies = [
    "<PRIVATE_PACKAGE>",
    # ... PyPI deps unchanged
]

# Workspace packages resolve from the local wheelhouse, mirrored from the
# private GCS index gs://<WHEELHOUSE_BUCKET> by scripts/sync_wheelhouse.py
# before `uv sync`/`uv run`. Plain version floors above + find-links here; no
# hashes, because find-links locks by filename.
[tool.uv]
find-links = ["./.wheelhouse"]
```

### (b) `.gitignore` — Phase 3

Track the directory (so a fresh clone can resolve `find-links` before the first sync) but never the wheels. **Use `.wheelhouse/*`, not `.wheelhouse/`** — git cannot re-include a file whose parent directory is excluded, so a directory-level ignore makes the `!` negation a no-op and leaves `.gitkeep` untracked (issue #71 Part 2; sibling repos CannObserv/archiver#116, CannObserv/watcher#239).

```gitignore
# Private package index mirror — populated by scripts/sync_wheelhouse.py from
# the private GCS index (gs://<WHEELHOUSE_BUCKET>). Wheels are never committed;
# the directory itself is tracked so `[tool.uv] find-links = ["./.wheelhouse"]`
# resolves on a fresh clone before the first sync.
# NB: `.wheelhouse/*`, not `.wheelhouse/` — git cannot re-include a file whose
# parent directory is excluded, so a directory-level ignore would make the
# negation below a no-op and leave .gitkeep untracked.
.wheelhouse/*
!.wheelhouse/.gitkeep
```

The `.gitkeep` is load-bearing, not cosmetic: `uv` errors on a `find-links` path that does not exist, so a fresh clone that has not synced yet cannot even run `uv sync` without it. Phase 3b creates it.

### (c) systemd unit — Phase 7b (only when `DEPLOY_TARGET=systemd`)

Add a **non-fatal** `ExecStartPre` sync, placed just **before** the existing `ExecStart` line in [`systemd-deploy.md`](systemd-deploy.md) (which keeps its `--frozen --no-sync uvicorn …` form unchanged):

```ini
# Refresh the wheelhouse. Non-fatal ('-' prefix): a transient GCS failure is
# surfaced to the journal, and an already-populated wheelhouse still starts.
# Only a genuinely missing wheel surfaces as a hard uv resolution error.
ExecStartPre=-/usr/local/bin/uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

This line writes **plain text** to journald on every service start — `wheelhouse in sync: N downloaded, M already present -> …` on the happy path, and `error: could not sync gs://…` on the non-fatal failure path (stderr, which journald captures the same way) — and that is deliberate — it is the one documented exception to the JSON-only log stream `--log-config` establishes (skills#81, skills#83). The script runs `--no-project` in an ephemeral environment holding `google-cloud-storage` and nothing else, *before* `uv sync`, so importing `src.core.logging` is structurally impossible; emitting JSON would mean a second, hand-maintained copy of the `{level, logger, message, timestamp}` schema in a file that cannot share `build_json_formatter()` — the exact drift skills#81/#82 exist to prevent, spent on one boot line. Scope matters too: this is deploy-step output, not the application's log stream. A shipper reading journald natively is unaffected (the entry still carries `_SYSTEMD_UNIT`, `_PID`, `SYSLOG_IDENTIFIER`); the pipeline that trips is one that `json.loads` every `MESSAGE`.

Two systemd traps: `uv` needs an **absolute path** (`ExecStartPre` does no `PATH` lookup without a shell), and the script path is **relative**, resolved against `WorkingDirectory=`. `GOOGLE_APPLICATION_CREDENTIALS` must come from an `EnvironmentFile=` that precedes this line — it already does, since `/etc/<PROJECT_NAME>/.env` is loaded before `ExecStart*`. The unit's `ExecStartPre` sync refreshes for the *next* deploy; it is **not** a substitute for the deploy-time `uv sync --frozen` (that is why it can be `-` prefixed — see Invariants).

### (d) CI — Phase 7c (only when `GITHUB_CI=yes AND PRIVATE_WHEELHOUSE=find-links`)

The WIF block is **CI-only**: when `GITHUB_CI=no`, nothing here applies and the wheelhouse is exercised solely by 3b (local dev) + 7b (VM). This is a **delta** on the base workflow in [`github-ci.md`](github-ci.md) — keep that file's step versions (`actions/checkout@v4`, `astral-sh/setup-uv@v5`, `uv sync --frozen`) and add only the pieces below to **every** job that runs `uv sync` (both lint and test): the job-level `permissions` block, and the three steps inserted **between `setup-uv` and `uv sync --frozen`** (the ordering from Invariants: `auth → sync → uv sync`).

```yaml
    # add at job level:
    permissions:
      contents: read
      id-token: write
    steps:
      # ... existing checkout + setup-uv steps unchanged ...

      # Fail fast and legibly when the org variable is not visible to this repo.
      # google-github-actions/auth validates its own inputs before contacting
      # Google, so an empty provider surfaces as "must specify exactly one of
      # workload_identity_provider or credentials_json" — which reads like a
      # workflow-authoring bug and sends you to GCP IAM, where the problem is
      # not. Assert the precondition here instead.
      - name: Assert wheelhouse auth is configured
        env:
          WIF_PROVIDER: ${{ vars.GCP_WIF_PROVIDER }}
        run: |
          if [ -z "$WIF_PROVIDER" ]; then
            echo "::error::vars.GCP_WIF_PROVIDER is empty for this repo. GCP is not the problem — the org variable is not visible here. Fix under Org Settings > Secrets and variables > Actions > Variables > GCP_WIF_PROVIDER > Repository access."
            exit 1
          fi
          echo "WIF provider: $WIF_PROVIDER"

      - name: Authenticate to Google Cloud (WIF, read-only)
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: <WHEELHOUSE_SA>

      - name: Sync wheelhouse
        run: uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py

      # ... then the base workflow's `uv sync --frozen` and the rest, unchanged ...
```

The assert step earned its place: a new repo does **not** inherit org variables until it is added to that variable's repository-access list, and the native failure misdirects to GCP IAM. Phase 16 carries the matching checklist line ("add the new repo to `GCP_WIF_PROVIDER`'s repository access").

### (e) Import smoke — Phase 12

Resolution is not the contract; **import** is. Extras in particular resolve fine and then fail to import when the extra was not actually requested. `<WHEELHOUSE_PACKAGES>` is the set of **import lines** exercising those extras, not distribution names:

```yaml
      - name: <PRIVATE_PACKAGE> import smoke (extras wired)
        run: |
          uv run python -c "
          <WHEELHOUSE_PACKAGES>
          print('extras OK')
          "
```

Example `<WHEELHOUSE_PACKAGES>` (replicator's `co-core[extract]` / `co-core-aio[bus]`):

```python
from co_core.pure.util.hashing import sha256
from co_core.pure.extract import simhash
from co_core_aio.bus import AsyncBusConsumer, AsyncBusPublisher
```

### Phase 12 bootstrap recipe (populate → verify, or graceful-skip)

`uv sync` cannot resolve `find-links` from an empty `./.wheelhouse`, so the wheelhouse must be populated first — which needs readable ADC (a laptop bootstrap often lacks it). Probe for a **readable key file**, not merely a set variable: a stale path inherited from a sibling project's `.env` is the failure mode, and it surfaces later as a confusing `DefaultCredentialsError`.

```bash
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -r "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
  # then the Phase 12 "Always run" block (uv sync, …), then the import smoke:
  uv run python -c "
<WHEELHOUSE_PACKAGES>
print('extras OK')
"
else
  echo "ADC not readable — skipping wheelhouse-dependent verify (uv sync, import smoke)"
  # Record the follow-up in the GH issue (Phase 15):
  #   "wheelhouse never populated at bootstrap; uv sync will fail until
  #    sync_wheelhouse.py runs with ADC — do so before the first feature PR."
fi
```

With a skipped sync the repo *looks* complete but is not installable, so the GH-issue note is **mandatory**, not optional.

---

## Invariants

- **Ordering: `auth → sync_wheelhouse.py → uv sync --frozen`.** `uv.lock` records a `find-links` wheel by filename and version, with **no hash**. The lock is only satisfiable if a wheel of that exact filename is already present in `./.wheelhouse` when `uv sync --frozen` runs; syncing the wheelhouse *after* `uv sync` is a hard resolution error, not a slow path. This holds identically on the VM (`sync_wheelhouse.py` → `uv sync --frozen` as a **deploy step**, with `ExecStart` using `--frozen --no-sync` so service start never resolves deps) and in CI.
- **Never re-publish a wheel filename; bump the version.** Because the lock carries no hash, it does not pin *contents*. The same-size skip in `sync_wheelhouse.py` is safe only against an immutable publish policy — the bucket must never overwrite a published filename.
- **The `setup-uv` cache (if the base workflow enables it) does not rescue a mis-ordered sync.** It caches the resolved environment keyed on the lockfile, not the wheelhouse — so enabling it is orthogonal to the ordering above, never a substitute for syncing the wheelhouse first.
- **Secrets are referenced by path, never committed.** `GOOGLE_APPLICATION_CREDENTIALS` points at the SA key; the key itself is never committed, never inlined into a unit file or workflow. On the VM it lives beside the production env file (e.g. `/etc/<PROJECT_NAME>/co-pypi-reader.json`, mode `0400`, owned by the service user) — **outside** the repo, so a repo reset or worktree switch cannot strand or expose it. CI is keyless (WIF only; no `credentials_json`, no long-lived key in Actions secrets). The SA holds `roles/storage.objectViewer` on the one bucket and nothing else; publishing is a different identity, out of scope here. Deliberately **no blanket `*.json` `.gitignore` guard** — it would wrongly untrack legitimate config (`package.json`, `tsconfig.json`, …); the guarantee is key-outside-the-repo, not a catch-all ignore. If a project must keep the key in-tree, ignore its *specific* filename, not `*.json`.

## Prerequisites (surface to the user when enabling)

- A GCS bucket (`<WHEELHOUSE_BUCKET>`) holding the published wheels under `<WHEELHOUSE_PREFIX>`, with an immutable-filename publish policy.
- A `roles/storage.objectViewer` service account: a JSON key on the VM at `GOOGLE_APPLICATION_CREDENTIALS`; keyless WIF in CI.
- When `GITHUB_CI=yes`: the org variable `GCP_WIF_PROVIDER`, and the new repo added to its repository-access list (Phase 16 checklist).
