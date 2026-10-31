# Gate topology

Why `pre-ship.sh` runs what it runs, and which stage owns each check. The
rule: **every check runs once per change, at the stage that owns it**. Every
other stage runs a cheaper subset or reuses a recorded pass
([#537](https://github.com/gregoryfoster/skills/issues/537)).

## Who owns what

| Stage | Owns |
|---|---|
| pre-commit | Lint, format and budget gates; the tests, in parallel |
| ship gate (`pre-ship.sh`) | Every check below, **skipped when a pass is already recorded for this exact tree** |
| CI (where the repo has it) | The full suite once per change, in one consolidated job: on pull requests, plus push to main for direct pushes only |
| scheduled | Exact or billed measurement |

The pre-commit hook and the ship gate check the same tree once a commit
lands, so whichever runs first records the pass and the other reuses it.

## Three mechanisms

- **Detection, not variants.** `detect-stack.sh` reports each toolchain
  (`uv`, `composer`, `npm`), which decides the checks, and each framework
  (`fastapi`, `click`, `php`), which decides only the docs: doc-check's
  default watch list and which `stack-<framework>.md` applies. A repo with
  several stacks gets the checks of each.
- **A tree-keyed pass stamp.** `gate-stamp.sh` records a pass against the
  exact tree, under the git common directory, shared by every worktree. Only
  a clean tree can be stamped: no tracked change, no untracked file, no dirty
  submodule. The key is computed again after the run and the pass is
  recorded only if it still matches. `GATE_STAMP=off` forces a run;
  `GATE_STAMP_EXPLAIN=1` prints what went into a key.
- **A worker count shared across gates.** `gate-workers.sh` returns
  `PYTEST_XDIST_AUTO_NUM_WORKERS` (a coordinator's per-agent figure), else
  `.skills/test-workers` (`off`, `auto` or a number), else serial on two
  cores or fewer and otherwise min(8, cores ÷ (gates running + 1)). The gate
  uses xdist only when the project's environment already has it; it never
  adds a dependency.

## Overriding

A repo-root `scripts/pre-ship.sh` wins over this one, for this script alone
(SKILL.md Step 1, [#301](https://github.com/gregoryfoster/skills/issues/301)).
Make it a **wrapper** that loads what the project needs and `exec`s this gate;
the recipe is in the comment block at the top of `pre-ship.sh`. Write a whole
gate only for a toolchain this one cannot detect, and never copy the skill
into your own `skills/`.

## One decision per check

The per-stack gates this one replaced disagreed on every row below. Each row
is the decision now in force; "Before" names which variant did what.

| # | Check | Before (the variants) | Decision |
|---|---|---|---|
| 1 | Which gate runs | Picked by the variant's name | **Detected per repo, and every detected stack runs.** uv `pyproject.toml` → the Python checks; `composer.json` → the PHP checks; `package.json` → its npm scripts. A repo with two stacks (wordpress has composer and npm; a FastAPI app can have a `package.json`) runs both. |
| 1b | Which docs apply | Picked by the variant's name | **Framework, detected separately from toolchain.** fastapi when `fastapi` is among `[project].dependencies`; click when `click` or `typer` is and fastapi isn't; php for any `composer.json`. It chooses only doc-check defaults (row 23) and which `references/stack-*.md` loads, never which checks run. A repo can match more than one, and gets the union. |
| 2 | Nothing detected | Baseline: stub, exit 1 | Same: exit 1 with the remedy. A repo-root `scripts/pre-ship.sh` still wins (#301). |
| 3 | Stack detected, tool missing | uv / composer / node missing → exit 2 | Same. |
| 4 | Worktree-zombie audit | All four, a warning only | Same, run once. |
| 5 | `ruff check` | fastapi, click | Every uv repo. |
| 6 | `ruff format --check` | fastapi only | **Every uv repo.** A repo that has never been formatted goes red once; run `ruff format` once when it moves onto this gate. |
| 7 | Import check (`detect-import-targets.sh`) | click only | **Every uv repo.** `.skills/import-targets` always runs. Without it, the `[project] name` (`-` read as `_`) runs only when `<name>/` or `src/<name>/` exists; otherwise it is skipped with a note naming the knob. Most services package their code as `src`, so an unguarded guess failed them out of the box. |
| 8 | Test-directory detection (`detect-test-dirs.sh`) | click only | **Dropped from the gate.** pytest's own `testpaths` and rootdir rules decide, and exit 5 (row 9) covers a library with no suite. The script stays, because `reviewing-code-python-click` uses it. |
| 9 | pytest exit 5 (collected nothing) | fastapi, click: a pass | Same, plus a visible NOTE. |
| 10 | `-x` | fastapi yes, click no | **Off.** Under xdist a full run costs little more, and an agent fixes every failure in one pass instead of one per run. |
| 11 | `-v` | click yes, fastapi no | **Off.** Verbose output puts thousands of lines into agent context. |
| 12 | Integration deselect (the per-run plugin, never `-m`, #304) | fastapi only | **Every uv repo.** Integration tests are never in the ship gate (the contract). |
| 13 | `--no-cov` when pytest-cov is installed | fastapi only | **Every uv repo.** A coverage threshold belongs in CI. |
| 14 | xdist | None | **New.** `-n N --dist loadfile` from `gate-workers.sh` when the project's environment can import xdist; otherwise serial with a NOTE. The gate never adds a dependency. `.skills/test-workers off` is for suites that share a database or port. |
| 15 | Pass stamp | fastapi, click: `/tmp/<repo>-tests-clean-<HEAD sha>[-env-<hash>]`, pytest only; untracked files and modified `vendor/` paths still count as clean. php, npm: none | **`gate-stamp.sh` over the whole gate, every stack.** The key is the tree (lockfiles are tracked, so it covers them), the OS, the stack tools' versions, the `PRE_SHIP_ENV_NAMES` names, PYTEST_ADDOPTS and PYTHONPATH, and the untracked inputs in `.skills/gate-stamp-inputs` (default `.env`). An untracked file or a dirty submodule means no stamp. That is stricter than today's rule and can only cost a re-run, never fake a pass. |
| 16 | `PRE_SHIP_ENV_NAMES` (#497) | fastapi, click | Same contract: the names enter the key, and an exported but empty list writes no stamp. The wrapper-don't-fork recipe is unchanged. |
| 17 | `.skills/pre-ship-uv-args` | fastapi, click | Same, for every uv call. |
| 18 | `composer validate` | php: the root, plus `themes/*/` and `plugins/*/` at the repo root | Same. A Bedrock layout keeps its themes under `web/app/themes/`, which this does not search: an open question, kept as the variant had it until a Bedrock repo shows what it needs. |
| 19 | `php -l` | php: parallel, `PRE_SHIP_PHP_LINT_JOBS` or 4 | `PRE_SHIP_PHP_LINT_JOBS`, else `gate-workers.sh`'s answer with 0 read as 1, so a 2-vCPU VM lints on one job. |
| 20 | `composer test` | php, when the script exists; `run-script --list` stderr discarded | Same, but stderr is shown when that probe fails (gate-script| 23 | `doc-check.sh` | Four copies that differ only in default watch paths and one advice line | **One script.** Every repo watches `AGENTS.md` and `README.md`, plus each framework's paths from row 1b, exactly as its variant does today. fastapi: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `schema.sql`, `alembic/versions/`, `deploy/`, `src/{api,models,core}/`, `.env.example`. click: `pyproject.toml`, `uv.lock`, `src/`, `.env.example`. php: `composer.json`, `composer.lock`, `package.json`, `web/app/{themes,plugins,acf-json}/`, `.env.example`. A repo with no framework keeps the baseline's list. The AGENTS.md advice line names each matched framework's inventory: route table, command inventory, or CPT/Skills tables. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace the defaults. |ffer only in default watch paths and one advice line | **One script.** Defaults are the shared list plus each detected stack's additions: fastapi `alembic/versions/`, `deploy/`, `src/core/`, `CHANGELOG.md`, `uv.lock`; click `src/`, `uv.lock`; php `composer.lock`, `web/app/{themes,plugins,acf-json}/`; `.env.example` for all three. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace them. |
| 21 | npm `lint:js`, `format:js:check`, `test:js` | All four, identical, but python stops at the first failure and php continues | Same scripts, under row 22's policy. |
| 22 | What a failing check does | python: stop (`set -e`); php: run everything, then exit 1 | **Run every check, then exit 1, naming each failure.** Same reason as row 10. A tooling failure (exit 2) still stops at once. |
| 23 | `doc-check.sh` | Four copies that differ only in default watch paths and one advice line | **One script.** Every repo watches `AGENTS.md` and `README.md`, plus each framework's paths from row 1b, exactly as its variant does today. fastapi: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `schema.sql`, `alembic/versions/`, `deploy/`, `src/{api,models,core}/`, `.env.example`. click: `pyproject.toml`, `uv.lock`, `src/`, `.env.example`. php: `composer.json`, `composer.lock`, `package.json`, `web/app/{themes,plugins,acf-json}/`, `.env.example`. A repo with no framework keeps the baseline's list. The AGENTS.md advice line names each matched framework's inventory: route table, command inventory, or CPT/Skills tables. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace the defaults. |
| 24 | Exit codes | 0 / 1 / 2 in all four | Same: 0 pass, 1 a check failed, 2 tooling. |
