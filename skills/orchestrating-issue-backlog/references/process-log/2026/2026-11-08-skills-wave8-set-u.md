## Session 2026-11-08 — gregoryfoster/skills (epic #516, Wave 8 set U: the readers and knobs batch)

The seventh of Wave 8's local orchestrators.
- **Plan:** the brief was a comment on #605, and Steps 1–9 were skipped.
- **Shipped:** #585, #586, #605 (both halves), #587, #589, #588, #591, #603 and #590. The review rounds used the whole CR block, 1988–2037. The wrap-up is on #516.

**Shape:** four chains, one worker per chain, with reviews running beside them.
- **Chains:** W (using-git-worktrees), S (shipping-work), M (managing-skills) and P (writing-plans).
- **Phases:** W and S each worked in two phases, so S's #605 half landed before W's, which built on its shared test helper. P had two phases too (below).
- **Review rounds:** M took three; W took three plus a narrow fourth; S took three; P's first phase took one.
- **Counts:** the base matched the brief: 10,013 / 398. The skip hash is recipe-dependent: this run's `skiphash.py` gave `79b08fb45f91`, and the coordinator's gave `d192a2f990ec`. So skip sets were compared by identity.
  - The first integration gate read 10,200 / 398 / 0. Its +187 closed file by file against the workers' reports.

## Lessons

### 1. An operator's answer can carry a rule wider than the question
#591 asked whether `php -l` should reach into submodules, and the brief recommended yes. The operator answered no, and added: *a repo should only be responsible for its own code.*
- **The rule reversed shipped work.** It undid set T's CR 1862, which had made nested npm recurse into submodules. It also rescoped #588 before build.
- **The rule's copies were found later, one at a time.** A round-2 reviewer found a fourth copy of composer's reach in a different skill (`reviewing-code-php`'s `gather-context.sh`, CR 2003). A parity test now holds it to the gate's lister.
- **Treat a decision as a rule:** write it back to the issues, save it as a standing preference, and grep for every place it governs before scoping the chain.

### 2. Three rounds of special cases, then one rule
The `.bare`/gitfile lookup in `resolve-worktree-root.sh` drew a 🔴 or Medium finding in three successive rounds:
- **CR 1988:** git refused `<dir>`, and the bare case ran first.
- **CR 1993:** a CRLF or unreadable gitfile.
- **CR 2033:** a typo'd, empty or dangling gitfile.

Each fix added a case, and the next round found a variant. The round-3 brief asked for the general rule instead: a failed probe of a candidate with its own `.git` is exit 2 with git's reason. That removed the gitfile parsing entirely (15 lines in, 32 out), and the round-4 check found the class closed.

S's no-upstream remedy went the same way at smaller scale. It decided by branch name, which a bare clone can't see (CR 2011). The fix removed the branch detection, so one message is right on any branch.

This is set H's lesson 2 and set R's lesson 2 again. **After the second variant of one class, brief the rule, not the next case.**

### 3. The copy no issue named, and the parity test that made it cheap
At Step 0, a grep found `resolve-plans-dir.sh` to be a byte-for-byte copy of the lookup #585 fixes, though #585 named only one script.
- **Correction posted:** the extension went on #605 before build.
- **A second phase for P:** P's phase 2 ported each W fix in turn, behind a parity test that compares exit code and stderr across 31 layouts.
- **What the parity test did:** every W fix showed up as parity failures on the next commit hook, and every mirror cleared them. Without it, the reviews would have had to find the drift.
- **One gap surfaced:** the commit hook's test selection didn't tie the resolver to the parity file. That gap is a follow-up.

### 4. Plan the CR block for the rounds, not the chains
Fifty numbers covered four chains and eleven review passes, and ran out. A narrow round 4 then reported unnumbered findings (R4-n). Sets R and H had used four rounds on a single state machine. **When a brief holds a state machine or a copied idiom, budget the block at about four rounds per chain.**

### 5. Small observations
- **Adjacent rows conflict.** Two chains edited different rows of `docs/KNOBS.md`, but the rows were adjacent, so git saw one conflicting hunk. Resolving it as a union was mechanical. The brief's "merge P first" ordering didn't cover the W/S pair.
- **A recurring flake.** `test_coordinating_epics_scan` failed twice under load ("unable to create temporary file", and `git add` exiting 128) and passed alone both times. It is filed as a follow-up.
