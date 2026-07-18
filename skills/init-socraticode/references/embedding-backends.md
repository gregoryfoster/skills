# Embedding backends — the tradeoff

SocratiCode needs an embedding model to turn code chunks into vectors. The
backend is a **parameter the operator chooses up front** (SKILL.md Phase 0) — do
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
nomic-embed-text`, and configure SocratiCode to use the host endpoint instead of
the container. Exact env var names can drift between versions — confirm against
the installed `socraticode` release before relying on one.

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
