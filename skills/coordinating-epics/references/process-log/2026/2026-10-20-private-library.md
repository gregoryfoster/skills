## Session 2026-10-20 — private-library

The host repo is private, so this entry names mechanisms only; it was filed upstream as gregoryfoster/skills#453.

**Way in:** adoption ([creation.md](../../creation.md)). The epic body already existed, written from a sibling repo's design doc. A dated decision comment widened its scope to the shared library's work that downstream services were waiting on. It was adopted with `epic-edit.sh --adopt-live --lint-all`, after a dry run shown to the operator.

**Shape:**
- 12 children planned across four tiers, plus one parked.
- 3 more slotted mid-run: a correctness fix filed from a consumer, and two release vehicles the coordinator filed.
- 3 residuals filed and parked.
- About 20 check-ins over 5 days, three releases (MINOR, PATCH, MINOR), closed on an empty re-scan.
- Two "scope it" requests were handled as a check-in type of their own: read and probe, post a proposal, and mark the line "awaiting the owner".

**What was different:**
- A shared library whose consumers live in five sibling repos. Every release needed a pointer on each waiting issue. The order rule was "unblock a waiting consumer first, then group by release".
- Most children were contract or extractor changes. A wire-visible change that the changelog rule can't see, such as how an envelope key is derived, had to be harvested by hand.

### Findings
1. **When the next child waits on the owner, run the next unblocked one, and re-route its obligations in writing.**
   - A dependency approval held child A, so child B went first.
   - B inherited an obligation the plan had given A: declaring a mirror obligation.
   - One harvest comment on A recorded the reorder and the shifted obligations, and B's brief carried them.
   - Nothing was lost, and A's brief later built on B's merged surface.
2. **The coordinator's claims about consumer code were wrong four times,** each time taken from notes rather than the consumer's `main`:
   - two briefs put a closed `Literal` on a vocabulary the producer owns;
   - one said a consumer's preview caught only `ValueError`, when it also caught the selector error;
   - one framed an uncaught exception as a production crash, when the consumer's child process already caught `BaseException`.

   The implementer's pre-build review corrected each one, and each was recorded on the epic line as a coordinator error. **Candidate rule:** label a claim about consumer behaviour `[traced]` only when it was read on that consumer's `main` in this check-in. Otherwise label it `[stated]`.
3. **Probe a new dependency in the real environment, not only a clean one.** A throwaway-environment probe leaked the workspace venv and showed the library loading an optional regex engine, a C extension. That turned out to be the production fact: an existing dependency always installs the engine, so the library always switches behaviour. The brief then asked for tests that pin it. A truly clean probe would have hidden it.
4. **Put "close at merge" in the brief.** Three implementers in a row wrote "leave open until the release" in their post-merge steps. Each then corrected themselves by citing the previous child. The epic's practice should travel in the kickoff, not be rediscovered each time.
5. **A Waits row is "met" only when its unblock condition is met, not when our side is done.** At close, the coordinator nearly marked rows met whose condition was a consumer deploying the release. They became "our part done; waits on X". The exit criterion allowed that, because the downstream half lives in the sibling repos.
6. **A release vehicle the coordinator files carries the bump as an operator decision, and starting the thread does *not* approve it.** The body gave the rule (breaking means MINOR) and its precedent. The owner chose MINOR twice: once against the rule, to signal a contract set, and once with it.
7. **Pre-flight found two measured hazards no issue mentioned:**
   - a selector error that isn't a `ValueError` escaped the extraction-error path;
   - a canonicalizer shared "as is" would have rejected the floats and nulls real bodies carry.

   Both went into briefs as items with options, and each was settled in its thread.
8. **Scripts.**
   - `scan.sh` caught every downstream move. It also caught the epic's own new issue right after the coordinator filed it, so re-scan after filing, before `{last_seen}` is written.
   - `epic-edit.sh`'s lint refused a short cross-repo ref once.
   - Missed: a `note` on a Parked table row lands in its "Last re-read" cell. It's harmless, but a note target that knows the row's columns would read better.
