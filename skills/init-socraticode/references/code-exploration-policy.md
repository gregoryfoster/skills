# Code Exploration Policy — AGENTS.md block + SessionStart hook

Three artifacts the skill installs into the target project (SKILL.md Phase 3):

1. A **Code Exploration Policy** section in the project's `AGENTS.md`, wrapped in
   idempotency markers so re-runs never duplicate it.
2. A **`docs/SOCRATICODE.md`** detail doc carrying the full tool table, the
   prefetch query and the per-tool guidance — see
   [`socraticode-doc.md`](socraticode-doc.md).
3. A **SessionStart hook** in `.claude/settings.json` that re-emits the
   `ToolSearch` prefetch instruction each session (the `codebase_*` MCP tools
   are *deferred* — their schemas load only after the prefetch).

All must be **project-adapted, not copied verbatim** (acceptance criterion).
The block below is trimmed wording descended from `init-project-fastapi`'s
`agents-md-template.md`; keep the negative rule and the three-row table, but
tailor the path examples to the project's actual layout.

**Why the block is small.** `AGENTS.md` is loaded on every invocation, and this
section is the one `curating-context` refuses to touch (it has its own
idempotency contract — see
[`../../curating-context/references/cohort-patterns.md`](../../curating-context/references/cohort-patterns.md)),
so whatever lands here is a fixed cost the repo can never curate away. Measured
on `CannObserv/watcher`, the pre-split section was **1,247 exact tokens — 15% of
the whole curated file and 21% of the 6,000-token budget**, the largest single
section, and it blocked that repo from reaching budget without cutting class-A
operational rules ([#115](https://github.com/gregoryfoster/skills/issues/115)).
Everything that is not needed *on nearly every task* belongs in
`docs/SOCRATICODE.md`, which is read on demand.

---

## 1. AGENTS.md block (marker-delimited — idempotent)

Land exactly one marker-delimited block in `AGENTS.md`, applying these steps in
order so a repo in any prior state converges to a single marked block, in place
where one already exists:

1. **Write the block, preferring the existing position:**
   - a `<!-- BEGIN socraticode-policy -->` / `<!-- END socraticode-policy -->`
     pair already exists → **replace the content between the markers**;
   - else an unmarked `## Code Exploration Policy` section exists → **rescue any
     repo-authored content in it (step 1a), then replace that section in place**
     (its heading through the line before the next `##`, or end of file if none
     follows) with the marked block below;
   - else → **append** the marked block below. (If no `AGENTS.md` exists, create
     one and add the block.)
   1. **Rescue before you replace (unmarked branch only).** Read the span first
      and compare it to the template. Any paragraph, list, table row or
      sub-heading that the template does not itself carry is **repo-authored**
      and must not be deleted. Move it out, unchanged, into a
      `## Code Exploration Notes (repo-specific)` section placed immediately
      *after* the `<!-- END socraticode-policy -->` marker, and **name every
      moved block in the completion report**. Nothing enclosed by the marker
      pair survives a re-run, so this is the only opportunity to notice.
2. **Then, unconditionally,** delete any *other* `## Code Exploration Policy`
   section **not** enclosed by the marker pair (same heading-to-next-`##` span).
   Step 1 fixes at most one location; this sweeps any remaining stray copy — e.g.
   a repo where an earlier `init-socraticode` run appended a marked block beside
   the original unmarked one, where step 1 takes the marker-pair branch and would
   otherwise leave the unmarked copy behind. The rescue heading is deliberately
   **not** `## Code Exploration Policy`, so this sweep never eats it.

Never leave more than one policy section.

> **Why step 1a exists.** The unmarked branch is a whole-span replacement, and
> repos accumulate real content inside that span: `CannObserv/watcher` had grown
> a 732-byte `**Index scope.**` paragraph there — `.socraticodeignore` policy,
> why vendored prose outranks first-party code in `codebase_search`, and the
> fact that editing the ignore file only affects subsequent scans — none of it
> recoverable from the template. Deleting it was correct per the old contract
> and **silent**, which is what made it a defect
> ([#115](https://github.com/gregoryfoster/skills/issues/115)). Tell the repo,
> once, where repo-specific additions belong: **outside the marker pair.**

### Variant A — standard (graph yield OK)

```markdown
<!-- BEGIN socraticode-policy -->
## Code Exploration Policy

SocratiCode is the preferred semantic-search tool here once indexed (local
Qdrant store + on-disk graph; manifest `.socraticodecontextartifacts.json`).
Its MCP tools are **deferred** — schemas load only after the `ToolSearch`
prefetch that `.claude/hooks/socraticode-reminder.sh` prints each session.

**Negative rule.** Use SocratiCode MCP tools first for semantic questions
("where is X", "how does Y work", "what depends on Z"). Reach for `grep`/`rg`
only on exact strings (error messages, log lines, known symbols). Reserve the
Explore subagent for path-pattern walks (`*.py` under `src/api/routes/`), not
semantic search.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what touches Z | `codebase_search` |
| Exact string or regex (errors, log lines, known symbols) | `grep` / `rg` |
| Imports/dependents of a file · blast radius of a change | `codebase_graph_query` / `codebase_impact` |

Full tool table, prefetch query, per-tool guidance: [`docs/SOCRATICODE.md`](docs/SOCRATICODE.md).
<!-- END socraticode-policy -->
```

### Variant B — degraded (graph yield LOW)

Write **this** block instead when Phase 6's yield gate returns `low` — the
dependency graph resolved almost no edges, so `codebase_graph_query`,
`codebase_impact` and `codebase_flow` answer with an ordinary "no dependency
information found" sentence rather than an error. An agent reads that as *no
dependents*, which is the opposite of the truth
([#107](https://github.com/gregoryfoster/skills/issues/107)). Substitute the
real numbers from `mcp-driver.mjs health-check` and the repo's real import
syntax in the `rg` example.

```markdown
<!-- BEGIN socraticode-policy -->
## Code Exploration Policy

SocratiCode is the preferred semantic-search tool here once indexed (local
Qdrant store + on-disk graph; manifest `.socraticodecontextartifacts.json`).
Its MCP tools are **deferred** — schemas load only after the `ToolSearch`
prefetch that `.claude/hooks/socraticode-reminder.sh` prints each session.

**Negative rule.** Use SocratiCode MCP tools first for semantic questions
("where is X", "how does Y work", "what depends on Z"). Reach for `grep`/`rg`
only on exact strings (error messages, log lines, known symbols). Reserve the
Explore subagent for path-pattern walks, not semantic search.

> **The dependency graph here is LOW-YIELD** — <EDGES> edges across <NODES>
> files, <UNRESOLVED>% unresolved (<DATE>). `codebase_graph_query`,
> `codebase_impact` and `codebase_flow` answer empty rather than erroring, so
> **treat empty graph output as tool failure, not as absence** — "No dependency
> information found" means the resolver failed, never that nothing depends on
> the file. Use `rg -n 'from <module> import|import <module>'` instead.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what touches Z | `codebase_search` |
| Exact string or regex (errors, log lines, known symbols) | `grep` / `rg` |
| Imports/dependents of a file · blast radius of a change | `grep` / `rg` — graph low-yield |

Full tool table, prefetch query, per-tool guidance: [`docs/SOCRATICODE.md`](docs/SOCRATICODE.md).
<!-- END socraticode-policy -->
```

Everything else — the marker discipline, the rescue step, the sweep — is
identical for both variants. Re-run the yield gate after any upstream
SocratiCode upgrade and switch the variant back when the graph recovers.

## 2. SessionStart hooks (script file + `.claude/settings.json`)

Two of them, installed the same way into the same `.claude/hooks/`: a
**prefetch reminder** that re-emits the prefetch instruction each session so a
fresh Claude Code session loads the deferred `codebase_*` schemas without the
operator remembering to, and a **once-per-day health check**. Both print to
stdout; Claude Code injects SessionStart stdout as session context.

The org convention (archiver, power-map, usa-wa, observo) is a **script-file
hook**: the echo lives in `.claude/hooks/socraticode-reminder.sh`, referenced
from settings.json. This keeps the ~600-char `select:` string out of
JSON-escaping and makes later edits a plain shell-file change upstream.
Standardize on this form.

**Both installs run one shared script.** `managing-skills` ships
`scripts/install-hook.sh`, which takes the hook's constants as arguments and
installs the same two artifacts for any of them
([#200](https://github.com/gregoryfoster/skills/issues/200)). The refresh hook
that lands in this same `.claude/hooks/` is installed by it too, so all three
inherit one mechanism and one set of hardening rounds rather than three prose
procedures that must be kept in agreement by attention
([#167](https://github.com/gregoryfoster/skills/issues/167),
[#178](https://github.com/gregoryfoster/skills/issues/178)).

**Step A — install the reminder hook.** Do **not** retype it and do not wire it
by hand:

```bash
bash "<SKILL_DIR>/../managing-skills/scripts/install-hook.sh" \
  --hook socraticode-reminder.sh --skill init-socraticode \
  --marker socraticode-prefetch --marker socraticode-reminder --copy-fallback
```

It writes **two** artifacts, and only the second makes the hook run:

1. `.claude/hooks/socraticode-reminder.sh` — `ln -sfn` at the vendored
   [`../scripts/socraticode-reminder.sh`](../scripts/socraticode-reminder.sh).
   The target is relative and derived from the `skills-vendor/` directory the
   installer actually found, never a hand-substituted `<owner>-<repo>` — that
   substitution is how a symlink ends up pointing at a plausible path which does
   not exist. `ln -sfn` replaces an existing regular file in place, so a re-run
   upgrades a legacy consumer from its hand-typed copy with no separate step.
2. a `SessionStart` entry in `.claude/settings.json` (Step B) — created if
   absent, merged if present, never clobbered.

**`--copy-fallback` is the no-`skills-vendor/` branch**, and passing it is why
this is one command rather than two. A consumer that does not vendor via
`managing-skills` has nothing to point a symlink at, so the installer copies its
own vendored file and `chmod +x`es it — and says so, loudly, because a **copy**
freezes at install day and `.skills/doctor.sh` scans `.claude/hooks/*` for
*dangling symlinks* ([#99](https://github.com/gregoryfoster/skills/issues/99)),
so a copy is a perfectly valid regular file it can never see. A symlinked hook
self-heals on the next preflight and a copy never can. Report which of the two
the run said it did in Phase 6's completion table.

Until [#186](https://github.com/gregoryfoster/skills/issues/186) this hook had no
source file at all — it was rendered from prose in *this* document, so every
consumer's copy was whatever the installing agent typed that day. That is worse
than the copy [#179](https://github.com/gregoryfoster/skills/issues/179)
rejected, which at least starts as a byte-for-byte snapshot of a known version,
and it carries the identical justification: "it carries no per-project state" is
the argument *for* the symlink.

**Step B — what lands in `.claude/settings.json`.** The installer merges this
entry, preserving every other hook, event and top-level key:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-reminder.sh\" # socraticode-prefetch"
          }
        ]
      }
    ]
  }
}
```

Three deliberate details, all of them arguments to the command above rather than
steps for you to perform:

- **`${CLAUDE_PROJECT_DIR:-.}`** — a best-effort fallback (cwd is the launch
  directory, normally the project root) for any environment that fires the hook
  without `CLAUDE_PROJECT_DIR` set. Without it, an unset variable degrades to
  `bash "/.claude/hooks/..."` and errors on every session start; with it, the
  worst case resolves relative to the launch dir instead of erroring outright.
- **trailing `# socraticode-prefetch`** — the first `--marker`, written into the
  *command string itself* rather than only inside the script file, so the merge
  recognizes the entry by reading settings.json alone.
- **the second `--marker socraticode-reminder`** — a legacy alias, recognized on
  read and never written. It matches installs whose command references
  `socraticode-reminder.sh` without the trailing marker comment. The installer
  strips every entry matching either marker and appends one canonical entry, so
  a re-run **upgrades** a fallback-less `bash "$CLAUDE_PROJECT_DIR/…"` or a
  legacy inline echo, and **collapses** a duplicate pair left by a prior
  verbatim re-run — where a skip-only dedupe would leave both stranded on the
  old, erroring command.

Verify without changing anything by adding `--check` to the Step A command: it
reports both artifacts independently and exits 3 if either is missing, or if the
hook is a copy in a repo that has a vendored source to link at instead.

**Step C — install the once-per-day health hook.** The same installer with the
hook's own constants — same `ln -sfn` into `skills-vendor/`, same merge, same
copy fallback:

```bash
bash "<SKILL_DIR>/../managing-skills/scripts/install-hook.sh" \
  --hook socraticode-health.sh --skill init-socraticode \
  --marker socraticode-health --copy-fallback
```

Its marker is deliberately distinct from `socraticode-prefetch` /
`socraticode-reminder`: markers are per-hook precisely so that one hook's
dedupe-strip cannot evict the other's entry from the array they share. This hook
is also the worst possible candidate for a silent copy — it is silent when clean
by design, so a stale copy that has stopped detecting something is
indistinguishable from a healthy install
([#179](https://github.com/gregoryfoster/skills/issues/179)).

The hook is silent unless it finds something, runs at most once per UTC day, and
exits 0 on every path; it re-checks the Phase 6 yield gate, `codebase_health`,
and a failed last operation, so an install that was green in January is not
assumed green in June
([#107](https://github.com/gregoryfoster/skills/issues/107)). Set
`SOCRATICODE_PROBE_FILE` in `.claude/settings.local.json`'s `env` block to a
file with several first-party imports if you want the confirmatory graph probe.

**It reports; it does not repair.** No re-index, no `docker start`, no file
edit. A SessionStart hook runs before the agent has any context, and a hook that
started a two-hour index — or rewrote `AGENTS.md` under an agent already at work
— would be a worse failure than the one it detected.

> **Duplicate-config trap.** If a session shows BOTH
> `mcp__plugin_socraticode_socraticode__*` and a standalone
> `mcp__socraticode__*`, the user has a duplicate MCP registration. Remove the
> standalone (the plugin already provides the server):
> `claude mcp remove socraticode`.

## Adaptation checklist (per project)

- [ ] Variant chosen from the Phase 6 yield gate — **A** on `ok`/`unknown`,
      **B** on `low`, with the real edge/node/unresolved numbers substituted.
- [ ] Any path examples in the negative rule match the project's tree
      (`src/api/routes/` is FastAPI-shaped; change for CLI/PHP/etc.).
- [ ] `docs/SOCRATICODE.md` written from [`socraticode-doc.md`](socraticode-doc.md),
      with its `codebase_context` row naming the project's real non-code
      knowledge (schemas, OpenAPI, Terraform) — see
      [`context-artifacts.md`](context-artifacts.md). The block's link is
      relative to the repo root; if the project keeps detail docs elsewhere,
      change both the destination and the link.
- [ ] Repo-authored content found in an unmarked section was **rescued**, not
      replaced (step 1a), and every moved block is named in the report. Same
      check for an unmarked `docs/SOCRATICODE.md` (step 2) — rescue below its
      `<!-- END socraticode-doc -->` marker.
- [ ] `AGENTS.md` vs `CLAUDE.md`: this org standardizes on `AGENTS.md` with a
      one-line `CLAUDE.md` that reads `@AGENTS.md`. If the project only has
      `CLAUDE.md`, put the block there instead.
