# VoidSwitch — backend

A production-grade, multi-provider LLM API reverse proxy with resilient key &
proxy failover. Accepts **OpenAI-style** (`/v1/chat/completions`) and
**Anthropic-style** (`/v1/messages`, what Claude Code speaks) traffic, translates
between the two transparently, and forwards to any configured upstream over
optional HTTP/SOCKS proxies or specific local source IPs.

## Highlights

- **Multi-provider** adapters: OpenAI, Anthropic, **Claude Code (subscription
  OAuth)**, DeepSeek, SiliconFlow, OpenRouter, Groq, xAI, Moonshot, plus a generic
  OpenAI-compatible catch-all.
- **Bidirectional translation** OpenAI ⇄ Anthropic for requests, responses, and
  streaming (SSE), so a client of either dialect can reach a provider of either
  dialect. Point Claude Code's `ANTHROPIC_BASE_URL` here.
- **Resilient dispatcher**: rotates keys on auth/balance errors, rotates proxies
  on network/timeout errors, disables resources past dynamic thresholds, and
  retries — all without dropping a streaming connection before first byte.
- **Outbound routing** via `httpx` + `httpx-socks`: HTTP/SOCKS proxies and
  `local_address` source-IP binding, with pooled connection reuse.
- **Prism OAuth** login (OIDC, PKCE) for the dashboard; long-lived `vs-…`
  Void-Tokens for clients.
- **Background crons**: balance probe (fast-fails empty keys) and proxy
  resurrector (re-enables recovered proxies).
- **Audit + request logs**, per-token quotas/RPM, runtime-tunable thresholds.

## Quick start

```bash
cd backend
cp config.example.yaml config.yaml      # then fill in Prism client_id/secret
uv sync
uv run voidswitch                        # serves on http://0.0.0.0:8080
```

Open `http://localhost:8080/docs` for the OpenAPI UI.

### Point a client at it

OpenAI SDK:

```bash
export OPENAI_BASE_URL=http://localhost:8080/v1
export OPENAI_API_KEY=vs-...            # a Void-Token from the dashboard
```

Claude Code / Anthropic SDK:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8080
export ANTHROPIC_AUTH_TOKEN=vs-...
```

## Claude via a subscription (the "reverse-engineered" path)

The `claude-code` provider type lets a Claude **Pro/Max subscription** back the
gateway instead of a metered API key. It authenticates the way the Claude Code
CLI does:

- `Authorization: Bearer <token>` using a token from `claude setup-token`
  (a long-lived, inference-only OAuth token) — **not** `x-api-key`.
- the `oauth-2025-04-20` + `claude-code-20250219` beta headers, and
- the Claude Code identity system prompt is injected automatically so OAuth
  inference is accepted.

Set it up: create a provider of type **`claude-code`**, run `claude setup-token`,
and paste the token in as a provider key (batch-add works too). Models are the
normal `claude-*` IDs. Both OpenAI-style and Anthropic-style inbound requests are
translated and routed to it like any other provider.

> Use only with credentials you're entitled to; subscription terms apply.

## Configuration

`config.yaml` holds **only** server info and Prism OAuth credentials (see
`config.example.yaml`). Every value can be overridden by environment variables
prefixed `VOIDSWITCH_` with `__` as the nesting separator, e.g.
`VOIDSWITCH_SERVER__PORT=9000`.

All operational thresholds (failure limits, probe intervals, timeouts, retry
budget) live in the database and are editable at runtime from the dashboard or
`PUT /api/admin/settings`.

## Development

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uvx ty check                 # type-check (zero errors expected)
uv run pytest                # async test suite
```

## Architecture

```
voidswitch/
├── core/        config, logging, async DB, security (token hashing + AES), auth
├── models/      SQLAlchemy 2.0 async models + Pydantic v2 schemas
├── services/
│   ├── network.py      pooled httpx clients with proxy/SOCKS/local-IP routing
│   ├── transform.py    OpenAI ⇄ Anthropic translation (incl. streaming)
│   ├── selector.py     weighted-least-used provider/key/route selection
│   ├── dispatcher.py   the failover engine
│   └── providers/      BaseProvider + per-vendor adapters
├── api/         gateway (/v1/*), auth, self-service (/api/me), admin CRUD
└── tasks/       background balance probe + proxy resurrector
```

See the repository root for the decoupled **frontend** (Bun + React + Fluent UI).
