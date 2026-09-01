# 供应商目录与支持情况

本页按类别列出所有内置**适配器类型**及其支持情况，方便在[添加供应商](/admin/providers)时选型。

## 能力说明

各列含义如下：

- **协议** — 网关与上游对话的线路格式。入站的 OpenAI-chat / Anthropic / OpenAI-Responses
  请求都会被透明转换，因此调用者无需关心上游实际协议。
  - `OpenAI Chat` — `POST /v1/chat/completions`
  - `OpenAI Responses` — `POST /v1/responses`
  - `Anthropic Messages` — `POST /v1/messages`
- **余额** — 是否支持余额查询（供应商页面显示**余额**列与"刷新余额"操作）。
- **导入** — 是否可在该供应商的密钥页面导入 cpa / sub2api / CLIProxyAPI 的凭据文件。
  参见[上游密钥](/admin/keys)。
- **OAuth 刷新** — 是否支持 OAuth 凭证包（`access_token` / `refresh_token`），
  并在临近过期或收到 401 时自动刷新。

> ✓ 表示支持，— 表示不支持。所有适配器都支持模型映射、密钥池、故障转移与出口代理等通用能力。

## 官方原生协议

对接各家官方 API，使用其原生线路格式。

| 适配器 `type` | 协议 | 默认 Base URL | 余额 | 导入 | OAuth 刷新 |
| --- | --- | --- | :---: | :---: | :---: |
| `openai` | OpenAI Chat | `https://api.openai.com/v1` | — | — | — |
| `openai-resp` | OpenAI Responses | `https://api.openai.com/v1` | — | — | — |
| `anthropic` | Anthropic Messages | `https://api.anthropic.com` | — | — | — |

::: tip openai-resp
为使用 OpenAI 较新的
[Responses API](https://developers.openai.com/api/reference/resources/responses)
而非 Chat Completions 的上游选择 `openai-resp` 适配器。
:::

## 订阅登录 / OAuth 账号

复用订阅版账号或逆向网页后端，密钥来自 OAuth 凭证或 SSO Cookie，可批量导入。

| 适配器 `type` | 协议 | 默认 Base URL | 余额 | 导入 | OAuth 刷新 |
| --- | --- | --- | :---: | :---: | :---: |
| `claude-code` | Anthropic Messages | `https://api.anthropic.com` | — | ✓ | ✓ |
| `codex` | OpenAI Responses | `https://chatgpt.com/backend-api/codex` | — | ✓ | ✓ |
| `xai` | OpenAI Chat | `https://api.x.ai/v1` | — | ✓ | ✓ |
| `grok-build` | OpenAI Chat | `https://cli-chat-proxy.grok.com/v1` | — | — | ✓ |
| `grok` | OpenAI Responses | `https://console.x.ai/v1` | — | ✓ | — |

::: tip Grok（`xai` vs `grok-build` vs `grok`）
- `xai` 对接官方 `api.x.ai`，密钥可为标准 API Key 或 xAI **OAuth 凭证包**（自动刷新）。
- `grok-build` 对接 Grok CLI 订阅后端 `cli-chat-proxy.grok.com`，通过 **OAuth 登录**获取凭证（自动刷新），
  默认模型 `grok-4.5`。这是 grok 命令行工具的订阅额度，与 `xai` API、`grok` 网页后端相互独立。
- `grok` 对接 `console.x.ai` 网页后端（参考
  [grok2api](https://github.com/jiujiu532/grok2api)），密钥填 **SSO Token**。

详见[供应商 · Grok 说明](/admin/providers)。
:::

`codex` 使用 ChatGPT/Codex 订阅额度。密钥页支持浏览器 OAuth（批准后粘贴 localhost 回调 URL）
和设备代码登录；访问令牌到期前会自动刷新。默认模型为 `gpt-5.6-sol`、`gpt-5.6-terra`
和 `gpt-5.6-luna`。

## OpenAI 兼容（国际）

暴露 OpenAI 兼容 `/v1/chat/completions` 端点的国际厂商与聚合平台。

| 适配器 `type` | 默认 Base URL | 余额 | 导入 | OAuth 刷新 |
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
`gemini` 适配器走 Google 的 OpenAI 兼容端点，因此以标准 OpenAI Chat 协议接入。
:::

::: tip cloudflare
`cloudflare` 的 Base URL 含 `{account_id}` 占位符，添加供应商时需替换为实际账户 ID。
:::

## OpenAI 兼容（国内）

暴露 OpenAI 兼容端点的国内厂商。

| 适配器 `type` | 默认 Base URL | 余额 | 导入 | OAuth 刷新 |
| --- | --- | :---: | :---: | :---: |
| `deepseek` | `https://api.deepseek.com` | ✓ | — | — |
| `siliconflow` | `https://api.siliconflow.cn/v1` | — | — | — |
| `moonshot` | `https://api.moonshot.cn/v1` | — | — | — |
| `mimo` | `https://api.xiaomimimo.com/v1` | — | — | — |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | — | — | — |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | — | — | — |
| `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` | — | — | — |
| `minimax` | `https://api.minimax.io/v1` | — | — | — |

## 通用 catch-all

| 适配器 `type` | 协议 | 默认 Base URL | 余额 | 导入 | OAuth 刷新 |
| --- | --- | --- | :---: | :---: | :---: |
| `generic` | OpenAI Chat | （无预设，需手填 Base URL） | — | — | — |

::: tip generic
任何未预设、但兼容 OpenAI `/v1/chat/completions` 的上游都可用 `generic` 接入，
手动填写 Base URL 与模型列表即可。
:::
