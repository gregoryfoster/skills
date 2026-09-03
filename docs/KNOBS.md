# `.skills/` — every file a project may commit

The complete inventory of paths these skills read or write under a consuming
repo's `.skills/` directory. [AGENTS.md](../AGENTS.md) states the resolution
*shape* that three of them share; this is the list, which is the question a
maintainer actually asks — *what may my repo put here, and what does each one
do?*

Until [#264](https://github.com/gregoryfoster/skills/issues/264) there was no
such list. Six paths were documented in AGENTS.md or `docs/`, and the other
sixteen only inside the SKILL.md or `references/` file of the skill that reads
them. A project learned a knob existed when an agent happened to run the skill
that read it, which is how [#261](https://github.com/gregoryfoster/skills/issues/261)
was found: a repo tailored `doc-sensitive-paths`, could not discover its
companion, and got advice written for a stack it does not run.

**Two columns carry the weight.** *Replaces or extends* is the difference
between narrowing a list and only ever widening it. *Absent means* is the
difference between a default and a feature that is off — and, for a gate,
between a pass and a check that never ran. Neither can be derived from the
filename, which is why this table is maintained by hand and held complete by
[tests/structural/test_skills_knob_inventory.py](../tests/structural/test_skills_knob_inventory.py):
a `.skills/<name>` literal anywhere in `skills/`, `scripts/`, `.claude/hooks/`,
`docs/` or `AGENTS.md` with no row here fails the suite.

## Configuration a project commits

These are the knobs. A project writes them by hand to change behaviour without
forking a skill.

| Path | Grammar | Read by | Replaces or extends | Absent means |
|---|---|---|---|---|
| `doctor.sh` | executable script | every `reviewing-*` / `shipping-*` preflight, `init-*` | n/a — it *is* the implementation | no preflight; the calling step is a no-op |
| `worktree_root` | single-line path | `using-git-worktrees`, `managing-skills` | replaces the built-in default | sibling `../<repo>-worktrees/` |
| `worktree_venv` | single word: `link` or `none` | `using-git-worktrees` | replaces the default | `link` — the primary checkout's `.venv` is symlinked in |
| `default_branch` | single-line ref name | `using-git-worktrees` | first step of a 3-step resolution | falls to `origin/HEAD`, then `main` |
| `plans_dir` | single-line path | `writing-plans`, `orchestrating-issue-backlog`, `init-project-fastapi` | replaces the built-in default | `docs/plans/` |
| `skills-pin` | one `<submodule-path> <commit-ish>` per line | `managing-skills` | replaces the default | submodules track their remote's default branch |
| `forked-ok` | one repo-relative path per line, `#`-comments | `managing-skills`' doctor | replaces the default (empty) | no fork is declared, so every divergence is reported |
| `doc-sensitive-paths` | one path per line, `#`-comments | `shipping-work*`' doc-check | **replaces** `SENSITIVE_PATHS` wholesale | the variant's built-in path list |
| `doc-sections` | one section per line, `#`-comments | `shipping-work*`' doc-check | **replaces** `DOC_SECTIONS` wholesale | the variant's built-in advice |
| `import-targets` | one package name per line, `#`-comments | `shipping-work-python-click`, `reviewing-code-python-click` | replaces the pyproject-derived default | the `[project] name` from `pyproject.toml` |
| `context-budget` | a single number | `curating-context`, the context-budget hook | env `CONTEXT_BUDGET` wins, then this file | 6,000 tokens |
| `context-doc-budget` | a single number | `curating-context` | env `CONTEXT_DOC_BUDGET` wins, then this file | 10,000 tokens per doc |
| `context-docs-dir` | single-line path | `curating-context` | replaces the default | `docs` |
| `cohort` | one repo per line, `#`-comment header carrying `wave:` / `pair:` | `curating-context`'s cohort scoring | no default — the file *is* the cohort | scoring has nothing to score |

### Acknowledgement files

Four files that **suppress a `curating-context` gate**. Each entry needs a named
warrant from a closed set, and an unrecognised warrant is refused rather than
ignored. They are listed apart because a file whose purpose is to turn a check
off deserves to be found by someone auditing what is switched off, not only by
someone reading the skill that honours it.

| Path | Suppresses | Absent means |
|---|---|---|
| `context-seams-ok` | the seam check in `curating-context` | every seam finding is reported |
| `context-loss-ok` | the loss check (`prove-no-loss.sh`) | every loss finding is reported |
| `context-claims-ok` | the claims check | every claim finding is reported |
| `context-counts-ok` | the counts check (`check-counts.sh`) | every count finding is reported |

## State a skill writes

Not knobs. A project does not hand-write these; a skill creates and maintains
them. They are inventoried because a maintainer who finds one in their tree
still needs to know what put it there and whether it is safe to delete.

| Path | Shape | Written by | Deleting it |
|---|---|---|---|
| `context-metrics.jsonl` | append-only JSONL ledger, one row per curation | `curating-context`'s telemetry | loses history; the next run starts an empty ledger |
| `context-token-counts` | calibration rows: an anchored path and its last exact count | `curating-context` under `--exact` | estimates fall back to the repo-wide ratio |
| `context-token-ratio` | a single number, bytes per token | `curating-context` under `--exact` | estimates fall back to the built-in ratio |
| `experiments/` | a directory of `NN-<slug>.yml` pre-registrations | `curating-context`'s experiment log | unregisters the experiment; scoring refuses to guess |

## Adding a knob

Add the row in the same change that adds the reader. The completeness test
fails otherwise, which is the point: this table went sixteen paths out of date
because nothing forced the pairing, and an inventory that lags is worse than
none — a reader takes it as exhaustive.

State what the file *is* for, not how the reader is implemented. A row that
says "replaces the defaults" and "absent means the built-in list" survives a
refactor of the parsing loop; one that names the loop does not.
