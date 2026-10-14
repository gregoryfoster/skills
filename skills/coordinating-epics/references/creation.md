# Creating the epic

How a coordinator thread builds the epic it will hold, from any of six starting points, and what every way in must produce before the first hand-off. A citation such as "power-map 55" names a run's entry in [process-log.md](process-log.md), then that run's finding number.

## The six ways in

| Way in | The input | What's different | Runs |
|---|---|---|---|
| **Inherited** | A design doc whose Steps table already holds the phases, blocked-by edges and cross-repo owners | Don't re-score. Consume the table, and file the design's "file X separately" promises now, as blocked issues | archiver (5, 59) |
| **Backlog plus a rule** | Open issues and the operator's one-line rule, e.g. "prioritize bugs and smaller workstreams" | Read every issue in full, comments included; tag each type · size · touch surface; sort by the rule; write the tiebreaks down | status (8, 9), broker |
| **Number range** | "Issues ≥ #N" | It sweeps in closed issues (list them as "already closed in range") and PRs (filter them out) | address-validator (38), power-map |
| **Scoping first** | An epic whose lines are "not yet scoped" | Each check-in may end "scoped: here are the decisions" rather than "next: #N". The decisions comment becomes the child's spec | cannobserv (23, 24) |
| **Adoption checklist** | An upstream release's per-change list | Check it against the host's open PRs and branches; check the upstream summary against its own per-change "Downstream" lines | private-cli (38, 40) |
| **Whole-backlog audit** | Dozens of issues, months old | Fan the audit out to read-only agents; the epic is mostly closures and parking | private-backlog (83–90) |

