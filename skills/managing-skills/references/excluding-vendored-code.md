# Excluding `skills-vendor/` from the project's tools

Step 1 puts code in the tree that this project must not edit: `skills-vendor/`
is read-only here, and changes go upstream. Every tool that walks the tree from
the root reads it anyway. Exclude it from each one when you add the submodule
([#336](https://github.com/gregoryfoster/skills/issues/336)).

## Why it bites late

Nothing fails on the day you vendor. It fails on a refresh: the daily hook
bumps the pointer, and the next local `ruff check .` goes red with no local
change behind it. CI does not see it, because `actions/checkout` without
`submodules:` leaves `skills-vendor/*` empty. Nor does pre-commit. So it lands
on whoever runs the documented local command, which is where it misleads most.
On one consumer that adopted skills through this skill, `ruff check
--show-files .` listed 139 vendored files, and `ruff format --check .` read 226
files where 88 were its own. Both passed that day, by luck.

What ruff applies to a vendored file [measured, ruff 0.16.6]:

- **The vendor's own config, by default.** Ruff takes the nearest config to
  each file, and this repo ships a `[tool.ruff]` table. But the version is
  still the consumer's. A ruff that predates a key in the vendor's config
  cannot parse it, and then the whole run fails, not only the vendored files.
- **The consumer's config**, under `ruff --config <file>`, or for a vendor
  that ships no ruff config of its own. Then the consumer's `select`,
  `line-length` and target version apply to code it cannot change.

An exclude avoids both cases: ruff never reads the vendor's config or its files.

## What to set

The canonical snippets are in `init-project-fastapi`, whose bootstrap sets all
of this from the start:
[pyproject-toml.md](../../init-project-fastapi/references/pyproject-toml.md).
Copy them from there; one copy cannot drift.

| Tool | Section of that file | Setting |
|---|---|---|
| ruff | *Ruff config* (both profiles) | `extend-exclude` in `[tool.ruff]` |
| ty | *ty config* | `exclude` in `[tool.ty.src]` |
| pytest | *Pytest config* | `testpaths` |

- **ruff.** Use `extend-exclude`. Plain `exclude` replaces ruff's default
  list (`.git`, `.venv`, `node_modules` and the rest). Put it in the
  `[tool.ruff]` table itself, because an exclude in `[tool.ruff.lint]` still
  leaves `ruff format` reading the vendor. Ruff reads the first of
  `.ruff.toml`, `ruff.toml` and `pyproject.toml` it finds; in the first two
  the key goes at the top level.
- **ty** walks the whole tree by default. Without the exclude, its output is
  mostly unresolved-import noise from the vendor.
- **pytest.** `testpaths` applies only when pytest is given no path. A path
  that contains the vendor, such as `pytest .`, still walks into
  `skills-vendor/*/tests/` and collects upstream's suite; `pytest tests/` does
  not. If the project runs pytest over the root, also add `skills-vendor` to
  `norecursedirs`. That key replaces pytest's default list,
  so restate the defaults with it: `*.egg`, `.*`, `_darcs`, `build`, `CVS`,
  `dist`, `node_modules`, `venv` and `{arch}` [measured, pytest 9.0.3].
- **Anything else that walks the tree** reads the vendor the same way: another
  type checker, a shell or Markdown linter run over a glob, a search index.
  Exclude it in that tool's own config. This repo has no canonical snippet for
  those.

## What the doctor checks

`.skills/doctor.sh` warns when the root ruff config never names
`skills-vendor` in its top-level table. The root config is the file ruff
itself would read, in the order above, and for `pyproject.toml` the top-level
table is `[tool.ruff]`. A dotted key in that table, such as `lint.exclude`,
belongs to a sub-table and does not count, any more than `[tool.ruff.lint]`
does. The doctor stays silent when there is no
`skills-vendor/` directory or no ruff config at the root. Its warning prints
the `extend-exclude` line to add, or, where that table already has an
`extend-exclude`, says to append `"skills-vendor/"` to it: a second
`extend-exclude` is a duplicate key, and ruff refuses the whole file.

The warning is advisory in every mode, `--check-only` included, and never
changes the exit code. The gap is in the repo's tooling, not in the diff under
review. Only ruff is read: ty is non-gating where `init-project-fastapi`
scaffolds it, and pytest's config can live in several files.

To lint the vendor on purpose, say so in a comment in that table that names
`skills-vendor`. The doctor counts any other mention there as covered.
