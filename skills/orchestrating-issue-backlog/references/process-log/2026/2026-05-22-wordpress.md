## Session 2026-05-22 (port-pool incident)

**Project:** `cannabis.observer-wordpress` (Bedrock + Sage 11 + Lima VM monorepo)

**Incident:** `/orchestrating-issue-backlog` launched 10 parallel worker agents for Batch A. The host project's `dev.sh worktree create` script allocates ports from a pool of 9 slots (8001–8009) for per-worktree Nginx vhosts. Agents 9–10 (and several others starting near-simultaneously) hit the ceiling.

**Fall-through modes observed:**
- **Majority (A4, A6, A8, A10):** `dev.sh worktree create` printed "port pool exhausted" and fell back to plain `git worktree add`. Lost VM vhost, DB clone, node_modules overlay — but git branch + commits landed correctly on the agent's feature branch.
- **One agent (A9):** Silently fell through to the **main checkout** as its working directory. Modified tracked files in place, ran tests against them (passed — because the modifications WERE the working tree), and was about to run `php -l` when the orchestrator caught it via `git status` on main showing uncommitted modifications.

**Salvage (A9):** Stashed uncommitted work + untracked files (`stash push -u`) in the main checkout, switched to A9's empty feature branch (`feature/batch-a-249-tranche-c6-c9`), popped the stash, committed manually as `e0307c0`. No work lost.

**Rules added (Rule 5, Rule 6):**
- **Rule 5** — Cap per-batch parallelism at the host project's worktree provisioning ceiling. Establish via new Q5 in interview.
- **Rule 6** — Orchestrator runs `git -C <main> status --porcelain` between worker completion signals to detect fall-through. Cheap, mandatory, runs on every signal.

**Recovery procedure documented:** Stash-and-replay salvage with mandatory test re-run post-salvage (the agent's pre-salvage test pass is invalid).

**Step 3 interview** gained Q5 — worktree provisioning mechanics and ceiling.

**Step 7 batch design** gained ceiling-driven chunking: when file-disjoint agent count exceeds the ceiling, split into sub-waves rather than narrowing the batch.

**"Worktrees always" key principle** amended to acknowledge that the `isolation: "worktree"` Agent parameter does not guarantee filesystem isolation if host-project tooling falls through.

**Anecdotal ceiling patterns** (from this incident only — surface the actual ceiling via Q5 per session; do not extrapolate these as defaults):
- In this incident: cannabis.observer-wordpress (Bedrock + Lima + Nginx vhost per worktree) had a 9-slot port pool (8001–8009).
- Adjacent project shapes worth probing during Q5: Docker-Compose projects may be bounded by their port-mapping range, OR may share a single set of services across worktrees (different failure mode — shared state instead of a ceiling). Plain git-worktree-only projects have no ceiling beyond `git worktree add` concurrency.

**Host project follow-up (not yet filed):** widen `dev.sh worktree create` port pool past 8009, recycle stale ports on `worktree destroy`, or fall back cleanly to "no Nginx vhost" without changing cwd. The originating Q2 backlog tracking issue is `CannObserv/cannabis.observer-wordpress#279`; the port-pool work is a separate follow-up to be filed against that project.
