# Style — scripts and SKILL.md bodies

Conventions with a reference implementation. The short rules that apply to every
script live inline in [AGENTS.md](../AGENTS.md) under `## Scripts`; this file
carries the conventions that need a full template and a rationale.

## Invoking a skill's own scripts (per-script resolution)

**Never write `bash scripts/X.sh` in a SKILL.md.** The agent's cwd is the *project* root, but `scripts/` ships inside the skill directory, so a bare relative path resolves to a file that doesn't exist — the invocation fails with "No such file or directory" in every project that doesn't happen to carry its own `scripts/` copy ([#63](https://github.com/gregoryfoster/skills/issues/63)). [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) (`TestNoBareScriptPaths`) fails the suite if the form reappears.

Instead, resolve and substitute — **per script, never per directory.** Each skill's SKILL.md carries one resolution block — for `shipping-*` it is folded into the Step 1 doctor preflight; `using-git-worktrees`, `writing-plans`, `curating-context` and `auditing-ci-cost` get a standalone "Script path resolution" section. It resolves **every script the skill's steps and references run** and prints one `<name.sh>=<path>` line each:

```bash
N=<skill-name>

# shipping-* only — resolution follows the doctor so a freshly healed
# symlink chain is visible to the probe.
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1

for S in <script>.sh … <step-script>.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  echo "<$S>=${SD:?$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
done

# shipping-* only: runs the script resolved LAST, so the step's own
# script (pre-ship.sh) ends the list.
bash "${SD:?}/$S"
```

Later steps are written `bash "<doc-check.sh>"` and substitute the path printed for that script. `reviewing-*` run one script from one block and feed no later step, so theirs is the degenerate case: header `N=<skill-name> S=gather-context.sh SD=`, the doctor, the inner loop, then `bash "${SD:?not found in …}/$S"`, publishing nothing.

Notes on the shape:

