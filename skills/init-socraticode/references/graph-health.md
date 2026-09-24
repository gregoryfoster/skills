# Graph health — the long form

The generated `docs/SOCRATICODE.md` carries the **Graph health** rules a
consumer acts on: measure yield rather than status, what each verdict means,
how to read the `Built by:` stamp, rebuild after an upgrade, and what
`unresolvedPct` is not. This file keeps what those rules were learned from,
and every finding's wording in full, for an agent diagnosing a graph or a
maintainer changing the driver.

**Why it moved.** Until [#329](https://github.com/gregoryfoster/skills/issues/329)
all of it sat in the template, and the template was 5,729 exact tokens — 57% of
`curating-context`'s 10,000-token per-doc budget before a consumer wrote a line
of their own notes, with this section alone half of it. Only what follows the
END marker is curatable, and the generated half comes back on every re-run, so
the skill's fixed cost was displacing the part it tells consumers to write: on
CannObserv/watcher#300 the template plus the notes an audit re-run rescued came
to 11,444 tokens, and getting under meant cutting that repo's own measured
notes. A consumer reaches this file through the vendored skill, at
`skills/init-socraticode/references/graph-health.md`; the generated doc names
that path in plain text, since a relative link from `docs/` would resolve here
and nowhere else.

## Name the checkout, not the cwd

SocratiCode indexes by absolute project path, so a literal `.` run from a git
worktree asks about a project the server never saw and reports a healthy index
as broken ([#180](https://github.com/gregoryfoster/skills/issues/180)). The
generated doc's spelling —
`dirname "$(git rev-parse --path-format=absolute --git-common-dir)"` — is the
one `socraticode-health.sh` uses; `--show-toplevel` is the near miss, because
in a worktree it yields the worktree. Current drivers resolve a relative
argument this way themselves, so `.` also works — the explicit form is there
because it works against an older vendored driver too, and because it says out
loud which path is being measured
([#226](https://github.com/gregoryfoster/skills/issues/226)).

## `unresolvedPct` — the finding, word for word

`health-check`, and the daily `socraticode-health.sh` run, report the figure
whenever it clears the threshold, on a healthy graph too, and word it from the
verdict. Beside `ok`: `graph unresolved N% (> 50%) — share of captured symbol
edges (calls, imports, re-exports, type or value references) matching no
project symbol; edges into builtins and external libraries count by
construction, so it runs high on healthy code — verdict is ok, so this is a
statistic, not a defect`. Beside `low` or `unknown`, where the verdict already
stands on the yield arithmetic and the server's advisory: `graph unresolved N%
(> 50%) — share of captured symbol edges (calls, imports, re-exports, type or
value references) matching no project symbol — reported beside the verdict,
not as evidence for it, since edges into builtins and external libraries count
by construction`. Either way it is filed as a **note** — it appears as `note:
graph unresolved N% …` and does not set the exit code, so a repo whose only
finding is this one stays silent through the daily hook.

The denominator is the server's own: since v1.14.0 `codebase_graph_status` says
the same thing and adds that the share "is not a resolver failure rate". A repo
that leans on frameworks, the stdlib and SDKs runs high by construction,
because those symbols are not in the repo — no re-index brings them in and
none lowers the figure. A high `unresolvedPct` beside `verdict: "ok"` is
normal; the src-layout resolver defect it can be mistaken for
(<https://github.com/giancarloerra/SocratiCode/issues/107>) shows up instead as
near-zero edges/file. Do not cite the figure as the *cause* of an
under-reporting graph query; test the import graph instead
([#308](https://github.com/gregoryfoster/skills/issues/308)).

**If you suspect the import graph, test the import graph.** Take a file you
know has first-party importers, run `codebase_graph_query` on it, and compare
the result against an `rg` sweep over every spelling that import could be
written as. If the two sets match, the import graph is exact, and whatever
`unresolvedPct` counts, it is not your first-party imports. Prefer that
differential to any figure written into a doc, which is repo- and day-specific.

## The server's own advisory

Since SocratiCode 1.13.0, when resolution collapses, `codebase_graph_status`
prints an advisory beneath the edge count:

```
Import resolution: 35 of 2959 captured imports resolved to project files (1.2%)
  Most imports did not resolve, so codebase_graph_query, codebase_graph_stats
  and codebase_impact will under-report dependencies — an empty answer there
  means unresolved, not independent.
```

That ratio is **resolved-over-captured**, which is a better measure than the
edges/file floor this skill computes locally: it does not move with repo size,
and it does not read as broken on a repo that is merely orphan-heavy. It is
also not `unresolvedPct`, which counts every captured symbol edge, external
ones included.

**Believe a present advisory when `Built by:` is current.** It reports what the
builder that *cut* this graph resolved, so on a stale graph it judges an older
resolver and a rebuild may clear it. The `Built by:` line tells you whether the
reading — advisory or silence — is about the resolvers you are actually
running; the generated doc's table says what each form of it means.

## Why the stamp is checked, not trusted

**A stale graph looks like a broken resolver.** A graph sitting at 37 edges
across 621 files looked like a resolver collapse for over a week and was
merely stale — rebuilt on 1.13.1 the same repo yields **2156 edges across 627
files**. Run `codebase_graph_build` before concluding anything from a graph
whose builder is stale or unstamped. `health-check` reports this as its own
defect, and reports which measure ruled (`source: "server"` or `"local"`) in
its JSON.

**Read "current" as *the server did not call it stale*.** The annotation is
the server's to volunteer, and every way of not volunteering it used to land on
the table's first row: `CannObserv/cannabis.observer-wordpress#803` spent three
rounds concluding a PSR-4 `composer.json` declaration "would not help", from a
graph **cut by v1.10.0** — PSR-4 resolution having shipped in **v1.11.0**, so
the graph predated the feature under discussion. READY throughout, and nothing
said so. Since [#297](https://github.com/gregoryfoster/skills/issues/297)
`health-check` keeps the running server's `serverInfo.version` from the MCP
handshake and makes the comparison itself, so the first row now means *both*
parties checked. Reading the stamp **by hand**, you do not have that second
opinion: compare it against the server you are running before you trust it.

**The server that matters is the one answering your queries.** A rebuild runs
through the session's server — under Claude Code, the plugin's — which need not
be the one `health-check` launched to measure. Where the plugin's definition
fixes a version, the check judges the graph against that one, and a graph
matching it while trailing the check's own server is a *note*: rebuilding would
re-stamp the same version, so the fix is to update the plugin, restart Claude
Code so its MCP server reloads, then rebuild. Where the definition floats
(`socraticode@latest`) the session's version cannot be read, and the finding
says so; if a rebuild leaves the stamp unchanged, restart and rebuild
([#305](https://github.com/gregoryfoster/skills/issues/305)). The JSON records
every version compared: `graph.builderCheck` holds the builder, `checkServer`,
`sessionServer` and which of the two ruled; `server` is the check's own launch
and `sessionServer` says how the session's version was known.

**Stale is not the same as unmeasured, and the two answer different
questions.** A graph a release or two behind still carries the import counts
its builder recorded, so the running server reads them and its advisory — or
its silence — is a real ruling about resolution; `health-check` keeps that
ruling (`source: "server"`) and reports the staleness *beside* it. Only a graph
cut before **1.13.0**, which recorded no counts at all, leaves the server with
nothing to measure and sends the verdict back to the edges/file fallback
(`source: "local"`). Do not read "this graph is old" as "this graph is broken":
on an orphan-heavy repo the local floor reads LOW on a graph that is perfectly
fine, which is the reading that writes variant B.
