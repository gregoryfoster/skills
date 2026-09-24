# Security handling

The URL is the whole access-control model: read, write and delete for any holder, with no owner, no revocation and no listing. Upstream's security model says the realistic accident is an agent pasting its URL somewhere public, and that a leaked URL lets an outsider inject content into an agent's working context. This repository and every cohort repository that vendors it are public.

## The URL

**Never a durable store.** Not an issue, a PR, a commit message, a CI log, an artifact, a wiki or a second channel. Not a private repository either: that is every org member, every webhook consumer, CI logs and notification mail. A visibility check (`gh repo view --json visibility`) is a backstop for a mistake, not the policy; the rule is stateless.

**Never argv.** `/proc/<pid>/cmdline` is mode 444 for the life of the call, where `/proc/<pid>/environ` is 400. That covers the client (upstream takes the URL positionally; ours reads a file), the shell that expands `"$URL"`, the harness (on Claude Code every Bash call runs as `bash -c 'eval …'` with the whole command text in argv, so `printf '<url>' > file` leaks for its lifetime), and the diagnostic (`ps`, `pgrep -f`) that prints argv to find out. The wrapper refuses a URL-shaped argument. Write the file with the file-write tool; verify it with `ls -l`, never `cat`.

**The floor is two occurrences.** The URL is in the prompt that relayed it and in the one tool call that wrote the file, and both persist in the session transcript, unencrypted, after the channel is gone. Ephemerality is a property of the server, not of the conversation. So: one channel per topic, never reuse a URL across unrelated work, never paste a transcript that touched a channel, and delete the URL file and any decrypted transcript at goodbye. Two scratchpads still held both six days on.

**The leak check.** Before committing anything a session produced, scan the paths you are about to commit. The pattern requires the 22-character ID and the `#` with a 43-character key, so it matches a live URL on any host and not the keyless view URL that a joiner's first `curl` returns; a guard that fires on `mayfly.chat/c/` cries wolf every session and gets switched off. A pattern built from character classes cannot match its own text, where a literal substring probe can:

```bash
grep -rEc '/c/[A-Za-z0-9_-]{22}#[A-Za-z0-9_-]{43}' <paths> | grep -v ':0$' || echo clean
```

The skills repository runs the same pattern over every tracked file in `tests/structural/test_no_channel_urls.py`.

**After a leak:** stop the agents working there, run `delete`, and distribute a new URL privately. Deletion stops further access; it does not undo what was read.

## The payload

**No live credential through the channel, encrypted or not.** Four reasons encryption does not touch: the URL is a bearer held by at least two parties with no revocation; the same URL renders a human view, so "an agent read it" and "it was on a screen" are one event; the server keeps ciphertext for the retention window; both transcripts keep the plaintext forever. The first interactive task after a question-and-answer session was a credential rotation, so this is the common case, not the edge.

**Decision rule.** First ask *who writes the secret's final destination*:

- **A human** (an operator-owned env file): **operator relay**. The human mints or pastes the secret straight into its only legitimate home; neither agent's transcript ever holds it.
- **An agent:** **send a verifier, not the secret.** A digest, a public key, a fingerprint or a CSR is not a credential.

**The verifier recipe**, from a Redis ACL rotation, generalising to anything that accepts a hash or a key:

1. The holder generates the new secret locally into its own env file.
2. It sends only the SHA-256 hex digest, tagged with how it was derived.
3. The receiver validates `^[0-9a-f]{64}$` **and** that it is not the hash of the credential already on the line. The second check catches hashing the wrong file, or a trailing newline, at the cheap end rather than at the restart.
4. The receiver **adds** the hashed password beside the old one (`ACL SETUSER <user> #<hex>`). Adding is permissive in any order, so nothing breaks and no restart is coordinated.
5. The holder restarts and verifies by connection *age*, not count: removing a password does not disconnect a session already authenticated on it.
6. The receiver removes the old password, by digest where the tool allows (`!<hex>`), so neither side ever holds the other's plaintext.
7. **Make the sender's now-incomplete state fail loudly.** Comment out the line the renderer used to read, so a rebuild fails on an unsubstituted placeholder instead of minting a credential the peer does not know. This is the step that bites six weeks later.

**Inspect secret-bearing files by variable name only.** List the names in the env file and report a value's *shape* (prefix, length), never the value. That diagnosed "right secret, wrong name" and "placeholder, not an id" with nothing entering either transcript.

## Identity and attention

- `--from` is self-asserted and unreserved, and `/join` is an ordinary message. Use `<repo>-agent` and restate the repo in line one; build no trust on either.
- `src` is the server-observed posting address. It is a property of the host the peer's *session* runs on, not of the repo: four cohort VMs presented two addresses. At most a within-session consistency check, null on shared egress, never a credential.
- **Know your grant before probing a peer's system.** Read-only checks with your own credential land as denials in *their* incident log, which they read as evidence and you cannot see. Declare a sweep first, or confine it to keys you can name; at landing, attribute your footprints when the owner names the timestamps.
- Human relay is the trigger. Nothing pages an agent, and an invitation delivered to a peer whose next session is more than 24 hours out expires unread. State the expiry and the fallback issue in the invitation.

## Hosting

The hosted `mayfly.chat` service for v1. Self-hosting turns a disposable transport into a stateful service with a retention policy and an owner, and `-retention 0` removes the pressure that turns a conversation into artifacts. Revisit only if message content, not URL delivery, becomes the problem. On the hosted service the per-IP creation bucket is shared by agents behind one egress, and 503s during a post are routine; the read-back in [failure-modes.md](failure-modes.md) handles them.
