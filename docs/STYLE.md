# Style — scripts and SKILL.md bodies

Conventions with a reference implementation. The short rules that apply to every
script live inline in [AGENTS.md](../AGENTS.md) under `## Scripts`; this file
carries the two that need a full template and a rationale.

## Invoking a skill's own scripts (`<SKILL_SCRIPTS>`)

**Never write `bash scripts/X.sh` in a SKILL.md.** The agent's cwd is the *project* root, but `scripts/` ships inside the skill directory, so a bare relative path resolves to a file that doesn't exist — the invocation fails with "No such file or directory" in every project that doesn't happen to carry its own `scripts/` copy ([#63](https://github.com/gregoryfoster/skills/issues/63)). [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) (`TestNoBareScriptPaths`) fails the suite if the form reappears.

Instead, resolve once and substitute. Each skill's SKILL.md carries one resolution block — for `reviewing-*` / `shipping-*` this is folded into the Phase 1 / Step 1 doctor preflight; other skills get a standalone "Script path resolution" section. The header, loop, probe, and `done` are common to all 11 skills; the doctor preflight and the final two lines are conditional, as annotated:

```bash
N=<skill-name> S=<sentinel-script>.sh SD=

# reviewing-* / shipping-* only — resolution follows the doctor so a freshly
# healed symlink chain is visible to the probe.
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1

for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done

# Only when later steps substitute <SKILL_SCRIPTS> — shipping-*,
# using-git-worktrees, writing-plans. Omit for reviewing-*, which has a
# single call site and no later steps to feed.
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"

# Only when this block also runs the script — reviewing-*, shipping-*. Omit
# for using-git-worktrees and writing-plans, which publish the path but
# invoke their scripts from later steps.
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

Notes on the shape:

- **Probe for the sentinel file, not the directory.** `[ -d "$d" ]` would falsely match any project that has an unrelated root `scripts/` — this repo does.
- **Clear `SD` on the header line.** Without it, a value inherited from the environment — or left by an earlier block in the same shell — survives the loop and defeats `${SD:?…}`, silently reproducing the #63 "No such file or directory" symptom against a misleading path.
- **Guard at the call site, not just once.** Every expansion that feeds a path uses the full `${SD:?…}` form, so no invocation depends on an earlier line having aborted first.
- **Project-local `scripts/` wins.** Preserves consumers that already worked around #63 with their own copy.
- **`$HOME/.claude/skills/…` last** covers user-level and plugin installs.
- **Resolution must run *after* `.skills/doctor.sh`,** so a freshly healed vendor symlink chain is visible to the probe.
- **`<SKILL_SCRIPTS>` is a placeholder, not a shell variable** — same convention as `init-project-fastapi` Phase 0's `<SKILL_DIR>`. Each Bash tool call is a fresh shell, so nothing is inherited between steps; later steps substitute the literal path printed above and are written `bash "<SKILL_SCRIPTS>/X.sh"`.

`TestScriptResolutionBlock` in [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) enforces the four common lines across every skill carrying a block, and fails the suite if a skill uses `<SKILL_SCRIPTS>` without publishing it.

## Gate-script discipline (pre-ship, doc-check)

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

Document any intentional silent fallback (e.g., `git rev-parse --show-toplevel 2>/dev/null || pwd`) with a one-line comment describing what the fallback actually does, not the rationale you assume it has.

This convention is enforced for `shipping-work*/scripts/pre-ship.sh` by [tests/structural/test_content_invariants.py](../tests/structural/test_content_invariants.py) (`TestPreShipGateHardening`). Reverting a hardened site to `done < <(...)` form fails the structural suite. If process substitution is genuinely required, tag the loop with `# unhardened: <reason>` either on the `done` line itself or anywhere within the prior 10 lines as an opt-out.

## Project-local overrides: wrap, don't fork

A gate script that invites project-local customization must name the mechanism, or every consumer invents its own. The supported mechanism is a **wrapper**, never a fork: the `<SKILL_SCRIPTS>` resolution block above probes `scripts/` first, so a project-local `scripts/<gate>.sh` wins, does its extra work, and `exec`s the vendored script through the `skills/…` symlink. A fork copies the whole gate to add a few lines and then drifts silently on every submodule update — the consumer keeps running a pre-fix script with no signal that it does.

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
