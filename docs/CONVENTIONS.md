# Conventions — project overrides and reference files

Detail behind two conventions whose binding rules are stated inline in
[AGENTS.md](../AGENTS.md). Read this when authoring a project-level override, or
when adding a `references/*.md` file that gates content on a parameter.

## Project overrides

The resolution model — local replaces global, completely, with no inheritance —
is in AGENTS.md. What follows is what an override author needs.

### Signal that a project override is needed

A project-level override is appropriate when the global skill would require project-specific knowledge to function correctly, such as:
- Commit message format conventions
- Deployment commands (`systemctl restart`, `fly deploy`, etc.)
- Test runner invocation (`uv run pytest`, `go test ./...`, etc.)
- Project-specific CI/CD steps
- Custom severity criteria for that codebase

### Required override frontmatter

Every project-level override **must** declare two fields in its `metadata` block:

- `overrides: <vendor>/<upstream-skill-name>` — the upstream skill being replaced, qualified by the vendor it comes from
- `override-reason: <one-line rationale>` — why a full replacement was needed

```yaml
metadata:
  author: gregoryfoster
  version: "1.0"
  overrides: gregoryfoster-skills/reviewing-code
  override-reason: Adds project-specific commit convention and systemctl restart step
```

The `<vendor>` token matches the submodule directory name under `skills-vendor/` (e.g. `gregoryfoster-skills`, `obra-superpowers`). This is the same `<owner>-<repo>` convention documented in [`managing-skills`](../skills/managing-skills/). When the same upstream skill name exists in two vendored sources (e.g. both `gregoryfoster-skills/writing-plans` and `obra-superpowers/writing-plans`), the vendor prefix is the only thing that disambiguates which parent the override is replacing — a reader (or audit tool) should never have to consult git history to figure that out.

If the same upstream repo is vendored from two forks, the submodule directory name still disambiguates (e.g. `gregoryfoster-skills` vs `someone-else-skills`); the vendor token is whatever the project actually checked out, not the canonical upstream.

These keys make it possible to audit divergence across downstream repos (e.g. "which overrides have drifted from upstream") without inspecting every SKILL.md by hand. Upstream skills in this repo do not carry these keys — they aren't overrides.

#### Legacy unqualified form

The earlier convention allowed bare `overrides: <skill-name>` without a vendor prefix. That form is **tolerated for existing downstream files** but should be migrated to the qualified form during the next routine touch (e.g., as part of a downstream sweep). New overrides must use the qualified form. Bare entries are ambiguous as soon as a second vendor ships a skill of the same name, so the tolerance window closes once the audited downstreams have been updated.

### Project-name suffix on the H1

When an override is active, suffix the `SKILL.md` body's top-level heading with the project name so users can tell at a glance which version is loaded:

```markdown
# Code & Documentation Review — Address Validator
```

The suffix is recommended (not required) and applies to the H1 only — not the skill `name` field (which must continue to match the directory name).

## Reference files

Skills may carry supplementary `references/*.md` files for content that exceeds the SKILL.md body cap (SKILL.md is recommended to stay under 500 lines). References files are loaded on demand by the agent, not on skill activation.

- **No frontmatter.** Plain markdown, no YAML preamble.
- **Linked from the sibling SKILL.md.** Every `references/<name>.md` must appear as a `[label](references/<name>.md)` link in its sibling SKILL.md body. Orphans are blocked by [tests/structural/test_references.py](../tests/structural/test_references.py).
- **Flat directory.** No subdirectories under `references/`. The structural no-orphan check compares link targets against `references/*.md` (non-recursive); nested layouts would be silently missed.
- **No length cap.** The whole point of a references file is escaping the SKILL.md body recommendation — don't reimpose one.
- **Naming:** `lowercase-kebab.md`, matching the broader skill naming convention.
- **Conditional blocks are delimited.** A reference that gates content on a branch-point parameter opens the block with `> Include when <COND>:` and closes it with `> end include` — always both. Conditions may be `AND`-joined. The renderer drops the whole block when the condition is false, so an unterminated open has no boundary and silently takes following prose with it. `TestConditionalBlockMarkers` in [tests/structural/test_references.py](../tests/structural/test_references.py) fails the suite on an unterminated open or a stray close ([#82](https://github.com/gregoryfoster/skills/issues/82)).

The same conventions apply to `assets/` (templates, schemas, copy-into-place artifacts), with the obvious adjustment that `assets/` files are typically not markdown.
