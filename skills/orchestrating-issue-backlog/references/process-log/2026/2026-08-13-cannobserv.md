## Session 2026-08-13

**Project:** CannObserv/cannobserv (shared Python library, uv workspace). User-named subset: #278, #295, #296, #297. Tracking issue #329; plan `docs/plans/2026-08-13-co-v1-oracle-followups-backlog.md`.

**Interview:** Correctness ×3 (2nd Correctness-leading weight, after 2026-05-24); early production; #278 deferred at Q3 by the project's standing async-parity policy; hybrid parallelism; ceiling 3 (generic worktree scripts, no host provisioning — never bound).

**Batch shape:** two sequential single-agent batches. Batch A = Shape-A bundle: foundation re-pin commit → #296 (retire waivers) → #297 (collapse walker). Batch B = #295 (task-performers read + two model extensions), gated on A's PR merge. PR + regular merge per repo precedent; no `batch/<X>` branches.

### Upstream-blocked backlog: the sibling repo's blocker states are the first grep

New provenance flavor: three of four issues were filed as **blocked on another repo's issues** (wp#663/664/666), each opening with "actionable the moment that ships and the pin refreshes." The orchestration-triggering fact was not local — all three upstream issues closed within a 5-day window (verified via `gh issue view --repo` before the interview), and the local contract pin predated every fix. For this shape, check blocker states **before** scoring: they decide which issues are actionable at all, and the closure dates tell you the shared vendored artifact (here `openapi.pinned.json`) is stale — which surfaces the foundation step.

### A shared first step that is not an issue

All three issues' step 1 was the same script run (`sync_openapi.py --write`). Modeled as **commit 1 of the Batch A bundle**, verifying all three upstream expectations at once (including Batch B's — the params check), then declared read-only for Batch B. Running it per-issue would have produced provenance churn and cross-batch conflicts on the pin. Generalization of the foundation-shared-file read-only rule (2026-06-08) to a foundation *artifact refresh*.

### Same-function overlap is the sharpest Shape-A signal yet

#296 (waiver filter) and #297 (walker call) edit **adjacent lines in one function** (`test_write_bodies.py:22-23`) — beyond same-file into same-lines. Combined with the issues' own "sequence together" notes and the retire-then-collapse define→use order (emptying the dict first moots #297's waiver-rekeying step), bundling was overdetermined. Continues the 2026-08-10 hard-bundle-signal thread (generated artifact + sync test).

### A clarifying "Other" answer flipped a decision and exposed a latent data drop

The #295 issue body framed decision 2 as "observation has no such field on either backend" — add speculatively or leave out. I recommended leave-out (early production, no speculative model changes). The user answered with a *question*: "Legacy production Observations include a task/performer list — is that the same thing?" Greps confirmed it is: production observation posts carry the ACF `co_roles` repeater, the wp/v2 event/event_type adapters map it, and the **observation adapter silently drops it on read**. The issue body's claim was true of the *model* but misleading about the *data*. Decision flipped to add-on-both-backends, and the "speculative" change turned out to fix a real read-time loss. Lessons: (1) an "Other" answer phrased as domain knowledge is a grep target, not a preference to be slotted into the offered options — verify before locking; (2) a "no such field" claim in an issue body describes the code, not necessarily the upstream data; the recommended option was wrong because the option framing inherited that gap.

### Also captured

- Hybrid preference **degenerated to fully sequential** — every issue pairing shared a file (`_manifest.py` adjacent sections, `test_write_bodies.py` same lines, CHANGELOG, the pin). Small-N backlogs from a single followup cycle may have no file-safe parallelism at all; say so plainly rather than manufacturing a parallel batch.
- Policy-deferral of a **user-named** issue: #278 was in the named set but AGENTS.md's async-parity policy says defer; Q3 confirmed the policy holds. Naming an issue in the subset is not an override of a standing policy — ask.
- Planning-time resolution of both flagged build-time decisions (label column → carry both; observation roles → both backends) moved MINOR public-model calls from worker discretion to the design doc's Key Decisions — right call under this repo's API-stability tracking rule.
- Precedent (a): plan committed without prefix, then #329 opened.
- `gh issue create --body-file` from the scratchpad; body contained backticks throughout.

### Post-gate addendum (same day): a nomenclature decision reopened after approval

After the plan shipped, the user reopened #295's naming: the `roles` model field predates the
project's Roles CPT and now collides with the real Role entity — replace with Task/Performer
nomenclature (`task_performers` field, `get_task_performers` facade, `task_label`+`performer_label`
columns), justified by "there are no downstream consumers so we can do this right." The audit
**half-confirmed** that claim: the *new* surfaces had none, but the *existing* `EventModel.roles` /
`EventTypeModel.roles` had production consumers in the adjacent `cli` checkout (cancellation
stripping, event-add seeding, an export command, direct `TaskPerformerModel(task=...)` construction).
Lessons: (1) a user's no-consumers assertion spans whatever *they* mean by the surface — grep the
adjacent downstream checkouts before accepting it for the surfaces the rename actually touches, and
surface the split (new-surface-free vs existing-field-consumed) so the breaking half is a deliberate
choice; (2) post-gate decision changes flow through the same write-back circuit as mid-orchestration
surgery (2026-08-11 observo): plan Key Decisions + issue comment + tracking-issue body, before any
agent exists. The user chose the full rename with a cli adoption issue at ship time (adopt-a-release
covers it); the plan gained Key Decision 9.

### Execution addendum (same day): both batches shipped

Full pipeline ran to completion in-session: Batch A (worker → reconcile → independent verify →
PR #331 → user-invoked CR round → merge) then Batch B (same shape → PR #332 → CR round → merge);
cli adoption issue CannObserv/cli#903 filed at ship time from the audited call-site list; tracking
#329 closed. Execution notes worth keeping:

- **A per-batch CR skill round slotted cleanly between "PR opened" and "merge"** — the user invoked
  `/reviewing-code-python-click` on each batch branch, and its directives ("N: fix … then proceed to
  the next batch") doubled as the merge-gate confirmation. The orchestrator implemented CR fixes
  directly on the PR branch (small, reviewed deltas) rather than re-dispatching the worker — right
  call at that size.
- **Review the reviewer's collapse**: Batch A's CR found that after #297 folded the walker into
  strict validation, nothing guarded the *strictness itself* for the 24 non-replayed ops — a
  re-pin could silently degrade the oracle back to types-only. The meta-test
  (`test_request_schemas_stay_strict`) closes the same "nothing fails when it goes stale" class the
  batch was retiring; look for this shape whenever a hand check collapses into an
  externally-supplied property.
- **Worker-report claims spot-verified cheaply**: the orchestrator re-ran the full suite + gates in
  each worktree (same env, seconds) and independently probed Batch A's central claim (28/28 write
  bodies strict at every reached level) with a ten-line script before opening the PR. Both workers'
  reports proved accurate; the probes are what made "accurate" a verified word.
- **Harness/tooling mismatch**: `worktree-destroy.sh` expects `.worktrees/`; `isolation: "worktree"`
  provisions under `.claude/worktrees/`. Equivalent manual sequence: `merge-base --is-ancestor`
  check → `git worktree remove` → `branch -D`. Also, the review skill's gather-context preflight
  self-refreshed `.skills/doctor.sh` mid-pipeline — commit that noise promptly or it trips the
  Rule 6 clean-checkout check on the next completion signal.
- Both workers returned clean first-pass reports (4111→4139→4170 tests); the single-agent
  sequential shape meant zero reconciliation surprises — no fall-through, no uncommitted work,
  no custom branch names.
