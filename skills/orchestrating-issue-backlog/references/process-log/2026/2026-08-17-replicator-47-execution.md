## Session 2026-08-16/17 (CannObserv/replicator) — execution addendum

Execution of the #47 plan (planning entry `2026-08-17-replicator.md`). Five issues (#17, #20,
#25, #37, #44), three batches, ceiling 2 agents per batch. All merged; suite 687 → 773;
tracking issue #47 closed.

### Q5 answered "none" and that was the true answer

Plain `git worktree add`, hermetic fakeredis, uuid-scoped integration streams. One
`grep -rE 'docker|POSTGRES|DATABASE_URL|PORT_POOL'` confirmed it; the ceiling was host
CPU/RAM/disk. The existing log line already warns against hunting until a ceiling appears, and
it was right to.

### But the prescribed grep cannot see every shared backing service

This repo has one the database-shaped pattern misses entirely: a local Qdrant store behind a
committed docs manifest (`.socraticodecontextartifacts.json`), which three of the five issues
had reason to edit. Not a DSN, not a port, not a container — a *tracked JSON file* plus an
out-of-band embedding store that nothing re-embeds on commit. Resolution: name the manifest
**read-only for every agent** and re-index once post-merge, as a fourth resolution beside the
three the skill lists.

**Suggested addition to Q5 sub-question 2:** "…a shared search index — including one whose
only visible surface is a tracked config file rather than a service."

### Four of my five worker briefs contained an error, each caught by the worker

The pattern is worth the skill's attention because the *shape* is consistent — every error was
an orchestrator asserting a fact about a file it had not opened at the revision the worker
would see:

1. Told a worker the baseline was 687 tests. Unreachable without `git submodule update --init`.
2. Told a worker its change was "additions only". Ruff `I001` forced an import-block rewrite.
3. Gave a worker an OFF-LIMITS window that made its issue unimplementable — the import it had
   to add sat at line 42, inside a co-batch agent's 24–82 window.
4. **Briefed the wrong budget.** I flagged AGENTS.md at 5,997/6,000 as the binding constraint;
   the binding one was `docs/ARCHITECTURE.md` at 9,510/10,000, which the worker actually had to
   edit.

**Suggested addition to Step 7 (worker briefs):** every load-bearing number in a brief — a test
count, a line window, a token budget — is *measured at the revision the worker will branch
from*, not carried from the orchestrator's own reading. A stale number in a brief is worse than
an absent one: the worker spends its first cycle reconciling it.

### The fifth error was the expensive one, and it is the Step 5 grep failing on a sibling repo

#25 restores an escalation Watcher lost at a cutover, so the brief recovered Watcher's
constants from history. `last_request_at` exists **twice** in Watcher: `rate_limiter.py`
(in-memory, written on every request) and `models/domain.py` (the DB row the decay reads,
written only by `_persist_backoff` — *"after a 429 response"*). I named the first. Implemented
as briefed, the quiet window would measure from the last *request*, so a host fetched every
minute never sees a half-hour gap and escalation persists forever on exactly the hosts busy
enough to earn one.

**Suggested addition to Step 5:** when recovering a behaviour from a sibling repo's history,
grep the symbol and then **find its writers**. A same-named field in two layers is the common
case in any repo with both a cache and a table, and the orchestrator's grep will land on
whichever is more prominent — which is the wrong one whenever the behaviour being recovered is
the persisted half.

### A "neutral" constant carried across repos was not neutral

The brief said matching Watcher's `BACKOFF_MAX_INTERVAL = 60.0` "keeps this neutral". It does
not: Watcher had one global 1 s floor and no per-host published intervals, while Replicator has
them, so an absolute 60 s ceiling was **silently inert for every host published slower than
60 s** — the origins an issuer has already marked fragile. Found at review round 3, not at
planning, and only by executing the case rather than reading the code.

**Suggested addition to Step 5's "a grep sizes a surface; only execution measures a
behaviour":** a constant transplanted between repos inherits the *source* repo's surrounding
invariants, and those are what the destination has to be checked against — the number
travelling unchanged is what makes it look reviewed.

### The plan's one dependency edge was real but not load-bearing

I gated #25 behind #17 because `TransientFetchError` carries no `status_code`, so escalation
seemed to need the status after classification. The worker reported from the call site *before*
the classifier, reading status off the result — the dependency was a file-region conflict only,
and even that was avoidable. **Worth a line in Step 5:** a dependency edge derived from "B needs
data A's change exposes" is a hypothesis about *where* B reads, not a fact. Ask whether B could
read earlier.

### Harness and cleanup

- **Rule 6's tripwire fired on every clean run** until `.claude/worktrees/` joined
  `.worktrees/` in `.gitignore`. Worth naming in the Rule 6 text: the Agent tool's
  `isolation: "worktree"` path differs from the one `using-git-worktrees` creates, so a repo
  that has ignored the latter still reports a dirty tree on every completion signal.
- **Cleanup gotcha:** `git worktree remove` refuses outright on a worktree containing
  submodules ("working trees containing submodules cannot be moved or removed"). `--force`
  works; a bare `remove` in a cleanup step will fail on any repo with a vendored submodule —
  which includes every repo that vendors these skills.

### Filing convention

This session's Step 10 writes reached this repo as issues (#183 planning, #197 execution)
rather than as commits into `skills-vendor/gregoryfoster-skills`: a branch-and-commit in the
submodule leaves the parent dirty as `M skills-vendor/gregoryfoster-skills`, which is exactly
the tripwire Rule 6 reads as a worker falling through into the main checkout.
