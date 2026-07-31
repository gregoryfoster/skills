---
title: Add a PRIVATE_WHEELHOUSE branch point to init-project-fastapi (find-links from GCS)
date: 2026-07-31
status: draft
---

# init-project-fastapi — `PRIVATE_WHEELHOUSE` branch point

## Problem

Three of the four CannObserv Python services (`archiver`, `watcher`, `replicator`) resolve their
shared libraries (`co-core`, `co-core-aio`) not from PyPI but from a **private GCS index mirrored
into a local `./.wheelhouse`**, wired into uv via `[tool.uv] find-links`. The skill has no concept
of this, so every new such service hand-ports the mechanism from a sibling — five coupled call sites
(pyproject, `.gitignore`, systemd, CI, import smoke) plus a sync script, each an opportunity to get
the ordering or the `.gitignore` glob subtly wrong. The pattern has now proven out a third time
(replicator, end-to-end), so it should become a first-class, default-off branch point. Issue
[#71](https://github.com/gregoryfoster/skills/issues/71); the reference body and all five gap answers
are in the issue thread (comment from the author, bootstrapped from `gregoryfoster/skills@37226fb`).

## Approach

Add one branch point, `PRIVATE_WHEELHOUSE` (`no` default | `find-links`), following the exact
convention the skill already uses for multi-phase branch points like `DEPLOY_TARGET` and `ADMIN_UI`:
a single dedicated reference (`references/private-wheelhouse.md`) holds the sync script verbatim plus
all five call sites and the invariants, and each touched phase gets a gated blockquote pointing at it.
Transcribe the reference faithfully from the issue comment (attributing provenance), then wire the
gated edits into the parameter table, a new Phase 3b, and Phases 3 / 7b / 7c / 12 / 16, plus the
`cohort-context.md` rationale. Default-off means PyPI-only projects render byte-identically to today —
the whole feature is inert unless the user opts in.

## Tradeoffs / alternatives

- **Let the author open the PR** (their offer) — rejected: the comment is complete enough to
  transcribe now, keeping authorship, provenance, and the phase-wiring (which the comment does *not*
  do — it supplies the reference body, not the SKILL.md edits) in one reviewed change. Their PR would
  still need the same wiring done by someone.
- **Fold Part 2 (`.gitignore` fix) in as a standalone edit** — rejected: within this skill there is no
  wheelhouse `.gitignore` block today, so the correct `.wheelhouse/*` form simply *is* how the new
  Phase 3 block ships. There is nothing to "fix" separately; it lands as part of the reference.
- **A broader `PRIVATE_INDEX` param covering both find-links and a future private-PyPI index
  (`[[tool.uv.index]]` + keyring)** — rejected as premature: only the find-links mechanism is
  validated. Naming the enabled value `find-links` (not `yes`) already leaves that door open for a
  second choice later without a rename.
- **Default it on for the shared-library cohort** — rejected: unlike every other default-off branch
  point (which encode a *preference*), this one depends on external infra that cannot be assumed to
  exist (a GCS bucket + a `storage.objectViewer` SA + WIF). Default-off is correct; the rationale gets
  stated explicitly in `cohort-context.md` so the next contributor does not read it as an oversight.

## Steps

1. **Author `references/private-wheelhouse.md`** — transcribe from the issue comment: `sync_wheelhouse.py`
   verbatim (with the three project-specific constants as placeholders), the five call sites (pyproject
   `find-links`; `.gitignore` `.wheelhouse/*` + `!.wheelhouse/.gitkeep` with the load-bearing-`.gitkeep`
   note; systemd `ExecStartPre`; CI WIF block incl. the "assert org variable visible" step; Phase 12
   import smoke), and the invariants section (the `auth → sync → uv sync --frozen` ordering,
   never-republish-a-filename, path-only secret handling, env-namespaced bucket/prefix overrides). Add a
   provenance line citing the issue comment + `gregoryfoster/skills@37226fb`. *Verifiable:* file exists,
   contains all five call sites and the invariants block.
2. **Parameter table (SKILL.md)** — add the `PRIVATE_WHEELHOUSE` row to the branch-point table and the
   enabled-only sub-parameter table (`WHEELHOUSE_BUCKET`, `WHEELHOUSE_PREFIX` default `wheels/`,
   `WHEELHOUSE_SA` required only when `GITHUB_CI=yes`, `WHEELHOUSE_PACKAGES` = import lines), reusing the
   existing project env prefix for the namespaced overrides rather than adding a parameter. Note
   `GCP_WIF_PROVIDER` is an **org variable**, not a skill parameter. *Verifiable:* both tables list the
   new rows; "Drives" column names Phases 3, 3b, 7b, 7c, 12, 16.
3. **Phase 3 edits** — gated blockquote: when `PRIVATE_WHEELHOUSE=find-links`, splice `[tool.uv]
   find-links` into `pyproject.toml` (plain version floors, no hashes) and emit the `.wheelhouse/*`
   `.gitignore` block, both per the reference. *Verifiable:* Phase 3 prose gates both on the param and
   links the reference.
4. **New Phase 3b** — `scripts/sync_wheelhouse.py` + `.wheelhouse/.gitkeep`; the README Setup block
   (`sync` before `uv sync`) emitted **whenever enabled, regardless of `DEPLOY_TARGET`** (it is the only
   place the ordering is recorded when `DEPLOY_TARGET=none`); the `GOOGLE_APPLICATION_CREDENTIALS` env row.
   Skip entirely when `PRIVATE_WHEELHOUSE=no`. *Verifiable:* new phase exists with the skip guard and the
   deploy-target-independent README obligation.
5. **Phases 7b / 7c edits** — 7b: add the non-fatal `ExecStartPre=-…sync…` (before `ExecStart --frozen
   --no-sync`) when `DEPLOY_TARGET=systemd AND PRIVATE_WHEELHOUSE=find-links`. 7c: add the WIF auth +
   assert-org-variable + sync steps, gated on `GITHUB_CI=yes AND PRIVATE_WHEELHOUSE=find-links`, stating
   the WIF block is CI-only and nothing else changes when absent. *Verifiable:* both phases carry the
   compound gate; the systemd ordering matches the existing BUILD_ID `ExecStartPre` invariant style.
6. **Phase 12 + Phase 16 edits** — 12: gated import-smoke step probing a **readable** key file
   (`-n && -r "$GOOGLE_APPLICATION_CREDENTIALS"`), graceful-skip with a bootstrap-issue note ("wheelhouse
   never populated; `uv sync` fails until sync runs with ADC") mirroring the `TEST_DATABASE_URL` skip. 16:
   completion-table row + a checklist line "add the new repo to `GCP_WIF_PROVIDER`'s repository access"
   when CI is enabled. *Verifiable:* Phase 12 skip is keyed on readability not mere set-ness; Phase 16
   has the row and the WIF-access checklist item.
7. **`cohort-context.md` + version bump + Key invariants** — add the default-off rationale bullet
   (cohort majority that still defaults off because it depends on unassumable external infra); bump
   SKILL.md `version` 1.3.4 → 1.4.0; add the `auth → sync → uv sync --frozen` ordering and never-republish
   invariants to the "Key invariants" section. *Verifiable:* rationale bullet present, version is 1.4.0.
8. **Verify + commit** — run `pytest tests/structural/` (the repo's structural gate parses SKILL.md /
   references, so it catches malformed tables, dangling reference links, and version-format issues), fix
   any failures, commit with an issue-referencing message crediting the reference provenance. *Verifiable:*
   structural tests green; single commit referencing #71.

## Open questions / risks

- **Structural-test coverage of a new reference.** The repo's `tests/structural/` may assert that every
  `references/*.md` is linked from SKILL.md and vice-versa; the new reference and its links must satisfy
  whatever that suite checks. Risk is low (it's the same shape as every existing reference) but the suite
  is the arbiter — step 8 gates on it.
- **Transcription fidelity of `sync_wheelhouse.py`.** The script is contributed verbatim; the three
  properties the author flagged as load-bearing (same-size skip, temp-file + `os.replace`, broad
  `except`) must survive transcription unchanged. I will not "improve" it.
- **No live end-to-end test here.** This repo cannot exercise a real GCS bucket + WIF, so correctness of
  the wired mechanism rests on replicator's proven bootstrap, not a test in this repo. The structural
  suite validates the skill *document*, not the runtime behavior it describes — same as every other
  branch point.
- **Interaction matrix is wide** (`PRIVATE_WHEELHOUSE` × `DEPLOY_TARGET` × `GITHUB_CI`). The plan gates
  each phase on the precise compound condition; the one non-obvious cell — `DEPLOY_TARGET=none` +
  enabled — is explicitly handled by the always-emitted README obligation in step 4.
