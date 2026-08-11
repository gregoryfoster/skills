# The Continuous Surfaces

The three surfaces Phase 8 offers once per repo, as SKILL.md carried them before
v1.7 demoted them here: the prompt to put to the user, what each one covers that
the others do not, and the wiring etiquette. Design of the weekly job lives in
[cadence.md](cadence.md); guard semantics in
[write-guard-hook.md](write-guard-hook.md).

## Phase 8 — Wire the continuous surfaces

Three surfaces keep the ground this run won. Offer all three once per repo, after
the first successful curation.

### The cadence

```bash
bash "<SKILL_SCRIPTS>/install-cadence.sh"
```

What goes on the clock is a **measurement, not a curation** — regrowth, budget
adherence and seam accrual all come from measuring, and judgement on a timer is
what this skill avoids everywhere else. The weekly job records a `baseline` row
and warns when the surface drifts; a human or an agent curates on that evidence.
It never runs on `pull_request`.

**It needs the `ANTHROPIC_API_KEY` repository secret.** Without it the job
records *nothing*, silently, every week — `record-telemetry.sh` refuses an
estimate against exact rows. Set the secret first, then run it once by hand.

Design, the annotated template, and what it deliberately does not do:
[references/cadence.md](cadence.md) ([#118](https://github.com/gregoryfoster/skills/issues/118)).

The next two catch regrowth *between* those weekly measurements.

### Review-time delta

`context-delta.sh` reports the branch's effect on the surface — token delta and
budget position per changed file, nothing at all when the diff touches no
context-surface file. The four `reviewing-code*` variants already call it from
their `gather-context.sh` when this skill is vendored alongside them, so it needs
no wiring there. It is informational by construction and exits 0 on every path.

It sees what the write guard cannot, twice over: the guard evaluates one edit at a
time, so a 400-token addition that replaced 600 elsewhere reads the same as a
straight gain; and it matches `Edit|Write|MultiEdit`, so a shell redirect
(`cat >> AGENTS.md <<'EOF'`) or a `NotebookEdit` never reaches it
([#103](https://github.com/gregoryfoster/skills/issues/103)). Review sees the
whole branch however the bytes arrived, while the tradeoff is still cheap.

### Write guard

> Install the context-budget write guard? It is a `PostToolUse` hook that flags an
> edit which pushes `AGENTS.md` or a live reference doc further over budget. It
> never blocks, and it stays silent when an edit *reduces* the count.

On yes:

```bash
bash "<SKILL_SCRIPTS>/install-guard.sh" --budget 6000 --doc-budget 10000
```

The guard and the weekly run are two halves of one ratchet: the guard stops
regrowth cheaply, in the turn that caused it, on the common path; the run and the
review-time delta recover ground and catch what the matcher never saw. A repo with
the run but no guard sawtooths, and no curation fixes a file something else keeps
appending to. Semantics, the speak-only-on-both-conditions rule, the uncovered
write paths, and uninstall:
[references/write-guard-hook.md](write-guard-hook.md).

The installer prints its `git add` line rather than committing, and names the log
path to tail. Hook wiring lands through the project's normal gate — a hook that
starts running because something committed it unannounced is a bad surprise.
