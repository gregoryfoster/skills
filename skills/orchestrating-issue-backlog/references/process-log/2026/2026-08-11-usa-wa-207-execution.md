## Session 2026-08-11→13 — CannObserv/usa-wa (#207 execution)

Execution half of the plan the 2026-08-11 usa-wa entry records (filed as #146; companion to #129,
which covered planning). 7 issues → 7 agents across 5 batches (A: 3 parallel on `batch/g`; B–E solo,
PR-per-batch). All 7 closed; 4 follow-ups filed (usa-wa#208, #216, notes on #202; skills#145). A CR
round ran after every batch and found real defects in four of five.

### The skill's own batch-branch checkout step took production down — **promoted**

`git checkout -b batch/<x>` in the main checkout is the skill's standing instruction. **In a repo
that deploys from that checkout, it stops the deployment.** Every code-running unit in usa-wa carries
`ExecStartPre=assert-main-checkout.sh` (usa-wa#87): with `batch/g` — and later a feature branch —
checked out, `usa-wa.service` could not start, and a parallel operator had to stop it cleanly to keep
it from flapping through its start limit into alert emails. The journal showed the same refusal from
two *earlier* sessions (`batch/a`, `batch/b`, Aug 8/9). Recurrent, not a one-off, and invisible from
inside the orchestration because the failure lands in the deploy unit rather than in git.

The pattern that respects both the skill and such repos:

- Multi-agent batch: `git branch batch/<x> main` — create, **never** check out — then merge, test and
  fix inside a worktree on that branch.
- Single-agent batch: create no local branch; push the worker's `worktree-agent-*` branch as the
  feature branch (`git push origin worktree-agent-<id>:<feature>`) and PR from there.
- Before walking away: `git -C <main> branch --show-current` must print the default branch, and the
  deploy unit must be active.

**Promoted into Orchestrator step 2**, with the detection grep (`ExecStartPre=.*assert.*main`) folded
in. **Correction to #146's body:** it says the instruction lives in "orchestrator step 2 and Rule 3."
It lived in *four* places — Orchestrator step 2, Rule 3's canonical pattern block, the Branch strategy
section ("creates this branch and checks it out"), and the Key Principles worktrees bullet ("check out
the batch branch first"). Promoting the rule in one place and leaving the other three would have left
three copies of the instruction that caused the outage. Orchestrator step 2 is now the single
conditional statement; the other three defer to it.

**And the fourth site was still missed on the first pass** — caught in review, worth recording as its
own small rule. Three of the four sites are *prose*, and rewriting prose to defer to a new condition
is the natural motion. The fourth was Rule 3's copy-paste runbook block, a fenced `bash` snippet whose
`git checkout -b batch/f` line carried no caveat at all. It was the last one noticed and it is the
**most** dangerous, because a runbook block is executed rather than read: an orchestrator pastes it,
and the prose two sections away that says "unless the repo deploys from this checkout" never enters
the transaction. **When promoting a conditional rule, enumerate the executable sites first and the
prose sites second** — a fenced command block is the site the condition has to reach, and it is the
one a prose-shaped edit pass slides past.

### A repo-documented wrap-up restart resurrected a deliberately-held daemon — **promoted, folded in**

usa-wa's AGENTS.md wrap-up says `sudo systemctl restart usa-wa usa-wa-sync-powermap`. Run verbatim
after Batch A's merge, it restarted a daemon a parallel workstream had deliberately stopped 94 seconds
earlier, mid-incident (PM API saturation, usa-wa#211). The operator then had to harden the hold with a
`ConditionPathExists` drop-in so a start *fails* rather than succeeding silently.

A unit that is `inactive` **and** `disabled` while its preset is `enabled` is a deliberate hold, not a
fault. Check `systemctl is-enabled` and `systemctl cat` (for drop-ins) before running any
repo-documented restart, and narrow the restart to what this work actually changed. An orchestrator
running "always restart X and Y" boilerplate is an automation hazard precisely because it executes
documentation that predates the incident.

Promoted as a clause on the same Orchestrator step 2 rule rather than as its own: both findings are
the same proposition — *the host repo is live, and the orchestrator's own boilerplate is written as if
it were not* — and a reader who has just been told the main checkout is load-bearing is the reader who
needs the restart caution.

### Worker reports: one verifiable discrepancy per batch — re-verification is load-bearing

Every completion report was materially useful AND contained at least one claim that did not survive
checking:

- **A (briefing defect, the worker caught it):** the orchestrator's DB-safety rule — "db-marked tests
  are safe inside the savepointed fixture" — was wrong. The session-scoped `test_engine` fixture drops
  every schema CASCADE at session start and teardown, so any db-marked *session* destroys concurrent
  siblings, not just `reset_migration_schemas` callers. Filed as usa-wa#208; the ceiling note from
  2026-06-16 upgrades from "contention" to "destruction".
- **D:** "exits 0 with no flags" held only with a worktree-only test deselected; the plain command
  reproduced exit 1. True in the main checkout, verified post-merge.
- **E:** the orchestrator's own budget table (4 files over) was measured with the wrong tokenizer;
  exact counts showed 2 (skills#145).
- **C:** self-report accurate, but the CR still found a stale unit count in AGENTS.md and two docs
  pushed over budget that the report understated ("+~2 net lines" was +9 lines / +408 bytes).

The orchestrator re-running the workers' *own headline verification commands* — not merely the full
suite — caught something every single time. Not promoted: Worker step 5 and the report-back slot
already mandate the corrections, and the orchestrator's re-verification is Orchestrator step 6's
existing gate run applied with more curiosity, not a new rule. Recorded here so a third recurrence can
argue for it as a standing step.

### Harness-worktree mechanics

- **Stale in #146's body, corrected here.** It reports that `worktree-destroy.sh` resolves
  `.worktrees/<branch-slug>` and therefore cannot drive harness worktrees. That was true when the
  session ran; it is **fixed in this repo** — #149 shipped branch-first lookup, and
  `using-git-worktrees/SKILL.md` now documents `worktree-agent-<id>` at `.claude/worktrees/agent-<id>`
  explicitly. The manual equivalent the session used (`git merge-base --is-ancestor` →
  `git worktree remove --force` → `git worktree prune` → `git branch -d`) remains the fallback for
  consumers pinned to an older submodule.
- Linked worktrees don't populate submodules: one submodule-dependent test fails in *every* worktree
  and passes in the main checkout. Brief workers to ignore it by name.
- Worktrees have no `.venv` (`uv sync --locked` once) and the sandbox refuses `export $(cat …)` — use
  `uv run --env-file …`. Still live upstream as skills#156.

### Tactical

- PR-per-batch (user-chosen) worked well: 5 PRs, each with the batch's reasoning as the body; CR
  directives (`N: fix/stet/GH`) between open and merge.
- `--body-file` for every gh write, again. GitHub SSH-push 500s plus intermittent publickey refusals
  hit during final ship while HTTPS API writes kept working — retry with `ls-remote` confirmation,
  don't hammer.
- A session hook's auto-commit (`chore: update skills submodules`) collided with a PR merge → rebase
  the local-only commit onto the merged main rather than discarding it; an *uncommitted pre-existing*
  edit belonging to another workstream is stashed across the rebase and restored, never committed.
- Rescope-to-residual (#160, from the planning session's Q0) executed cleanly: the residual shipped as
  ⅓ of Batch A with its design decision recorded in the commit.