A **cross-repo parent epic** (a parent over child epics in sibling repos, CannObserv/watcher#368) is created the same way, child epic by child epic. Its check-in loop is not covered by v1.

If no rule is given, propose one, with its tiebreaks and standing overrides, under "challenge it here" (processor F64). An operator rule can conflict with itself ("bugs first" against "smaller first"): make the call once, say so in the hand-off, and offer the swap (status 9).

## Dispositions

Every issue in scope gets one:
- **keep**;
- **rework**, with the new scope written on its line;
- **close**, as done in fact or not planned. Proposed only; nothing closes before the operator approves;
- **park**, with a named re-entry trigger;
- **move** to the repo that owns it, carrying its repro, with pointers both ways (watcher F7);
- **split**, when part of it is actionable now and the rest is blocked (private-cli 41).

Rules for choosing:
- **"Superseded" means the need is gone.** "Deferred because the place for it doesn't exist yet" is a park with a trigger (watcher F8).
- **Close what is done or superseded; park ideas, even dormant ones.** Write the rule into the epic so later triage follows it (private-backlog 94).
- **After an architecture change, creation is a disposition pass,** not only a sort. Issues filed before the change may describe a system that no longer exists (power-map 54).
- **The operator's first closures set a classification rule.** Write it into "Boundary decisions" and classify later arrivals against it without asking again (power-map 56, private-launch 24).
- **Every close and park carries "When to reopen: …"**, and, where the issue's own fix would be wrong by then, the cheaper option to weigh instead (power-map 59).
- **Closed-in-fact:** grep `origin/main` for the fix before slotting. Zero hits is ambiguous, not proof. Rescope a partly fixed issue to its residual.

Walk proposed closures with the operator. Four parts each: what it asks, what changed since it was filed (with evidence), the recommendation, and **the one reason to keep it**. Four closures per question at most (power-map 58, private-backlog 94).

## What to measure before slotting

- **Measure the shared premise once,** and put it at the top of the epic as "Measured state". Lines then cite it instead of repeating evidence (power-map 55).
- **Measure a hazard before you tier it.** A read-only query against real data settles "latent or live" in seconds (private-launch 25).
- **A latent bug may be live in a fallback state.** Check runbooks and outage procedures for the state that triggers it (address-validator 40).
- **Measured impact from a consumer outranks a label.** Another coordinator's comment with numbers defines a tier (address-validator 39).
- **Re-measure counts quoted in old bodies.** "92 overlapping pairs" was 56 after the cutover (power-map 55).
- **Closed issues can leave steps that never landed.** Grep live config for `TEMPORARY`, `revert` and refs to closed issues, and read host memory for scope that never reached GitHub (power-map 57).
- **Check a design doc's "cross-repo changes" table against the target repos,** not just against open issues (processor F65).
- **If an issue copies another thread's rules, read that thread's newest comment** before slotting it (processor F66).

## Ordering

- **A gate tier sits above the operator's rule** when an external event dominates (a launch, a cutover). Label the deferred set so it can be filtered out of view (private-launch 23).
- **Ordering can key on an event window,** read from a live flag at each check-in, not only on a date (processor F64).
- **Order guards and ratchets that protect later items first** (private-backlog 89).
- **The order is a living sort, not a snapshot.** New issues can go above everything remaining (private-launch 26).
- **With serial work, shared files decide order,** not conflicts. Keep an Overlaps table only for ordering, and prune it at every tick (address-validator 42, status 21).
- **Offer to split an item at an approval gate, or to bundle two that share a file.** Either is the operator's call. Record the answer on the line so it isn't reopened (private-launch 27, power-map 62, processor F71).

## The verify recipe, gate and baseline

- **Work out the host's deploy check at creation,** write it into the epic, and run it at every check-in (address-validator 43). A host may have no CI: the merge commit's zero check-runs is easy to misread as green.
- **Run the gate, don't just derive it.** A gate already red becomes the first child, because every later tick verifies against it (broker 83).
- **Record the test baseline:** the command, the environment step (an env file sourced, or not), the passed and skipped counts, and the date. Compare the skip set by identity, not by count (broker 84, 158).
- **Record which gate runs which half of the suite,** and check that each exclusion's reason still holds. One run found about 40% of its tests in no gate (watcher F4, F29).
- **Measure what the verification depends on,** so the first real event settles it (watcher F2). A standing probe is run once when written, and its output goes in the creation log (private-backlog 98).

## Blockers, gates and waits

- **Each cross-repo blocker records an observable unblock condition** (a served spec, a tag and a matching build, a schema pin), its **owner** (operator or agent), and **the stages it gates**: merge, verify, deploy or downstream (archiver 7, 22, 28, 43).
- **A child that must wait upstream gets the operator's choice of interim,** recorded on its line ("waits on owner/repo#N, no interim") (cannobserv 27).
- **Mark approval gates on the line,** such as a production read that needs the operator to name the query. They aren't blockers, but an implementer who meets one unwarned stalls (address-validator 41).
- **Lockstep cross-repo pairs need an AND-form re-entry test** (processor F81).
- **Sibling hits sort three ways:** waiting on us, FYI, or waiting on them. Post the replies owed at creation, so their latency overlaps the queue (private-backlog 87, broker 90). [siblings.md](siblings.md) has the rest.
- **When a gate waits on an event nobody schedules,** write the reorder into the epic in advance, so whoever sees the event acts on it without re-asking (watcher F3).

## Mechanics

- **Draft the body to a file first.** A refused create then costs one handed-over command, not a rewrite (power-map 60).
- **Children not yet created** are drafted with `SUBn` placeholders, created in dependency order, and their real numbers substituted afterwards with Python `str.replace`, never `sed` (archiver 1, watcher F10). `epic-edit.sh` refuses a leftover `SUBn`.
- **Assert the epic's own number against the watermark the body predicted** (watcher F11). The epic takes a number too.
- **Native sub-issues are optional.** A `#N` task list is enough for one repo and fewer than about ten children (status 22). Where used, verify links against the `/sub_issues` list, not `sub_issues_summary`, which lags (archiver 3). List queries also lag right after bulk label edits: verify per issue (private-launch 35).
- **Read a label's description before applying it** (archiver 4).
- **After the epic exists,** take it as the baseline with `--adopt-live`. For a whole-backlog or number-range epic, run the accounting check too: `epic-edit.sh … --account [N] --ops - <<<'[]'`. It names every open issue (from #N, if given) that the body doesn't reference. Header lines don't count as references.
- **Fan-out audits** give each read-only agent one fixed per-issue schema (disposition; type, size and surface; live or latent; dependencies and shared files), a "no GitHub writes" preamble, and the host's known tool failures with the command that works (private-backlog 83, 93).
- **On a public repo, state conclusions, not raw production facts.** "No writers since 2026-09-06", not the per-client breakdown (power-map 60).
