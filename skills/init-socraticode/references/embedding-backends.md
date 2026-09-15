# Embedding backends — the tradeoff

SocratiCode needs an embedding model to turn code chunks into vectors. The
backend is a **parameter the operator chooses up front** (SKILL.md's parameters) — do
not silently default it for large repos, because the default is CPU-bound and
slow.

| Backend | How | Key needed | Speed | When to pick |
|---|---|---|---|---|
| **Dockerized Ollama** (default) | `nomic-embed-text` in the `socraticode-ollama` container | none | **Slow (CPU-only)** | Small/medium repos, no API budget, fully local/offline |
| **Native Ollama (Metal/CUDA)** | point at a host Ollama with GPU | none | Fast | Apple Silicon or NVIDIA host, want local + fast |
| **OpenAI** | `EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY` | yes | Fast | Large repos, cloud OK, have a key |
| **Google** | `EMBEDDING_PROVIDER=google` + key | yes | Fast | Large repos, GCP-aligned |

## Setting a cloud/native backend

The plugin MCP server reads provider config from its environment. Set these
where the server launches (plugin config, or the shell that runs the driver):

```bash
# OpenAI
export EMBEDDING_PROVIDER=openai
export OPENAI_API_KEY=sk-...

# Google
export EMBEDDING_PROVIDER=google
export GOOGLE_API_KEY=...      # or the provider's documented var for the installed version
```

Native (host) Ollama with a GPU: install Ollama on the host, `ollama pull
nomic-embed-text`, and point SocratiCode at it instead of the container:
`OLLAMA_MODE=external` and `OLLAMA_URL=http://<host>:11434` (the names in
1.13.3's `embedding-config.js`; confirm against the installed release if it is
far newer). Left at the default `auto`, the server uses a native Ollama only
when one answers on localhost:11434 and otherwise starts a container.

With `STORE=external` the embedder is not a free choice: every client of one
store must embed with the same model at the same dimension, because a
collection holds vectors of one shape. Use what the store's other clients use —
the `env` block in [`external-store.md`](external-store.md) sets it, and an
external Ollama keeps the client Docker-free.

## Cost/time reality (default CPU Ollama)

From the `usa-wa` first index (2026-07-17): **~1105 files → 6019 chunks → ~75
min** end to end on CPU Ollama. The one-time first run also pulls the Qdrant
image, the Ollama image, and the `nomic-embed-text` model (~277 MB) before any
embedding starts. Budget accordingly and set generous timeouts.

**Rule of thumb:** repos past a few thousand files on CPU Ollama get painful.
Offer OpenAI/Google or native-GPU Ollama when the operator has a key or GPU;
otherwise warn them the first index is a long, one-time cost (subsequent
re-indexes reuse the running containers and are fast — see the troubleshooting
matrix, gotcha F).
