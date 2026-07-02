# Calling the API

VoidSwitch speaks both **OpenAI-style** and **Anthropic-style** APIs on the same
host. Use whichever your client expects — the gateway translates as needed.

Replace `https://your-voidswitch-host` with your deployment's URL and
`vs-your-token` with a [Void-Token](/guide/api-keys).

## List available models

```bash
curl https://your-voidswitch-host/v1/models \
  -H "Authorization: Bearer vs-your-token"
```

Only models you're allowed to call are returned. See [Models](/guide/models).

## OpenAI-style

Base URL: `https://your-voidswitch-host/v1`

::: code-group

```bash [curl]
curl https://your-voidswitch-host/v1/chat/completions \
  -H "Authorization: Bearer vs-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

```python [Python (openai)]
from openai import OpenAI

client = OpenAI(
    base_url="https://your-voidswitch-host/v1",
    api_key="vs-your-token",
)

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

```javascript [Node (openai)]
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://your-voidswitch-host/v1",
  apiKey: "vs-your-token",
});

const resp = await client.chat.completions.create({
  model: "deepseek-chat",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(resp.choices[0].message.content);
```

:::

### Streaming

Set `"stream": true` (or `stream=True`). Server-Sent Events are streamed through
and translated if the upstream is Anthropic-style.

## Anthropic-style

Base URL: `https://your-voidswitch-host`

```bash
curl https://your-voidswitch-host/v1/messages \
  -H "x-api-key: vs-your-token" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

```python [Python (anthropic)]
from anthropic import Anthropic

client = Anthropic(
    base_url="https://your-voidswitch-host",
    auth_token="vs-your-token",
)

msg = client.messages.create(
    model="claude-sonnet-4",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(msg.content[0].text)
```

## Authentication

Any of these carry your token:

- `Authorization: Bearer vs-your-token` (OpenAI-style)
- `x-api-key: vs-your-token` (Anthropic-style)

## Errors you may see

| Status | Meaning |
| ------ | ------- |
| `401` | Missing/invalid token, or token expired/disabled. |
| `403` | Token not allowed to call this model. |
| `429` | You hit your token's RPM limit or daily quota. |
| `5xx` | Upstream failed after failover; retry shortly. |

::: tip Interactive reference
The full request/response schema is available in **Swagger UI** at
`https://your-voidswitch-host/swagger`.
:::
