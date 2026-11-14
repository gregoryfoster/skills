# Private index (`PRIVATE_INDEX=co-pypi`)

What `init-project-fastapi` emits when the project resolves cannobserv's packages (`co-core`, `co-core-aio`, `co-core-sync`, `cannobserv`) from the org's co-pypi Artifact Registry index. Skip this reference when `PRIVATE_INDEX=no` (the default).

This is cannobserv's `docs/RELEASING.md` § *Path C*, which says new consumers take it, in the shape CannObserv/broker reached in broker#144. The token wrapper is not copied from here: `deploying-releases` ships and installs it ([#632](https://github.com/gregoryfoster/skills/issues/632)), so every repo runs one marker-checked copy and an upgrade is a diff. It replaced the find-links wheelhouse, which no new repo takes.

**Sub-parameter:** `PRIVATE_DEPS` (required), the private requirement lines with floors, such as `co-core[extract]>=0.40,<0.41`. List every cannobserv package the project resolves, **transitive siblings included**: uv applies `[tool.uv.sources]` to direct dependencies only, so a sibling reached only transitively is looked up on PyPI and not found.

## (a) `pyproject.toml`: Phase 3

Splice `<PRIVATE_DEPS>` into `[project] dependencies`, then add:

```toml
[dependency-groups]
# scripts/co_pypi_token.py's own dependency, locked. scripts/co-pypi.sh runs it
# `--frozen --only-group co-pypi` before any private file is fetched, so nothing
# in the process that holds the key is resolved at run time (but the first
# `uv lock`, which resolves this pin from PyPI and says so).
co-pypi = ["google-auth[requests]>=2,<3"]

# cannobserv's packages come from its co-pypi index, and only they do
# (cannobserv docs/RELEASING.md, Path C). `explicit`: uv asks the index only for
# the names [tool.uv.sources] pins to it, so none comes from a PyPI namesake.
# The URL is the org registry's byte for byte, trailing slash included, so
# Dependabot's updater authenticates it. uv.lock records each file's sha256 and
# `uv sync --locked` refuses one that misses it. A `uv lock`, or a sync that
# downloads, needs the reader's token: `scripts/co-pypi.sh uv ...`.
[[tool.uv.index]]
name = "co-pypi"
url = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/simple/"
explicit = true

[tool.uv.sources]
co-core = { index = "co-pypi" }     # one line per name in <PRIVATE_DEPS>
```

If the project has a `dev` group, the `co-pypi` group stays separate: the wrapper needs it alone, from public PyPI. Append `"scripts/co_pypi_token.py"` to `[tool.ruff] extend-exclude`, since pre-commit's `ruff --fix` and `ruff-format` would otherwise edit the installed minter and break its marker.

## (b) The wrapper: Phase 3b

```bash
bash "<SKILL_DIR>/../deploying-releases/scripts/install.sh" --co-pypi
```

This writes `scripts/co-pypi.sh` and `scripts/co_pypi_token.py`, both marked, and `tests/test_co_pypi.py`, which pins the rules in (a) and the markers. It warns about a missing `co-pypi` group or ruff exclude.

**The key:** the `co-pypi-reader` service account's JSON key (`roles/artifactregistry.reader` on co-pypi alone), at `/etc/<PROJECT_NAME>/co-pypi-reader.json`, `root:<deploy user> 640`. `CO_PYPI_KEY` overrides the path. Under `LAYOUT=workspace` the root has no `[project].name`, so `CO_PYPI_KEY` is required, in the developer's shell and the deploy user's environment. It's never `GOOGLE_APPLICATION_CREDENTIALS`, which would hand an identity to every Google client in the shell, and it never sits in the repo or a `.env`.

Emit the dev recipe into the README's Setup block and AGENTS.md's Common Commands, **regardless of `DEPLOY_TARGET`**:

```bash
scripts/co-pypi.sh uv sync --locked      # first sync, and after a private bump
scripts/co-pypi.sh uv lock               # any change to the pins
```

Only a command that downloads from the index needs the wrapper. Once the private files are installed or cached, a plain `uv sync` or `uv run` works, and `uv lock --locked` never needs it.

## (c) The deploy: Phase 7b

