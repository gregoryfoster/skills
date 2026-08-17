# Re-run on an existing project (audit/repair)

Read this before re-running `init-socraticode` on a project that already has
SocratiCode. A first install does not need it.

## The re-run *is* the audit

Running this skill on a project that already has SocratiCode is safe, because
every file edit is idempotent:

| Phase | What a re-run does |
|---|---|
| 1–2 | read-only when already satisfied |
| 3 | policy block replaces between the markers; `docs/SOCRATICODE.md` is overwritten wholesale; both hook merges dedupe |
| 4 | migrates a legacy top-level-array manifest in place, and re-validates every artifact path |
| 5 | re-indexes only if the index is missing or stale |
| 6 | re-verifies the completion signals, and re-measures graph yield |

Because Phase 6 re-measures yield, a repo installed before the yield gate
existed gets its degraded policy (variant B) the first time it is audited.

## What a re-run repairs

The common drift found across the cohort
([#65](https://github.com/gregoryfoster/skills/issues/65)):

- a manifest with **no policy block or prefetch hook** (observo);
- hook docs that drifted from `settings.json` (archiver);
- a manifest the server silently rejected, which has been reporting `artifacts
  0/0` as if healthy (gotcha K) — a re-run is the only thing that catches it.

## One thing a re-run must not do quietly

On the unmarked-section branch, Phase 3 replaces a whole `## Code Exploration
Policy` span, and a repo that has been running for a while has usually grown its
own prose in there. Rescue anything the template does not itself carry to a
`## Code Exploration Notes (repo-specific)` section outside the markers, and
name every moved block in the report. The first audit re-run is exactly when
this bites and exactly when nobody is watching for it
([#115](https://github.com/gregoryfoster/skills/issues/115)).
