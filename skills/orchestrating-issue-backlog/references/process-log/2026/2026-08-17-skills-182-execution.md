## Session 2026-08-17 (gregoryfoster/skills) — execution addendum

Execution of the #182 plan (planning entry above). Four batches, 9 worker agents in harness
worktrees, all merged; 13 issues implemented, #164 closed-in-fact, #163 deferred. Four CR rounds,
27 findings. Ten follow-up issues filed (#184–#190, #193–#196). One scoped `curating-context` run
at the end, on the doc the batch had pushed to 37 tokens of margin.

### Every CR round found a defect introduced by the fix for another defect

Four rounds, four instances, and it is the single most reliable thing this execution produced. The
sharpest is round 4:

#181's whole subject is a write whose failure is swallowed. Its fix added
`trap 'rm -f "$SETTINGS.tmp"' EXIT` so a killed run could not strand a temp file — and the name
carries no PID suffix while the trap fires on **every** exit, including `--check`, which writes
nothing. Before the trap, a concurrent run's in-flight file was safe. After it, any invocation
deletes any writer's. A two-writer race widened into "anything clobbers anything", by the change
closing a neighbouring hazard, **while the correct shape sat in a sibling script in the same batch**
(`install-doctor.sh`'s `.doctor.sh.tmp.$$`, which the same agent had just audited and praised).

Earlier rounds: a blanket `rm -f …findings.*` sweep that would have deleted a concurrent session's
file mid-write — the exact race the per-PID name existed to prevent; a `[ -n "$X" ] && printf` under
`set -e`, written into the branch whose issue sweeps for that idiom; an `AGENTS.md` reword that cost
+21 tokens against 29 of remaining headroom with two agents still queued.

**The generalisable form: a fix lands inside the blast radius of the defect it is fixing, and the
author has just finished proving they understand that defect.** The review pass that catches it
cannot be the author's.

### Hand the agent the gate command, not the number

Token headroom was briefed wrong **three times**, in both directions, and once shipped a ratchet
breach to `main` (186 tokens over, found by a later agent, repaired by a fifth). Each time the cause
was the same: quoting whichever reading was looser, against a gate that binds both.

The refinement came from an agent, and it is worth stating precisely because the obvious lesson is
wrong. *"Don't compute headroom as bytes ÷ 2.68"* is right in effect and wrong in cause — for a file
with no per-file calibration that arithmetic **is** the estimate, exactly (26,336 ÷ 9,826 = 2.6802).
The divergence is in the *exact* reading, and which of two estimators applies depends on whether the
file has an entry in `.skills/context-token-counts`. Two agents in the same batch reported
contradictory things about the estimator because they were measuring different files.

Batch D's briefs gave the gate invocation instead of a figure. **Zero budget errors in that batch**,
against three in the preceding three.

### Point a new gate at the specification that motivated it

The highest-value thing in the batch was unprompted. The agent building #117's pre-registration
mechanism ran it against `validation-gate.md`'s **own** registered steady-state primary — and got
*"no informative pairs — nothing was measured."* The registered metric is a derived rate over
scheduled rows, and the gate skips every scheduled row, so the metric it specifies is one it cannot
read. **This backlog's title defect, reintroduced by the mechanism built to close it**, found by
using the tool on the document that specifies the tool.

Cheap, repeatable, and not in any brief: when an agent ships a gate, the first input should be the
spec the gate came from.

### A correct general rule does not license a specific claim about a call site

#181's mechanism is true — under `set -e` the failure of the first element of an `&&` list is exempt
from errexit. Its conclusion for `install-guard.sh` is false: the list is the **last command of a
function**, and the function call is a simple command, so the list's status becomes the return
status and errexit fires on the caller before the success line. The agent ran a two-line probe rather
than reasoning from the rule, and I re-ran it rather than accepting the correction.

What actually reproduced was different and unnamed: an orphaned zero-byte temp file for `git add -A`
to collect, and an **undocumented exit 5** printed after `linked …`, leaving a half-install with
nothing saying which half landed. The issue was right that something was wrong there and wrong about
what.

Same shape, my own: the curation commit asserted that a demotion out of a *reference* doc has no
automated seam sweep. `check-seams.sh` takes `--file` and sweeps one happily — I had run it with the
wrong scope and written the gap up as fact. Caught by testing my own claim in the next CR round.

### Measure the "too noisy to be useful" hypothesis instead of asserting it

#181 anticipated that a grep-based rule might be unusable and said reporting that would be a
complete outcome. The agent produced the number instead of the opinion: the **symptom**-shaped rule
("a write followed by an unconditional success message") returned **37 candidates, 0 true
positives**; the **mechanism**-shaped rule (a file redirect in a non-final position of an `&&` list)
returned **0 on the current tree and 1 against the pre-fix file**. It shipped the second and wrote
the measurement into the module docstring, so the rejected formulation cannot be re-proposed
cost-free.

It also refused `|| true` as an exemption — accepting it would teach the fix that produces the
sibling bug — requiring a named marker instead, which flagged exactly one line.

### A per-file disposition assigned from one match blinds the sweep to the rest of the file

The sweep's file set came from `grep -rln '\.tmp'`. `skills-submodule-update.sh` matched, was
inspected at its `.tmp` site, found **correct**, and classified READ-ONLY. Its unchecked
`date … > "$LOCK" || true` at `:237` — a different spelling of the same defect class — was never
looked for, because the file already had a verdict. Filed as #193, and it is the script that the
*already-fixed* one names as its model in its own comment.

Two other enumeration faults in my own greps: `grep -r` does not follow symlinks found during
traversal, so `.claude/hooks/` contributed nothing to a set it appeared to cover (the file was
reachable only via its real path); and the `--file` scope above.

### Markdown line ranges go stale between batches — 2nd sighting, promoted

#117's issue comment named its owned window as `validation-gate.md` **L309–391**. By the time Batch D
launched, Batch C's edits above it had shifted the section to **L306–388**. Nothing overlapped and no
merge conflicted, but a brief that had been trusted rather than re-derived would have pointed an
agent three lines into another issue's territory.

Same rule as 2026-08-17 watcher, one day earlier and a different project, reached from the other
direction: there the contested surface was almost all Markdown *within* a batch; here the drift is
*across* batches, which is the worse case because the plan is written once and consumed four times.
**Promoted** to Step 5 as a clause on line-window ownership: name the section, verify at launch.

### Also captured

- **`core.bare = true` appeared in the main checkout's `.git/config` four-plus times** during agent
  runs, each occurrence tracking agent activity. It makes `git status` fail with rc=128 and empty
  stdout, so a stdout-only cleanliness check reads "clean" — it *disables* the detector rather than
  tripping it. Filed as #189; the hardened check (exit code plus an `--is-inside-work-tree` canary)
  was promoted into the skill mid-session.
- **A curation is available as a batch-tail step.** `validation-gate.md` ended Batch D at 37 tokens
  of margin — passing, and unworkable for whoever came next. One scoped `curating-context` run
  demoted the dated record of one experiment out of the doc that states the rule, returning it to
  949. Worth considering wherever a batch's budget contention was flagged at planning time.
- 9 of 9 worker reports corrected something in their brief. The two most valuable corrections in the
  session — the errexit diagnosis and the arm-predicate argument — were both *refutations of the
  issue*, not of me.
