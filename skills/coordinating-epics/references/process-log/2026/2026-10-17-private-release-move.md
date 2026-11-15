## Session 2026-10-17 — private-release-move

**Shape:** design-doc epic. Six children, serial, operator-paced. A single-host FastAPI service moved from "systemd runs the dev checkout" to a root-owned release run by a dedicated system user, with root-only secrets. Ran 2026-10-14 to 2026-10-17: seven check-ins, closed on an empty re-scan. The host repo is private, so this entry names mechanisms only; it was filed upstream as gregoryfoster/skills#428.

**Skill coverage:** the coordinator ran check-ins 1–6 by hand and adopted the skill only at close-out (`--adopt-live` on the final write). The findings below include what the skill would have caught earlier.

### Findings
1. **A box ticked by someone else turned up at every check-in.** Implementer threads, or the operator, ticked the child's box before the coordinator verified it, on 5 of 6 children. A hand-run coordinator just kept the tick. `epic-edit.sh`'s foreign-tick check is the right default, and this run is evidence for it.
2. **Independent verification found what the reports left out,** four times:
   - **Design:** a measured cgroup escape. Memory-capped children launched with `systemd-run --user --scope` sat outside the service's `MemoryMax`. It became its own child.
   - **A child's side note** had a 46-hour outage of a third-party credential that the health probe never saw. The journal showed onset and recovery, and an issue was filed.
   - **A cleaned path reappeared.** By bisecting test files with a throwaway teardown hook, the coordinator traced it to a test factory default, not production.
   - **A behaviour change nobody stated:** once the service's working directory moved to the release, a relative `env_file` entry stopped resolving. The dev env file then no longer reached production in any form, and the docs had to say so.

   Rule support: "verify live, never from the report".
3. **`scan.sh` failed its commit range when `origin/HEAD` was unset** in the local clone (`fatal: ambiguous argument … origin/HEAD`). It succeeded with `--ref origin/main`. The same run printed `closing issues unread: url` for every closing-issues read, on gh 2.45. **Already filed and closed upstream** as #411 and #424; this host's vendored copy predates the fixes. It is a second sighting, so no new issue.
4. **`epic-edit.sh` can't reach a sub-bullet under a ref's line.** A stale "Open: backup run due …" sub-bullet needed a `replace-section` of the whole checklist. (Related: #408, `replace-section`'s reach over `###` subsections.) **Tool gap, not yet filed:** a `set-subline` op, or `note` with `replace_sub`.
5. **A legacy bold-paragraph cursor** (`**Last check-in:** …`, not a list item) was rewritten in place by `header`, while the new cursors went into a separate list. The result has mixed formats. A second sighting of **#399**.
6. **The agent permission classifier blocked prod-touching verification in child threads:** creating a short prod Job, and a read-only prod-DB column scan. Both went through only with the operator's per-run consent. **Brief rule:** a Verify step that needs a prod Job or a prod-DB read names the operator's consent as a precondition, in the brief.
7. **A gate dated after the last child held the epic open about 19 hours:** a nightly backup timer after the user switch. That was acceptable here because it was short and certain. close-out.md's "a check dated after the end goes to a dated issue" (watcher F60) would have closed sooner. Record the choice either way.
8. **Kickoff prompts should say "fix the review", not "run the review"** (operator's revision). Implementer threads sometimes reported before their review's fixes had landed:
   - On one child, 12 review findings in 3 rounds landed after its closing comment.
   - On another, a doc fix held in review shipped after its first Verify report.

   Each time, the SHA the coordinator verified was no longer the final one. **Rule for hand-off.md's kickoff prompt and the implementer contract:** run the code review and **fix its findings**, or record each declined one with its reason, before reporting. The report then names the final SHA, the one the coordinator verifies.
