# `.skills/` — every file a project may commit

The complete inventory of paths these skills read or write under a consuming
repo's `.skills/` directory. [AGENTS.md](../AGENTS.md) states the resolution
*shape* that many of them share, and the "Replaces or extends" column below
says which; this is the list, which is the question a maintainer actually
asks — *what may my repo put here, and what does each one do?*

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
| `worktree_root` | single-line path; a relative one resolves against the primary checkout, and `~` is not expanded | `using-git-worktrees`' `resolve-worktree-root.sh`, from the primary checkout; exit 2 when git refuses the primary or none can be found, as from a linked worktree of a `--separate-git-dir` primary ([#585](https://github.com/gregoryfoster/skills/issues/585), [#605](https://github.com/gregoryfoster/skills/issues/605)). `worktree-create.sh` refuses (exit 2) a root inside the repo that git does not ignore ([#567](https://github.com/gregoryfoster/skills/issues/567)). `managing-skills` only declines to stage it | env `WORKTREE_ROOT` wins, then this file | `<repo-root>/.worktrees/`, which the repo must ignore |
| `deploy_command` | one command line of whitespace-separated words, no shell syntax; blank lines and whole-line `#`-comments ignored | `shipping-work`'s `run-deploy-command.sh` (Steps 3, 6 and 8, [#345](https://github.com/gregoryfoster/skills/issues/345)) | no env var; read from the primary checkout, the first `git worktree list` entry's work tree (a bare primary's is the current checkout's, and a `--separate-git-dir` primary is read only from itself, [#605](https://github.com/gregoryfoster/skills/issues/605)), and run from its root with the pushed SHA appended as the last argument | today's Step 8: migrate and restart are listed and offered by hand; present but unusable is exit 2, never absent |
| `pre_restart` | `deploy_command`'s grammar, through the same reader (`_command-knob.sh`); nothing is appended | `shipping-work`'s `run-pre-restart.sh`: Step 8 runs it before offering any row that restarts the service, and Step 6 waits for Step 8 ([#557](https://github.com/gregoryfoster/skills/issues/557)) | no env var; read from the primary checkout, like `deploy_command`, and run from its root with stdin from `/dev/null`. Not run when `deploy_command` is set: the deploy command owns its own check | no check: the restart rows are offered as before the knob. A non-zero exit offers none; present but unusable is exit 2, never absent |
| `merge_mode` | single word: `pr` or `direct`; blank lines and whole-line `#`-comments ignored | `merge-mode.sh`, one copy in `shipping-work` and one in `using-git-worktrees` ([#342](https://github.com/gregoryfoster/skills/issues/342)): `shipping-work` Steps 2.5–8 and `run-deploy-command.sh`; `using-git-worktrees` Phase 4 and `worktree-destroy.sh`; `curating-context`'s `install-cadence.sh`, which renders the cadence workflow by it, and a `pr`-rendered workflow, which reads the committed file inline at run time; `managing-skills`' `skills-submodule-update.sh`, inline, on `main` ([#560](https://github.com/gregoryfoster/skills/issues/560)), and its doctor, which warns when `pr` leaves that hook no token for `gh` ([#576](https://github.com/gregoryfoster/skills/issues/576)) | no env var; read from the primary checkout, like `worktree_root` (the workflow reads its own checkout). `pr` replaces the local merge with a pushed branch and a PR, the cadence's push to the default branch with one PR from `context/weekly-measurement`, and the refresh hook's push of its bump with one PR from `skills/submodule-refresh` | `direct`: merge locally, then push, as before the knob; the cadence workflow renders, and the refresh hook runs, as before; present but unusable (another word, an empty file) is exit 2 (`install-cadence.sh`: exit 5 on an install or `--print`, nothing written, and exit 3 under `--check`; the refresh hook: no refresh and no push, said once a day), never `direct` |
| `worktree_venv` | single word: `link` or `none` | `using-git-worktrees` | replaces the default | `link` — the primary checkout's `.venv` is symlinked in |
| `default_branch` | single-line ref name | `using-git-worktrees`' `worktree-destroy.sh` ([#559](https://github.com/gregoryfoster/skills/issues/559)); in `pr` mode, `shipping-work`'s `run-deploy-command.sh`, which deploys only this branch, and its PR's `--base` ([#342](https://github.com/gregoryfoster/skills/issues/342)). Both read it from the primary checkout, like `worktree_root`, so an untracked file works from a linked worktree | first step of a 3-step resolution | falls to `origin/HEAD`, then `main` |
| `plans_dir` | single-line path; a relative one resolves against the primary checkout ([#590](https://github.com/gregoryfoster/skills/issues/590)), and `~` is not expanded | `writing-plans`' `resolve-plans-dir.sh`, from the primary checkout, which `orchestrating-issue-backlog` also runs; `init-project-fastapi` points a new project at it | env `PLANS_DIR` wins, then this file | `<repo-root>/docs/plans/` |
| `skills-pin` | one `<submodule-path> <commit-ish>` per line, `#`-comments | `managing-skills`' refresh hook, and its doctor's override pointer finding | env `SKILLS_PIN_FILE` wins, then this file | no pins — every submodule is refreshed |
| `refresh-skip-hooks` | pre-commit hook ids, whitespace-separated, any number per line; blank lines and whole-line `#`-comments ignored | `managing-skills`' refresh hook, from the committing checkout, on `main`; its doctor checks each id against `.pre-commit-config.yaml` ([#572](https://github.com/gregoryfoster/skills/issues/572)) | no env var. **Extends** a session's own `SKIP`, for the hook's `git commit` and `git push` only, so a commit made by hand runs every hook | nothing skipped: the hook commits and pushes through every hook, inside its 120 s timeout. Present but unusable skips nothing too, said on stderr once in each run that commits or pushes, and by the doctor |
| `forked-ok` | one repo-relative path per line, `#`-comments | `managing-skills`' doctor | declares rather than configures — there is no default to replace | nothing is declared, so every divergence is reported (advisory in every mode, never healed) |
| `doc-sensitive-paths` | one path per line, `#`-comments | `shipping-work`'s doc-check | **replaces** `SENSITIVE_PATHS` wholesale | the built-in path list: each detected framework's paths, or a generic list ([#537](https://github.com/gregoryfoster/skills/issues/537)); a hit says so when `doc-sections` is tailored ([#284](https://github.com/gregoryfoster/skills/issues/284)) |
| `doc-sections` | one section per line, `#`-comments | `shipping-work`'s doc-check | **replaces** `DOC_SECTIONS` wholesale | the built-in advice, naming each detected framework's inventory; a hit says so when `doc-sensitive-paths` is tailored (#284) |
| `next-steps` | one row per line, `#`-comments: `doc-sections`' grammar, through a byte-equal copy of doc-check's reader. A row is free text naming its trigger and action | `shipping-work`'s `read-next-steps.sh`, Step 8 ([#564](https://github.com/gregoryfoster/skills/issues/564)) | no env var; read from the primary checkout, where Step 8 runs. **Replaces** the detected stack file's Step 8 table and SKILL.md's common categories; deploying stays with `deploy_command`. With `pre_restart` set, its check gates every row, since a project's rows can't be told apart | the stack file's table, else SKILL.md's. Present but unusable (no row after comments, not a regular file, a dangling link, unreadable, or a `.skills` that can't be searched) is exit 2, never the stack file's rows |
| `import-targets` | one package name per line, `#`-comments | `shipping-work` (every uv repo, #537) and `reviewing-code-python-click` | replaces the pyproject-derived default | the `[project] name` from `pyproject.toml` |
| `pre-ship-uv-args` | `uv run` arguments, whitespace-separated, any number per line, `#`-comments | `shipping-work` (every uv repo, #537) pre-ship | **extends** every uv call the gate makes in the project, inserted after `uv run` (the `[project]`-name probe runs `--no-project`, #553) — so the gate runs the suite the project's own hook runs ([#304](https://github.com/gregoryfoster/skills/issues/304)) | a bare `uv run`; present but unreadable is exit 2, never a bare `uv run` |
| `test-workers` | single word: `off`, `auto`, or a number; `#`-comments | `shipping-work`'s `gate-workers.sh`, and this repo's `scripts/structural-tests.sh` through it ([#537](https://github.com/gregoryfoster/skills/issues/537)) | env `PYTEST_XDIST_AUTO_NUM_WORKERS` wins (a coordinator sets it per agent), then this file | `auto`: serial on 2 cores or fewer, otherwise min(8, cores ÷ (active gates + 1)). Read as `test-dist` is ([#589](https://github.com/gregoryfoster/skills/issues/589)): a second word on the line warns and is ignored, and present but not a readable file warns and is `auto`. Any other word is exit 2 |
| `test-dist` | single word: `loadfile`, `load`, `loadscope`, `loadgroup` or `worksteal`; `#`-comments | `shipping-work`'s `gate-workers.sh --dist`, and this repo's `scripts/structural-tests.sh` through it ([#563](https://github.com/gregoryfoster/skills/issues/563)) | env `PYTEST_XDIST_DIST` wins, then this file; `PYTEST_ADDOPTS` cannot override the gate's `--dist` | `loadfile`; an unknown value warns and is `loadfile`, a second word on the line warns and is ignored, and present but not a readable file warns and is `loadfile`. Not in the stamp key |
| `gate-stamp-inputs` | one path or glob per line, `#`-comments | `shipping-work`'s `gate-stamp.sh` (#537) | env `GATE_STAMP_INPUTS` (colon-separated) wins, then this file, which **replaces** the default | `.env` is the only untracked input whose content hash joins a stamp's key |
| `context-budget` | a single number | `curating-context`, the context-budget hook | env `CONTEXT_BUDGET` wins, then this file | 6,000 tokens |
| `context-doc-budget` | a single number | `curating-context` | env `CONTEXT_DOC_BUDGET` wins, then this file | 10,000 tokens per doc |
| `context-proximity-pct` | a single number, 1-100 | `curating-context`, the context-budget hook | env `CONTEXT_PROXIMITY_PCT` wins, then this file | 90 — a file is reported as approaching its budget from 90% of it |
| `context-docs-dir` | single-line path | `curating-context` | env `CONTEXT_DOCS_DIR` wins, then this file | `docs` |
| `cohort` | one repo per line, `#`-comment header carrying `wave:` / `pair:` | `curating-context`'s cohort scoring | no default — the file *is* the cohort | scoring has nothing to score |
| `typesafe` | single word: `on` or `off`, `#`-comments | the TypeSafe client `scripts/_typesafe.py`, copied into each skill whose advisory pass calls TypeSafe ([#448](https://github.com/gregoryfoster/skills/issues/448)) | env `TYPESAFE_OPT_IN` wins, then this file, read from the primary checkout | off: no text is sent, and each TypeSafe step prints one skip line naming why. Any other word also reads as off |
| `patching-hosts` | one directive per line, `#`-comments, optional `[host <glob>]` sections — [grammar](../skills/patching-hosts/references/knob.md) | `patching-hosts`' `read-knob.sh`, `probe.sh` and `apply.sh`, over one library | declares rather than configures: a section overrides the global lines for the hosts it matches, a `hold` line naming a default step replaces that default, and a `bulk-factor` line replaces the bulk's span factor of 3 ([#556](https://github.com/gregoryfoster/skills/issues/556)) | every host is `production`, compared against the reference `automatic` posture; deviations are reported and nothing is applied |

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
