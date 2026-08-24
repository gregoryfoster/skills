# Acquiring the skill source when running detached

Phase 0 of `SKILL.md`, in full. It applies **only** when the project does not
already vendor `gregoryfoster/skills`, which most installs do — hence the
demotion. If the project vendors it, there is nothing to do here.

## Already vendored — skip this

This skill's scripts (`preflight.sh`, `mcp-driver.mjs`) live in *this* skill
directory. If you're running inside a project that already vendors
`gregoryfoster/skills` (submodule + symlink), reference them at
`skills-vendor/<owner>-<repo>/skills/init-socraticode/scripts/…` — the real
path that `skills/…` symlinks to, and the one the health hook resolves first
([#177](https://github.com/gregoryfoster/skills/issues/177)) — and skip this
phase.

## Not vendored — clone once to a scratch dir

Reference scripts through the captured path:

```bash
set -euo pipefail
SKILL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/init-socraticode.XXXXXX")
git clone --depth 1 https://github.com/gregoryfoster/skills.git "$SKILL_TMP/gregoryfoster-skills"
SKILL_DIR="$SKILL_TMP/gregoryfoster-skills/skills/init-socraticode"
test -f "$SKILL_DIR/scripts/preflight.sh" || { echo "Phase 0 clone failed"; exit 1; }
echo "SKILL_DIR=$SKILL_DIR"; echo "SKILL_TMP=$SKILL_TMP"
```

`<SKILL_DIR>` / `<SKILL_TMP>` in `SKILL.md` are **placeholders** for the literal
paths printed here (each Bash call runs in a fresh shell — they are not
inherited). Clean up `<SKILL_TMP>` in Phase 6.
