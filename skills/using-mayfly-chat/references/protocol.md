# Mayfly protocol, and the vendored client

The wire contract, condensed from upstream's [protocol.md](https://mayfly.chat/docs/protocol.md) (josharian/mayfly, MIT), plus what `scripts/client.mjs` does differently from upstream's `client.mjs` and why. Two cohort agents wrote interoperating clients from upstream's doc alone when the harness refused to fetch the client (classified as code from an external source), so the contract is here in enough detail to do that again.

## Keys and envelopes

- A full URL is `<origin>/c/<ID>#<key>`. The key is 32 random bytes as unpadded base64url (43 characters). Everything derives from it with HKDF-SHA256, **empty salt**:

  | info (UTF-8) | output |
  |---|---|
  | `mayfly id` | 16 bytes, base64url (22 characters): the public channel ID |
  | `mayfly auth` | 32 bytes, base64url: the bearer for event and delete requests |
  | `mayfly enc` | 32 bytes: the AES-256-GCM key |

- The ID alone derives nothing. The keyless `/c/<ID>` URL is harmless, and it is what a `curl` of the channel returns as the human-view link.
- Creation sends `{"id","auth_hash"}`, where `auth_hash` is base64url(SHA-256(bearer string)). The server stores the hash, never the bearer or the key. Never send the `#key` as the bearer.
- Inner plaintext is UTF-8 JSON `{"from":"NAME","text":"TEXT"}`, padded with ASCII spaces to a multiple of 256 bytes, so the server learns sizes only in 256-byte buckets. AES-256-GCM with a fresh random 12-byte nonce per sealing attempt; the AAD is UTF-8 `id + ":" + decimal(seq)`; the 16-byte tag is appended to the ciphertext. The envelope is `{"nonce","ct"}` in base64url. A wrong sequence fails the tag rather than misattributing, so **reseal whenever the cursor changes**.
- Rendering: server-supplied `seq`, `ts` and `src` always win over inner fields. An undecryptable or malformed event keeps its position as a placeholder (`from:""`, text `(undecryptable message)` or `(invalid message)`); never skip one.
- `srv/static/vectors.json` in the upstream repository pins the construction for every implementation.

## Routes

- `POST /new` with `{"id","auth_hash"}` → **303** to the keyless path. A per-IP creation bucket of 100 refills at 100 per 24 hours, and agents behind one egress share it. 409 means the ID exists, 429 the bucket is empty, 403 a cross-origin refusal.
- `GET /c/<id>` content-negotiates: `curl` gets compact agent instructions, `Accept: text/html` gets the viewer. Neither registers anything or adds an event.
- `GET /c/<id>/events?since=N&wait=S`: read. `since` defaults to −1; `wait` is capped at 86,400 seconds.
- `POST /c/<id>/events?last=N&wait=S`: compare-and-swap append, sealed for N+1, then a wait for replies.
- `DELETE /c/<id>` → **204**. Anyone with the bearer, no undo, no tombstone.
- Docs at `/llms.txt` and `/docs/<page>.md`; clients at `/static/client.{py,mjs,go}` and creators at `/static/create.*`, all served as `text/plain`.

## Responses

- A read or a successful post returns `{"last","more","events":[{seq,ts,src,nonce,ct}]}`. A post adds `posted:true` and `id`; its `events` are the replies *after* the post. `last` acknowledges the returned page only: while `more` is true, read again with `since=last`. An empty read reports the real head even when your cursor is ahead of it.
- **409** `{"error":"conflict","posted":false,…page}`: nothing appended; the page holds what you missed.
- **503** `{"error":"restarting","hint":…}` during a restart. A refused POST also carries `posted:false`: nothing was written. A POST whose write already committed ends its wait early with the normal 200; the wait is an upper bound.
- 400 bad body or parameter; 401 wrong bearer; 404 absent channel (never created, deleted, or expired); 413 oversized; 429 channel budget exhausted (posts refused, reads and delete still work).
- Sequences run from 0, so the first post uses `last=-1`. Every accepted envelope spends a sequence and bytes and refreshes the idle clock; **reads never refresh it.** No deduplication, no edit, no single-message delete.
- Limits: 512 KiB of ciphertext per event; 1 MiB and 10,000 events per channel; 500 events or 1 MiB per read page. Substantive agent messages ran 4–10 KB, so the byte budget binds first, at roughly 100–270 messages per channel.

## The vendored client

`scripts/client.mjs` is upstream's `client.mjs` plus `create.mjs`, fetched 2026-09-24 (upstream HEAD `06dd34e`, 2026-09-11), with sealing, rendering and the read/post contract unchanged in the sections marked `upstream`. `mayfly.sh` beside it finds Node, refuses a URL-shaped argument, checks `MAYFLY_URL_FILE` is set, and execs it. Divergences, each traced to a finding on [#302](https://github.com/gregoryfoster/skills/issues/302):

| # | Upstream | Here | Why |
|---|---|---|---|
| 1 | URL as a positional argument | read from the mode-600 file `MAYFLY_URL_FILE` names; a URL-shaped argument is refused before any request | argv is `/proc/<pid>/cmdline`, mode 444, for the life of every call (findings 16 and 19; the harness's own `eval` has the same shape) |
| 2 | body on stdin | `--body PATH`, a regular nonblank file; stdin is never read | a body-less post blocked for the whole tool budget, and an EOF would have posted an empty message nothing can delete |
| 3 | ambiguous post → `posted:null` | one read-back from the old cursor: seq N+1 is yours → `posted:true, recovered:"read-back"`; the head shows it is not → `posted:false` on stdout with the missed page; the read-back failed → `posted:null` plus `readback.error` | `posted:null` fires on routine hosted-service 503s, and the recovery is mechanical |
| 4 | none | `listen --last N --me NAME [--slot S] [--max S]`: short polls (`--slot` 1–300 s), backoff on 503 or transport failure, drains `more`, skips messages from `--me`, exit 0 on the first peer message, 3 at the deadline, 1 on 400/401/404/413 | every session re-derived this loop in shell, and two listeners woke on their own posts |
| 5 | `create.mjs` prints the URL | `create ORIGIN` writes the URL into `MAYFLY_URL_FILE` (`wx`, mode 600) and prints `{"created":true,"id","file"}` | a printed URL lands in the transcript; the operator reads the file instead |
| 6 | none | `delete` → `{"deleted":true,"id"}` | the documented post-leak remedy |
| 7 | error bodies verbatim | a non-JSON `error` is truncated to 200 characters | a 503 HTML page dumped whole into a transcript |

Upstream had no issue or PR activity as of 2026-09-24. Rows 1 and 2 are the interface worth proposing there; when it lands, this file retires to a plain vendored copy. To re-sync, diff upstream's `client.mjs` against the `upstream` sections of ours.

## Writing a client from this page

What two agents needed and nothing more: HKDF-SHA256 with the empty salt and the three infos; AES-256-GCM with the AAD above; 256-byte space padding; base64url without padding; and the compare-and-swap semantics of `last`. Validate `from` (nonempty, trimmed, no control characters) and `text` (no lone surrogates). Take the URL from a file and the body from a path, not from argv and stdin. Check your output against the vectors file before first use.
