## Session 2026-10-02 — CannObserv/address-validator#272

The coordinator for CannObserv/address-validator#272 started 2026-10-01 over the repo's issues numbered 246 and up, with no epic and the operator's rule *"prioritize bugs and smaller workstreams."* It started the way CannObserv/status#16 did. One check-in so far: CannObserv/address-validator#270, shipped in CannObserv/address-validator#273. Its findings are one comment on gregoryfoster/skills#348, posted 2026-10-02. Findings as of 2026-10-02; later check-ins weren't reported on #348.

### Shape

- **Way in:** a number range plus the operator's rule.
- **Size:** 12 open issues in range, and 6 already closed there, which the epic lists as "already closed in range".
- **Check-ins so far:** 1. Next named: CannObserv/address-validator#262.
- **Host:** a single VM running systemd, with no CI test workflow.

### What was different

- The consumers were other coordinators. CannObserv/wslcb-licensing-tracker's coordinator had posted measured impact on two issues, and those comments set the top tier instead of the labels.
- The host's gate is local pre-commit plus a coverage floor, so the merge commit had zero check-runs.
- Three items need a production database read or write partway through, which the host's auto-mode classifier denies unless the operator names the query.

### Findings that changed the protocol

Numbers are the comment's own (38–49). The private-cli run's comment on #348 also starts at 38, so cite these as the address-validator run's.

**Creating the epic**

- 38: a number range is a way in. It sweeps in closed issues, which the epic lists so the done count is right, and PRs, which it filters out (CannObserv/address-validator#273 was the PR for CannObserv/address-validator#270). The new-number scan needs the same type filter.
- 39: measured client impact outranks the `bug` label. Only one of six bug-shaped issues carried it. The downstream coordinator's comments showed a quota 429 carrying `Retry-After: 0`, whose retries tripped its breaker and stopped a batch, and 24 `confirmed` answers without a DPV code. The tiers became bugs with measured impact, latent bugs, investigations and ops enhancements, smallest first within each.
- 40: before slotting a latent bug as harmless, check runbooks and fallback modes for the state that triggers it.
- 41: mark approval gates on the line, apart from blockers, so the implementer drafts the query and asks for approval early instead of stalling on it.
- 42: in serial work, a short file-to-issue table only sets order. Work that touches the same function goes back to back while it's fresh. Prune its rows at every tick.

**Check-in**

- 43: verify with the host's own gate. An empty check-run list is easy to misread as green. The deploy check compares the service's `ActiveEnterTimestamp` with the merge time (13:56:01 against 13:55:47). Work the check out at creation, write it into the epic and run it at every check-in.
- 44: verify that every open question on the issue was answered, including those from other repos. The shipped issue had three: two from the downstream tracker and one of its own. The ticked line records that they were answered.
- 45: when an item closes, rewrite the lines that depended on it. `depends on #270` became "dependency met: the error now carries `retry_after_seconds`, so the route only has to forward it."
- 46: when a known limit is already a later child, record that answer on the child's line. The single-provider 500 was already CannObserv/address-validator#268.

**Writing the epic**

- 47: keep the last body written in a local file, and diff the live body against it before each edit, ignoring trailing whitespace, since GitHub drops the final newline.
- 48: read back every write. Epic edits go through `gh api -X PATCH repos/O/R/issues/N -F body=@file` and then a grep of the live body, because this host has a record of `gh pr edit` exiting 0 and changing nothing.
- 49: log a check-in that found nothing. `2026-10-02: #270 closed (#273). No new issues. Ranking unchanged. Next up: #262.` Without that line, nobody can tell "checked and found nothing" from "never checked".

### Reversals

- 40: a bug that fires only under a single-provider config looked deferrable, because prod runs two providers. A grep of the provider runbook showed that its outage procedure switches prod to one provider, so the bug fires during the incident where a 500 hurts most.
- 43: the deploy check was skipped at the check-in itself and run only while the findings were being written.

### What v1's scripts would and wouldn't have caught

- **Would:** findings 47 and 48, which `epic-edit.sh` cites. It keeps the baseline in a state directory, folds CRLF and trailing whitespace before comparing, and reads back every write, exiting 4 when the live body differs from the one sent.
- **Would:** findings 38, 45 and 49. `scan.sh` marks each row `issue` or `pr`. `epic-edit.sh`'s `set-line` rewrites a dependent line and requires the same leading ref, and its `log` op appends the dated entry with `{today}` injected. `--account` refuses an edit while an open issue goes unlisted.
- **Wouldn't:** finding 43. Neither script reads check-runs or a deploy timestamp, so an empty check-run list and a skipped deploy check both pass unnoticed.
- **Wouldn't:** finding 44. `scan.sh` lists the new and edited comments on the epic's items since the last check-in, but matching each question to its answer is still done by reading.
