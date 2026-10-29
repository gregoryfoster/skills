# SocratiCode's containers on loopback

The managed stack's two containers, created bound to `127.0.0.1` with Qdrant's
telemetry off, then checked from preflight and the daily hook, and moved to
loopback by hand when one is found wide
([#494](https://github.com/gregoryfoster/skills/issues/494)).

## Why upstream's own containers are a hazard

SocratiCode creates each container with no host IP in its publish:

```text
docker run -d --name socraticode-qdrant -p ${QDRANT_PORT}:6333 -p ${QDRANT_GRPC_PORT}:6334 \
  -v socraticode_qdrant_data:/qdrant/storage --restart unless-stopped qdrant/qdrant:v1.17.0
docker run -d --name socraticode-ollama -p ${OLLAMA_PORT}:11434 \
  -v socraticode_ollama_data:/root/.ollama --restart unless-stopped ollama/ollama:latest
```

So both listen on every interface, IPv4 and IPv6. Docker's publishes bypass
the host firewall. Qdrant has no API key in this mode and stores every indexed
chunk's source text, and its anonymous telemetry is on. Ollama has no
authentication at all. Defaults are 16333, 16334 and 11435.

**What holds, and for how long.** SocratiCode finds its containers by name only
(`docker ps [-a] --filter name=<name>`, then a substring `.includes(name)`).
It `docker start`s one that exists, and it `docker run`s only when none does.
It never reads the image, ports, volume or labels, and an upgrade never
recreates a container. So a container created first on loopback is the one it
keeps. That lasts until the container is removed. The next call then
recreates it on every interface, with telemetry on.
[Traced in 1.13.1 and 1.16.1 `dist/services/docker.js`. Measured with 1.16.1
against a throwaway Docker daemon on 2026-10-28: a stopped loopback container
was started, not replaced, and a removed one came back on `0.0.0.0` and
`[::]`.]

**What creates one.** Server startup never does: auto-resume only asks whether
Qdrant is running. The first creator is the first call that runs
`ensureQdrantReady`, which means index, search, status or the context tools.
That includes the health hook's own `codebase_status`. An Ollama container is
created on the first embed, under `OLLAMA_MODE=docker`, or under `auto` when no
native Ollama answers on `localhost:11434`.

## Create them first

Run this in Phase 1, before anything calls a `codebase_*` tool, whenever
preflight prints it. That happens when a container is missing, and on a
socket-activated host whose daemon is down, where preflight inspects nothing.
The command has only the targets that run locally, with any non-default port
in front:

```bash
bash "<SKILL_DIR>/scripts/loopback-containers.sh" qdrant ollama
```

It creates each **missing** target with upstream's names, volumes, container
ports, restart policy and image tags. The only differences are
`127.0.0.1:` on every publish and `QDRANT__TELEMETRY_DISABLED=true` on Qdrant.

- It never removes, stops, renames or recreates an existing container. It only
  reports on one.
- A container that was removed but whose volume was kept comes back with its
  data, since the volume names match.
- `--check` is the same inspection, read-only.
- Each target gets one tab-separated line: `ok`, `created`, `missing`,
  `wide`, `broken`, `decoy`, `telemetry` or `unknown`. The script's `--help` explains
  each one.

The image tags are upstream's own, so SocratiCode doesn't pull a second image.
Upstream floats Ollama on `latest`, and so does this script. Override either
tag with `--qdrant-image` / `--ollama-image`.

**An IPv4-only loopback bind needs Node 20 or later.** Upstream's URLs say
`localhost`, and from Node 20 a refused `::1` falls back to `127.0.0.1`, for
both `fetch` and `http.get`. Node 18 and 19 try only the first address. Where
`localhost` resolves to `::1` first, every call is refused. Upstream's own
wide publish also listens on `[::]`, which hid this. Preflight fails a Node
below 20 unless `localhost` resolves to `127.*` first. It skips any container
not addressed through `localhost`: Qdrant with a `127.*` `QDRANT_HOST`, and a
docker-mode Ollama whose `OLLAMA_URL` and `OLLAMA_HOST` are both `127.*`.
Auto mode hard-codes `localhost:11435`.
[Measured 2026-10-28 with an IPv4-only listener: 18.20.8 was refused, while
20.20.2 and 22.23.2 fell back; Node 26 by the mitigation.]

## How it's checked

| Where | Reads | Verdict |
|---|---|---|
| `preflight.sh`, Gate 1b | `loopback-containers.sh --check`, only where Docker already answered; on an idle socket, nothing, and the create command is named | **✗** wide (host networking included), missing (its fix is the create command), or broken (never started, or not on SocratiCode's port); **•** telemetry on, a decoy, unreadable |
| `socraticode-health.sh`, once a day | TCP listeners on the three ports: `ss -ltn` (Linux), `lsof -iTCP -sTCP:LISTEN` (macOS). It runs no docker command | one session line naming each non-loopback bind |

What the listener check can't see:
- a publish that has no listening socket, under Docker's `userland-proxy: false`;
- a listener in another network namespace;
- on macOS without root, another user's sockets (Docker Desktop's listener is
  the user's own);
- telemetry, which preflight's check covers.

On a host with no `ss` or `lsof`, the hook writes `listeners not read` to its
log and says nothing in the session. That's a property of the host, so a
session line would fire every day.

## Moving a wide container to loopback (manual)

**Each destructive step needs the operator's approval:** the rename, the stop,
removing the backup, and any rollback. A recreate run to prove the procedure
counts too. The procedure swaps a container under a live index, so it stays
out of every script. It's the one the 2026-10-28 mitigation ran on a
workstation and a cohort host.
Below, `C=socraticode-qdrant`, `B=bak494-qdrant`, `P=16333` and `G=16334`,
or the host's `QDRANT_PORT` / `QDRANT_GRPC_PORT`. For Ollama, it's
the same steps with its own volume, port and `/root/.ollama`, and no telemetry
variable.

**The backup's name must not contain `$C`.** SocratiCode's existence check is a
substring match. A stopped `socraticode-qdrant-old` would read as the container
existing, and SocratiCode would `docker start` a name with nothing behind it.
`--check` reports such a name as `decoy`.

1. **Record.**
   ```bash
   docker inspect "$C" > before.json
   TAG="$(docker inspect -f '{{.Config.Image}}' "$C")"; IMG="$(docker inspect -f '{{.Image}}' "$C")"
   [ "$(docker image inspect -f '{{.Id}}' "$TAG")" = "$IMG" ] || echo "tag moved: run from $IMG instead"
   for c in $(curl -s "localhost:$P/collections" | jq -r '.result.collections[].name'); do
     printf '%s\t%s\n' "$c" "$(curl -s -X POST "localhost:$P/collections/$c/points/count" \
       -H 'content-type: application/json' -d '{"exact":true}' | jq .result.count)"
   done > counts.before.tsv
   ```
   - Count each collection with `"exact": true`. `codebase_status` can't stand
     in for this, because a checkout with no index answers `Not Found`.
   - For Ollama, record the model digests from `/api/tags`.
   - Note any run-time labels, env or mounts beyond the image's own, and carry
     them over in step 2. The mitigation found none.
2. **Rename, then stop, then run**, back to back:
   ```bash
   docker rename "$C" "$B" && docker stop "$B" && \
   docker run -d --pull never --name "$C" -p "127.0.0.1:$P:6333" -p "127.0.0.1:$G:6334" \
     -v socraticode_qdrant_data:/qdrant/storage --restart unless-stopped \
     -e QDRANT__TELEMETRY_DISABLED=true "$TAG"
   ```
   - Each new container was healthy within 6 s. In that window, a session whose
     60 s readiness cache has expired finds no `$C` and runs its own.
   - If its run lands first, yours fails on the name. Landing between the
     rename and the stop, it can't bind the port and leaves a `Created`
     container behind. Landing after the stop, it runs wide. Either way
     `--check` shows `$C` as `wide`. Remove it (with approval) and run yours
     again.
   - If its run lands after yours, it fails on the name and leaves nothing
     behind.
   - The backup is stopped before the new container starts, so two Qdrants never
     share the volume.
3. **Verify.**
   - `QDRANT_PORT="$P" loopback-containers.sh --check qdrant` reports `ok`.
     Without the port it checks 16333, and on another port a correct
     container reads `broken`.
   - The listeners are `127.0.0.1` only (`lsof -nP -iTCP -sTCP:LISTEN` or
     `ss -ltn`).
   - `counts.before.tsv` matches a recount, collection by collection.
   - One `codebase_search` answers.
   - Expect one `fetch failed` per open session first, from a pooled connection
     to the old container. The retry works.
   - The inspect diff shows only the `HostIp` values and the telemetry
     variable, once Docker's reorderings are taken out:
   ```bash
   norm() { jq -S '.[0] | del(.Id, .Created, .State, .Name, .NetworkSettings, .ResolvConfPath,
     .HostnamePath, .HostsPath, .LogPath, .Config.Hostname, .GraphDriver)
     | .Config.Env |= sort | .HostConfig.MaskedPaths |= sort | .HostConfig.Dns |= (. // [])' "$1"; }
   docker inspect "$C" > after.json; diff <(norm before.json) <(norm after.json)
   ```
   Docker can reorder `Env` and `MaskedPaths`, and `Dns: []` can come back as
   `null`. Neither changes anything that runs.
4. **Remove the backup** once verified: `docker rm "$B"`. Keep the volume.

**Rollback**, before step 4:

```bash
docker stop "$C" && docker rm "$C" && docker rename "$B" "$C" && docker start "$C"
```
