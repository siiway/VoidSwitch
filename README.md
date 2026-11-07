# ⚡ VoidSwitch

A production-grade, multi-provider **LLM API reverse proxy** with resilient
upstream routing. It accepts **OpenAI-style** (`/v1/chat/completions`), **OpenAI
Responses** (`/v1/responses`), and **Anthropic-style** (`/v1/messages`) traffic,
translates between them on the fly, and dispatches to any configured upstream
through **outbound node groups** (HTTP/SOCKS proxies, voidswitch-agent relays, or
direct).

Point an OpenAI SDK, an Anthropic SDK, or **Claude Code** / **OpenCode** at one
endpoint and let VoidSwitch handle provider selection, key rotation, outbound
routing, failover, and quotas.

```
         OpenAI client ─┐                          ┌─ OpenAI-style upstreams
                        ├─►  VoidSwitch gateway  ──┤   (OpenAI, DeepSeek, Groq, …)
    Claude Code / SDK ──┘   translate · failover   └─ Anthropic-style upstreams
                             key+node rotation          (Anthropic / Claude)
```

| Path               | Stack                                          | What it is                  |
| ------------------ | ---------------------------------------------- | --------------------------- |
| `backend/`         | Go 1.25 · Gin · GORM · PostgreSQL · Redis      | The gateway + admin API     |
| `frontend/`        | Bun · React 19 · Fluent UI v9                  | Decoupled admin dashboard   |
| `agent/`           | Go · static binary                             | Outbound relay agent        |
| `opencode-plugin/` | Bun · TypeScript · `@opencode-ai/plugin`       | OpenCode provider plugin    |

The Go backend is the actively maintained gateway. The previous Python
implementation is preserved on the `legacy` branch (and can still be run from
there). See `docs/migration/` for the cutover runbook and existing-deployment
migration notes.

## Feature summary

- **Multi-provider adapters** — OpenAI, Anthropic, Claude Code (subscription
  OAuth), DeepSeek (with strict balance / auth edge-case handling), plus presets
  for SiliconFlow, OpenRouter, Groq, xAI, Moonshot, MiMo, NVIDIA, Mistral,
  Together, Fireworks, Perplexity, Cerebras, DeepInfra, Gemini, Novita, SambaNova,
  Hyperbolic, Nebius, GitHub Models, Zhipu/GLM, Qwen, Volcengine/Doubao, MiniMax,
  and a generic OpenAI-compatible catch-all. Add more by subclassing `BaseProvider`.
- **Bidirectional translation** — OpenAI Chat, OpenAI Responses, Anthropic, and
  Gemini via [RelayKit](https://github.com/QuantumNous/new-api/tree/main/relaykit)
  (requests, responses, and **streaming SSE**, including tool calls, reasoning,
  multimodal, and usage). Note: RelayKit is AGPL-3.0; the gateway is therefore
  distributed under AGPL-3.0.
- **Resilient dispatcher** — auth/balance errors rotate the *key*; network/timeout
  errors rotate the *node* (disabling it past a dynamic threshold); rate-limit and
  5xx errors retry on the next key/provider. Streaming-safe.
- **Model routing** — per-model route flowcharts (exposed model → ordered fallback
  layers → weighted upstream entries). Each layer can try multiple providers with
  different upstream models and key pools.
- **Provider passthrough** — models from a provider can be directly exposed to
  users as `provider-id/model-id`, bypassing the route system entirely (whitelist
  mode with optional pool scoping and exposed-id renaming).
- **Model categories** — group models into categories for the catalog UI; provider
  passthrough models auto-form virtual categories.
- **Outbound routing** — node groups (with inheritance) pick HTTP/SOCKS proxies,
  voidswitch-agent relays, or direct connections. Dynamic ranking by latency +
  stability.
- **voidswitch-agent** — Go static binary for custom H2 relay (X-VS-Upstream-URL)
  + CONNECT fallback, token auth, metrics, Docker.
- **Prism OAuth** (OIDC + PKCE) dashboard login; long-lived `vs-…` client tokens
  with per-token model allow-lists and RPM limits.
- **Background crons** — balance probe (fast-fails empty keys), node resurrector
  (re-enables recovered nodes), log cleanup. Intervals tunable at runtime.
- **Observability** — request/usage/audit logs, live SSE stream, statistics,
  activity heatmap.
- **OpenCode plugin** — registers VoidSwitch as a first-class OpenCode provider and
  reproduces the full Claude Code request surface. See `opencode-plugin/`.

## Build & run

```bash
# From source (gateway + dashboard + Postgres + Redis):
docker compose -f compose.yaml -f compose-build.override.yaml up -d --build

# Or pull published images:
docker compose up -d
```

Configuration is via `VOIDSWITCH_*` env vars — copy `.env.example` to `.env`.

## Quality gates

```bash
# Go backend
cd backend
go build ./...
go vet ./...
go test ./... && go test -race ./...

# Frontend
cd ../frontend
bun run lint            # tsc --noEmit
bun run build           # vite production build
```
