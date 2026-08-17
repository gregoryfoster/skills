## Session 2026-08-17 — gregoryfoster/skills (#161 promotion pass)

An adjudication session rather than an orchestration one: #161 collected two promotion candidates
from `CannObserv/observo`'s execution batches (`0de8010`, `ec5dcdb`; tracking `observo#447`), and
Batch A of this repo's own #182 backlog added three more while it ran. Five candidates, one file,
**13 tokens of nominal headroom** — the scope decision was promote **net-neutral**, never raise the
ratchet in `tests/structural/test_skill_self_budget.py`.

Four promoted, and the payment is recorded below. See the SKILL.md diff on `#161 feat:` for the
prose.

### The two candidates that defeat a detector the skill already prescribes — **both promoted**

What made these worth their bytes at one sighting each is not novelty. It is that **the check the
skill already tells you to run reports success under the failure**:

- **Vacuous assertions** (→ Step 5). A change that moves *which* column carries state leaves
  `assert companion.started_at == first_started_at` reading `None == None`. The test stays green
  while verifying nothing — and it is unreachable by keyword sweep, because it names neither the
  literal the fix removes nor the one it adds. Two observo idempotency tests silently stopped
  checking their issue's own acceptance criterion ("existing idempotency holds"). Step 5's existing
  test-surface grep hunts assertions a fix *invalidates*; those go red and you notice. This is the
  opposite half, and a worker running a green suite has no signal at all. The fix idiom travelled
  with the warning: re-anchor on the new field **and** assert it non-null, so the replacement cannot
  degrade the same way.
- **`core.bare = true` written through a shared `.git/config`** (→ Rule 6; skills#189). A linked
  worktree *shares* `.git/config` with the main checkout, so a worker's stray `git config` — or a
  bare `git init --bare` whose path mis-resolves — reaches out of the worktree. `core.bare` on a
  repo with a work tree makes `git status` **fail**, with empty stdout. Rule 6 is
  `git status --porcelain` on the main checkout, and empty stdout is exactly what "clean" looks
  like: the corruption **disables** the orchestrator's only runtime fall-through detector rather
  than tripping it, and keeps answering "clean" forever. Twice in one four-agent batch. Promoted as
  read-the-exit-code plus a `rev-parse --is-inside-work-tree` canary, plus a worker-briefing clause
  (give every repo-creating git command an explicit path).

Both are the same shape as 2026-08-13 observo's zero-hits rule — a **false negative in a check the
skill itself prescribes** — which is the class this log has now promoted three times at one sighting.

### A `failed` subagent signal is not an empty worktree — **promoted**

Orchestrator step 5 covered "work left uncommitted despite a *completed* signal" and named no other
signal. An observo worker was killed by a weekly API limit between its red and green phases and
notified as `status: failed`; the instinct is to relaunch from scratch, which discards real work.
Running the *same* reconciliation recovered four modified test files at 6 failed / 15 passed, every
failure describing intended behaviour. Rule 6's `git status --porcelain` on the main checkout was
still the correct first move, because from outside the worktree "died" and "fell through" are
indistinguishable. Resuming the same agent (rather than spawning a fresh one) preserved its context
and it finished the green phase without re-deriving anything.

### The collected-count requirement — **promoted, folded not appended**

That a worker's completion report must state `N passed, M skipped` rather than "green" was unwritten
policy: applied by hand in eight #182 briefs, present nowhere in SKILL.md. It earned promotion on
two grounds, and neither is elegance:

1. It is what makes a batch gate reconcile **arithmetically**. Batch A: `2252 + 4 + 6 + 15 + 17 =
   2294`, matching the merged run exactly. Four "full suite green" claims cannot be checked against
   each other; four counts can.
2. It converts a stale briefed baseline from a silent trap into a diagnosis. Three of four Batch A
   agents caught the orchestrator's stale 2250 and reported the `+2` rather than reconciling to it —
   precisely because they were reporting a number instead of a verdict.

Source is the #156 comment (observo worker worktrees resolving an environment that ran green while
collecting ~125 *fewer* tests than the orchestrator's). Folded into the existing report-back
sentence, not added beside it, and cross-referenced to Rule 3 — it is the same rule seen from the
worker's end, and Rule 3 already says to give a number rather than an exhortation.

### The `--no-verify` correction — the live instance of this skill's own rule

Candidate B, as filed, ended: *"The pre-commit hook runs ruff, not pytest, so a red commit lands
cleanly."* True of `observo`. **False of this repo**, whose single pre-commit hook runs the entire
structural suite and therefore rejects a red commit outright. The sentence was copied from the issue
into four Batch A briefs unchecked and caught independently by **three** agents.

Promoted in corrected form — the red commit lands cleanly *only where the pre-commit hook does not
run the suite*, and checking which is the worker's job — and pinned by a test that fails on the
unconditional phrasing, because the error would otherwise have travelled upstream into a skill that
eleven cohort repos vendor. This is the "issue body is a proposal, not a specification" rule
(Worker step 5) firing on an issue body written *by* this skill's own maintainer *about* this skill.

### Held at one sighting — logged, not promoted

- **Commit the red phase separately rather than squashing.** Promoted, but *in reduced form*: one
  clause on Worker step 6 rather than the standalone rule the issue proposed. It arrived by accident
  (an interruption forced `#443 test: RED` then `#443 feat: GREEN`) and its value — making the
  TDD-discipline dimension of a code review checkable rather than assumed — is real but cheap to
  state.
- **Stale batch branches from a prior cycle block `git checkout -b batch/a`.** The issue floated one
  line in Orchestrator step 2. Declined: `git branch --merged main` then `-d` is recoverable in
  seconds at runtime, the lowercase flag already refuses on unmerged work, and the file had no room
  for a failure that announces itself.
- **Round 2 of code review mostly finds defects introduced by round 1's fixes** (a comment
  line-wrapped mid-identifier so its test name could not be grepped; a warning conflating two
  failure modes). Belongs to `reviewing-code`, not here.
