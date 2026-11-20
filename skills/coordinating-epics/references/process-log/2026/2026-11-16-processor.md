## Session 2026-11-16 — CannObserv/processor#84 (burn-down to parking lot)

A whole-backlog burn-down, created from an audit on 2026-10-24 under the operator's one-line rule: "Prioritize bugs, issues other repos are waiting on, and operational conformance and stability." It met its exit criterion on 2026-11-16, and at the operator's choice it stays open as a parking lot with two items. Findings are numbered here, cited `processor#84-F<n>`, and not posted on [#348](https://github.com/gregoryfoster/skills/issues/348). The host's earlier run is [2026-10-12](2026-10-12-processor.md) and [2026-10-23](2026-10-23-processor.md). Bare `#N` refs below are CannObserv/processor's.

### Shape

- **Way in:** a whole-backlog audit. It kept 2 open issues (#75 in Tier 3; #54 parked) and filed 8 gaps that nothing tracked (#76–#83): host patching never run, a journald priority bug, a sibling's per-host ask, and cohort practices Processor lacked. The coordinator's tiebreaks were numbered, so the operator could challenge any one (F1).
- **Children:**
  - 22 lines done.
  - 14 arrived after creation. 5 were filed by the coordinator (#87, #106, #112, #113, #138). The rest came at the operator's request, from sibling and skills sessions, or from a child (#140).
  - 6 were ports of a sibling's shipped fix: CannObserv/broker#90, CannObserv/broker#112, CannObserv/broker#113, CannObserv/broker#122, CannObserv/broker#125 and CannObserv/replicator#193.
- **Check-ins:** 58 log entries over 23 days. In the last stretch a 12-hour idle alarm wrote read-only reports between the operator's visits.
- **End:** parked on 2026-11-16 (operator). #54 waits on a broker window; #140, a shared-library bump filed by the last security child, waits on any of three triggers. One verification debt rides #54's trigger.

### What was different

- **The exit criterion was met twice.** At #130, Tiers 1 and 2 were closed, but the re-scan was not empty in substance. It held an unslotted sibling-filed issue (#134) and four Dependabot alerts with no issue at all. The operator slotted both and left the epic open. `scan.sh` reads issues and PRs, not alerts; the audit and the alerts API surfaced them (F5).
- **Three briefs held errors that the implementer's pre-build review caught.** Each was recorded on its epic line:
  - #113: three claims;
  - #130: a doc mention the grep missed, because the doc wrapped the term in backticks (F3);
  - #138: the brief took the shared library's compatibility check, which covered only the latest major of a dependency (soupsieve 4.0). It missed 3.0's strict `:has()`, which turns some selectors from results into refusals (F4).

  The kickoff line "review the brief against the code and post corrections before you build" caught every one before code was written.
- **A pre-flight probe in a throwaway copy.** For #138 the coordinator applied the issue's recipe to a scratch copy of `origin/main` and ran the parity and containment suites, never touching the repo. That made upstream's `[stated]` claim `[measured]`, found the exact locked version, and named two test hazards the brief hadn't (F6).
- **An attended gate missed on its first real use.** #113 built a "patch due → missed → ok" check-in. The first window passed unanswered: the coordinator asked at 05:07Z, and the operator was away. The run happened out of window under a one-off dated window. Only then was the mechanism proven end to end, the miss path included (F2).
- **Verification debt attached to a parked trigger.** #134's live record can't be forced in production. Its first chance is the same broker window #54 waits on, so the debt rides that trigger instead of holding the epic open (F7).
- **A restart decision folded into a child's deploy.** A glibc update sat unrestarted for days. #138's deploy restarted the service anyway, so the brief named the restart as an expected side effect, and the patch window had nothing left to do (F11).

### Findings that changed the protocol (proposed)

**Handing off**
- A doc correction's search must match the term with and without markup (backticks, links), not only bare (F3; extends broker 154).
- When a child crosses several majors of a dependency, read every intermediate major's breaking changes. An upstream consumer's compatibility claim covers only what that consumer checked (F4).
- Probe the issue's recipe in a throwaway copy before briefing, when the build is a lock or config move: apply it, run the guarding suites, discard the copy (F6).

**Verifying**
- An attended gate (a window, an approval) is proven only once its miss path has fired and recovered, not by its first "due" (F2).
- At an apparent exit, read the alert and audit sources too, not only the scan: an advisory can sit with no issue (F5).

**Recording**
- Debt that can't be forced goes on the parked item whose trigger will produce the evidence (F7).
- A notice posted by an implementer thread "with approval" is `[stated]` to the coordinator: check that it exists, and say the approval wasn't witnessed (F12).

### Open suggestions for the scripts

- **`log` op:** text that starts with `- ` was written as `- - ` (11 lines, 2026-11-07 to 11-11). Strip it, or refuse it (F8).
- **`set-line` and `add-line`:** the refusal "the new line doesn't lead with #N" means "starts without `- [ ] `/`- [x] `". Say so, or add the box (F9).
- **`add-line` `section`:** "no section headed 'Tier 1'" needs the full heading. Accept a unique prefix, or list the headings in the refusal (F10).
- **`scan.sh`:** report open Dependabot alerts (count, and package names) beside the issue watermark (F5).
