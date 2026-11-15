# Compacting an existing epic

A one-time pass that brings an epic written before #654 onto the short form: the log in comments on the epic, and each ticked line cut to its title and a link to the comment that holds its evidence. Do it when the editor's summary shows the body past 85% of its limit, or when adopting an epic that will run for months. Past the host's cap (inferred near 262,144 characters) a write keeps the old body and still reports success (#653).

An epic that reached the cap held 115 ticked lines (about 146,000 characters) and 117 log entries (about 69,000), in a 260,000-character body. Only 22 of its ticked children had a verification comment to link (#654).

## 1. Measure

Dry-run an empty ops file. The summary's `body` gives `chars`, `limit` and `share`; note `counts_before`, and keep the dry run's body as the reference for step 5.

## 2. Move the log into comments, oldest first

- **On an `--account` epic, first keep each disposition only the log holds** (#657). `--account` reads the body, never a log comment, so an issue that only a log line accounts for ("out of epic", "duplicate of") reads as unlisted once the log goes. Dry-run the second call below with `--account`: its refusal names each one. In that same call, `add-section` an `## Out of epic` section holding one line each, `- #N · out of epic: why`.
- Post the `## Log` entries as `log-comment` ops, in date order, one call holding only those ops: the body doesn't change, so each posts as soon as every check passes.
- GitHub refuses a comment over 65,536 characters, and the editor refuses one first. Split the log at entry boundaries into parts under that, one op per part, each with a `"date"` naming its span: `{"op": "log-comment", "text": "...", "date": "2026-09-01 to 2026-10-15, moved from the body"}`.
- Confirm the summary's `log_comments` URLs, then, in a second call, `replace-section` the Log with the pointer the template shows. Two calls, so the in-body log goes only once the comments exist.

## 3. Give every ticked child a comment to link

- A child whose verification comment exists (posted at its check-in, holding the evidence) links that one, `"label": "verified"`.
- Any other: post a record comment on the child, first line `**Coordinator record, OWNER/REPO#<epic>**`, then the line's text whole: its evidence, decisions and notes. `scan.sh` reads that first line, never the author, and drops the comment from the next scan. Link it with `"label": "record"` when the line held no evidence, only a description; `verified` when it did.
- Post each with `comment.sh`, from a file written with a quoted heredoc: it lints the text with the editor's rules and reads the comment back.

## 4. Compact the ticked lines

One `compact` op per ticked child, `{"op": "compact", "ref": "#N", "link": "<comment URL>", "label": "record"}`. It takes the issue's title from GitHub (or `"title"`), replaces a `·` in it, puts a bare `name#N` in a code span, and qualifies another repo's bare `#N`. It keeps a `not planned` or `out of epic` field, so a disposed line stays disposed, and drops the line's indented sub-block. It refuses one that holds an open box, and names it: give that item a line of its own (`add-line`) or remove it (`set-subline`), then compact. `set-line` alone would orphan the sub-block, which is why #654's run rebuilt whole tier sections; `compact` doesn't need that.

## 5. Dry-run, then write

- `counts_after` equals `counts_before`, less only the ticked boxes of the sub-blocks it dropped.
- In the diff, every open line is unchanged.
- `body.share` is well under 0.85.

Then write the same ops. The next `scan.sh` drops the record comments, and names any child they alone had listed in `own_comments.rows_dropped`.