Under `DEPLOY_TARGET=releases`, the hooks set `UV_WRAPPER=scripts/co-pypi.sh`, and the core's build is the only runtime caller. No unit syncs anything, and there is no `ExecStartPre` sync.

## (d) CI: Phase 7c

This is a delta on [`github-ci.md`](github-ci.md)'s workflow for **every** job that runs `uv sync`: `lint` and `test`, or `gate` and `test` under `GITHUB_CI=pre-commit`. broker, processor, watcher, observo and replicator all mint this way, as the same identity:

```yaml
    # at job level:
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          # Unpruned, the saved cache holds the private wheels unpacked, in a
          # cache a fork's PR can restore.
          prune-cache: true

      # Fail legibly when the org variable isn't visible to this repo: the auth
      # action's own error reads like a workflow bug and sends you to GCP IAM.
      - name: Assert WIF is configured
        env:
          WIF_PROVIDER: ${{ vars.GCP_WIF_PROVIDER }}
        run: |
          if [ -z "$WIF_PROVIDER" ]; then
            echo "::error::vars.GCP_WIF_PROVIDER is not visible to this repo: grant it under Org Settings > Variables > GCP_WIF_PROVIDER > Repository access."
            exit 1
          fi

      - name: Authenticate to Google Cloud (WIF, read-only)
        id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: co-pypi-reader@co-gcs.iam.gserviceaccount.com
          token_format: access_token

      # The pair on this step alone: later `uv run`s find the venv synced.
      # A masked output; never echo it.
      - name: uv sync
        env:
          UV_INDEX_CO_PYPI_USERNAME: oauth2accesstoken
          UV_INDEX_CO_PYPI_PASSWORD: ${{ steps.auth.outputs.access_token }}
        run: uv sync
```

CI doesn't run the wrapper: the workflow has no key, and WIF mints the same reader's token.

## (e) Verify: Phase 12

`uv lock` can't resolve a private name without the token, so probe for a **readable** key first, not a set variable:

```bash
KEY="${CO_PYPI_KEY:-/etc/<PROJECT_NAME>/co-pypi-reader.json}"
if [ -r "$KEY" ]; then
  scripts/co-pypi.sh uv lock && scripts/co-pypi.sh uv sync --locked
  # then the "Always run" block; its plain `uv sync` downloads nothing more
else
  echo "co-pypi reader key not readable at $KEY: skipping the lock, the sync and every check that needs them"
fi
```

With the lock skipped the repo *looks* complete but can't be installed, so Phase 15's follow-up is mandatory.

## (f) Follow-ups: Phase 15

Add these to `## Follow-ups`:

1. If Phase 12 skipped the lock: "`uv.lock` was never written. Run `scripts/co-pypi.sh uv lock` with the reader key before the first feature PR."
2. Unless `GITHUB_CI=no`: "Add this repo to the `GCP_WIF_PROVIDER` org variable's repository access, and have the provider's attribute condition admit it." A new repo inherits neither, and CI's auth fails until both are done.
3. On each host that deploys or develops: "Install the `co-pypi-reader` key at `/etc/<PROJECT_NAME>/co-pypi-reader.json`, `root:<deploy user> 640`."
4. If the repo adopts Dependabot (`adopting-dependabot`): "An org owner admits the repo to the org's co-pypi registry before its `dependabot.yml` change merges (cannobserv `docs/DEPENDABOT.md` § Onboarding a consumer)."

## Invariants

- **One explicit index, every private name sourced and declared directly**, with the URL byte for byte. `tests/test_co_pypi.py` holds all three.
- **The lock carries each private file's sha256, as a wheel.** `uv sync --locked` holds every download to it, so the lock replaces the wheelhouse's filename-only pin and any hand-kept digest table. A wheel, not an sdist: `prune-cache` keeps wheels built from source.
- **The token goes to one `uv`, never to a file, argv or a log.** The wrapper starts from an env allowlist, so a loaded `.env`'s PATs never reach uv. Whatever that uv spawns inherits the pair (the build backend). The bound is the identity's read-only role and the token's hour.
- **The installed pair is never edited.** A change is raised on gregoryfoster/skills and arrives through `install.sh --co-pypi`.
