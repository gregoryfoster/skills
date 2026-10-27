# The credential context of a Dependabot run

## What a run gets

| | On a Dependabot-triggered run | Source |
|---|---|---|
| Secrets | Only **Dependabot** secrets, a store separate from Actions secrets | GitHub's docs |
| `GITHUB_TOKEN` | Read-only, whatever `permissions:` asks for | GitHub's docs |
| `vars.` | **Not spelled out.** It resolved on watcher, 2026-10-09 | watcher#354–#357 |
| OIDC (`id-token: write`) | **Not spelled out.** GitHub issued the token on watcher, 2026-10-09: WIF auth passed in all four Python jobs | watcher#354–#357 |

**Verified versus stated:** the two rows marked "not spelled out" were
observed once, on one repo. Don't carry them to another repo as fact. **Test
them with the first real PR**: take `github-actions` first, whose PRs touch
nothing but the workflows, so a red job there is the credential context and
not the bump. Per job, check that the actor is `dependabot[bot]` and the auth
steps succeeded:

```bash
gh run view <run-id> --json jobs,actor -q '.actor.login, (.jobs[] | "\(.name)\t\(.conclusion)")'
gh run view <run-id> --log | grep -n -i -E 'auth|token|credential' | head -40
```

## Red-auth triage, by the auth action's own error

Read the auth step first and match its error. None of these is the bump's
fault, so none is a reason to hold the PR's change: fix the context, then
re-run.

### `google-github-actions/auth`

| Error text | Means |
|---|---|
| *"must specify exactly one of workload_identity_provider or credentials_json"* | The variable didn't reach the run: `vars.` didn't resolve, or a secret isn't in the Dependabot store |
| *"did not inject $ACTIONS_ID_TOKEN_REQUEST_TOKEN"* | No OIDC token was granted: `id-token: write` is missing from the job or workflow, or the run wasn't allowed one |
| Fails after both, at the token exchange | The workload identity provider's attribute condition (often `assertion.actor` or `assertion.ref`) or the service account binding refuses this run |

A provider whose condition names the actor or the event refuses
`dependabot[bot]` until the condition allows it. Widen it deliberately, for
the read-only scopes CI needs, never for deploy rights.

### Other auth actions

Add a table per action as the cohort meets one: its exact error strings, from
a real failing run, each mapped to the missing piece. A guessed string is worse
than none, because the triage reads it as a match.

## A private index in CI

A CI step that syncs a wheelhouse or authenticates to an index is a
**credential** question here (it ran on watcher's Dependabot PRs, with WIF),
and a **resolution** question for the updater itself, which runs none of
CI's steps ([inventory.md](inventory.md#phase-2-what-the-bot-can-and-cant-move)).
Solving the first doesn't solve the second.
