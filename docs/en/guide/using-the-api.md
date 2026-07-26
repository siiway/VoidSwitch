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
