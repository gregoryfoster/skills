# Stack: PHP / WordPress

Applies when `pre-ship.sh` reports `framework php`: a `composer.json` at the
root, or a tracked one one level under `themes/` or `plugins/`. The checks
are the composer toolchain's (see [gate-topology.md](gate-topology.md)):
`composer validate` at each of those `composer.json` files, `php -l` on
every tracked PHP file, and `composer test` when the project defines it. A
repo that also has a `package.json` at the root, or a tracked one one level
under `themes/` or `plugins/`, gets its npm scripts too. A nested manifest
counts only when git tracks it, so a gitignored plugin that composer
installs is neither validated nor run
([#588](https://github.com/gregoryfoster/skills/issues/588)). A theme
vendored as a git submodule is its own repo, and neither of its manifests
counts: a submodule's code is its own repo's to gate. A theme directory
that is a symlink is one link to git, so nothing under it is listed
either. Its files are checked where git tracks them: its PHP is linted
there, but a `composer.json` under `web/app/` is not validated, since
neither reach searches there (the Bedrock question below, and
[gate-topology.md](gate-topology.md) row 18).

## Lint workers

`php -l` runs in parallel on the gate's worker count (one job on a 2-vCPU
machine). `PRE_SHIP_PHP_LINT_JOBS=N` overrides it for a very large monorepo.

`php -l` lints the PHP files this repo tracks. `php -l` stops at a
submodule: a theme or plugin vendored as one is its own repo, and a
submodule's PHP is linted by its own repo's gate
([#591](https://github.com/gregoryfoster/skills/issues/591)).

## Bedrock layouts

`composer validate` looks for theme and plugin `composer.json` files under
`themes/*/` and `plugins/*/` at the repo root, as the PHP variant did, and
npm looks for their `package.json` files there too. A Bedrock repo keeps
them under `web/app/`, which neither searches: an open question until a
Bedrock repo shows what it needs. Its root `composer.json` is validated, and
its root `package.json`'s scripts run, either way.

## What doc-check watches by default

`AGENTS.md`, `README.md`, `composer.json`, `composer.lock`, `package.json`,
`web/app/themes/`, `web/app/plugins/`, `web/app/acf-json/` and
`.env.example`. On a hit, check the AGENTS.md CPT/Skills tables along with
its structure and conventions.

## Step 8 — next steps for WordPress / Bedrock / Sage 11

A project's `.skills/next-steps`, when present, replaces this table
(SKILL.md Step 8).

| Category | Trigger | Example action |
|---|---|---|
| ACF JSON sync | `acf-json/` changed | `wp acf import` or "Sync changes" in admin |
| Asset build | `resources/assets/` changed | `yarn bud build` then `wp acorn view:clear` |
| WP-CLI cache | Code change touching cached output | `wp cache flush; wp rewrite flush` |
| Composer deps | `composer.lock` changed | `composer install --no-dev` on deploy box |
| Env vars | `.env.example` updated | Propagate to production `.env` |
