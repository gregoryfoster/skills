# Carve-outs — keeping tooling off the generated tree

Generated code is not the consumer's code to lint, type-check, cover, or
review. Every tool that walks the source tree needs an explicit exclusion,
or the first regen after a producer change drowns CI in noise that isn't
anyone's to fix.

`<GENERATED_PATH>` below is the generated tree for the chosen layout:
`clients/<PRODUCER_NAME>-python/src/<CLIENT_PACKAGE>/generated/`
(sdk-package) or
`src/<CONSUMER_PACKAGE>/shared/<PRODUCER_UNDERSCORE>_generated/`
(generated-tree).

## ruff (consumer root `pyproject.toml`)

```toml
[tool.ruff]
extend-exclude = ["<GENERATED_PATH>"]
```

sdk-package note: the SDK dir has its own `[tool.ruff]` config (used by the
regen format pass), and the root exclusion keeps root-level `ruff check .`
runs from re-styling it with the wrong config. Exclude the whole generated
dir at the root even so — root ruff and SDK ruff may disagree.

## coverage (consumer root `pyproject.toml`)

```toml
[tool.coverage.run]
omit = ["<GENERATED_PATH>*"]   # generated OpenAPI client; not our code to test
```

Without this a large generated tree deflates the coverage percentage and a
`fail_under` gate starts failing for reasons unrelated to the change under
review.

## pre-commit (when the repo uses it — `.pre-commit-config.yaml`)

```yaml
exclude: '^<GENERATED_PATH_REGEX>'
```

(top-level `exclude`, or per-hook when only some hooks conflict with
generated style).

## mypy / ty (when the repo type-checks)

```toml
[tool.mypy]
exclude = ["<GENERATED_PATH_REGEX>"]
```

The generated client ships `py.typed` and is fine to *import* from checked
code — the exclusion only stops the checker from reporting on generated
internals.

## `.gitattributes` — collapse in PR diffs

```gitattributes
<GENERATED_PATH>** linguist-generated=true
```

GitHub folds `linguist-generated` files in PR diffs by default, so a regen PR
reads as its snapshot/sidecar diff plus a one-line "generated files changed"
fold instead of thousands of generated lines. Reviewers review the contract
change, not the generator output.

## What NOT to carve out

- The **snapshot and sidecar** — these are the reviewable contract; they must
  appear in full in diffs.
- The SDK's hand-authored shell (`pyproject.toml`, `__init__.py` re-exports,
  README, tests) — that is real code, reviewed and linted normally.
