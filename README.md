# ⚡ VoidSwitch

A production-grade, multi-provider **LLM API reverse proxy** with resilient key &
proxy failover. It accepts both **OpenAI-style** (`/v1/chat/completions`) and
**Anthropic-style** (`/v1/messages`) traffic, translates between the two on the
fly, and forwards to any configured upstream over optional HTTP/SOCKS proxies or
specific local source IPs.

Point an OpenAI SDK, an Anthropic SDK, or **Claude Code** at one endpoint and let
VoidSwitch handle provider selection, key rotation, proxy failover, and quotas.

```
        OpenAI client ─┐                          ┌─ OpenAI-style upstreams
                       ├─►  VoidSwitch gateway  ──┤   (OpenAI, DeepSeek, Groq, …)
   Claude Code / SDK ──┘   translate · failover   └─ Anthropic-style upstreams
                            key+proxy rotation         (Anthropic / Claude)
```

## Repository layout

| Path               | Stack                                   | What it is                          |
|--------------------|-----------------------------------------|-------------------------------------|
| `backend/`         | Python 3.13 · uv · FastAPI · SQLAlchemy  | The gateway + admin API             |
| `frontend/`        | Bun · React 19 · Fluent UI v9            | Decoupled admin dashboard           |
| `opencode-plugin/` | Bun · TypeScript · `@opencode-ai/plugin` | OpenCode provider plugin            |

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
  errors rotate the *proxy* (disabling it past a dynamic threshold); rate-limit and
  5xx errors retry on the next key/provider. Streaming-safe.
- **Outbound routing** — `httpx` + `httpx-socks`: HTTP & SOCKS proxies plus
  `local_address` source-IP binding, with pooled connection reuse.
- **Prism OAuth** (OIDC + PKCE) dashboard login; long-lived `vs-…` client tokens
  with per-token model allow-lists and RPM limits.
- **Background crons** — balance probe (fast-fails empty keys) and proxy
  resurrector (re-enables recovered proxies). Intervals tunable at runtime.
- **Model catalog** — a **Models** page (visible to every signed-in user) collects
  every model id served across the platform as cards. Admins set per-model
  descriptions (individually or in batch) and a custom OpenCode model config that
  the plugin deep-merges into each model. Any user can refresh the catalog from the
  dashboard, the `POST /v1/models/sync` endpoint, or the OpenCode `/sync-models` command.
- **Observability** — request/usage logs, administrative audit trail, live stats.
- **OpenCode plugin** — registers VoidSwitch as a first-class OpenCode provider and
  reproduces the full Claude Code request surface (effort levels, fast mode, adaptive
  thinking, task budgets, 1M context) at the wire level. See `opencode-plugin/`.

## Quick start

**1. Backend**

```bash
cd backend
cp config.example.yaml config.yaml     # fill in Prism client_id / client_secret
uv sync
uv run voidswitch                       # http://localhost:8080  (docs at /docs)
```

**2. Frontend**

```bash
cd frontend
bun install
bun run dev                             # http://localhost:5173
```

Sign in with Prism — the first user to log in becomes an owner. Add a provider,
paste in some API keys (and optionally proxies), mint a Void-Token, and point your
client at the gateway:

```bash
# OpenAI-style
export OPENAI_BASE_URL=http://localhost:8080/v1
export OPENAI_API_KEY=vs-...

# Claude Code / Anthropic-style
export ANTHROPIC_BASE_URL=http://localhost:8080
export ANTHROPIC_AUTH_TOKEN=vs-...
```

For **OpenCode**, install the `opencode-plugin/` provider plugin instead — it adds
the full Claude Code request surface (effort, fast mode, thinking). See its README.

## Quality gates

```bash
cd backend
uv run ruff check .     # lint        → clean
uvx ty check            # type-check  → zero errors
uv run pytest           # async tests → all green

cd ../frontend
bun run build           # tsc + vite production build
```

## Configuration

`backend/config.yaml` holds **only** server info and Prism OAuth credentials. All
operational thresholds (failure limits, probe intervals, timeouts, retry budget)
live in the database and are edited from the dashboard **Settings** page or
`PUT /api/admin/settings`. Any config value can also be set via environment, e.g.
`VOIDSWITCH_SERVER__PORT=9000`, `VOIDSWITCH_PRISM__CLIENT_SECRET=…`.
