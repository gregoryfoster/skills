# Fitness function playbook

Vetted, per-tool config for graduating an accepted architecture finding into an executable check.
Each section is: **the rule the finding fixed → the exact config → the dev dependency → how it wires
into the check surface**. Fill in the placeholders (`<…>`) from the finding; do not improvise the
tool's schema from memory — a wrong key ships a check that passes while enforcing nothing.

Pick the tool by stack:

| Stack (manifest) | Layering / no-cycles tool | Module-size gate |
|---|---|---|
| Python (`pyproject.toml`) | [import-linter](https://import-linter.readthedocs.io/) | `pylint --max-module-lines` or portable gate |
| JS/TS (`package.json`) | [dependency-cruiser](https://github.com/sverweij/dependency-cruiser) | eslint `max-lines` |
| PHP (`composer.json`) | [deptrac](https://github.com/qossmic/deptrac) | portable gate |
| Contract (OpenAPI spec present) | **delegate** → `vendoring-openapi-client` drift guard | — |

---

## Python — import-linter

Rule shape: "layer `A` may not import layer `B`" (a **forbidden** contract), or "no import cycles
within `pkg`" (an **independence** or **layers** contract).

`pyproject.toml` (or `.importlinter` / `setup.cfg`):

```toml
[tool.importlinter]
root_package = "<root_pkg>"

# "models may not import services"
[[tool.importlinter.contracts]]
name = "<root_pkg>.models must not depend on <root_pkg>.services"
type = "forbidden"
source_modules = ["<root_pkg>.models"]
forbidden_modules = ["<root_pkg>.services"]

# strict top-down layering (higher layers may import lower, never the reverse)
[[tool.importlinter.contracts]]
name = "layered architecture"
type = "layers"
layers = ["<root_pkg>.routers", "<root_pkg>.services", "<root_pkg>.models"]
```

Dev dependency: `uv add --dev import-linter` (or `--group dev`). Run: `lint-imports`.

Wiring: add `lint-imports` to the existing lint step. If a `[tool.ruff]`/pytest CI job exists, append a
`lint-imports` invocation there; if pre-commit is used, add a `repo: local` hook running `lint-imports`.

---

## JS/TS — dependency-cruiser

Rule shape: a `forbidden` rule. `.dependency-cruiser.js`:

```js
module.exports = {
  forbidden: [
    {
      name: "no-models-to-services",
      comment: "models may not import services",
      severity: "error",
      from: { path: "^src/models" },
      to:   { path: "^src/services" },
    },
    {
      name: "no-circular",
      comment: "no import cycles in services/",
      severity: "error",
      from: { path: "^src/services" },
      to:   { circular: true },
    },
  ],
  options: { doNotFollow: { path: "node_modules" }, tsConfig: { fileName: "tsconfig.json" } },
};
```

Dev dependency: `npm i -D dependency-cruiser` (or the project's package manager). Add a script:
`"depcruise": "depcruise src --config .dependency-cruiser.js"`.

Wiring: add `npm run depcruise` to the CI lint job and/or a pre-commit `repo: local` hook.

---

## PHP — deptrac

Rule shape: layer boundaries via a ruleset. `deptrac.yaml` at repo root (or per-package for a
Bedrock/Sage monorepo — one config per composer package under `themes/`/`plugins/` when layers don't
span the whole tree):

```yaml
deptrac:
  paths:
    - ./app
  layers:
    - name: Providers
      collectors:
        - type: directory
          value: app/Providers/.*
    - name: Composers
      collectors:
        - type: directory
          value: app/View/Composers/.*
  ruleset:
    Composers:
      - Providers   # Composers may depend on Providers, not vice versa
    Providers: ~     # Providers may depend on nothing above
```

Dev dependency: `composer require --dev deptrac/deptrac` (the maintained package; the older
`qossmic/deptrac-shim` still installs but is legacy — or use the phar). Run: `vendor/bin/deptrac analyse`.

Wiring: add a composer script `"deptrac": "deptrac analyse"`, then reference it from the CI job and/or
a GrumPHP task if GrumPHP is the local pre-commit surface.

---

## Module size — per-language gate

When the finding is "module X does too many jobs; keep it under N lines", prefer a linter-native rule;
fall back to a portable CI gate.

- **JS/TS** — eslint: `"max-lines": ["error", { "max": <N>, "skipComments": true }]`.
- **Python** — use the portable gate below (the CannObserv Python stack is ruff-based, and ruff has no
  per-file line rule; pulling in pylint just for a line ceiling is an out-of-stack dependency). Reach
  for pylint's `[tool.pylint.format] max-module-lines = <N>` **only** if the project already runs pylint.
- **PHP / portable fallback / anything else** — a shell gate in CI (no new dependency):

  ```bash
  # fail (non-zero exit) if any tracked file in <dir> exceeds <N> lines
  git ls-files -z '<dir>' | xargs -0r wc -l | awk -v n=<N> '$1>n && $2!="total"{print; bad=1} END{exit bad}'
  ```

Wiring: the eslint/pylint rule rides the existing lint job; the portable gate becomes a named CI step.

---

## Contract stability — delegate, don't reimplement

For "this API/schema must not break at the boundary" findings, **do not** hand-roll an OpenAPI differ.
Invoke [`vendoring-openapi-client`](../../vendoring-openapi-client/SKILL.md) and use its tiered drift
guard (`DRIFT_GUARD=none|ci|ci+live`): the committed spec snapshot is the contract-of-record and the
hermetic CI regen-diff gate fails the build on drift. Route the finding there with the boundary's spec
location and the desired tier; that skill owns the wiring.

---

## Detecting the check surface

Before wiring, detect what the project actually uses (don't assume `.github/workflows/`):

```bash
ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null   # GitHub Actions
test -f .pre-commit-config.yaml && echo pre-commit
test -f grumphp.yml -o -f grumphp.yml.dist && echo grumphp        # PHP local gate
{ command -v jq >/dev/null && jq -e '.scripts' package.json >/dev/null 2>&1; } \
  || grep -q '"scripts"' package.json 2>/dev/null && echo npm-scripts   # jq-optional
grep -q '"scripts"' composer.json 2>/dev/null && echo composer-scripts
```

Wire into every surface the project already runs on merge/commit; where none exists, propose adding one
CI job and surface it as a diff for review — never enable a gate the user hasn't seen.
