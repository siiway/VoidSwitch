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

| Path               | Stack                                    | What it is                  |
| ------------------ | ---------------------------------------- | --------------------------- |
| `backend/`         | Python 3.13 · uv · FastAPI · SQLAlchemy  | The gateway + admin API     |
| `frontend/`        | Bun · React 19 · Fluent UI v9            | Decoupled admin dashboard   |
| `agent/`           | Go · static binary                       | Outbound relay agent        |
| `opencode-plugin/` | Bun · TypeScript · `@opencode-ai/plugin` | OpenCode provider plugin    |

Each has its own README with full details.

## Feature summary

- **Multi-provider adapters** — OpenAI, Anthropic, Claude Code (subscription
  OAuth), DeepSeek (with strict balance / auth edge-case handling), plus presets
  for SiliconFlow, OpenRouter, Groq, xAI, Moonshot, MiMo, NVIDIA, Mistral,
  Together, Fireworks, Perplexity, Cerebras, DeepInfra, Gemini, Novita, SambaNova,
  Hyperbolic, Nebius, GitHub Models, Zhipu/GLM, Qwen, Volcengine/Doubao, MiniMax,
  and a generic OpenAI-compatible catch-all. Add more by subclassing `BaseProvider`.
- **Bidirectional translation** — OpenAI ⇄ Anthropic for requests, responses, and
  **streaming SSE**, including tool/function calls and token usage.
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

## Quality gates

```bash
cd backend
uv run ruff check .     # lint        → clean
uvx ty check            # type-check  → zero errors
uv run pytest           # async tests → all green

cd ../frontend
bun run build           # tsc + vite production build
```
