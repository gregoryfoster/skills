# Live-drift guard — snapshot vs the running producer

The CI drift gate is hermetic: it proves `generated/` == regen-from-snapshot,
but cannot see the snapshot going stale relative to the live producer. The
live-drift guard closes that gap by periodically fetching the producer's
live `/openapi.json`, canonicalizing it EXACTLY as the refresh script does,
and comparing against the committed snapshot.

**Failure mode is "drifted," not "broken."** Live drift is surfaced on a
schedule, never as a merge blocker — the producer can change at any moment,
and a PR author shouldn't be blocked by an unrelated upstream deploy.
Remediation is always the same bundle: refresh the snapshot, regenerate,
run the consumer's adapter tests, PR the result.

Two flavors, chosen by producer reachability:

## Flavor A — scheduled GitHub workflow (producer publicly reachable)

Runs on GitHub-hosted runners. Appropriate when the producer's spec endpoint
is public (or reachable with a repo-secret API key).

```yaml
name: <PRODUCER_NAME>-spec-drift

on:
  schedule:
    - cron: '0 14 * * *'   # daily; pick a time an operator will see
  workflow_dispatch:

permissions:
  contents: read

jobs:
  drift-check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    # Drift surfacing should never block other workflows.
    continue-on-error: true
    env:
      # Public spec endpoint → workflow variable. If the producer locks the
      # endpoint: move the URL to a secret and add the API-key header to curl.
      <PRODUCER_BASE_URL_ENV>: <PRODUCER_BASE_URL>
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          python-version: "3.12"
      - run: uv sync --frozen
      - name: Fetch live producer spec
        run: |
          curl --fail --silent --show-error --max-time 30 \
            "${<PRODUCER_BASE_URL_ENV>%/}/openapi.json" > /tmp/live-openapi.json
      # When FILTER_SPEC=yes: filter the live spec identically to the vendored
      # flow and diff filtered-vs-filtered; otherwise canonicalize (the same
      # order-preserving pretty-print as the refresh script) and diff raw.
      - name: Canonicalize / filter to the consumed surface
        run: |
          uv run python scripts/filter_openapi_spec.py \
            /tmp/live-openapi.json /tmp/live-openapi.filtered.json \
            --keep-prefix "<KEEP_PREFIX>"
      - name: Diff against vendored snapshot
        run: |
          if ! diff -u "<SPEC_DIR>/openapi.filtered.json" /tmp/live-openapi.filtered.json; then
            echo "::warning::<PRODUCER_NAME> spec has drifted from the vendored snapshot."
            echo "::warning::Refresh (scripts/refresh-<PRODUCER_NAME>-spec.sh), regenerate,"
            echo "::warning::run the adapter tests, and PR the bundle."
            exit 1
          fi
```

## Flavor B — on-VM systemd timer + auto-PR (producer not publicly reachable)

When the producer only listens on localhost (or inside a private network) a
GitHub runner can't reach it — run the check on the VM that co-hosts the
producer. This flavor is inherently deployment-specific: the templates below
are the generic shape; user names, paths, env files, and the deploy-checkout
convention belong to the consuming project (a project-level skill override or
the project's deploy docs), not to this skill.

Three pieces:

1. **Detector script** (stdlib-only): fetch live `/openapi.json`, canonicalize
   exactly as the refresh script does, byte-compare vs the committed snapshot.
   Distinct exit codes matter: `0` no drift · `1` drift (print the live spec's
   sha256 for branch keying) · `2` internal error · `3` producer unreachable
   (a *skip*, never reported as drift).

2. **PR-opener wrapper**: on exit 1, regenerate snapshot + tree in an isolated
   `git worktree` off `origin/main`, commit, push, and `gh pr create`. Key the
   branch on the live spec's SHA-256 so re-runs while a PR is open are no-ops
   (one PR per distinct upstream shape). Exit 0 on no-drift and on unreachable.
   The opened PR runs the hermetic CI gate (a no-op post-regen) plus the test
   suite, so real upstream drift becomes a reviewable PR instead of a runtime
   incident.

3. **systemd units**:

```ini
# <CONSUMER_NAME>-<PRODUCER_NAME>-live-drift.timer
[Unit]
Description=Daily <PRODUCER_NAME> client live-drift check

[Timer]
OnCalendar=daily
Persistent=true            # run a missed timer after the VM was off
RandomizedDelaySec=1h      # don't stampede other daily jobs

[Install]
WantedBy=timers.target
```

```ini
# <CONSUMER_NAME>-<PRODUCER_NAME>-live-drift.service
[Unit]
Description=Detect <PRODUCER_NAME> spec drift vs live service; open a PR
After=network.target

[Service]
Type=oneshot
User=<DEPLOY_USER>
WorkingDirectory=<DEPLOY_CHECKOUT>
# systemd gives a minimal PATH; make uv/gh/git discoverable.
Environment=PATH=/usr/local/bin:/usr/bin:/bin
# GH_TOKEN for gh + git credentials.
EnvironmentFile=<DEPLOY_ENV_FILE>
ExecStart=/bin/bash <DEPLOY_CHECKOUT>/scripts/<PRODUCER_NAME>_live_drift_pr.sh
```

Non-blocking by design: an unreachable producer exits 0 (skip); a non-zero
exit is a genuine tooling failure worth a journal entry, not a restart loop.

## Choosing a flavor

| Producer spec endpoint | Flavor |
|---|---|
| Public URL (or secret-key reachable from GH runners) | A — scheduled workflow |
| localhost / private network only | B — on-VM timer |
| Producer app lives in the consumer repo itself | Neither — use the offline freshness test in [ci-drift-job.md](ci-drift-job.md) |
