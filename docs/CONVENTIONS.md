# Conventions — project overrides and reference files

Detail behind the conventions whose binding rules are stated inline in
[AGENTS.md](../AGENTS.md). Read this when authoring a project-level override,
when adding a `references/*.md` file that gates content on a parameter, or when
repointing one of the three `.skills/` resolution knobs.

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

### Fragments an override may not drop

`version:` in an override records **the vendor version last synced from**, and comparing it to the vendor's catches an override that has fallen *behind* ([#238](https://github.com/gregoryfoster/skills/issues/238)). It cannot catch divergence at the *same* version — an override synced honestly from v1.1 whose text replaced upstream v1.1 with something worse — and [#63](https://github.com/gregoryfoster/skills/issues/63) was reintroduced a second time through exactly that opening ([#260](https://github.com/gregoryfoster/skills/issues/260)): a `shipping-work-php` override at a matching `1.1` had swapped `bash "<SKILL_SCRIPTS>/pre-ship.sh"` for `bash scripts/pre-ship.sh`, with a note explaining that the scripts `cd "$(git rev-parse --show-toplevel)"` so the path was safe. True, and beside the point — that resolves the root the scripts *operate on*, not the path `bash` uses to *open the file*.

An override exists to differ, so no diff-and-warn can work here. Instead an upstream skill fences the small set that is **not** optional:

Shown four-backticked so the inner fence survives; a zero-width space would
have hidden an invisible character in text people copy.

````markdown
<!-- skill:required id=skill-scripts -->
```bash
N=<skill-name> S=<script>.sh SD=
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
```
````

The marker arms **the fenced block that follows it**, and only a fenced block — prose gets legitimately reworded, so a fragment check over prose would flag every honest edit. `.skills/doctor.sh` reads each override's `overrides:` target, extracts the vendor's armed blocks, and warns when the override does not carry one, compared insensitive to whitespace. It runs whatever the version stamps say, because a matching stamp is the state being reported.

`id=<slug>` **names** the fragment so a consumer can declare it inapplicable (below). Every marker in this repo carries one, and [tests/structural/test_override_required_fragments.py](../tests/structural/test_override_required_fragments.py) holds that: an un-idded fragment cannot be declared, so a vendor that arms one leaves its consumers no move but to paste it back or to fork away from it. Ids are unique within a file — a declaration that resolved to two fragments would excuse the wrong one — and stable across releases, because renaming one silently voids every declaration naming it.

Three rules for an override author:

