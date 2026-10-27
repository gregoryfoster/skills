# The security path: three switches, all on

Version updates and security updates are separate paths. **Security updates
need three repository settings on together:** the **dependency graph**,
**Dependabot alerts** and **Dependabot security updates**. With any one off,
a transitive advisory arrives only as a red audit.

Version updates read manifests themselves, so with the graph off the repo still
looks healthy: version PRs open, the config parses, the guard test passes.
Alerts match advisories against the graph, so with no graph there's nothing to
match.

## What it cost

notifier had the graph off while alerts and security updates were on. It had
**0 alerts, ever**, across three rounds of GHSA-listed transitive advisories in
`uv.lock` (CannObserv/notifier#103, #132, #135). Each reached `main` as a red
`uv audit`, with no Dependabot PR. `GET …/dependency-graph/sbom` returned 404,
and GraphQL `dependencyGraphManifests` returned 0. With the graph on: 8
manifests, both `uv.lock` files among them, and the SBOM listed 101 packages
(CannObserv/notifier#140, 2026-10-26).

## The cohort measurement, 2026-10-26

Observed 2026-10-26 with the manifest query below, run per repo with each
repo's own token, and not re-verified. Re-derive it with
`bash "<check-dependabot.sh>" --repo CannObserv/<r>`:

- **Before:** each of the 11 other CannObserv repos holding a `uv.lock` on
  `main` showed 0 manifests, and some had alerts off too.
- **After** the owner turned on all three switches org-wide, with auto-enable
  for new repos, all 12 listed their `uv.lock`. Two needed the graph switched
  on individually after the org-wide action.
- **Within minutes**, Dependabot opened security PRs for transitive dev-tool
  advisories in three repos (CannObserv/status#61 and #62, CannObserv/index#14
  and #15, CannObserv/power-map#699 and #700), each bumping `filelock` and
  `virtualenv`: the packages that had turned notifier's `main` red in
  CannObserv/notifier#135. **So security updates do cover transitive `uv.lock`
  entries**, once all three switches are on.

Version updates propose only direct dependencies, so a transitive advisory is
exactly the case security updates fix.

## The check

`check-dependabot.sh`'s `graph`, `alerts` and `security-updates` checks. The
graph check is the one a least-privilege token can read: it needs only metadata
read. It passes when every committed lockfile is a manifest; `0` on a repo
holding a lock means the graph is off, or the token can't see it. The alerts
list needs Dependabot alerts: read; the toggles need **Administration: read**.
Without them, each reads `unread`, never `pass`. The bare query, for a repo the
script can't reach:

```bash
gh api graphql -H 'Accept: application/vnd.github.hawkgirl-preview+json' -f query='
{repository(owner:"OWNER",name:"REPO"){dependencyGraphManifests(first:50){totalCount nodes{filename}}}}' \
  --jq '.data.repository.dependencyGraphManifests | "\(.totalCount) \([.nodes[].filename]|join(", "))"'
```

## Turning them on

The switches are repository (or organization) settings: an owner's action,
outward-facing, and not something the skill flips. Ask for all three together,
with auto-enable for new repos at the org level, then run the check, since an
org-wide action didn't reach every repo's graph.

## Where an audit still fits

A scheduled `uv audit` (or the ecosystem's equivalent) in the repo's CI stays
**the gate**. Security updates are the early PR in front of it. On the host, the
deployed tree is audited separately by `patching-hosts`'s language-dependencies
class: a fix merged to `main` isn't patched until the repo's own deploy ships it.
