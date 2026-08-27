# Session 2026-08-27 — gregoryfoster/skills (selection surface, #240–#244)

Second orchestration session on this repo the same day. The user named a range
(`for GH 240-244`) rather than "the backlog", so the set was fixed up front and the
open-issue listing's other entries were out of scope by construction.

## Interview

**Q0 (pair resolution)** — #240 and #241 both edit skill `description:` frontmatter
on the selection surface, in disjoint files (two baselines vs. four stack variants).
Offered bundle vs. two parallel agents; user chose **bundle** (Shape A). Six edited
lines total — splitting them across two review surfaces is ceremony, and they form
one coherent pass over the same surface even though they are not a define→use pair.

**Q1–Q5 inherited wholesale** from `2026-08-27-skills-audit-and-hardening-backlog.md`
— same repo, same day, same constraints. Presented as a single question ("inherit
all?") with the alternatives spelled out, rather than re-walking five questions the
user had answered hours earlier. Equal-weight rubric, early production, hybrid
parallelism, no ceiling, regular merge commits. **Q5 seventh consecutive negative.**

## Batch shape

Batch A: three parallel agents (A1 = #240+#241 bundle, A2 = #243, A3 = #244).
Batch B: one agent (#242), gated on A.

Zero contested files — a genuinely disjoint five-issue backlog.

## Lessons

**A single-batch-boundary gate justified purely by verification-mode asymmetry.**
The interesting property here is not the dependency edge (#242 asserts against the
descriptions #240/#241 write — a textbook no-file-overlap edge, and #242's body
already named the ordering). It is what the asymmetry implies about Batch A's own
green suite: the integration tests that would measure whether #240 actually fixes
Haiku's Go-project fallback are **opt-in** (`-m integration` + API key) and skipped
by default. So A1 changes live selection behaviour and verifies only that the
descriptions are *well-formed*, never that they *select correctly*. The design doc
had to say, in as many words, "do not read Batch A's green as confirmation the
selection defect is fixed."

This generalizes the Step 8 verification-mode-asymmetry note in a direction the
existing instances don't cover. The 2026-08-23 instance was a new *check* whose first
real run was post-merge; 2026-08-27 (#239) was a config change verified under the old
mode. **This one is neither — the verifying suite exists, passes, and is simply not
run**, because it costs money and needs a key. An opt-in test tier is a permanent
verification blind spot for every batch that doesn't explicitly opt in, not a
one-batch transient. Worth checking for whenever a repo has a `-m` marker gating a
paid or slow tier.

**#244's "either/or" body resolved by one grep, in the direction the body's own
ordering discouraged.** The issue listed *delete as dead* first and *keep with a
documented disable* second. Two `grep -rn` calls showed both variables are read by
the sourced library (`_context-lib.sh:307,499`), which shellcheck cannot follow
across `source` — so the first branch would have broken the script. The confirming
detail was that the same assign-then-source pattern appears in two sibling scripts
and is documented in the library's own header comments, making it a calling
convention rather than an accident. A worker handed the body unresolved had a
coin-flip between "delete two lines" and "add two comments", and one of those faces
is a regression. **Written back to the issue** before any batch design, per Step 4.

**Baseline capture surfaced an interpreter trap worth briefing explicitly.** Bare
`python -m pytest tests/structural/` fails collection on six modules
(`ModuleNotFoundError: No module named 'frontmatter'`); `.venv/bin/python` yields
**3407 passed, 158 skipped**. Rule 3 says to give workers a number — this session is
a reminder that the number is meaningless without the interpreter that produces it,
since a worker running bare `python` sees *six collection errors*, not a different
count, and might reasonably report that as a broken tree rather than a wrong
invocation. The design doc pins both.

**The pre-commit hook runs the 228s structural suite, which exceeds the default Bash
timeout.** First `git commit` was killed at 2m with the change staged but uncommitted
— recoverable, but the retry has to go through `run_in_background`. Same shape as any
long hook; worth expecting on this repo specifically.

**`gh`/`git` heredoc-in-`$()` bit again, on the *commit message* this time.** The
skill's Step 9 warning is scoped to `gh issue create` bodies, but the same apostrophe
failure hit `git commit -m "$(cat <<'EOF' … )"` — `#97's` and `Haiku's` broke the
outer substitution. Fix is identical: write the message to a file and use `-F`. The
warning generalizes from "issue bodies" to "any multi-line text with apostrophes
passed through a shell substitution."