- **Carry every armed block verbatim.** Re-indent it if you must; do not rewrite it.
- **Never write a bare `bash scripts/X.sh`.** The doctor reports that shape in an override regardless of any fence, because it needs no vendor cooperation and it is what the two occurrences of #63 had in common. Use the resolved `<SKILL_SCRIPTS>` placeholder. A path that *exists at the project root* is exempt — that is the project's own `scripts/`, not the skill's ([#266](https://github.com/gregoryfoster/skills/issues/266)).
- **Declare a fragment that genuinely cannot apply; do not paste it back dead** ([#265](https://github.com/gregoryfoster/skills/issues/265)). An override that ships none of the scripts a block resolves cannot satisfy it by carrying it — the fence would be a runnable-looking instruction that fails, which is the #63 shape arriving through the remedy. Say so in the frontmatter instead:

  ```yaml
  metadata:
    overrides: <owner>-<repo>/using-git-worktrees
    omits-required: "skill-scripts: this project ships none of the vendor's
      worktree scripts, so <SKILL_SCRIPTS> resolution resolves nothing here"
  ```

  The grammar is `"<id>[, <id>…]: <why>"`, ids **first** because the doctor reads one line and a reason worth writing gets folded across two. A declaration excuses the fragment it names and nothing else, so a fragment armed in a later release still reports against a file that already carries one — the property that keeps this from becoming a blanket mute. A declaration that matches no armed fragment (a renamed id, a fragment the override has since re-synced) is itself reported: a mute with nothing under it reads to the next reader as a decision taken.

All three findings are advisory in every mode, like the drift check beside them: re-syncing an override is debt paid down on a schedule, and a probe that failed on it would push consumers toward deleting overrides rather than repairing them. The most durable fix is to need less override — per-file symlinks for everything not genuinely local, leaving `SKILL.md` as the one file no symlink can reach.

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
- **Flat, unless the doc is an index.** A reference that indexes many small entries — the `orchestrating-issue-backlog` process log is the only one — may hold them in a subdirectory, provided the index links each entry and `SKILL.md` links the index. `TestReferences` enforces that as reachability: top-level references must be linked *directly* from `SKILL.md`, and anything deeper must be reachable through a chain of reference links, so an unlinked subdirectory still fails ([#152](https://github.com/gregoryfoster/skills/issues/152)). Every other check over `references/` is recursive for the same reason. Do not nest for tidiness: a subdirectory that is not an index's entry set has nothing to link it.
- **No length cap.** The whole point of a references file is escaping the SKILL.md body recommendation — don't reimpose one.
- **Naming:** `lowercase-kebab.md`, matching the broader skill naming convention.
- **Conditional blocks are delimited.** A reference that gates content on a branch-point parameter opens the block with `> Include when <COND>:` and closes it with `> end include` — always both. Conditions may be `AND`-joined. The renderer drops the whole block when the condition is false, so an unterminated open has no boundary and silently takes following prose with it. `TestConditionalBlockMarkers` in [tests/structural/test_references.py](../tests/structural/test_references.py) fails the suite on an unterminated open or a stray close ([#82](https://github.com/gregoryfoster/skills/issues/82)).

The same conventions apply to `assets/` (templates, schemas, copy-into-place artifacts), with the obvious adjustment that `assets/` files are typically not markdown.

## Worktree root convention

Skills and project-local scripts that operate on `git worktree`s resolve the worktree root via a three-step lookup (see [`using-git-worktrees`](../skills/using-git-worktrees/)):

1. `WORKTREE_ROOT` env var (highest priority — one-off overrides)
2. `.skills/worktree_root` file under the repo root (single-line path; the project's persistent default)
3. `<repo-root>/.worktrees/` (fallback)

The helper `bash skills/using-git-worktrees/scripts/resolve-worktree-root.sh` prints the resolved root. Project-local wrapper scripts (e.g., `dev.sh worktree create`) should invoke the upstream `worktree-*.sh` scripts rather than reimplement them, and may pre-populate env files, allocate ports, or run extra bootstrap — but must not bypass the Iron Law gates.

## Plans directory convention

Skills that read or write plan documents resolve the plans directory via the same three-step lookup pattern (see [`writing-plans`](../skills/writing-plans/)):

1. `PLANS_DIR` env var (highest priority — one-off overrides)
2. `.skills/plans_dir` file under the repo root (single-line path; the project's persistent default)
3. `<repo-root>/docs/plans/` (fallback)

The helper `bash skills/writing-plans/scripts/resolve-plans-dir.sh` prints the resolved directory. Downstream projects that previously carried a `writing-plans` override solely to repoint the storage path can drop the override and configure `.skills/plans_dir` instead — the upstream skill's resolution order makes the path a knob rather than a fork.

## Submodule pin convention

The auto-refresh hook resolves per-submodule pins via the same three-step lookup (see [`managing-skills`](../skills/managing-skills/)):

1. `SKILLS_PIN_FILE` env var (highest priority — one-off overrides)
2. `.skills/skills-pin` file under the repo root (one `<submodule-path> <commit-ish>` per line; `#` comments ignored)
3. no pins — every `skills-vendor/` submodule refreshes (prior behaviour)

A pinned submodule is excluded from both the update and the auto-commit, and each honoured pin is logged by name. Use it to hold one vendored repo at a known-good commit — an experiment control arm, say — while the rest keep refreshing; before this the only remedy was deleting the hook's `SessionStart` entry, which also stopped the sibling refreshes and the `.skills/doctor.sh` self-heal ([#100](https://github.com/gregoryfoster/skills/issues/100)).

## Variant selection surface

A variant is created by copying its baseline, so it inherits that baseline's
`description:` — and the runtime selects on `name` + `description` alone. Three
rules follow, each with a test behind it.

**Remove the baseline's fallback clause.** Both baselines end their description
by declaring themselves the fallback of last resort for stacks with no dedicated
variant (#240 — on a Go project, Haiku-tier models otherwise pick *no* skill at
all, 8/8 in #97's probe). A variant repeating that claim tells the runtime to
pick it for stacks it does not handle. `tests/structural/test_baseline_fallback_clause.py`
asserts the clause is on the baselines and on nothing else. Note that
`test_description_differs_from_baseline` does **not** cover this — it catches a
byte-identical copy, not a lightly-edited one that keeps the sentence.

**Add a stack-distinguishing parenthetical.** Name what this variant actually
covers, in terms traceable to its own body: `Click decorator order, custom
ParamTypes` versus `async route handlers, Alembic migration safety`. Before
#241 the Click and FastAPI pairs carried byte-identical toolchain parentheticals
(`uv + ruff + pytest + Pydantic v2`), leaving a single differentiating token at
0.94 pairwise similarity — the thinnest margin in the library. Do not describe
capabilities the skill does not have; an unhonoured coverage claim on the
selection surface is the same defect as a missing one, pointed the other way.

**Leave `metadata.triggers` byte-identical to the baseline's.**
`TestVariantFamilyConsistency::test_triggers_match_baseline` asserts exact
equality, so editing a baseline's triggers turns every variant in its family red
at once. This equality is also what licenses trigger xfails to be inherited
family-wide (#243).

### Declaring the family

`tests/utils/skill_families.py`'s `VARIANT_FAMILIES` is the single authority on
which skills are variants of which baseline; both the drift assertions and the
trigger-xfail keying read it. Add `(baseline, variant, stack_keyword)` there.

Membership is **declared, not inferred from the name**, so a future
`shipping-work-orders` — a different skill that merely reads like a variant —
cannot silently inherit the family's xfails and turn a real routing regression
into a quiet pass. Because an authoritative list is also a list you can forget
to update, the name inference survives as a *detector*:
`undeclared_variant_candidates()` flags anything shaped like `<baseline>-<suffix>`
that is undeclared, and `test_naming.py` fails on it by name. If a lookalike is
genuinely not a variant, record it in `NOT_VARIANTS` with the reason.