- **Check every "refuse the bad values" guard for allowlist-vs-denylist shape** — a denylist of
  unsafe enum members silently *permits* a future member, and a test parametrized over a literal of
  the same members notices nothing. The safe default is refuse-unless-known-good. A code-review
  finding, not an orchestration one.
- **Four agents, four substantive corrections to the orchestrator's brief**, continuing observo's
  13-for-13 rate. Already carried by Worker step 5; the recurrence count is the only new fact.
- **A pre-existing intermittent was correctly not attributed to the batch** (`observo#449`, a ~25%
  hang parked in `selectors.poll`). The 2026-05-09 discriminate-pre-existing rule held under
  pressure; nothing new to promote.

### What the net-neutral constraint actually cost, and what it bought

Additions ran ~2,400 bytes. Payment matched them, and **none of it was content**:

| Cut | Why it was free |
|---|---|
| Five Key Principles bullets | Verbatim restatements of Step 7, the Branch strategy section and the worker protocol. The 22,900→23,110 raise had already removed four of the same kind. |
| Rule 3's canonical-pattern block | The sentence directly above it says "follow it there rather than duplicating it here". Rule 1 carries the sync, Orchestrator step 2 the branch creation and the deploy-guard caveat. |
| Rule 2's second push snippet | A one-line code block for "just push". |
| Process Logs' closing paragraph | A strict subset of Step 10's "Where to capture them". |
| The low-discovery block | Spec-derived and followup-derived were each defined twice — once there, once in the provenance list ten lines below. |
| Step 8's three authoring routes | Demoted to `references/design-doc-authoring.md`. Every run reaches the where-to-commit *decision*; only a run that answers it "feature branch" needs the routes. The trigger condition stayed in the body, so the reader knows when to fetch. |

**The demotion the ratchet comment asks for is blocked by a test, and that is worth recording.** The
comment names the classification pass and the obvious candidate is the Process Logs provenance list —
~3,900 bytes of "which rule came from which session", pure history, zero runtime use. It cannot move:
`test_content_invariants.py::test_worker_step_cross_references_point_at_the_right_step` resolves the
citation `Worker step 5 "issue body is a proposal, not a specification"` **out of that list**, against
the cited step's title, to catch the renumbering that silently invalidated two citations in #150.
Demoting the list takes the citation out of `SKILL.md`'s body and the guard with it. Whoever attempts
the classification pass has to move the test's anchor in the same change — it is a coupled edit, not
an independent one.

### Corrections to the record

- **"13 tokens of headroom" was stale.** `.skills/context-token-ratio` moved 2.65 → 2.68 on
  2026-08-14 (`2025bca`, fitting the ratio over the whole surface rather than the policy file).
  Under the ratio actually in force the file measured **22,838 / 23,110 — 272 tokens of headroom**,
  and 21,586 exact (1,524). The decision to stay net-neutral survives the correction (a re-fit ratio
  can move back, and byte-neutrality is robust to it where token-neutrality is not), but the
  constraint that justified it was ~20× looser than believed, and #189's body repeats the same 13.
  The general lesson is the one the orchestrator drew: `bytes / <remembered ratio>` computed in a
  shell is an estimate standing in for a measurement, and it was optimistic in one direction
  (stale ratio) and pessimistic in another (this file carries the repo's largest estimator drift,
  +5.8%) for the same reason. Two clauses were cut under the wrong number and restored after
  measuring — the trim is only "paid for" once the exact reading agrees.
- **`SKILL.md` still reads "Nine sessions across four projects" for Q5.** The 2026-08-17 watcher
  entry records the **11th session / 10th positive**. Left alone deliberately — it is the watcher
  session's own count to fold in, and the 2026-08-13 power-map entry shows this exact number has gone
  stale before (the file was reading "six across three" then). Flagged rather than fixed: the count
  and its provenance line are the watcher session's own to fold in, and #182's Step 10 pass lands on
  the same lines.
- **The index is now the next budget to bind.** `references/process-log.md` reads **8,452 of its
  10,000-token per-doc ceiling** after this row — roughly four more rows at the size the last three
  sessions have been writing them. #152 resolved the ratchet-vs-append-only contradiction by making
  the ledger an indexed journal, and the index inherits the same contradiction one level up: it is
  still append-only, and it is still one file. The file's own rule ("keep the row to a headline") is
  the mitigation and the last three rows have not honoured it — this one was cut by a third after
  measuring. Worth a decision before it is worth a fix.

### Numbers

`2296 passed, 127 skipped` at baseline; **`2305 passed, 127 skipped`** after. The `+9` is five new
assertions plus four parametrized cases the two new markdown files pick up in `test_relative_links`
and `TestNoBareScriptPaths` — which is the whole argument for reporting the count: a verdict would
have hidden a `+9` that needed explaining. `SKILL.md`: 61,208 → 61,202 bytes; estimate
22,838 → 22,836 tokens; exact 21,586 → 21,554. Ratchet unchanged at 23,110, and the binding
(estimate) reading keeps 274 tokens of headroom.
