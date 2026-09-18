# Batch geometry: special cases and priors

Loaded from [`SKILL.md`](../SKILL.md) Steps 5–7, whose Step numbers it cites.

## Special cases that force a shape (Step 7)

Each overrides what the file map alone would suggest.

- **At most one chain-appending agent per batch.** Migrations (Alembic `down_revision`, Django dependency lists), sequence-numbered ADRs, and any "append to a linear chain" artifact fork **silently** when two agents generate one in the same batch: both compute the same predecessor, git reports no conflict because the files are different and new, and the break appears only when the chain is replayed (process-log 2026-08-07). Identify chain artifacts during Step 5 and name the owning agent in the design doc.
- **A generated artifact under a byte-for-byte sync test is a hard bundle signal.** When two issues both regenerate the same committed artifact *and* a test pins committed == generated exactly, bundle them (Shape A) regardless of the define→use heuristic — the merge can succeed textually and still fail the build, forcing whichever agent lands second to regenerate. Bundling makes the conflict *impossible* rather than *manageable* (process-log 2026-08-10: two unrelated REST routes, both regenerating `openapi.json` under a byte-for-byte sync test). **But the invariant is one regenerator per batch, and bundling is only one way to hold it.** Separate batches hold it too, free wherever the ceiling has already forced enough of them, and without putting unrelated work through a single review surface — which is the Shape A/B heuristic's own objection. Bundle when the regenerators outnumber the batches you already have; otherwise give each its own (2026-09-16 wordpress: four `openapi.json` regenerators on unrelated routes, with 13 items at a ceiling of 3 already forcing five batches — at four, bundling is the worse answer). Same shape as the chain-appending rule above, which is written as a per-batch cardinality rather than as a bundling instruction.
- **A gate can be justified by design coherence with zero file overlap.** When one issue's own acceptance says "decide the seam once" and names another as a future consumer, gate it behind that consumer even if the file sets are verified disjoint — otherwise the seam ships with one consumer and a third connective issue becomes necessary (process-log 2026-08-10: the gated seam ended up serving **four** consumers, two of which did not exist as consumers until the gating issue merged). This is the one sanctioned way for Foundation to override a correctness-first ordering; the cost is one batch boundary, not an inverted priority.
- **Foundation shared files are read-only for the follow-up batch.** The governing property is "one file every agent's verification depends on," regardless of file *kind* — a test harness bootstrap, a coverage index, a base class, or a config file such as `pyproject.toml`'s `addopts` (process-log 2026-08-11 observo). When a Batch A foundation issue ships or mutates one that downstream Batch B agents could plausibly want to extend, explicitly declare it read-only in the design doc's Key Decisions section and route necessary edits as small post-merge PRs after Batch B lands. Prevents the "three concurrent edits to one foundation file" failure mode by removing the temptation to amend it in flight.
- **A budget-tight file is single-writer, however disjoint its sections.** At Step 5, measure every token-gated file the backlog edits; where headroom is under one agent's plausible edit, separated windows still merge clean and turn the gate red — one writer per batch, re-measured at each gate (2026-08-16, 2026-08-18, 2026-09-14 observo).

## Chunking past a small ceiling (Step 7)

Step 7's sub-waves are the default and they are **fixed**. Where N greatly
exceeds a small ceiling, name the **never-concurrent sets** instead — one per
hub file, one per shared doc — and run the queue against them: that is what
makes rolling fill safe, because the orchestrator can pull a later item into a
freed slot without re-deriving the conflict map. Run the gate suite before each
refill, which holds suite concurrency at the ceiling (process-log 2026-09-14/15
observo: 18 issues, 15 workers, 2 slots, zero merge conflicts and zero
fall-throughs).

Then name the **longest exclusion chain as the critical path.** It sets the wall
time, and fixed sub-waves hide that, because every wave boundary looks like a
gate. Four function-disjoint items serialized on one hub file in that run — they
shared protocol test fakes — while the other slot drained its queue early and
idled. Ask at planning time whether that shared surface can be split first.

## Low-discovery backlog mode (Steps 5/6)

**Low-discovery backlog mode (compressed Steps 5/6).** Two shapes already name their contested files before the orchestrator arrives: **spec-derived** (issues carved out of a just-merged design spec, which declares the foundation file and the downstream split) and **followup-derived** (issues filed during a just-completed shipping cycle, whose PRs named the contested files). Recognize either when the issues were filed in the same session as the artifact they derive from. Compress Steps 5/6 to "list contested files, confirm nothing is surprising" — the formal dependency graph is ceremony when there is one edge. Run the skill anyway: its value moves to Step 7 (batch shape, including Shape A vs. B) and Step 8 (the design doc as a permanent ops manual for the orchestrator runtime — branch strategy, Key Decisions).

## Backlog provenance (Steps 5/6)

**Backlog provenance is a prior on batch geometry — confirm it with the grep, don't trust it.** Recognizing a backlog's origin front-runs the Step 7 batch shape, but it predicts *where issues came from*, not *whether they're disjoint* — always confirm via the contested-file grep (Step 5), never substitute the prior for it:

- **AR-surfaced** (issues carved from an *architectural* review) are the **inverse of CR-surfaced, and the trap in this list**: every finding is *about* structure, and structure is shared. Expect many mostly-serial batches, not two wide ones (process-log 2026-08-07: three issues claimed the same 47 CLI entry modules, four claimed root `pyproject.toml`, three claimed `docs/ARCHITECTURE.md` → six batches; 2026-08-09: three parallel waves front-loaded, then a four-link single-agent chain through the provider spine, every edge a shared file). **Do not let "review-derived" imply disjoint — check which kind of review.**
- **CR-surfaced** (issues found while reviewing recent feature work) tend to be **naturally disjoint** — the reviewer found one bug per surface — so high parallelism is the default, not the exception (process-log 2026-05-09: 6 agents, zero contested files). Don't impose sequential gates just because past backlogs had them.
- **Feature-followup** (issues filed against a just-shipped feature) cluster *or* disperse depending on **where the cycle's defects landed**, not on the fact that they're followups. When the followups all land in one partial (the implementer's TODOs, the reviewer's smells, and the QA gaps on the same file) expect a single-file critical path with a few parallel-safe outliers (process-log 2026-05-11: critical path through one template across three batches). But when the originating cycle spread defects **one-per-layer** across the stack, the same followup provenance produces a **CR-like, near-fully-disjoint** backlog (process-log 2026-06-28: six 5h.x followups across model / ETL / CLI / admin JS / admin meta / theme → high parallelism, single doc-file overlap). Heuristic: one-partial → clusters; across-the-stack → disjoint. Don't assume a single-file critical path just because the backlog is followup-derived.
- **Spec-derived** and **deep-architectural-chain** backlogs sit between: the spec or the shared core file dictates a foundation-then-split shape.
- **Adoption-feedback** (defects filed by consumers of a shared library/skill while adopting it, accumulating over weeks against *one* component's file family) is the **tightest clustering shape** — nearly every pair of issues shares a file with some other pair. But it decomposes on an axis the others lack: **the owning file**. The natural agent unit is therefore one agent per owning file, not one per issue (process-log 2026-08-11 skills: 15 issues → 7 parallel agents, grouped by which script each defect lived in). The parallelism comes from the *component's* modularity, not the backlog's independence — so derive the agent count from the file map, not from the issue count.
