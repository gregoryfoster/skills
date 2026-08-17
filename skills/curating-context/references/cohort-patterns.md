# Cohort Patterns

The conventions the CannObserv cohort has converged on, and the defects that
recur across it. Align a repo to these rather than inventing per-repo structure —
a normalized surface is what makes a weekly automated run safe.

Measurements below are the 2026-08-05 baseline across the twelve
skills-vendoring members, counted exactly with `count_tokens`.

Gathered **read-only**: local checkouts measured with `measure-context.sh --exact
--no-write`, GitHub-only members via `gh api`. Nothing was written to any member
repo. Adoption and remediation go out as per-repo issues — this skill never
commits across repos.

## The policy file

- **`AGENTS.md` at the repo root** is the policy file. `CLAUDE.md` is a symlink to
  it (`./AGENTS.md`) — uniform across all twelve members. Never let the two
  diverge into separate files; a second copy is duplication that drifts.
- **H1 is `# <repo> — Agent Guidelines`** (or `— Agent Guide` / `Agent Guidance —
  <repo>`; the three variants are equivalent and not worth churning).
- The `## Code Exploration Policy` section is installed by `init-socraticode` and
  is **not** this skill's to edit. It has its own idempotency contract; rewriting
  it in place will be reverted on that skill's next run.

### Canonical section order

The union across the cohort, in the dominant order. Not every repo needs every
section — the value is that when a section exists, it is in the expected place
with the expected name.

1. Project Overview — 2–4 sentences. What it is, what it talks to.
2. Development Methodology
3. Environment & Tooling
4. Code Exploration Policy *(owned by `init-socraticode`)*
5. Architecture — non-obvious structure only; the enumeration is class B
6. Infrastructure
7. Server Lifecycle
8. Environment Files / Environment Variables
9. Common Commands
10. Constraints & Working Rules — numbered, each with its reason
11. Conventions
12. Key Domain Entities
13. Known Issues
14. Agent Skills — inventory + SocratiCode pointer
15. Commit Convention
16. **Detail Docs** — the index; last

### The Detail Docs index

The shape to converge on. Present in `cannobserv`, `cli`,
`cannabis.observer-wordpress`, and `observo`; absent in `archiver`, `notifier`,
`power-map`, `replicator`, `watcher`, `usa-wa` — which is exactly the set with
orphaned docs.

```markdown
## Detail Docs

- [docs/COMMANDS.md](docs/COMMANDS.md) — every runnable command, with flags
- [docs/STYLE.md](docs/STYLE.md) — code style and formatting rules
- [docs/TESTING.md](docs/TESTING.md) — test layout, fixtures, coverage gates
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — systemd units, env, rollout
```

One line per live doc, each naming **what a task would need it for** — the line is
the routing signal that decides whether an agent loads a 10k-token file, so
"style guide" is worse than "code style and formatting rules". The index is class
A by construction: it is the mechanism progressive disclosure runs on.

### Normalizing the index — the Phase 5 step in full

Phase 5's step 3 carried this inline until v1.7 demoted it here:

   A `## Detail Docs` section listing every live
   reference doc with a one-line purpose. See
   [references/cohort-patterns.md](cohort-patterns.md) for the shape
   the cohort has converged on, and the canonical section order and `docs/`
   filenames to align with.

## Cross-repo surveys stay read-only

Two mechanics enforce this:

- `measure-context.sh --no-write` suppresses the one side effect an `--exact` run
  has — persisting the observed token ratio to `.skills/context-token-ratio`.
  **Always pass it when surveying a repo you are not curating.** Without it, a
  read-only-looking survey leaves an untracked file behind in every repo it
  touched.
- `cohort-report.sh` and `score-cohort.sh` read ledgers over `gh api` and never
  clone or write.

A cohort ledger therefore fills in as each repo adopts the skill, not from one
central sweep. `cohort-report.sh` reporting "no ledger" for a member is the
expected state before adoption, not a failure.

### The rule in full

This skill edits **the repo it is invoked in**. It never writes to a sibling
checkout, even one it just measured.

Cross-repo work is filed as **issues**, not commits — the same convention the
skill-family sweeps already follow. So a cohort pass is: measure each member
read-only, then open an adoption issue per repo carrying that repo's numbers and
findings. The repo's own maintainers (or an agent invoked inside it) run the
curation.

