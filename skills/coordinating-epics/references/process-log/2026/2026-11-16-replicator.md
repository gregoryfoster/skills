## Session 2026-11-16 — CannObserv/replicator#154

A whole-backlog epic on a public bus-worker repo, coordinated in one thread for 23 days, from creation on 2026-10-24 to parking-lot mode on 2026-11-16. The host is a bus consumer with no HTTP API. It started the run deploying the main checkout plus a restart. It ended deploying a root-owned release under `/srv`, as its own confined user. The shared contracts library and its private package index live in a **private** repo, so they're named here by role only: "the library" and "the index".

### Shape

- **Way in:** a whole-backlog audit with the operator's one-line rule: bug fixes, sibling waits, operational conformance and stability, and re-check older issues for relevance. It found 8 open issues: 5 slotted in tiers, 1 new child filed, 3 parked, and 0 closures proposed.
- **Children:**
  - 8 at creation, 40 ticked at the park.
  - About 30 were filed mid-run: review-born follow-ups, pins the idle checks found, bugs the coordinator measured, and siblings' asks.
  - One child epic (CannObserv/replicator#135) was handed to this thread mid-park and closed here.
- **Check-ins:** 44 numbered, plus about 20 idle checks.
  - The thread outlived several context compactions. The epic body and a scratch directory of builders and briefs carried the state across each one.
- **Baseline:** 1468 passed, 1 skipped at check-in 1; 2062 passed, 1 skipped at the park. The skip set was compared by identity at every check-in.
- **Ending:** the exit criterion's six issues were all closed by check-in 8. The order rule then kept going for three more weeks, until no child was unblocked. The operator chose parking-lot mode, with 4 parked rows and 1 external wait.

### What was different

- **The library moved faster than the burn-down.** It got 8 pin moves in 23 days: 0.39 → 0.40, the 0.40.1 floor, 0.41, 0.41 → 0.44, 0.45, 0.46, and 0.46 → 0.48.2, plus the first catch-up. Each move was one deploy and one restart. Each was its own small child, filed the day the index listed it.
- **A 12-hourly idle check, run by the coordinator thread itself.** It was a session cron with a verbatim read-only prompt, reset at every check-in. Two of the pin moves came from it.
- **Measured hazards re-ordered the queue three times:**
  - a disk page at 85% brought forward the GC adoption, then a disk grow;
  - a pre-flight found that the service's user had passwordless sudo and the unit had no sandboxing. That jumped the queue ahead of a drift check;
  - a flaky test turned out to print a broker password.
- **The coordinator ran approved non-code operations itself:**
  - one Dependabot merge;
  - a by-hand GC run;
  - code-index refreshes;
  - one host-config install, on the operator's authorization.

### Findings

**Pin moves**
- **B1. Probe the index unbounded, every time.** A pickup probe at `<0.43` proved only that no 0.42.x patch existed, while 0.43 and 0.44 were already listed. The review caught it, and the move widened to 0.44, saving a restart. After that the idle check's prompt said "unbounded, every time (not optional)", and it found 0.45 and 0.46 within hours of tagging.
- **B2. A brief's "what changes" comes from a whole-wheel diff, not the CHANGELOG.** It was wrong three times:
  - a fallback described wrongly;
  - two removals the CHANGELOG names that ship in none of the three wheels, because they live in an extension package.
  
  The fix is a closure-diff script over the host's import closure: it classifies each file as identical, version-only or changed. Paste its report into the pin comment, and read every `changed` file. Twice a `changed` file was settled by measurement: the module can't load here because its third-party dependency isn't installed.
- **B3. A pin move's literal sites are greppable, so list them in the brief:** the policy file, the dependency doc, the manifest, the pin comment, and an index test whose upper bound goes red on purpose. Briefing that grep made the last three moves uneventful.

**Pre-flight and briefs**
- **B4. Every pre-flight found sites its issue missed:** 9 more on the index move, plus a credential hazard (the host's default credentials were the *writer*'s); 2 on the docs retirement; and the implementer's pickup review found 3 more, which it triaged. A pre-flight is a measured list, and the implementer's review against `origin/main` is a second, independent one. Both pay.
- **B5. The coordinator's own brief errors were corrected in place, about ten times.** They clustered on claims taken from upstream text rather than measured: an extra's name, a decode site (twice), an index claim, "a stale shell value fails closed" (it could open a gate), release-retention arithmetic, a rollback target (caught before posting). Each was marked visibly and searched for wherever else it was made.
- **B6. Cite the exact token count, not the estimate, near a budget.** A brief said a doc was "9999 of 10000". The implementer measured 10101 exact, already over. The repo's bytes-per-token ratio runs higher than this doc's.

**Verify**
- **B7. Run the suite in both a clean and a loaded shell.** A watched 1-in-10 flake was really 5 tests failing every time after the env loader, because the scrub missed two flags. The next child found a loaded-shell test printing the broker URL with its password. Both became Tier 1 bugs.
- **B8. Compare skips by identity, including where they come from.** A coordinator run launched detached from the session root skipped a session-premise test the implementer's run passed. Running it in the foreground settled it in one command.
- **B9. The submodule auto-refresh pushed a red `main` twice.** Read CI on the hook's commits too, not only the child's range.
- **B10. A blocked question stops the coordinator's own scheduled checks.** A session cron fires only when the REPL is idle. A structured question left open for 11 h held back one idle check, and the answer arrived after a new upstream release. Re-verify live state when an answer lands, and say the missed check out loud.

**Exit and parking**
- **B11. A whole-backlog epic outlives its exit criterion.** The criterion named the issues that were open at creation, and they were done in 6 days. The order rule then produced 30 more children. Its real end was "no child unblocked". For a backlog run, write the criterion that way, or expect to restate it.
- **B12. At the park, re-read every row against the latest upstream release, not only its trigger.** The library's 0.48.2 was re-checked against a row whose trigger is a decode rule, and that rule was still optional. A downstream sibling was still on 0.38. Both are recorded as measured, on the parked row.

### Ending

Parked 2026-11-16, after the last unblocked child (a docs retirement, `d549a06`, not deployed by the operator's choice) was verified. Retitled "Parking lot". `Next: none`. Four parked rows, each brief-grade with trigger, action, hazards and evidence: a drift check parked on an upstream scope ask (gregoryfoster/skills#641), the Dependabot `uv` ecosystem, retiring an unordered stream path, and archival-capture research. One external wait: the broker's maintenance window. The idle check continues as the watch.
