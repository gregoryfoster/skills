# Sibling repos

Most epics depend on another repo somewhere: an upstream release, a consumer's adoption, a question another coordinator asked. This covers waits, replies, claims and sibling epics. A citation such as "broker 109" names a run's entry in [process-log.md](process-log.md), then that run's finding number.

## Reaching them

- **List repos and tokens from the source** (the env file or the credential helper), never from memory or a notes table. A 404 can mean "no access" rather than "doesn't exist"; say which (broker 86, 159). `scan.sh` reports an unreadable cross-repo ref as an error and a warning, not as absent.
- **Write every ref as `owner/repo#N`** wherever it's posted. A bare `#N` links to the host repo's issue of that number, and leaves a stray backlink there. `epic-edit.sh` refuses a bare ref after a qualified one, and a bare ref above the host's highest number (broker 92, 145; watcher F61).
- **Reading a sibling repo is allowed,** and is often the cheapest way to settle a question. Read its code at a pinned commit, not its original ask (broker 113, 129; private-cli 42).

## Waits

- **Each wait records who waits, on what, where it was asked (thread and time), and its unblock condition** (broker 150). Separate "reply owed" from "work owed". Post replies at creation, so their latency overlaps the queue (broker 90).
- **External replies are coordinator lines.** The coordinator drafts each one and posts it only with the operator's consent for that post. They never go to an implementer (private-backlog 88). A decision that creates recurring cross-repo posts says whether it grants standing approval. The default is no (processor F111).
- **Strike a wait as soon as its reply is posted, and audit the list itself each tick** (broker 105). When the last answer arrives, flip the wait from "we wait on them" to "they wait on us", and re-tier (broker 110).
- **Re-read every tracked ask each check-in, by subject keywords as well as by number.** Answers and fixes happen without anyone telling the epic. A fix shipped upstream while the epic said "drafted, not filed" for a day (power-map 63, private-backlog 152).
- **Re-scan siblings for the same concern, not only for refs to the epic.** A parallel effort may never mention it. Search by subject before framing any decision that spans repos (cannobserv 30).
- **Look for other epics' lines that name this repo** (broker 118). Grep the host's own recent comments for future-tense promises ("we'll ask", "will file") (watcher F5).
- **In a deadlock, whoever holds the credential acts.** Read the target's own tracker to see who it thinks acts (broker 136).

## Claims from a sibling

- **Hold a cross-repo claim until it's checked against the sibling's code** (watcher F47). Check an answer's claims against the source wherever a claim would imply a grant, a permission or a contract. Correct the sibling's record, with its owner (broker 109).
- **Read sibling answers against each other.** On a conflict, read the artifact both describe before asking either again (broker 108, 113).
- **An upstream checklist can't see the downstream repo's open PRs,** and its summary can contradict its own per-change notes. Go by the detailed note (private-cli 38, 40).
- **Upstream closing comments carry "For <consumer>:" sections.** Turn each into write-backs to the dependent children (archiver 29).
- **Downstream audits follow inheritance and delegation,** not only direct calls (cannobserv 29).
- **Check that a sibling's doc or PR is ordered against the cut,** and put that order on the waiting child's line (broker 111).
- **Moving answers:** put an answer on the child that waits for it within the hour (broker 107).

## Sibling epics

- **Never edit a sibling epic's body** (broker 157). Comment on it, or on the child it tracks.
- **A sibling epic filed in the same repo is referenced, not tracked twice.** Pull in only its unblocked children, and write the reorder trigger down when you slot one (broker 157).
- **Mirror a wait** on both sides when two epics wait on each other (broker 118).
- **Amending a peer's agreement includes telling the peer,** as part of done (processor F128). An ownership transfer moves the duties too: file each one, or record that it isn't wanted (processor F131).
- **Scope that moves between epics is written back to both,** with the reason, so the losing epic's checklist doesn't keep claiming it (cannobserv 33).

## A private host, a public destination

- **When the host is private and the destination is public** (this skills repo's process log, a public sibling's issue), name mechanisms, not identifiers: no repo, issue numbers, files, routes, units or data. Grep the text before posting (private-launch 37).
- **On a public repo, state conclusions, not raw production facts.** "No writers since 2026-09-06", not the per-client breakdown. A harness's safety classifier may refuse the write anyway: draft it to a file, so the operator can post it by hand (power-map 60).
- **Live reads extract only flags or counts.** The check before posting asserts that no secrets or digests are in the text (broker 120). `epic-edit.sh` refuses common token shapes in the lines it adds.
- **A live-channel outcome lands on a durable issue.** The epic links that comment, never the channel (processor F77).
