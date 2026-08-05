# Cohort Patterns

The conventions the CannObserv cohort has converged on, and the defects that
recur across it. Align a repo to these rather than inventing per-repo structure —
a normalized surface is what makes a weekly automated run safe.

Measurements below are the 2026-08-05 baseline across the twelve
skills-vendoring members.

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

### Archival subtrees

`docs/plans/` (11 repos), `docs/research/` (6), `docs/specs/` (4),
`docs/audits/` (1). These are **dated snapshots, not live context**: a
since-moved path inside a plan is a correct historical record. `measure-context.sh`
excludes them at any depth — including the nested `docs/superpowers/plans/` and
`docs/superpowers/specs/` that vendored skill trees create. Never widen
`--archival` and then act on the result.

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

### 2. Runaway reference docs

Demotion without a per-doc budget just relocates the cost. Live docs measured
over 10k tokens:

| Doc | Tokens |
|---|---:|
| `cannabis.observer-wordpress/docs/API.md` | 44,924 |
| `cannabis.observer-wordpress/docs/UI.md` | 31,690 |
| `cannabis.observer-wordpress/docs/SCHEMA.md` | 28,400 |
| `archiver/docs/UI.md` | 16,045 |
| `cannabis.observer-wordpress/docs/TESTING.md` | 15,094 |

`observo/docs/ARCHITECTURE.md` at 194 KB (~49k tokens) is the extreme. A doc that
large is not progressive disclosure; loading it costs more than the policy file it
was meant to relieve. Split on its top-level headings.

### 3. One section dominating the file

`cannabis.observer-wordpress`: `## Constraints & Working Rules` is **90% of
`AGENTS.md` at 26,445 tokens**. `cannobserv`: `Constraints & Working Rules` 45% +
`Architecture` 42%. When `sections[0].share` exceeds ~30%, that section is the
finding — demote it wholesale rather than tightening the file around it.

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

### 6. Cross-repo and moved link targets

`cli/docs/STYLE.md` links `cannobserv/docs/STYLE.md` — a path valid only in a
sibling checkout. These are genuine FALSE verdicts and are auto-fixable: point at
the sibling repo's GitHub URL, or inline the rule.

## Baseline: policy-file tokens, 2026-08-05

| Repo | Lines | Tokens | vs 4k budget |
|---|---:|---:|:--|
| usa-wa | 535 | 33,028 | over |
| cannabis.observer-wordpress | 332 | 29,183 | over |
| observo | 560 | 17,388 | over |
| cannobserv | 377 | 16,145 | over |
| watcher | 536 | 12,381 | over |
| replicator | 293 | 9,371 | over |
| archiver | 527 | 9,063 | over |
| power-map | 189 | 8,032 | over |
| address-validator | 217 | 3,906 | under |
| cli | 182 | 3,712 | under |
| notifier | 210 | 3,353 | under |
| wslcb-licensing-tracker | 205 | 3,245 | under |

**~148,800 tokens** of policy file across the cohort. Note how weakly lines
predict tokens: `power-map` is the second-smallest by lines and eighth by tokens;
`watcher` and `usa-wa` have nearly identical line counts and differ by 20k
tokens. This is the entire case for gating on tokens.

`gregoryfoster/skills` itself measures 324 lines / 5,633 tokens — over budget,
with `## Scripts` at 31%. Dogfood before sweeping the cohort.
