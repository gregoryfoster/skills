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
2. A `PostToolUse` entry in `.claude/settings.json` matching
   `Edit|Write|MultiEdit`, with a 10s timeout. The jq merge strips any prior
   entry for this command before appending, and defaults `.hooks` /
   `.hooks.PostToolUse` into existence, so it works against `{}`, a settings file
   with no hooks block, and one with other hooks already wired. A settings file
   that is not valid JSON is **refused, not overwritten** — it may hold
   permissions and env config that would be expensive to lose.
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

## What it watches

| Path | Budget | Knob |
|---|---:|---|
| `AGENTS.md` / `CLAUDE.md` at the repo root | 6,000 | `CONTEXT_BUDGET`, then `.skills/context-budget` |
| `docs/**/*.md`, excluding archival subtrees | 10,000 | `CONTEXT_DOC_BUDGET`, then `.skills/context-doc-budget` |

Archival subtrees (`plans`, `specs`, `research`, `audits`, `archive`) are ignored
at any depth, matching `measure-context.sh` — including the nested
`docs/superpowers/plans/` that vendored skill trees create. Reference docs get a
higher budget because their cost is paid on load rather than on every invocation.

Env var, then `.skills/` file, then default — the same three-step lookup the repo
already uses for `worktree_root` and `plans_dir`.

## How it reports

Exit 0 with JSON on stdout, carrying the advisory twice:

- `hookSpecificOutput.additionalContext` — reaches the **agent**, at the tool
  result, so it can act in the same turn rather than at the next weekly run.
- `systemMessage` — reaches the **human**.

`PostToolUse` cannot block; the tool has already run. Exits 1 and 2 both surface
as a "hook error" notice, which is the wrong frame for an advisory — this is
information, not a failure. So the guard exits 0 on **every** path, including
every internal failure. A hook must never be the reason a session misbehaves.

Every decision, speak or stay quiet, is logged to `.git/context-budget.log`
(truncated to the last 200 lines past 64 KiB). That log is how you confirm the
hook is wired at all:

```bash
tail .git/context-budget.log
```

An `ok:` line proves the hook ran and chose silence — a distinction you cannot
otherwise make from the outside, and the first thing to check when someone
reports "the guard never fires".

## Deliberate limits

- **Offline estimate, never `count_tokens`.** A hook runs on every edit and must
  be fast, so it divides bytes by a calibrated ratio rather than calling the API.
  The default is 2.7 bytes/token and `measure-context.sh --exact` refines it per
  repo into `.skills/context-token-ratio`; on this repo the calibrated estimate
  reproduces the exact count to the token. It is still an estimate — it only
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

## Relationship to the weekly run

The guard and the skill are the two halves of one ratchet: the guard stops
regrowth, the weekly run recovers ground. Neither substitutes for the other. A
repo with the guard but no weekly run stays at whatever size it was when the
guard went in; a repo with the weekly run but no guard sawtooths.

If a genuine addition has to land and push the file over, that is fine — the
advisory is not a veto. Land it, and let the next run classify it. What the guard
buys is that the decision was seen rather than accreted.
