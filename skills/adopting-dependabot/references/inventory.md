# Inventory: phases 1–3

What to read before writing a line of config, and the disposition each finding
gets. `inventory.sh` reads phases 1 and 2. Phase 3 is a test you add.

## Phase 1: CI's credential surface

A Dependabot-triggered run gets **only Dependabot secrets** (a separate store
from Actions secrets) and a **read-only `GITHUB_TOKEN`**. Read every workflow
that gates `pull_request`, job by job (`workflows[].jobs[]`):

| `needs` | What it means on a Dependabot PR |
|---|---|
| `nothing` | Passes regardless. watcher's `css` job was one |
| `secret` | Fails unless the secret is also stored as a **Dependabot** secret. A step that needs it only to publish should be skipped on `github.actor == 'dependabot[bot]'`, not fed the secret |
| `oidc` | Depends on GitHub granting the OIDC token to the run. Not spelled out in GitHub's docs: [credential-context.md](credential-context.md) |

Also read `vars` (whether `vars.` resolves on a Dependabot run is stated
nowhere either; on watcher, 2026-10-09, it did), `write_permissions` (a
job that pushes, comments or labels fails on the read-only token), and
`private_index_steps` (a step that syncs or points at an index).

## Phase 2: what the bot can and can't move

Each item gets one disposition: **bot**, **bot with ignore**, **manual (say
why)** or **blocked → issue**. Write them in the issue or plan; the config's
comments and the guard test's `HELD_BACK` and `IGNORED` carry them after.

| Finding (`inventory.sh` key) | Usual disposition | Why |
|---|---|---|
| `ecosystems` | bot, one ecosystem at a time | `github-actions` first: it resolves nothing |
| `private_indexes` with `local: true`, or a `find-links` / index the updater can't reach | **blocked → issue** | The updater resolves in its own container, with no sync script and no credentials, so every run fails. `ignore:` doesn't help: resolution still needs the package. watcher's wheelhouse synced from GCS (watcher#283 blocker 2 → watcher#358) |
| `pinned_sources` (git, path, url) | manual | `tool.uv.sources` git tags aren't bumped at all. Say so in the config's comment, or a quiet bot looks like full coverage |
| `exact_pins` that move in lockstep with another repo | bot with ignore | e.g. a shared library's pins that move when a contract changes. `IGNORED` in the guard test holds each |
| `workflows[].generated` | bot, then guard the generator | Dependabot bumps `uses:` in a generated file too. The next re-render quietly downgrades it ([merge-paths.md](merge-paths.md#generated-workflows)) |
| `workflows[].scheduled_only` | bot, then dispatch once | A bump there runs in no PR's CI ([first-batch.md](first-batch.md)) |
| `runner_labels[].floating` | manual | `ubuntu-latest` moves on GitHub's schedule. No Dependabot config covers it. It's the same CI surface |

### Pin forms against upstream's tag scheme

`inventory.sh --upstream` reads each action's tags with `git ls-remote` and
gives every `uses:` ref a `status`:

- **`frozen`**: a major-form pin (`@v5`) whose upstream stopped floating
  major tags. Dependabot proposes refs **in the pin's own form**, so it stops
  at the last floating major and never says it's behind. `astral-sh/setup-uv`
  stopped at `v7` when it moved to immutable `vX.Y.Z` tags from v8 on; watcher's
  `@v5` went to `@v7` and stopped, while the current release was v10.2.0
  (watcher#360, 2026-10-09).
- `behind`, `current`, `missing` (no such tag upstream), `mismatch` (a SHA
  whose `# vX.Y.Z` comment names another commit), `branch` or `unpinned` (no
  version to compare, and nothing for Dependabot to propose: pin a tag or a
  SHA), `unknown`, `unread`.

A `frozen` action moves to an immutable tag or to a SHA with its version
comment, `@<sha> # vX.Y.Z`, which Dependabot updates both halves of. SHA-pinning
**every** action is what tj-actions-style tag re-pointing argues for, and what
setup-uv's own change recommends. It's a policy decision for the repo, or the
cohort; the guard test's `SHA_PINS` enforces it once made.

## Phase 3: stale declarations

Before turning on a package ecosystem, sweep for runtime declarations nothing
imports. Each would get bump PRs for a package nobody chooses, and keeps a cap
in force that means nothing. watcher found 8 of 26 (watcher `93aa3f8`).

Copy [assets/test_dependency_imports.py](../assets/test_dependency_imports.py)
to `tests/ci/`, set `SOURCE_DIRS`, and run it **test-first**: it fails, naming
each stale declaration. For each one, either drop it, or add it to
`NEEDED_WITHOUT_IMPORT` with a **witness**: a glob and the text that reaches
the package by name. The test checks the witness still exists, so the entry
can't outlive its reason:

| Reached by name | Witness |
|---|---|
| a database driver named in a URL scheme | `src/**/*.py` contains `postgresql+asyncpg` |
| a server a unit file runs | `deploy/*.service` contains `uvicorn ` |
| a parser a framework loads | `src/**/*.py` contains `Form(` (python-multipart) |

The sweep resolves each import by its longest dotted prefix, so a namespace
like `google` doesn't let one declared distribution pass the rest. It needs the
environment synced from the lockfile.
