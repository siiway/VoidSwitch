# Provider Catalog and Support Status

This page lists all built-in **adapter types** by category along with their support status, to help you
choose when [adding a provider](/en/admin/providers).

## Capability notes

The columns mean the following:

- **Protocol** — the wire format the gateway uses to talk to the upstream. Inbound OpenAI-chat / Anthropic /
  OpenAI-Responses requests are all transparently converted, so callers do not need to care about the
  upstream's actual protocol.
  - `OpenAI Chat` — `POST /v1/chat/completions`
  - `OpenAI Responses` — `POST /v1/responses`
  - `Anthropic Messages` — `POST /v1/messages`
- **Balance** — whether balance queries are supported (the Providers page shows a **Balance** column and a
  "Refresh balance" action).
- **Import** — whether cpa / sub2api / CLIProxyAPI credential files can be imported on that provider's keys
  page. See [Upstream keys](/en/admin/keys).
- **OAuth refresh** — whether OAuth credential bundles (`access_token` / `refresh_token`) are supported and
  automatically refreshed when nearing expiry or receiving a 401.

> ✓ means supported, — means not supported. All adapters support the common capabilities of model mapping,
> key pools, failover, and egress proxies.

## Official native protocols

Talk to each vendor's official API using its native wire format.

| Adapter `type` | Protocol | Default Base URL | Balance | Import | OAuth refresh |
| --- | --- | --- | :---: | :---: | :---: |
| `openai` | OpenAI Chat | `https://api.openai.com/v1` | — | — | — |
| `openai-resp` | OpenAI Responses | `https://api.openai.com/v1` | — | — | — |
| `anthropic` | Anthropic Messages | `https://api.anthropic.com` | — | — | — |

::: tip openai-resp
For upstreams that use OpenAI's newer
[Responses API](https://developers.openai.com/api/reference/resources/responses)
instead of Chat Completions, choose the `openai-resp` adapter.
:::

## Subscription login / OAuth accounts

Reuse subscription accounts or reverse-engineered web backends; keys come from OAuth credentials or SSO
cookies and can be bulk-imported.

| Adapter `type` | Protocol | Default Base URL | Balance | Import | OAuth refresh |
| --- | --- | --- | :---: | :---: | :---: |
| `claude-code` | Anthropic Messages | `https://api.anthropic.com` | — | ✓ | ✓ |
| `codex` | OpenAI Responses | `https://chatgpt.com/backend-api/codex` | — | ✓ | ✓ |
| `xai` | OpenAI Chat | `https://api.x.ai/v1` | — | ✓ | ✓ |
| `grok-build` | OpenAI Chat | `https://cli-chat-proxy.grok.com/v1` | — | — | ✓ |
| `grok` | OpenAI Responses | `https://console.x.ai/v1` | — | ✓ | — |

::: tip Grok (`xai` vs `grok`)
- `xai` talks to the official `api.x.ai`; the key can be a standard API Key or an xAI **OAuth credential
  bundle** (auto-refreshed).
- `grok` talks to the `console.x.ai` web backend (see
  [grok2api](https://github.com/jiujiu532/grok2api)); the key is an **SSO Token**.

See [Providers · Grok notes](/en/admin/providers) for details.
:::

`codex` uses a ChatGPT/Codex subscription. Its key page supports browser OAuth (paste the localhost
callback URL after approval) and device-code login; access tokens refresh automatically. Its default
models are `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`.

## OpenAI-compatible (international)

International vendors and aggregation platforms that expose an OpenAI-compatible `/v1/chat/completions`
endpoint.

| Adapter `type` | Default Base URL | Balance | Import | OAuth refresh |
| --- | --- | :---: | :---: | :---: |
| `openrouter` | `https://openrouter.ai/api/v1` | — | — | — |
| `groq` | `https://api.groq.com/openai/v1` | — | — | — |
| `mistral` | `https://api.mistral.ai/v1` | — | — | — |
| `together` | `https://api.together.xyz/v1` | — | — | — |
| `fireworks` | `https://api.fireworks.ai/inference/v1` | — | — | — |
| `perplexity` | `https://api.perplexity.ai` | — | — | — |
| `cerebras` | `https://api.cerebras.ai/v1` | — | — | — |
| `deepinfra` | `https://api.deepinfra.com/v1/openai` | — | — | — |
| `novita` | `https://api.novita.ai/v3/openai` | — | — | — |
| `sambanova` | `https://api.sambanova.ai/v1` | — | — | — |
| `hyperbolic` | `https://api.hyperbolic.xyz/v1` | — | — | — |
| `nebius` | `https://api.studio.nebius.com/v1` | — | — | — |
| `nvidia` | `https://integrate.api.nvidia.com/v1` | — | — | — |
| `cloudflare` | `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` | — | — | — |
| `github-models` | `https://models.github.ai/inference` | — | — | — |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | — | — | — |

::: tip Gemini
The `gemini` adapter uses Google's OpenAI-compatible endpoint, so it connects with the standard OpenAI Chat
protocol.
:::

::: tip cloudflare
The `cloudflare` Base URL contains an `{account_id}` placeholder that must be replaced with the actual
account ID when adding the provider.
:::

## OpenAI-compatible (China)

Chinese vendors that expose OpenAI-compatible endpoints.

| Adapter `type` | Default Base URL | Balance | Import | OAuth refresh |
| --- | --- | :---: | :---: | :---: |
| `deepseek` | `https://api.deepseek.com` | ✓ | — | — |
| `siliconflow` | `https://api.siliconflow.cn/v1` | — | — | — |
| `moonshot` | `https://api.moonshot.cn/v1` | — | — | — |
| `mimo` | `https://api.xiaomimimo.com/v1` | — | — | — |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | — | — | — |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | — | — | — |
| `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` | — | — | — |
| `minimax` | `https://api.minimax.io/v1` | — | — | — |

## Generic catch-all

| Adapter `type` | Protocol | Default Base URL | Balance | Import | OAuth refresh |
| --- | --- | --- | :---: | :---: | :---: |
| `generic` | OpenAI Chat | (no preset, Base URL must be filled in manually) | — | — | — |

::: tip generic
Any upstream that has no preset but is compatible with OpenAI `/v1/chat/completions` can be connected with
`generic` by manually filling in the Base URL and model list.
:::
