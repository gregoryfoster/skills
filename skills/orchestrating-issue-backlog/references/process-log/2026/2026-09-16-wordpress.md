## Session 2026-09-16 — cannabis.observer-wordpress (0915-wave follow-ups)

Tracking issue `#908`; plan `docs/plans/2026-09-16-0915-wave-followups-backlog.md`. Named set:
803, 829, 832, 889-899, 904. Mostly CR follow-ups from the four branches merged 2026-09-15
(#900-#903). Filed upstream as
[#292](https://github.com/gregoryfoster/skills/issues/292); the skill is vendored here as a
submodule, so it was drafted in the consuming repo and nothing in the vendored copy was edited.

**Interview answers:**
- Q0:
  - #803 rescoped to its residual. The headline had shipped; see finding 1.
  - #895c bundled into #899: both edit `OpenApiGenerator::responses()`.
  - #896 → #893 bundled, #896 first: #893's refusals strand exactly the rows #896's cleanup strips.
  - #891 and #892 scored independently.
  - No duplicates.
- Q1: **Correctness ×3**, same as #687.
- Q2: pre-production.
- Q3: #829 deferred. The launch path is a fresh migration, so the backfill only helps
  already-migrated stacks.
- Q4: hybrid.
- Q5: **3**, not the port pool's 9. See finding 2.
- Merge path: **PR per work item**, with `batch/<x>` as a throwaway integration branch. See
  finding 5.

**Shape:** 15 issues → 1 deferred → 13 work items → **5 batches of 3/3/3/3/1**. Seven gate
decisions (D1-D5, with D2 and D4 split into parts) were posted to their issues before rescoring.
Two of them overruled the recommendation: D1 publish rather than drop, and D4b enumerate the
403 codes.

## Lessons

### 1. A thread's last word can be superseded by a doc the issue never links back to

#803's final comment declared the PSR-4 option "dead". The reversal lived only in
`docs/SKILLS.md`: PSR-4 resolution had shipped upstream in v1.11.0, and the graph had never been
rebuilt since v1.10.0. `AGENTS.md`'s policy line was the tell, because it contradicted the thread
("PHP file edges resolve only where a composer PSR-4 map is declared"). Reading the issue alone
would have closed it as done, or re-filed a disproven option. Same family as 2026-08-13 observo's
"read the doc the issue names as its contract", but here the contract doc was named by
`AGENTS.md`, not by the issue. **When an issue thread and the policy file disagree, the policy's
linked doc is newer.**

**Promoted ([#292](https://github.com/gregoryfoster/skills/issues/292)), as an extension to an
existing sentence in [`issue-audit.md`](../../issue-audit.md) rather than a bullet.** The
closed-in-fact grep already disambiguates zero hits "by reading the doc the issue names as its
contract". What this session adds is the case where the issue names none: the policy file does,
and a policy file that contradicts a thread is a dated artifact disagreeing with an older one.
Second sighting of the family, and the cheap direction — one grep of the policy file for the
issue's mechanism — was what the orchestrator actually ran.

### 2. A recorded ceiling from a prior session can be the wrong resource

#687 (2026-08-10) recorded "Ceiling: 9 (dev.sh port pool)" for this repo, resolved by grep.
Re-checking it this session with `limactl list` showed that one VM with **2 CPUs and 4 GiB** runs
every worktree's PHPUnit suite and MariaDB. The port pool caps provisioning; the VM caps
concurrent verification. #687 only peaked at 3, so the wrong number never bit. Q5 sub-question 2
asks about services the worktrees do *not* clone. A single VM hosting all the clones is that
service by **capacity** rather than by shared state, and the sub-question's wording ("shared test
database, shared Redis") steers away from it.

**Promoted ([#292](https://github.com/gregoryfoster/skills/issues/292)), in two places, and the
second is the one that matters.** Q5's sub-question and
[`shared-backing-services.md`](../../shared-backing-services.md) gain the capacity reading: after
the provisioning ceiling, ask what hardware runs the verification. But the live hazard is in
Rule 5, which tells a follow-up session it can re-verify an inherited ceiling cheaply by reading
the port number off any in-session `worktree create`. That shortcut confirms the *provisioning*
pool — the number that was already right — and cannot see the resource that actually binds, so a
session following the skill exactly re-confirms a wrong ceiling and records it again. That is a
detector reporting success under the failure, which is this log's standing bar for promotion at
one sighting (2026-08-17 #161). The host-CPU ceiling itself is not new: 2026-08-12 accepted it as
"none but CPU/RAM", and 2026-09-14 observo measured it at 2 pooled vCPUs. What is new is a
*recorded* ceiling naming the wrong one.

### 3. A prescribed test location can be vacuous by layer

#891's body says to pin `page=-3 → 1` in `CoRestCollectionPaginationTest`. That test builds
`new WP_REST_Request(null, $params)` and calls `co_rest_page()` directly, so WordPress core's
`sanitize_callback` (`absint`, the defect) never runs, and the pin passes **before** the fix. The
same file also pins `'absint'` literally, which does go red. This is the vacuous-assertion half of
Step 5 item 2, reached differently: not a *changed column* degrading an assertion, but a test that
never traverses the **layer the defect lives in**. It was found only by reading the test's request
builder. **An issue body's "pin it in test X" is a claim: check that X exercises the framework
layer the bug is in.**

**Promoted ([#292](https://github.com/gregoryfoster/skills/issues/292)), as a second mechanism on
the existing vacuous-assertion sentence in [`shared-files.md`](../../shared-files.md).** Third in
the family and the first that is vacuous *as filed* rather than made vacuous by a sibling's fix:
2026-08-14 observo (a moved column degrading an assertion to `None == None`, promoted in the #161
pass) and 2026-08-21 skills ("a deliberately loose pin is the highest-yield place to ask"). The
detection differs from both — neither a keyword sweep nor a diff of the assertion finds this one;
reading the test's *setup* does — which is why it is written as a clause about the request builder
rather than folded into the existing grep.

### 4. One regenerator per batch, as an alternative to bundling

The 2026-08-10 rule says two issues regenerating a byte-for-byte-pinned artifact should be
bundled. Here there were **four** regenerators of `openapi.json` on unrelated routes, and the
define→use test failed for every pair. Thirteen items at a ceiling of 3 already forced five
batches, so giving each regenerator its own batch made the conflict impossible without bundling
unrelated work and without adding a batch boundary. **Refinement: bundle *or* separate batches.
The choice is free when the batch count is already forced, and bundling is only required when the
regenerators outnumber the batches.**

**Promoted ([#292](https://github.com/gregoryfoster/skills/issues/292)), as a rewrite of the
existing bullet in [`batch-design.md`](../../batch-design.md).** The rule as written is an
absolute ("bundle them regardless of the define→use heuristic"), and it was derived from a
two-regenerator case in this same repo. At four it prescribes bundling four unrelated REST routes
into one agent — a review surface the Shape A/B heuristic exists to prevent. The invariant the
rule actually protects is *at most one regenerator per batch*; bundling is one way to guarantee
it and separate batches are another, free whenever the ceiling has already forced enough of them.
Same shape as the chain-appending bullet directly above it, which is already written as a
per-batch cardinality rather than as a bundling instruction.

### 5. The host's shipping convention can differ from the skill's batch-branch default

This repo's latest wave shipped one PR per work item, each with its own CR rounds. The skill's
model is `batch/<x>` → one reviewed merge. The user kept per-item PRs, so `batch/<x>` became a
throwaway integration branch that assembles the combined suite before any PR merges, and Rule 3's
FF/regular intra-batch merge still governs it. The merge-strategy question has a third answer:
**the batch branch as a verification artifact, not a review unit.**

**Promoted ([#292](https://github.com/gregoryfoster/skills/issues/292)), as one sentence on the
Branch strategy section of [`execution.md`](../../execution.md).** The skill asks the user for a
batch→main merge strategy and offers three answers, all of which assume the batch branch is what
gets reviewed. A host that ships per-item PRs has no answer to give, and the orchestrator is then
choosing between the skill and the repo's convention with nothing written down. Naming the third
answer costs a sentence and keeps the intra-batch rule that still applies — the FF/regular
constraint is a property of `worktree-destroy.sh --base`, not of who reviews what.

This was raised against [#288](https://github.com/gregoryfoster/skills/issues/288)'s local-main
discussion and is independent of it: #288 settled where the *plan* is committed, and closed on
commit-and-push-before-launch. This session used Step 8 route 3 and pushed `main` immediately, so
`origin/main` carried the plan before any worker was cut from it.

## Confirmations

- **Decisions create edges** (2026-08-28 power-map rule), 4th sighting. D4b, enumerating the 403
  codes, created #898 → #899. The generic-403 option would have left #899 free to run in Batch A.
  **Carried** — Step 4 already asks of each option whether it creates or removes a conflict edge.
- **Blast ≠ priority, isolate the multi-agent intersector.** #898 rewrites `permission_callback`
  lines in about 20 REST files that five smaller items also edit. It shares its batch only with
  other tiers, and the five follow on a `main` that already has it. **Carried** — Key Principles.
- **Footprint grep overstated a body** (#897 named `InformationTransformer`, which reads
  `get_post_meta`, not ACF). It also **understated** one: #897 omitted `TranscriptTransformer`,
  the deferred #829's file. The overstatement is what freed the two ETL items to run in parallel.
  **Carried** — Step 5 item 1, both directions, in one issue.
- **Bare `isolation: "worktree"` is insufficient here.** `dev.sh worktree create` provisions the
  DB clone and test DB the integration suite needs, so the orchestrator provisions and passes
  absolute paths. The plan worktree drew port 8002, which cheaply re-verified the pool (Rule 5) —
  and see finding 2 for what that re-verification does not cover.
- **Step 10 in a repo that vendors the skill as a submodule dirties the host's Rule 6 baseline.**
  Writing the entry in place leaves the main checkout reporting a modified submodule. The user's
  standing rule settles it: learnings are always filed upstream as an issue, never written into
  the vendored copy, which is how this entry arrived. **Promoted
  ([#292](https://github.com/gregoryfoster/skills/issues/292)), as a clause on Step 10.** Third
  sighting — 2026-09-14 observo and
  [#289](https://github.com/gregoryfoster/skills/issues/289) both carry the same note as a
  postscript — and the Rule 6 interaction is what lifts it above a convention: a modified
  submodule pointer is output from `git status --porcelain` on the main checkout, which is the
  one signal the orchestrator is told to treat as a fall-through, and it persists into the next
  session's Step 1-2 stray sweep.
- **The batch table was reconciled against the scored backlog** (13 = 3+3+3+3+1) before the design
  doc was written, which confirms the concern in
  [#291](https://github.com/gregoryfoster/skills/issues/291) cheaply. Adjudicating #291's own
  proposal is out of scope for this entry.
