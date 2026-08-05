# Keep / Cut Rubric

The classification in Phase 3. Every section of the policy file gets exactly one
class. This is the highest-leverage judgement in the skill: compressing a
class-B section is wasted work, and deleting a class-A section is damage that a
token count will report as success.

## The one question

**Could the model already know this?**

- **It could not** — the audience, the product, the environment, the quality bar,
  the constraint and *why* it exists. This is context, and context is never cruft.
  Keep it.
- **It could** — restatements of trained defaults, general language and tooling
  knowledge, behaviour the model does unprompted. Candidate for deletion.

A second cut sharpens the first: is this line a **constraint on behaviour**
(test it, it may be removable) or **context the model cannot get elsewhere**
(keep it)? Without that second question the rubric degenerates into a length
contest, and a naive shortening pass deletes exactly the highest-value words.

## The four classes

### Class A — keep inline

Needed on nearly every task, and not discoverable in one tool call.

- Build, test, lint, and migration commands **with their non-obvious flags** —
  "skip the coverage gate with `--no-cov` because it measures all of `src/`" is
  class A; `pytest` alone is not.
- Environment preconditions: which env file to source, which role a migration
  needs, which port belongs to systemd and is therefore unavailable for dev.
- Hard constraints with their reason: pinned dependency policy, a public-API
  stability rule, a purity rule for a core package.
- Project-specific gotchas that cost a session to rediscover — the kind of thing
  a postmortem produced.
- The index of reference docs (class A by construction: it is what makes
  progressive disclosure work).

### Class B — demote to `docs/`

Correct, valuable, and needed on *some* tasks. This is where most of the budget
is recovered.

- Exhaustive layout trees and module inventories. An agent can `ls` and `grep`;
  what it cannot derive is *why* a boundary exists — keep the why inline, demote
  the enumeration.
- Full API surface listings, schema documentation, style guides, UI conventions.
- Deployment topology, server lifecycle, infrastructure detail.
- Per-endpoint or per-table contracts.
- Domain vocabulary beyond the handful of terms used in every task.

**Architecture overviews are class B by default.** The ETH Zurich evaluation of
repository context files found that including an architectural overview or an
explanation of repository structure did *not* reduce the time agents spent
locating relevant files. Keep one or two sentences on non-obvious structure
inline; demote the rest.

### Class C — tighten in place

Class A content wrapped in prose the model does not need. The content stays; the
packaging shrinks.

- Rationale for a rule stated three times in three registers → once.
- Narrative history of how a convention arose → the convention, present tense.
  A rule's authority is the behaviour it prescribes, not the incident that
  motivated it.
- Migration-relative phrasing ("this now works differently", "no longer") →
  write as if the current rule is the only rule that ever existed. Relative
  phrasing is a diff against a version the model never saw.
- Bullet walls carrying behavioural guidance → prose that keeps the "because".
  Bullets flatten priority and sever rules from their reasons.
- Pressure language: `CRITICAL: You MUST` → `Use X when…`. Current models follow
  the policy file closely; emphasis written to overcome an older model's
  reluctance now over-triggers.

### Class D — delete

Requires a named warrant. One of exactly three:

1. **Verbatim duplication** — the same content exists elsewhere in the surface.
   Quote both copies in the PR body. Content that merely *overlaps* is a
   refactoring preference, not a warrant.
2. **Disproven** — a Phase 2 FALSE verdict, with the command that refuted it.
3. **Trained default** — restates what the model does anyway. The narrow list:
   generic virtues ("be accurate, thorough, clear"); instructions to think step
   by step or plan before acting; language-level facts ("Python uses
   snake_case"); scaffolding that forces progress updates on a fixed cadence;
   "do not be lazy" style exhortations.

Nothing else is class D. In particular, a section that *feels* like boilerplate
but states a real project constraint is class C, not class D.

## What never gets cut

The keep list, binding at equal strength to the rest of this rubric:

1. **Context is never cruft.** Too-short policy files produce generic work
   because the model fills the gaps with safe defaults.
2. **Cruft is not length.** The harm comes from specific stale or
   counterproductive instructions, not from volume. Never justify a deletion by
   byte count alone.
3. **Fragile operations keep their exact scripts.** Where exactly one sequence is
   safe — destructive commands, auth flows, migration ordering — prescriptive
   detail is correct. Match freedom to fragility.
4. **Prohibitions against demonstrated current failures stay.** The test is
   whether the failure still reproduces, not whether the sentence pattern-matches
   "prohibition".
5. **Working redundancy is not cruft.** Two docs stating the same contract and
   not disagreeing is a refactoring preference. Propose consolidation only when
   the copies actually conflict.
6. **A one-line role statement is fine.** Flag identity text only when it is the
   *only* context the file provides.

## Applying it to a section, not a line

Classify at section granularity first — that is what the Phase 1 census gives
you and what the budget arithmetic needs. Only descend to lines inside a section
you have already called class C. Line-by-line classification of a file that
should lose three whole sections is how a run burns its effort and reaches the
budget by shaving class A.

## Evidence behind these classes

- Human-written context files outperformed LLM-generated ones for all four agents
  tested (~4 percentage points on AGENTbench); LLM-generated files *reduced* task
  success by 2–3% on average versus no context file at all, while raising
  inference cost 20%+. The failure mode is generic, verbose instructions that
  state the obvious — precisely class D. This is why this skill classifies before
  it writes, and never regenerates a policy file wholesale.
- Codebase overviews did not measurably help agents locate relevant files →
  architecture is class B.
- Context files that duplicated existing README content were the clearest
  negative: when other documentation was removed, the LLM-generated files
  actually improved by 2.7%. Duplication is warrant #1 for a reason.
- Context is a finite resource with diminishing marginal returns; retrieval
  accuracy degrades as the window fills. An unnecessary token is not neutral.
