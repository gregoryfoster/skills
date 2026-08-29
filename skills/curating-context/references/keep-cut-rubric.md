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

### Proving a class-C tightening

Class C is the one disposition `prove-no-loss.sh` could not score. Its five
original warrants all name *moves*, and a tightening is a rewrite in place — so
a run that did exactly what this rubric prescribes had no honest verdict: `ok`
contradicts exit 3, `failed` tells `score-cohort.sh` content was dropped when
none was, `skipped` is false. The more disciplined the run, the worse its ledger
row looked (#247, #250).

A bare sixth warrant would have been worse than the gap. The other five are each
constrained by something outside the entry — `retarget` and `rename` are
**compulsory**, forced by this skill; `duplicate`, `disproven` and `default`
point at checkable evidence. `tighten` points at nothing but the author's own
edit, and the over-broad refusal cannot restrain it, because **class C's
defining defect is a section written as one paragraph**. One line, one entry, a
whole section waved through: on the run that found this, five entries would have
covered the entire body of a 9,826-token document.

So `tighten` is gated on evidence the rewrite cannot produce for itself, and is
**refused** — not warned about — if claimed without it:

```bash
bash "<SKILL_SCRIPTS>/prove-no-loss.sh" --base <branch-point> --claims
```

**Line matching proves the moves; atom matching proves the rewrites.** The atoms
are the tokens a faithful rewrite must carry across — backticked spans, `#NNN`
issue references, link targets, bare URLs — taken from `--base` and from every
destination and compared as sets. Anything a tightening legitimately drops, such
as the changelog reference that made a sentence long, gets a judged entry in
`.skills/context-claims-ok`: same grammar and same warrants as
`.skills/context-loss-ok` minus `tighten` itself, with the atom matched **whole**
rather than as a substring, so `#41` cannot warrant `#412`.

Both judgements are needed, and they are not the same judgement. `tighten`
accounts for the *line*; every atom that line carried is accounted for
separately, or the gate is back to trusting an author about their own rewrite.

The check earns its keep independently of the warrant it gates. On the run that
motivated it, it surfaced 19 dropped atoms of which **12 were real
over-compression that would otherwise have shipped** — including a `wp#569` that
was the load-bearing justification for an entire API being write-only.

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

### The four classes as Phase 3 tabulates them

| Class | Meaning | Disposition |
|---|---|---|
| **A — Keep inline** | Only the author knows it, and it is needed on nearly every task: build/test commands, non-obvious constraints, project-specific gotchas | stays, possibly tightened |
| **B — Demote** | Correct and valuable, needed on *some* tasks | move to `docs/<TOPIC>.md`, link from the index |
| **C — Tighten** | Class A content carrying prose an agent doesn't need | rewrite in place |
| **D — Delete** | Restates a trained default, duplicates another part of the surface, or was disproven in Phase 2 | delete, with the warrant named |

Classification is where the value is. Compressing a class-B section is wasted
work; deleting a class-A section is damage. Do the classification before writing
a single edit.

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

## Applying it to a section, then a subsection — not a line

Classify at `##` granularity first: that is what the budget arithmetic needs, and
line-by-line classification of a file that should lose three whole sections is how
a run burns its effort and reaches the budget by shaving class A.

But **the section is usually not the unit of the edit.** A large `##` section
typically splits: the rule stays inline and the reference implementation moves.
Phase 1 reports `subsections[]` for exactly this, each naming its parent; check
any child over ~5% of the file. Measured on this skill's first real run, three of
four demotions were A+B splits, and the two largest single wins were `###` blocks
(1,315 and 1,215 tokens) that a `##`-only census could not see.

Two rules for the split:

- **A parent's class does not descend to its children.** In the same run,
  `Self-discovery` (176 tokens) sat inside a section demoted almost whole and
  stayed inline, because the `../skills` vs `../../skills` footgun is class A. Its
  parent being class B said nothing about it.
- **When you split, leave a signpost.** A demoted subsection gets one inline
  bullet naming the rule and the test that enforces it. The rule stays
  discoverable at a fraction of the tokens; without it, an agent has no reason to
  open the doc.

Only descend to individual lines inside something already called class C.

### The measured example

**Most large sections split A+B rather than taking one class.** On this repo's
first run, three of four demotions were splits: the `##` section stayed and its
`###` subsections moved. So classify at `##` level first, then check
`subsections[]` for any child over ~5% of the file — that array exists because a
`##`-only census hides the unit the decision is actually made on. The measured
example:

| Section | Total | Kept inline | Demoted subsection |
|---|---:|---:|---|
| `Scripts` | 2,670 | 390 | `<SKILL_SCRIPTS>` 1,315 + gate-script discipline 1,215 |
| `Project-level superseding` | 1,351 | 384 | `Required override frontmatter` 789 |

Note the counter-example in the same run: `Self-discovery` (176) was a *child of a
demoted parent* and stayed inline, because the `../skills` vs `../../skills`
footgun is class A. A parent's class does not descend to its children.

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

## The third clause, and the three warrants

The third clause is what makes this skill safe to run unattended. Cutting a
section from `AGENTS.md` is a **move** to a `docs/` reference by default. Outright
deletion needs one of exactly three warrants: the content is verbatim-duplicated
elsewhere in the surface, a command proved it false, or it restates something the
model already knows (rubric class D — see below). Anything else gets relocated,
and the commit body names where it went.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "It's under 200 lines, so it's fine" | Line count is not the budget. Measured exactly, `wslcb-licensing-tracker` is 205 lines / **5,331 tokens** and `cannabis.observer-wordpress` is 332 lines / **49,103**. Both pass a line cap; one costs 9.2× the other. `watcher` and `usa-wa` differ by one line and 33,238 tokens. Gate on tokens. |
| "I'll move the bloat into `docs/`" | Only helps if the doc is *smaller than the thing an agent would otherwise read*. `cannabis.observer-wordpress` already carries 192k tokens of over-budget live docs; demoting its 44.8k `Constraints` section into one of them moves the cost, it doesn't remove it. Demotion is paired with a per-doc budget. |
| "This section looks redundant, cutting it" | Redundant with *what*? Verbatim duplication is a warrant; "feels like boilerplate" is not. Quote both copies or relocate instead. |
| "The path doesn't exist, so the claim is stale" | A policy file legitimately names paths that don't exist locally — illustrative templates, naming conventions, downstream consumer paths. `verify-facts.sh` marks those UNVERIFIABLE for exactly this reason. Deleting on UNVERIFIABLE is how real guidance gets destroyed. |
| "I'll write the architecture overview more concisely" | The ETH Zurich evaluation found codebase overviews did **not** help agents reach relevant files faster. Tightening a section that shouldn't be inline at all is wasted work — classify it first. |
| "More context is safer" | Which cost applies depends on which surface. For a **policy file**, loaded unconditionally: context is a finite resource with diminishing returns, retrieval accuracy degrades as the window fills, so an unnecessary token is not neutral — it dilutes attention on the necessary ones. For a **skill library**, loaded selectively, that claim does not transfer: [Skill Shadowing](https://arxiv.org/html/2605.24050v1) measures the two failure modes against each other and finds selection ambiguity between similar skills "significantly contributes to the performance degradation, whereas the context overhead effect remains small and indistinguishable from zero" ([#97](https://github.com/gregoryfoster/skills/issues/97)). Token volume is the policy-file cost, not the universal one. |
| "Nothing changed this week, skip the run" | The run's cheapest output is the telemetry row. A flat week is a signal worth recording, and the fact checks still catch drift the repo caused elsewhere. |
| "I can get seams to 0 by deleting the references" | A legitimate back-reference is navigation, and deleting it zeroes the metric while making the surface worse — the `tokens_live` mistake again. Acknowledge it in `.skills/context-seams-ok` instead; the healthy steady state is a stable acknowledged set with zero *new* hits. |
