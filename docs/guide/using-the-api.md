# 调用 API

VoidSwitch 在同一主机上支持 **OpenAI Chat Completions**、**OpenAI Responses** 和
**Anthropic Messages** API。使用你的客户端期望的格式 —
网关在需要时在它们之间转换，无论上游供应商使用何种格式。

| 格式 | 端点 |
| ----- | -------- |
| OpenAI Chat Completions | `POST /v1/chat/completions` |
| OpenAI Responses | `POST /v1/responses` |
| Anthropic Messages | `POST /v1/messages` |

将 `https://voidswitch.siiway.org` 替换为你的部署 URL，将 `vs-your-token` 替换为 [Void-Token](/guide/api-keys)。

## 列出可用模型

```bash
curl https://voidswitch.siiway.org/v1/models \
  -H "Authorization: Bearer vs-your-token"
```

仅返回你有权限调用的模型。参见[模型](/guide/models)。

每个条目除标准的 `id` / `object` / `created` / `owned_by` 外，还带有下游可直接使用的配置：

| 字段 | 说明 |
| --- | --- |
| `id` | 调用时填进 `model` 的模型 ID。passthrough 模型形如 `provider-slug/model-id` |
| `opencode` | 已合并好的 OpenCode **1.x** 模型配置块（`name`、`limit`、`reasoning`、`capabilities`、`modalities`、自定义配置等） |
| `opencode_v2` | 已合并好的 OpenCode **2.x** 模型配置块（`capabilities.input/output/tools/reasoning`、数组形式的 `variants`、`limit` 等）。V1 专有键不会出现在这里 |
| `display_name` | 展示名；未设置时省略 |
| `description` | 说明；未设置时省略 |

两代配置块的合并优先级相同（高 → 低）：**结构化字段**（展示名、limit、reasoning、能力、模态）
→ **对应版本的自定义 OpenCode 配置**（`opencode_config` / `opencode_config_v2`）→
**models.dev 占位信息**。插件侧默认值在客户端最后应用，不在此块内。上游供应商与密钥信息不会出现在这里。

两套块**不可混用**：把 V1 形状写进 V2 块会让 OpenCode 2 丢弃整个 provider（连同缓存的模型列表），
反之亦然。客户端应按自己的代际取用对应字段。

## OpenAI 风格

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

### 流式传输

设置 `"stream": true`（或 `stream=True`）。Server-Sent Events 会被流式传输，如果上游是 Anthropic 格式则会被转换。

## OpenAI Responses 风格

Base URL: `https://voidswitch.siiway.org/v1` — 与 Chat Completions 相同的 base，因此 OpenAI SDK
只需调用 Responses 方法即可。

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

无论上游供应商使用何种格式，网关都会接受 Responses 请求，并在设置 `"stream": true` 时流式返回 Responses 事件。

## Anthropic 风格

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

## 认证

以下任一方式均可携带你的令牌：

- `Authorization: Bearer vs-your-token`（OpenAI 风格）
- `x-api-key: vs-your-token`（Anthropic 风格）

## 可能遇到的错误

| 状态码 | 含义 |
| ------ | ------ |
| `401` | 令牌缺失/无效，或令牌已过期/已禁用。 |
| `403` | 令牌不允许调用此模型。 |
| `429` | 你达到了令牌的 RPM 限制 / 每日配额，或平台的每用户调用速率限制。 |
| `5xx` | 上游在故障转移后失败；请稍后重试。 |

::: tip 交互式参考
完整的请求/响应 schema 可在 **Swagger UI** 中查看，地址为
`https://voidswitch.siiway.org/swagger`。
:::