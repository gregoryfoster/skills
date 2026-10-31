# Stack: PHP / WordPress

Applies when `pre-ship.sh` reports `framework php`: a `composer.json` at the
root, or one level under `themes/` or `plugins/`. The checks are the composer
toolchain's (see [gate-topology.md](gate-topology.md)): `composer validate`
at each `composer.json`, `php -l` on every tracked PHP file, and
`composer test` when the project defines it. A repo that also has a
`package.json` gets its npm scripts too.

## Lint workers

`php -l` runs in parallel on the gate's worker count (one job on a 2-vCPU
machine). `PRE_SHIP_PHP_LINT_JOBS=N` overrides it for a very large monorepo.

## Bedrock layouts

`composer validate` looks for theme and plugin `composer.json` files under
`themes/*/` and `plugins/*/` at the repo root, as the PHP variant did. A
Bedrock repo keeps them under `web/app/`, which is not searched: an open
question until a Bedrock repo shows what it needs. Its root `composer.json`
is validated either way.

## What doc-check watches by default

`AGENTS.md`, `README.md`, `composer.json`, `composer.lock`, `package.json`,
`web/app/themes/`, `web/app/plugins/`, `web/app/acf-json/` and
`.env.example`. On a hit, check the AGENTS.md CPT/Skills tables along with
its structure and conventions.

## Step 8 — next steps for WordPress / Bedrock / Sage 11

| Category | Trigger | Example action |
|---|---|---|
| ACF JSON sync | `acf-json/` changed | `wp acf import` or "Sync changes" in admin |
| Asset build | `resources/assets/` changed | `yarn bud build` then `wp acorn view:clear` |
| WP-CLI cache | Code change touching cached output | `wp cache flush; wp rewrite flush` |
| Composer deps | `composer.lock` changed | `composer install --no-dev` on deploy box |
| Env vars | `.env.example` updated | Propagate to production `.env` |