Always pass `--no-write` when surveying a repo you are not curating — without it
an `--exact` run leaves an untracked ratio file behind.

## Reference-doc filenames

`UPPERCASE.md` under `docs/`. Observed frequency across the twelve:

| File | Repos | Contents |
|---|---:|---|
| `SKILLS.md` | 11 | vendored skill inventory and refresh procedure |
| `COMMANDS.md` | 9 | full command reference |
| `STYLE.md` | 9 | code style, formatting, naming |
| `ARCHITECTURE.md` | 4 | module boundaries and data flow |
| `DEPLOYMENT.md` | 4 | units, hosts, rollout |
| `TESTING.md` | 2 | test layout and gates |
| `SCHEMA.md` | 2 | database schema and invariants |
| `CONVENTIONS.md` | 2 | domain conventions |
| `API.md` / `PUBLIC_API.md` | 3 | endpoint contracts |

When demoting, prefer an existing name from this table over a new one. A
thirteenth distinct filename for the same concept is how the cohort loses its
shared shape.

### Starting with no `docs/` tree — the Phase 5 step 4 note in full

Phase 5's step 4 carried this inline until v1.7 demoted it here:

   When the repo has **no `docs/` tree at all** — as this one did — the run is
   creating it. Take filenames from the frequency table in
   [references/cohort-patterns.md](cohort-patterns.md) rather than
   inventing them; a thirteenth distinct name for the same concept is how the
   cohort loses its shared shape. This is a different starting state from the six
   members that have `docs/` but no index: there, step 2 is the whole job.

### Archival subtrees

`docs/plans/` (11 repos), `docs/research/` (6), `docs/specs/` (4),
`docs/audits/` (1). These are **dated snapshots, not live context**: a
since-moved path inside a plan is a correct historical record. `measure-context.sh`
excludes them at any depth — including the nested `docs/superpowers/plans/` and
`docs/superpowers/specs/` that vendored skill trees create. Never widen
`--archival` and then act on the result.

Archival subtrees (`docs/plans/`, `specs/`, `research/`, `audits/`, `archive/`, at
any depth) are excluded by default. Plans and audits are dated snapshots — a
since-moved path inside one is a correct historical record, and counting them
buries the live signal under hundreds of files. Do not widen `--archival` to
"measure everything" and then act on the result.

## Recurring defects

Ordered by how often they appear.

### 1. Orphaned reference docs — 6 of 12

A `docs/` tree the policy file never links. `archiver` carries
`docs/SKILLS.md`, `docs/STYLE.md`, and a 648-line `docs/UI.md` with **zero**
references from its 527-line `AGENTS.md`. Same in `notifier` (3 docs),
`power-map` (6, including a 151 KB `STYLE.md`), `replicator`, `address-validator`
(15), and `usa-wa`.

An unlinked doc is worse than a missing one: the maintenance cost is paid, the
routing benefit is not, and the content silently rots because nothing points at
it. Fix by adding the Detail Docs index — or by deleting the doc, if nothing
should point at it.

**A repo with no `docs/` tree at all is a different starting state**, and needs
more work rather than less. `gregoryfoster/skills` was in it: seven archival plans
and zero live docs, so there was nothing to relink and the run had to *create* the
tree. Phase 5 step 2 is then a no-op and step 3 is the whole job. Take filenames
from the table above; the temptation to invent one is strongest precisely when
there is no existing tree to be consistent with.

### Worked example: `gregoryfoster/skills`, 2026-08-05

The first real run of this skill, kept here because a measured example argues
better than a rationale.

| | Before | After |
|---|---:|---:|
| `AGENTS.md` | 8,462 | **4,273** |
| Lines | 328 | 231 |
| Largest section share | 31% | 9% |
| Live docs | 0 | 3 |

Four sections demoted, three of them A+B splits: `Scripts` (2,670 → 390) lost its
`<SKILL_SCRIPTS>` template (1,315) and gate-script discipline (1,215) to
`docs/STYLE.md`; `Project-level superseding` (1,351 → 384) lost its override
frontmatter spec (789) to `docs/CONVENTIONS.md`; `How downstream projects consume
this repo` (1,030) went almost whole to `docs/SKILLS.md`; `References convention`
(657) kept its two enforced rules and demoted the rest.

Zero deletions — Phase 2 found no FALSE verdicts, so no warrant existed. All three
destinations landed well under the 10k per-doc budget (2,774 / 1,753 / 1,061), so
the demotion removed cost rather than relocating it.

