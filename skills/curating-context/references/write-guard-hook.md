# The Write Guard Hook

Weekly curation cannot fix regrowth. A run reduces `AGENTS.md`, the next
fortnight of edits puts it back, and the telemetry trend sawtooths forever —
[budget-and-metrics.md](budget-and-metrics.md) names that shape and why it means
the file is not the problem. The guard closes the loop at the only moment the
growth is cheap to fix: the moment it happens.

`context-budget-guard.sh` is a Claude Code `PostToolUse` hook. It watches edits to
the context surface and speaks only when an edit pushes it further over budget.

## Install

```bash
bash "<SKILL_SCRIPTS>/install-guard.sh" --budget 6000 --doc-budget 10000
```

Idempotent — a re-run repairs partial state (symlink present, settings entry
missing, or the reverse) without ever producing a duplicate entry. Omit the
budget flags to leave existing knobs alone.

Three other modes:

```bash
bash "<SKILL_SCRIPTS>/install-guard.sh" --check      # exit 0 installed, 3 not
bash "<SKILL_SCRIPTS>/install-guard.sh" --uninstall  # removes entry + symlink
```

The installer does **not** commit. It prints the `git add` line; land the wiring
through the project's normal commit gate, the same rule
`enforcing-architecture` applies to CI edits — a hook that starts running because
something committed it unannounced is a bad surprise.

### What it writes

