# Resolving the doctor's SSH/HTTPS auth failures

The doctor distinguishes two failure modes; the remediation differs by mode.
`SKILL.md`'s Troubleshooting section names when each block appears.

## For auth failures (`Permission denied (…)` / `Authentication failed for 'https://…'`)

Walk the rungs top-down — most reports trace to one of the first three:

1. **Agent not reachable.** `ssh-add -l` returns "Error connecting to authentication agent" → start the agent and re-add keys. On macOS this usually happens after a reboot or a fresh shell session.
2. **Agent reachable but empty.** `ssh-add --apple-use-keychain ~/.ssh/id_ed25519` once, then add a `Host github.com` block to `~/.ssh/config` with `AddKeysToAgent yes` and `UseKeychain yes` so the key auto-loads on every shell.
3. **Agent works interactively but not from a wrapper script.** A `dev.sh` (or similar) in the call chain is scrubbing `SSH_AUTH_SOCK`. Test from the same shell with `ssh -T git@github.com`: if it works there but the wrapper's subshell fails, the fix lives in the wrapper.
4. **Public submodule, no credentials needed.** The global HTTPS rewrite (`git config --global url."https://github.com/".insteadOf "git@github.com:"`) lets git clone without auth — note it affects every repo on that machine. **In CI, ephemeral containers, or any non-interactive runner**, prefer the runner's native credential mechanism (deploy key, `GITHUB_TOKEN`, app token) over the global rewrite — those are scoped to the run and don't bleed across repos.

## For host-key failures (`Host key verification failed`)

The pre-flight runs `ssh -T` with `StrictHostKeyChecking=yes` so unknown hosts are rejected loudly instead of silently appended to your `known_hosts`. The doctor prints a separate, smaller block pointing at `ssh-keyscan`:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

Verify the forge's [published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints) against the `ssh-keyscan` output **before** appending — `ssh-keyscan` will happily echo whatever a man-in-the-middle answers.

## Skipping the pre-flight

Pass `--no-preflight` to skip the SSH ping if the operator already knows the agent state and wants to skip the 3-second `ConnectTimeout` per invocation. The submodule-init classification still runs after a failure either way.