### 2. Runaway reference docs

Demotion without a per-doc budget just relocates the cost. Live docs over the 10k
budget, exact:

| Doc | Tokens |
|---|---:|
| `cannabis.observer-wordpress/docs/API.md` | 71,317 |
| `cannabis.observer-wordpress/docs/UI.md` | 50,116 |
| `cannabis.observer-wordpress/docs/SCHEMA.md` | 46,124 |
| `archiver/docs/UI.md` | 25,154 |
| `cannabis.observer-wordpress/docs/TESTING.md` | 24,496 |

`observo/docs/ARCHITECTURE.md` at 194 KB is the extreme — on the measured ratio
that is around 72k tokens, more than the whole `cannabis.observer-wordpress`
policy file. A doc that large is not progressive disclosure; loading it costs more
than the policy file it was meant to relieve. Split on its top-level headings.

Note that `cannabis.observer-wordpress` alone carries **192k tokens** of
over-budget live docs plus a 49k policy file. Demoting more into that tree would
be moving deck chairs; it needs splitting first.

**Split before demoting, never after.** A doc split is free only while nothing in the surface points at what moves; once relocated prose points *into* a section, splitting it forces a choice between a circular pointer and a [no-loss failure](validation-gate.md#warranted-losses-are-not-the-same-claim-as-no-loss). One cohort run reverted a split because moving `## DB` into `docs/SCHEMA.md` routed 14 relocated bullets back to their own page. If a destination needs splitting, split it first.

### 3. One section dominating the file

`cannabis.observer-wordpress`: `## Constraints & Working Rules` is **91% of
`AGENTS.md` at 44,795 tokens** — one section larger than nine of the twelve repos'
entire policy files. `cannobserv` splits it two ways: `Constraints & Working Rules`
45% (11,835) plus `Architecture` 42% (11,040). When `sections[0].share` exceeds
~30%, that section is the finding — demote it wholesale rather than tightening the
file around it.

### 4. Rot-prone "Known Issues" sections

`observo` has `## Open Issues (as of last session)`. Any section whose title
admits it is a snapshot will be stale, and stale issue state is actively
misleading — an agent reads "pending in #42" and re-does shipped work. Verify
every referenced issue's state with `verify-facts.sh --issues`; a section that
cannot be kept current belongs in the tracker, not the policy file.

### 5. Command blocks duplicating `docs/COMMANDS.md`

Both `notifier` and `usa-wa` carry a long fenced `## Common Commands` block *and*
a `docs/COMMANDS.md`. Keep the two or three commands needed on nearly every task
inline (class A); the full reference is class B. When they disagree, that is
warrant #1 for deletion of the copy — but establish which is correct first.

### Demoting class B — the Phase 5 step 4 text in full

Phase 5's step 4 carried this inline until v1.7 demoted it here:

   **Demote class B**, creating or extending `docs/<TOPIC>.md`. Move the text;
   do not paraphrase it in transit. A paraphrase during a move is an
   unreviewable content change wearing a refactor's clothes — and it is the one
   thing a reader skimming the diff will not notice, because the words are all
   still there.

   Before **extending** an existing doc, read its `##` headings first: if the
   destination already covers the incoming topic, merge into the canonical
   section rather than appending a near-duplicate beside it — the cohort's
   defect #5 created at the destination by the run itself. And keep provenance
   out of headings: "Demoted from AGENTS.md (#412)" belongs in the commit, not
   baked into a permanent anchor slug. Phase 6.5 checks both.

   Two mechanical adjustments come with every move, and only these two:

   - **Relative links gain a level.** A block moving from the repo root into
     `docs/` turns every `](tests/x.py)` into `](../tests/x.py)`. Skip this and
     Phase 6 reports a wave of dead links — the check catches it, but the run
     fails rather than succeeding.
   - **A `###` subsection becomes `##`** at the top of its own document.

   `prove-no-loss.sh` normalises exactly these two and nothing else, so any
   other difference is reported as content loss.

### 6. Cross-repo and moved link targets

`cli/docs/STYLE.md` links `cannobserv/docs/STYLE.md` — a path valid only in a
sibling checkout. These are genuine FALSE verdicts and are auto-fixable: point at
the sibling repo's GitHub URL, or inline the rule.

`prove-no-loss.sh` proves moved content arrived; this proves the rest of the
surface still **describes where it went** — the *prose* half. `links.dead_anchors`
now decides the *link* half mechanically. One cohort adoption shipped a
clean run carrying ten such findings; a later one left 16 stale docstring
references across 13 shipped packages, which is why tracked **source** outside
the docs tree is swept too once a section leaves the policy file. Never repoint
one of those at a bare `docs/X.md` — no installed wheel resolves it, and it can
hit a *different* repo's file in a sibling checkout. Qualify or inline it.

The report is hits **to judge**, not defects to fix — a reference to the policy
file is wrong only if what it points at moved. Judge each: fix what lies, add
what is legitimate to `.skills/context-seams-ok` (entries match line *content*
and expire when the line changes, which is when they need re-judging; the
report warns on blanket patterns). Re-run, carry both counts to Phase 7
(`--seams N --seams-acked M`), and run this sweep *last*. No class sees a
command split from its claim: re-read any command beside a block that moved.

## Baseline: policy-file tokens, 2026-08-05

> **Frozen. Do not refresh these numbers in place.**
>
> This table is the cohort's **pre-registered before-state**. It was committed at
> `c10bf7f` on 2026-08-05, before any member repo had curated anything, and the
> validation split's pairs are defined by it. Because it predates every outcome,
> it is the one baseline that provably cannot have been chosen to favour an arm —
> which is the only reason the first experiment's rows can be scored at all
> ([#116](https://github.com/gregoryfoster/skills/issues/116): the gate needs a
> before-state and no ledger row carries one).
>
> Every repo here has since curated, so as a *description of the cohort today*
> these numbers are stale by design, and updating them in place would look like an
> obvious cleanup. It would destroy the experiment. Add a new dated table below
> instead, and leave this one alone.

Counted with `count_tokens` against `claude-opus-5` — **exact, not estimated**.
The `est` column is what the old uncalibrated `bytes/4` heuristic reported, kept
here because the gap is the point.

| Repo | Lines | est (bytes/4) | **Exact** | Error | vs 6k |
|---|---:|---:|---:|---:|:--|
| usa-wa | 535 | 33,028 | **52,953** | +60% | over |
| cannabis.observer-wordpress | 332 | 30,510 | **49,103** | +60% | over |
| observo | 560 | 17,388 | **28,110** | +61% | over |
| cannobserv | 377 | 16,145 | **25,949** | +60% | over |
| watcher | 536 | 12,381 | **19,715** | +59% | over |
| replicator | 293 | 9,371 | **14,633** | +56% | over |
| archiver | 527 | 9,063 | **14,358** | +58% | over |
| power-map | 189 | 8,032 | **13,298** | +65% | over |
| address-validator | 217 | 3,906 | **6,322** | +61% | over |
| cli | 182 | 3,712 | **6,013** | +61% | over |
| notifier | 210 | 3,353 | **5,468** | +63% | **under** |
| wslcb-licensing-tracker | 205 | 3,245 | **5,331** | +64% | **under** |
| **cohort total** | | 150,134 | **241,253** | **+60%** | |

**241,253 tokens** of policy file across the cohort. Against the 6,000 budget,
**ten of twelve are over**; only `wslcb-licensing-tracker` (5,331) and `notifier`
(5,468) are under, with `cli` (6,013) and `address-validator` (6,322) within 6%.
Anything measured before this table with `bytes/4` should be re-measured, not
scaled: the error is consistent enough (+56% to +65%) to be worth knowing, but not
so consistent that a blanket multiplier is a measurement.

Note how weakly lines predict tokens — the entire case for gating on tokens:

- `power-map` is second-smallest by lines (189) and **eighth** by tokens (13,298).
- `watcher` (536 lines) and `usa-wa` (535 lines) are within one line of each other
  and **33,238 tokens apart**.
- `wslcb-licensing-tracker` (205 lines, 5,331) and `cannabis.observer-wordpress`
  (332 lines, 49,103) differ by 1.6× on lines and **9.2×** on tokens.

`gregoryfoster/skills` itself measured 328 lines / **8,462 tokens** exact — over
budget, with `## Scripts` at 31%. It has since been curated to **4,273**; see the
worked example above. Dogfooding it first is what produced the `subsections[]`
census and `prove-no-loss.sh`, both of which came out of that single run.
