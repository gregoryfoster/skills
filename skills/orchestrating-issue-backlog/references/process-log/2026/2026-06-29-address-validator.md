## Session 2026-06-29 (address-validator AR backlog wave 2)

**Project:** `CannObserv/address-validator` (FastAPI; uv + ruff + pytest). Second wave of `/reviewing-architecture` findings — issues #133–141 (8 maintainability/cohesion refactors + 1 perf). Tracking issue `#142`.

**Interview answers:**
- Q1 Quality: **maintainability first** → formula flexed to `(Foundation × 3) + (Correctness × 2) + Scope`, max 18. First session where **Foundation** took the ×3 weight (prior sessions weighted Correctness). Confirms the "unless the user requests different weights" escape hatch covers Foundation-leading, not just Correctness-leading — no skill-level rubric change needed.
- Q2 Deploy: early production.
- Q3 Defer: none — all 9.
- Q4 Parallelism: hybrid.
- Q5 Ceiling: **none** — `worktree-create.sh` is plain `git worktree add` into `.worktrees/`; TDD agents run `uv run pytest` only (no per-worktree port pool / Nginx vhost, unlike the 2026-05-22 WordPress incident). Cap = file-disjoint count.
- Q6 Merge: regular merge commit (batch→main); intra-batch fixed FF/regular.

**Shape:** 9 issues → **5 agents** (bundling same-file issues) → **2 batches** (4 parallel + 1 gated). Batch A = {V2, STATUS, STD, ADMIN}; Batch B = {PARSER}.

**Non-obvious decisions captured:**

- **Aggressive cohesive bundling collapsed 9 issues to 5 agents.** The three v2-router-cleanup issues (#133/#134/#135) all rewrite the *same two* router files (`parse.py`, `standardize.py`) — parallel is impossible, so rather than serialize three agents with two gates, bundle them into ONE agent ("v2 router DRY pass") with sequential commits. Same for #137+#138 (both own `parser.py`) and #140+#141 (both own `dashboard.py`). Rule of thumb reinforced: when N issues all rewrite one hot file, one agent with ordered commits beats N agents with gates — and reviews as a coherent unit.

- **A high-scoring issue placed LAST and ALONE because it conflicts with multiple parallel agents.** #138 (score 14, 2nd-highest) went to Batch B by itself. Reason: it moves `set_audit_context`/`set_candidate_data` out of `parse_address` into the *callers* — and `parse_address` is called from all three files the V2 bundle rewrites (`parse.py`, `standardize.py`, `pipeline.py`) *plus* it edits `models.py`, which STATUS edits. So #138 conflicts with **two of the four** Batch-A agents. New nuance on "blast ≠ priority": when a single issue's blast radius intersects multiple otherwise-parallel agents, isolating it in its own gated batch (it rebases onto post-A main and inherits everything) is cheaper than threading it as an ordering constraint through each conflicting agent. Verify the conflict empirically — `grep` the function's call sites before assuming a service-layer change is router-disjoint.

- **Sub-score commit ordering can invert the score order for define-then-use.** ADMIN runs #141 (score 8) before #140 (score 9): #141 establishes the single `{path: label}` map that #140's parallelized queries consume. Score orders *batches/priority*; within a bundle, dependency wins.

- **Correctness-leads-refactor inside a bundle.** PARSER commits #138 (the ContextVar-flow rewrite — a documented sensitive area) before #137 (mechanical 250-line extraction), so the surgical behavior change lands against the known-good structure as a legible diff, and the pure move rebases on top.

**Tactical confirmations:**
- `gh issue create --body-file <path>` used from the start (the 2026-05-24 apostrophe lesson) — clean, no quoting issues.
- Design-doc commit used precedent (a): committed without `#<n>` prefix, then opened the tracking issue.
- `resolve-plans-dir.sh` lives under `skills-vendor/gregoryfoster-skills/skills/writing-plans/scripts/` (vendored submodule), not `skills/` — the SKILL's `bash skills/writing-plans/...` path is a symlink-relative reference that may not resolve from repo root; `find skills skills-vendor -name resolve-plans-dir.sh` locates it. Resolved to `docs/plans/`.
