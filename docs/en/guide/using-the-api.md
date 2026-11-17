# Calling the API

VoidSwitch supports the **OpenAI Chat Completions**, **OpenAI Responses**, and
**Anthropic Messages** APIs on the same host. Use the format your client expects —
the gateway translates between them when needed, regardless of what format the upstream provider uses.

| Format | Endpoint |
| ----- | -------- |
| OpenAI Chat Completions | `POST /v1/chat/completions` |
| OpenAI Responses | `POST /v1/responses` |
| Anthropic Messages | `POST /v1/messages` |

Replace `https://voidswitch.siiway.org` with your deployment URL, and replace `vs-your-token` with a [Void-Token](/en/guide/api-keys).

## List available models

```bash
curl https://voidswitch.siiway.org/v1/models \
  -H "Authorization: Bearer vs-your-token"
```

Only models you are allowed to call are returned. See [Models](/en/guide/models).

Each entry carries the standard `id` / `object` / `created` / `owned_by` plus config a client can use directly:

| Field | Meaning |
| --- | --- |
| `id` | The model ID to send as `model`. A passthrough model looks like `provider-slug/model-id` |
| `opencode` | The merged OpenCode **1.x** model config block (`name`, `limit`, `reasoning`, `capabilities`, `modalities`, custom config, …) |
| `opencode_v2` | The merged OpenCode **2.x** block (`capabilities.input/output/tools/reasoning`, array-shaped `variants`, `limit`, …). V1-only keys never appear here |
| `display_name` | Display name; omitted when unset |
| `description` | Description; omitted when unset |

Both blocks merge, highest precedence first: **structured fields** (display name, limits, reasoning,
capabilities, modalities) → **the matching custom OpenCode config** (`opencode_config` /
`opencode_config_v2`) → **models.dev placeholder**. Plugin defaults are applied last on the client and are
not part of these blocks. Upstream providers and keys never appear here.

The two blocks are **not interchangeable**: writing a V1 shape into the V2 block makes OpenCode 2 discard
the whole provider (and its cached model list), and vice versa. Clients pick the block matching their
generation.

## OpenAI style

Base URL: `https://voidswitch.siiway.org/v1`

::: code-group

```bash [curl]
curl https://voidswitch.siiway.org/v1/chat/completions \
  -H "Authorization: Bearer vs-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

```python [Python (openai)]
from openai import OpenAI

client = OpenAI(
    base_url="https://voidswitch.siiway.org/v1",
    api_key="vs-your-token",
)

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好！"}],
)
print(resp.choices[0].message.content)
```

```javascript [Node (openai)]
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://voidswitch.siiway.org/v1",
  apiKey: "vs-your-token",
});

const resp = await client.chat.completions.create({
  model: "deepseek-chat",
  messages: [{ role: "user", content: "你好！" }],
});
console.log(resp.choices[0].message.content);
```

:::

### Streaming

Set `"stream": true` (or `stream=True`). Server-Sent Events are streamed, and are converted if the upstream is in Anthropic format.

## OpenAI Responses style

Base URL: `https://voidswitch.siiway.org/v1` — the same base as Chat Completions, so the OpenAI SDK
only needs to call the Responses methods.

::: code-group

```bash [curl]
curl https://voidswitch.siiway.org/v1/responses \
  -H "Authorization: Bearer vs-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "input": "你好！"
  }'
```

```python [Python (openai)]
from openai import OpenAI

client = OpenAI(
    base_url="https://voidswitch.siiway.org/v1",
    api_key="vs-your-token",
)

resp = client.responses.create(
    model="deepseek-chat",
    input="你好！",
)
print(resp.output_text)
```

:::

Regardless of what format the upstream provider uses, the gateway accepts Responses requests and streams back Responses events when `"stream": true` is set.

## Anthropic style

Base URL: `https://voidswitch.siiway.org`

```bash
curl https://voidswitch.siiway.org/v1/messages \
  -H "x-api-key: vs-your-token" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

```python [Python (anthropic)]
from anthropic import Anthropic

client = Anthropic(
    base_url="https://voidswitch.siiway.org",
    auth_token="vs-your-token",
)

msg = client.messages.create(
    model="claude-sonnet-4",
    max_tokens=512,
    messages=[{"role": "user", "content": "你好！"}],
)
print(msg.content[0].text)
```

## Authentication

You can carry your token in either of the following ways:

- `Authorization: Bearer vs-your-token` (OpenAI style)
- `x-api-key: vs-your-token` (Anthropic style)

## Errors you may encounter

| Status code | Meaning |
| ------ | ------ |
| `401` | Token missing/invalid, or token expired/disabled. |
| `403` | Token is not allowed to call this model. |
| `429` | You hit the token's RPM limit / daily quota, or the platform's per-user request rate limit. |
| `5xx` | Upstream failed after failover; retry later. |

::: tip Interactive reference
The complete request/response schemas are available in **Swagger UI** at
`https://voidswitch.siiway.org/swagger`.
:::