- **Resolve per script, never reuse a directory** ([#301](https://github.com/gregoryfoster/skills/issues/301)). The publishing block used to probe one anchor (`pre-ship.sh`), print its directory as `SKILL_SCRIPTS=`, and run every later step's *different* script from it. The wrapper override below breaks that: CannObserv/watcher and usa-wa keep a `pre-ship.sh` wrapper in `scripts/` (power-map a fork) and none of the skill's other five scripts, so Steps 1.5, 2, 4, 5 and 6 all exited 127 — a code no step anticipated, in the two steps whose purpose is to refuse a silent pass. Requiring `scripts/` to be complete instead would have taken `pre-ship.sh` off the wrapper and failed the gate on missing secrets.
- **Every script up front.** One found nowhere stops the block at Step 1, by name, where the Iron Law can still act — not as a 127 five steps later.
- **Clear `SD` on every pass** (`do SD=`; on the header line in the single form). Otherwise a script found nowhere inherits the previous one's directory and exits 0, and a value inherited from the environment defeats `${SD:?…}`.
- **Probe for the script file, not the directory.** `[ -d "$d" ]` would falsely match any project that has an unrelated root `scripts/` — this repo does.
- **Guard at the call site.** Every expansion that feeds a path carries `${SD:?…}`; the loop's names the script, and the run line's bare `${SD:?}` is the backstop.
- **A project-local `scripts/<name>` wins, for that script alone.** Preserves consumers that worked around #63 with their own copies, and the wrapper override. A project script that merely shares a name wins too, and its printed `scripts/…` line is how that shows; no cohort repo had one when #301 was measured.
- **`$HOME/.claude/skills/…` last** covers user-level and plugin installs.
- **Resolution must run *after* `.skills/doctor.sh`,** so a freshly healed vendor symlink chain is visible to the probe.
- **`<name.sh>` is a placeholder, not a shell variable** — same convention as `init-project-fastapi` Phase 0's `<SKILL_DIR>`. Each Bash tool call is a fresh shell. There is deliberately no directory placeholder: a directory is what leaked from one script's resolution to another's.

`TestScriptResolutionBlock` in [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) pins the lines both shapes share. [tests/structural/test_per_script_resolution.py](../tests/structural/test_per_script_resolution.py) owns the list — every placeholder published, every published script shipped and used, no directory placeholder left — and runs each block against watcher's layout, a single project copy, and a missing script.

## Gate-script discipline

Scripts whose output drives a control-flow decision (will-we-ship vs. will-we-skip) must never silently swallow stderr from the tool that produces that output. The two-bucket rule:

- **Gate-like commands** — output drives a `for` loop, a "did we find anything?" branch, a "is the tree clean?" check, or a stamp-write. Capture exit code explicitly and treat non-zero as ERROR + exit 2. Use a tempfile when the command runs inside a process substitution (`done < <(...)`), since process-substitution exit codes aren't visible in the parent shell.
- **Reporting-only commands** — output is shown to the user as context (status output, log snippet, diff stat). Silent `2>/dev/null || true` is fine: degraded output is acceptable, false-success on a gate is not.

Reference patterns — search by the named anchor below rather than line number, since line numbers drift. Each bullet calls out which reference script(s) carry the canonical implementation; the two canonical scripts are [skills/shipping-work-php/scripts/pre-ship.sh](../skills/shipping-work-php/scripts/pre-ship.sh) and [skills/shipping-work/scripts/doc-check.sh](../skills/shipping-work/scripts/doc-check.sh).

All three exit-code-capture patterns below (`LS_RC`, `FIND_RC`, `DIFF_RC`) require an `RC=0` pre-init *before* the capturing line. Under `set -u`, a success path doesn't fire `|| RC=$?`, so any subsequent expansion of `$RC` would abort with `RC: unbound variable`. Don't omit the pre-init when adapting these patterns.

- **Tempfile + exit-code capture for process substitution** — grep for `LS_RC` (pre-ship.sh). Use when a command runs inside `done < <(...)` and you need its exit status: capture stdout to a tempfile, capture `$?` into a scalar, branch on it.
- **Three-case `find` handler** — grep for `FIND_RC` (pre-ship.sh). Non-zero exit → ERROR + exit 2; exit-0 with stderr → WARN + proceed; exit-0 silent → proceed.
- **Command substitution + exit-code capture (simpler variant)** — grep for `DIFF_RC` (doc-check.sh). Use when the output fits in a scalar and there's no process substitution; `$?` is directly observable via `RC=0; OUT=$(cmd) || RC=$?`, no tempfile needed.
- **Consolidated EXIT trap** — grep for `trap '` at the top of the file (pre-ship.sh). Multiple tempfile *scalars* (not an array) in one trap line for bash 3.2 + `set -u` compatibility.
- **`--help` exit-code block** — search the `--help` block (pre-ship.sh, doc-check.sh). Enumerates which infra failures map to exit 2 (vs. silently degrading).
- **Checked open of a project list file** — grep for `exec 3<` (doc-check.sh). A `while read` loop fed by `done < "$file"` cannot branch on the open, so `set -e` reports an unreadable committed file as bash's `Permission denied` at **exit 1** — a gate's act-on-this code. Open under `if ! exec 3<"$file"`, read from `<&3`, close with `exec 3<&-`. On bash 3.2.57 a failed `exec` in an `if` returns rather than exits.
- **Classify a config path before opening it** — grep for `override_present` (doc-check.sh). `-f` follows symlinks, so it reads false for a dangling link, a loop and a directory, silently restoring the defaults on a repo that tailored the file. Test `-e || -L`, then reject a broken link and a non-regular file by name — which also stops a FIFO blocking the open forever ([#261](https://github.com/gregoryfoster/skills/issues/261)).

Document any intentional silent fallback (e.g., `git rev-parse --show-toplevel 2>/dev/null || pwd`) with a one-line comment describing what the fallback actually does, not the rationale you assume it has.

This convention is enforced by [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) (`TestGateScriptHardening`). Reverting a hardened site to `done < <(...)` form fails the structural suite. **The rule is wider than that detector**: `cmd || true` straight to stdout and `[ -n "$(cmd)" ]` in a condition swallow a failure just as completely, and no regex over the text catches them — they are pinned by behaviour instead, in [tests/structural/test_gate_producer_exit_codes.py](../tests/structural/test_gate_producer_exit_codes.py). If process substitution is genuinely required, tag the loop with `# unhardened: <reason>` either on the `done` line itself or anywhere within the prior 10 lines as an opt-out.

**Which files it examines is derived from the discipline, not from one filename** — and not from this heading, which named `(pre-ship, doc-check)` until [#255](https://github.com/gregoryfoster/skills/issues/255): two filenames in a title read as the scope, and the enforcement followed the title rather than the rule. Every script under `skills/shipping-work*/scripts/` and `skills/reviewing-code*/scripts/` is classified in that file as `GATE_SCRIPTS` or `NON_GATE_SCRIPTS`, with a reason, and a new script cannot ship unclassified — the same forcing function [tests/structural/test_pre_ship_env_override.py](../tests/structural/test_pre_ship_env_override.py) applies to a new variant. Until [#255](https://github.com/gregoryfoster/skills/issues/255) the gate ran against `pre-ship.sh` alone, though this section named both scripts and cites `doc-check.sh` as canonical: a `done < <(git ls-files)` duly shipped in `doc-check.sh` with the suite green, feeding a did-we-match-anything branch whose empty answer is reported as *"the list is misconfigured for this repo"* — a confident diagnosis of the wrong problem, at the same exit code as the real one.

Three classifications are worth stating, since none is obvious from the filename:

- `reviewing-code*/scripts/gather-context.sh` is **reporting-only** — its output is context for a human, not a branch — and keeps its process-substitution sites.
- `check-status.sh` is a **gate**: its exit code *is* the working-tree verdict Step 2 branches on. It decided that verdict with `[ -n "$(git status --porcelain)" ]` until [#257](https://github.com/gregoryfoster/skills/issues/257) — a failing git substitutes the empty string, which is exactly what a clean tree substitutes to, so a dirty tree was reported clean with the modification printed four lines above the verdict denying it. Note where `set -e` does and does not help: it aborts on a failing simple command, but not on one inside `if [ -n "$(…)" ]`, so the three reporting commands failed loudly and the single deciding one failed silently.
- `detect-import-targets.sh` and `detect-test-dirs.sh` are **gate producers**, because `pre-ship.sh` skips the import check or pytest entirely when either answers with an empty list. Both used to run `uv run python -c …` under a `|| true`, so a `uv` that could not run at all was indistinguishable from a project with no package name and no test directories — while the caller's own careful exit-code capture around them reported a pass. Their behaviour is pinned by [tests/structural/test_gate_producer_exit_codes.py](../tests/structural/test_gate_producer_exit_codes.py): a resolver that cannot run exits 2, a resolver that answers nothing exits 0.

## Project-local overrides: wrap, don't fork

A gate script that invites project-local customization must name the mechanism, or every consumer invents its own. The supported mechanism is a **wrapper**, never a fork: the resolution block above probes `scripts/` first for each script, so a project-local `scripts/<gate>.sh` wins for the gate alone, does its extra work, and `exec`s the vendored script through the `skills/…` symlink. A fork copies the whole gate to add a few lines and then drifts silently on every submodule update — the consumer keeps running a pre-fix script with no signal that it does.

Every `shipping-work*/scripts/pre-ship.sh` carries this as a commented `# --- Project-local env loading (optional override point) ---` block, the worked example being the env loading a conftest with a hard DSN requirement forces. Rules the recipe encodes, each a trap a lone consumer hits:

- **Delegate through the symlink** (`skills/<skill>/scripts/…`), never `skills-vendor/…`. The symlink is the stable interface; the vendor layout is submodule bookkeeping.
- **`exec`**, so the exit code the Iron Law gates on propagates unchanged — and, for `shipping-work-python-click`, so `$0` still points at the vendored copy and its sibling helpers resolve.
- **Forward `"$@"`**, so `--help` reaches the real script.
- **Guard the missing delegate and exit 2**, matching the gate's own tooling/infra code. An unpopulated submodule otherwise fails as bash's generic "No such file or directory".
- **Parse the env file line by line; never source it** (see [skills/curating-context/scripts/measure-context.sh](../skills/curating-context/scripts/measure-context.sh)), and never `export $(cat … | xargs)`. That one-liner shipped here until [#144](https://github.com/gregoryfoster/skills/issues/144) and had three defects, each found by executing it rather than reading it:
  - with both files absent the substitution was empty and `export` degenerated to a bare `export`, printing every exported variable — secrets included — into the gate transcript;
  - a `#` comment line reached `export` as `'#': not a valid identifier`, and the wrapper's own `set -e` killed it **before** `exec`, so the gate never ran and the operator got a bare shell error to adjudicate — precisely the environmental-vs-real judgement call the override point exists to remove;
  - `xargs` word-split `PW=two words` into a wrong value and exited 0, which is worse than the crash because it is silent.
- **Quote the export**: `export "$key=$val"` is what makes spaces, globs and quoted values survive, so the recipe needs no `set -f` dance and no shellcheck suppressions. **Skip a key that is not a plain identifier** rather than aborting — a malformed line in a secrets file must not decide whether the gate runs.

`shipping-work`'s own `pre-ship.sh` is the documented exception: it is a stub that exits 1, so there is nothing to delegate to and its block puts the env loading in the project's override instead. [tests/structural/test_pre_ship_env_override.py](../tests/structural/test_pre_ship_env_override.py) holds the block across all four variants and classifies that exception explicitly, so a fifth variant cannot ship without one.

## A repo-creating git command must scrub `GIT_DIR`

**An inherited `GIT_DIR` overrides both `git -C <path>` and the process cwd.** Git resolves the config file and the repository from `GIT_DIR` and ignores the directory entirely — so `git -C "$tmpdir" config …` writes to whatever `GIT_DIR` names, not to `$tmpdir`.

This is not hypothetical here. **Git exports `GIT_DIR` to every hook process**, and from a linked worktree it is absolute, pointing at the shared git dir. So under a pre-commit hook, a test's throwaway-repo fixture addresses the *main checkout*. During [#199](https://github.com/gregoryfoster/skills/issues/199)'s Batch A this put `merge.ours.driver` into the real repo's config from a temp-directory fixture, and it is the mechanism behind the `core.bare = true` corruption of [#189](https://github.com/gregoryfoster/skills/issues/189) — twice in one four-agent batch, neither attributed, because every reviewer was checking for a missing `-C`.

The rule, for any script or test that creates or configures a repository:

```sh
env -u GIT_DIR -u GIT_WORK_TREE git -C "$tmpdir" init
env -u GIT_DIR -u GIT_WORK_TREE git -C "$tmpdir" config user.email a@b
```

In Python fixtures, strip `GIT_*` from the environment you pass to `subprocess` rather than relying on `cwd=`. [tests/structural/test_doctor_uninit_submodules.py](../tests/structural/test_doctor_uninit_submodules.py)'s `_clean_env` is the reference shape, including the one variable it deliberately puts back (`protocol.file.allow`, which local-path submodules need since CVE-2022-39253 and which cannot travel via `git -c`).

Two properties make this worth a rule rather than a habit:

- **`-C` is not a fix.** It is authoritative about which *directory*, and `GIT_DIR` outranks it. Briefing agents to "always pass `-C`" was tried across four concurrent workers and the corruption still appeared.
- **Files are addressed by path; config is addressed by environment.** A script that writes `.gitattributes` under `$ROOT` was never exposed; the same script's first `git config` call was. When auditing, look at what a command *writes through*, not where it appears to point.

Separately, `git config --local` from a **linked worktree** writes the *shared* config of the main checkout. Scrubbing the environment does not change that — it is what `--local` means — and neither does `extensions.worktreeConfig` (below). A script that sets repo-wide config should detect a linked worktree (`.git` is a file rather than a directory) and refuse, naming the command for the operator to run in the main checkout; [skills/curating-context/scripts/install-cadence.sh](../skills/curating-context/scripts/install-cadence.sh)'s `ensure_driver` is the reference.

## `extensions.worktreeConfig` is refused here

[#189](https://github.com/gregoryfoster/skills/issues/189) proposed it "so a worktree's `--local` writes stay local". Measured on git 2.39.3 against a throwaway repo with a linked worktree, it does not do that, and no variant of it earns its cost. Every claim below is pinned by [tests/structural/test_worktree_config_extension.py](../tests/structural/test_worktree_config_extension.py), so a git release that changes one turns the decision red instead of leaving a stale rationale in prose.

- **It does not redirect `--local`.** The extension *adds* a `--worktree` scope; it does not move `--local`. A `git config --local` from a linked worktree lands in the shared `.git/config` with the extension on and off alike. Only an explicit `git config --worktree` writes per-worktree, and nothing in the observed corruption used it.
- **It does not stop the corruption that actually happened.** #189's `core.bare = true` arrives through an inherited `GIT_DIR`, not through `--local`. With the extension enabled, `GIT_DIR=<shared> git init --bare` still sets `core.bare = true` in the shared config and still makes `git status` in the main checkout exit 128 with empty stdout.
- **The one variant that changes the outcome makes detection worse.** Pinning `core.bare = false` into the main worktree's `.git/config.worktree` does restore the main checkout: `status` exits 0 and `rev-parse --is-inside-work-tree` prints `true` while the shared config still reads `bare = true`. That is not a repair, it is a **blindfold on Rule 6's canary** — and it shields only the main worktree, leaving every linked worktree at exit 128 with nothing visible on the orchestrator's host.
- **Two costs, no offsetting benefit.** A clone does not inherit the extension, so it cannot be a property of the repository anyone else gets; and this repo is at `core.repositoryformatversion = 0`, where `extensions.*` is out of contract. Git 2.39.3 honours it there anyway, which is worse than refusing it: the behaviour is version-dependent and unannounced.

The defences that do work are already in place — the `GIT_DIR` scrub above, and Rule 6 reading the exit code rather than stdout.

## The SKILL.md self-budget, and how its two readings are reconciled

It binds **both** readings — the offline estimate pre-commit sees, and
`count_tokens` under `SKILL_BUDGET_EXACT=1`. On SKILL.md files the estimate is
observed running 13% low to 7% high, and `POLICY_ESTIMATE_BAND` permits 15%
either way — that band edge, not the observed figure, is what the warning below
computes a worst case from. So neither reading alone is the contract — and only
the estimate is always on, which let
three ratchets be breached past a green suite. Two things close that
([#217](https://github.com/gregoryfoster/skills/issues/217)): every pre-commit
run now **warns** about each skill whose worst permissible exact count exceeds
its ratchet (a warning, not a failure), and
[.github/workflows/skill-budget-exact.yml](../.github/workflows/skill-budget-exact.yml)
runs the exact pass weekly as the gate that does fail. On the commit path the
exact pass stays opt-in, not opportunistic: it costs ~20s and one API call per
surface, and an unusable key must never be able to block a commit.

## A write through a temp file must be checked

- A write through a temp file must be checked — `set -e` exempts the first element
of an `&&` list — and a success message must sit inside the branch that succeeded
([#181](https://github.com/gregoryfoster/skills/issues/181)). Same family, second
spelling: `> "$F" || true` discards the failure of a write something later reads
back, so it shows up as state that never changed rather than as an error
([#193](https://github.com/gregoryfoster/skills/issues/193)). Both are gated by
`test_checked_temp_writes.py`; a deliberate one is allowed but must say so, with
`# unchecked-write-ok: <reason>` on the line or just above it

## Inline Python shared by copying must stay one definition

Every line of Python in `skills/curating-context/scripts/` lives inline in a `python3 - <<'PY'` heredoc — twelve blocks across eight scripts — so there is no module to import, and a helper two scripts both need is **copied** between them. The copies drift. `_erasable_prefixes` was copied under [#272](https://github.com/gregoryfoster/skills/issues/272) and had diverged textually before the day was out; `FENCE` existed three times in two spellings with two behaviours, `HEADING` three times in three. Three of those scripts gate one phase chain over the same file and each puts a count on the same telemetry row, and two of them disagreed about where a fenced block ends ([#275](https://github.com/gregoryfoster/skills/issues/275)).

Two pins, chosen by what can be exercised:

- **By behaviour**, where the rule has an end-to-end observable — `TestCurationRuleIsOneRule` feeds one mixed ledger through `is_curation_row` in two scripts and `classify_run` in a third and requires one answer; `test_fence_close.py` and `test_seam_relocation_gate.py` do the same for a stray `~~~` inside a ``` block. This is the stronger pin and the one to add when a twin's behaviour can be driven from outside.
- **By syntax**, for everything — [tests/structural/test_heredoc_twins.py](../tests/structural/test_heredoc_twins.py) discovers every top-level function and `re.compile` constant defined in more than one heredoc and requires each set to be one definition. Compared as an AST with docstrings dropped, so a comment or a docstring written for its own file is not drift, and a renamed parameter or a respelled condition is.

A difference that is **deliberate** goes in that file's `DELIBERATE` table with its reason — the one entry today is `check-seams.sh`'s `HEADING`, which starts at `##` because a document title is not a section — and the table is itself checked: an entry whose twin no longer differs fails, so it cannot go stale the way an acknowledgement file would. The discovery has a vacuity guard naming the twins known to exist, because a parser that quietly matched nothing would pass every other assertion, which is the failure #272's own review met twice.

What this does **not** do is deduplicate anything. Extracting a shared `_context_py.py` beside `_context-lib.sh` is the thorough fix and a convention change for every script in the family; it is written up as option 3 on [#275](https://github.com/gregoryfoster/skills/issues/275) and stays open. Until then, a helper needed in a second script is copied verbatim, the copy names its twin in a comment, and the suite holds them together.