1. `.claude/hooks/context-budget-guard.sh` — a **symlink** to the vendored
   script, relative when the source is inside the repo. Symlink rather than copy
   so upstream fixes arrive on the normal submodule refresh. This is the opposite
   choice from `.skills/doctor.sh`, which must be a copy precisely because it
   exists to repair broken symlinks; the guard has no such constraint, and a copy
   would freeze exactly the way [#84](https://github.com/gregoryfoster/skills/issues/84)'s did.
   When the skill is installed at user level (`~/.claude/skills/…`) no relative
   path exists — the installer falls back to an absolute link and says so, since
   that link will not resolve for a collaborator.

   Because it is a symlink, the guard cannot find its library by
   `dirname "$0"` — that yields `.claude/hooks/`, which holds no library. It
   resolves the link chain to the real file first and sources
   `_context-lib.sh` from beside *that*. `install-guard.sh` refuses to install
   when the library is absent, and `--check` verifies it beside the resolved
   target: a guard missing its library wires up cleanly and then exits 0 on every
   edit, and not even an `ok:` line appears, because logging starts after the
   source.
2. A `PostToolUse` entry in `.claude/settings.json` matching
   `Edit|Write|MultiEdit`, with a 10s timeout. The command is
   `bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/context-budget-guard.sh"` —
   anchored on the project dir rather than on the hook process's cwd, which was
   an undocumented assumption the earlier relative form was load-bearing on
   ([#110](https://github.com/gregoryfoster/skills/issues/110)). The `:-.`
   fallback is `init-socraticode`'s house style: with the variable unset, a bare
   `"$CLAUDE_PROJECT_DIR/…"` degrades to `bash "/.claude/hooks/…"` and errors on
   every edit, where `.` degrades to exactly the old behaviour. The guard
   resolves the repo the same way, falling back to `$CLAUDE_PROJECT_DIR` when its
   cwd is not inside one.

   The jq merge strips any prior entry for this hook before appending, and
   defaults `.hooks` / `.hooks.PostToolUse` into existence, so it works against
   `{}`, a settings file with no hooks block, and one with other hooks already
   wired. The strip matches on the **script path**, not on the exact command
   string, so an install written by an older version is found, replaced, and
   still removable by `--uninstall`; matching the exact string would have made
   every existing install permanent. `--check` reports such an entry as installed
   and names it, since it works — a re-run normalizes it. A settings file that is
   not valid JSON is **refused, not overwritten** — it may hold permissions and
   env config that would be expensive to lose.
3. `.skills/context-budget` and `.skills/context-doc-budget`, only when the flags
   are passed.

## When it speaks

Two conditions must **both** hold:

- the file is over its budget, **and**
- it is larger than its committed (`HEAD`) version.

Requiring both is the whole design. Over-budget alone would fire on every edit to
a file that is already over — which, measured exactly, is the state **ten of the
twelve** cohort repos are in today, and a hook that fires on every edit is one
everybody turns off. An
increase alone would fire on healthy growth inside budget. Together they mean the
guard speaks exactly when someone is making a known-bad number worse.

**An edit that reduces the count is never flagged.** Curating is never nagged.

The comparison point is `HEAD`, not the previous edit, so the reported delta
covers all uncommitted changes to the file — the message says "since HEAD" rather
than "this edit" for that reason.

If a genuine addition has to land and push the file over, that is fine — the
advisory is not a veto. Land it, and let the next run classify it. What the guard
buys is that the decision was seen rather than accreted.

## What it watches

| Path | Budget | Knob |
|---|---:|---|
| `AGENTS.md` / `CLAUDE.md` at the repo root | 6,000 | `CONTEXT_BUDGET`, then `.skills/context-budget` |
| `<docs-dir>/**/*.md`, excluding archival subtrees | 10,000 | `CONTEXT_DOC_BUDGET`, then `.skills/context-doc-budget` |

Archival subtrees (`plans`, `specs`, `research`, `audits`, `archive`) are ignored
at any depth, matching `measure-context.sh` — including the nested
`docs/superpowers/plans/` that vendored skill trees create. Reference docs get a
higher budget because their cost is paid on load rather than on every invocation.

The reference-doc root is itself a knob: `CONTEXT_DOCS_DIR`, then
`.skills/context-docs-dir`, then `docs`. `measure-context.sh` takes the same knob
as its `--docs-dir` default, so setting it once points the weekly run and both
continuous surfaces at one tree. It needs setting only in a repo that keeps
references somewhere other than `docs/` — every cohort member uses the default —
but without the knob such a repo would get a correct weekly measurement and a
guard that silently classified nothing.

Env var, then `.skills/` file, then default — the same three-step lookup the repo
already uses for `worktree_root` and `plans_dir`.

### Symlinked policy files

`CLAUDE.md` is a symlink to `./AGENTS.md` in every cohort member, and Claude
Code's `#` memory shortcut writes by the `CLAUDE.md` name. That matters because
`wc -c` follows a symlink and **`git show HEAD:CLAUDE.md` does not** — it returns
the link target *string*, `./AGENTS.md`, eleven bytes.

Left alone, that puts `PREV` at about four tokens forever, which makes the
`NOW <= PREV` branch unreachable and turns the guard's central promise inside
out: a measured 60% reduction of a still-over-budget file reported as
`+17,181 since HEAD`. The guard resolves a symlinked path to its real target
before measuring, logs `note: … measuring …` when it does, and skips a chain
that leaves the repo.

The mirror case is covered too: a path that was a symlink at `HEAD` and is a real
file now. A `120000`-mode blob is treated as *no comparable committed version*
rather than as eleven bytes of content, so the first edit after such a conversion
reports honestly instead of claiming the whole file as growth.

## How it reports

Exit 0 with JSON on stdout, carrying the advisory twice:

- `hookSpecificOutput.additionalContext` — reaches the **agent**, at the tool
  result, so it can act in the same turn rather than at the next weekly run.
- `systemMessage` — reaches the **human**.

`PostToolUse` cannot block; the tool has already run. Exits 1 and 2 both surface
as a "hook error" notice, which is the wrong frame for an advisory — this is
information, not a failure. So the guard exits 0 on **every** path, including
every internal failure. A hook must never be the reason a session misbehaves.

Every decision, speak or stay quiet, is logged to
`$(git rev-parse --absolute-git-dir)/context-budget.log` (truncated to the last
200 lines past 64 KiB). That log is how you confirm the hook is wired at all:

```bash
tail "$(git rev-parse --absolute-git-dir)/context-budget.log"
```

The git *dir*, not `.git`, because in a linked worktree `.git` is a file
containing `gitdir: …` — the earlier hardcoded path could never be appended to
there, and the failure was swallowed, so repos that mandate worktree development
got no audit trail in exactly the trees where editing happens
([#109](https://github.com/gregoryfoster/skills/issues/109)). The log is
per-worktree, matching `skills-submodule-update.sh`; the installer prints the
resolved path when it finishes.

An `ok:` line proves the hook ran and chose silence — a distinction you cannot
otherwise make from the outside, and the first thing to check when someone
reports "the guard never fires".

## Deliberate limits

- **One measurement library, not three copies.** The ratio, the archival matcher,
  the docs-dir knob, and the symlink/git comparison live in
  `scripts/_context-lib.sh`, sourced by the guard, `context-delta.sh`, and
  `measure-context.sh`. They previously existed as copies and drifted: the
  `bytes/4` correction had to land in three places, a fourth copy in the section
  census was missed, and the parts then contradicted the whole by 38%. The skill's
  own rubric calls verbatim duplication warrant #1 for deletion — this is that
  rule applied to its scripts. A missing library is fatal for
  `measure-context.sh` (exit 2: a measurement that quietly used different
  constants is worse than none) and silent-but-logged for the hook.
- **Offline estimate, never `count_tokens`.** A hook runs on every edit and must
  be fast, so it divides bytes by a calibrated ratio rather than calling the API.
  The default is 2.7 bytes/token; `measure-context.sh --exact` refines it per
  repo into `.skills/context-token-ratio` and then per FILE into
  `.skills/context-token-counts`, which the guard prefers where it has one
  ([#145](https://github.com/gregoryfoster/skills/issues/145) — one ratio for a
  whole repo is wrong by -23% to +14% across this repo's surface depending on
  which file it is pointed at). The repo ratio is the fallback for a file with no
  row, and is fitted over the whole surface rather than the policy file alone
  ([#172](https://github.com/gregoryfoster/skills/issues/172) — fitting it to the
  most prose-heavy file over-reported the doc class nearest its budget by up to
  15%, which is how the guard came to warn `385 tokens over` on a file 848 tokens
  under). It is still an estimate — it only
  decides whether to speak, which is why the guard never gates anything. Note
  what the earlier `bytes/4` divisor cost: it under-reports this cohort's markdown
  by 56–65%, so with a 6,000 budget the guard would silently tolerate a real file
  of nearly 15,000 tokens.
- **No writes to the repo.** The guard measures and reports. Only the ledger and
  the skill's own phases mutate tracked files.
- **Symlink resolution on both sides.** The repo root and the incoming
  `file_path` are both resolved with `pwd -P` before the prefix test. Without
  that, a checkout reached through a symlinked parent — `/tmp` → `/private/tmp`
  on macOS, or any symlinked home — produces a root that no absolute
  `file_path` is a prefix of, and the guard silently ignores every edit while
  appearing installed. This was a real bug found in testing, and it is the exact
  failure mode the `ok:` log lines exist to expose.
- **Needs `python3` or `jq`** to parse the hook payload. With neither it logs a
  skip line and exits 0 rather than parsing JSON with a regex.
- **One edit at a time — net is invisible.** The hook sees the file it was just
  handed, so a 400-token addition that replaced 600 elsewhere reads the same as
  a straight 400-token gain. No `PostToolUse` payload carries the rest of the
  branch. That is `context-delta.sh`'s job at review time
  ([continuous-surfaces.md § Review-time delta](continuous-surfaces.md#review-time-delta)).
- **Structured edits only — not every write.** The matcher is
  `Edit|Write|MultiEdit`, so two write paths are invisible to it: a **shell
  redirect** (`cat >> AGENTS.md <<'EOF'`, `tee -a`, `sed -i`), which arrives as a
  `Bash` call the guard never sees, and **`NotebookEdit`**, narrower in practice.
  A bulk heredoc append is exactly what regrowth looks like between runs, and in
  one adoption run it added the single largest block in the whole curation
  without the guard firing
  ([#103](https://github.com/gregoryfoster/skills/issues/103)). Adding `Bash` to
  the matcher is **not** the fix: it would run the guard on every shell command
  in the session, the overwhelming majority of which touch nothing, to catch a
  small fraction of writes — inverting the cheapness that makes the guard
  tolerable. The gap is covered at review time instead, by `context-delta.sh`,
  which measures the branch's whole effect regardless of how the bytes arrived.

## Relationship to the weekly run

The guard and the skill are the two halves of one ratchet: the guard stops
regrowth, the weekly run recovers ground. Neither substitutes for the other. A
repo with the guard but no weekly run stays at whatever size it was when the
guard went in; a repo with the weekly run but no guard sawtooths.

That second half was unwireable until
[#118](https://github.com/gregoryfoster/skills/issues/118): the skill named a
weekly run throughout and shipped no way to schedule one. `install-cadence.sh`
now installs it — as a weekly *measurement* rather than a weekly curation, so
what it recovers is the evidence that ground was lost, not the ground itself.
See [cadence.md](cadence.md).
