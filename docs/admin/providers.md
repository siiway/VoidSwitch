# 供应商

**供应商**是一个上游 LLM 平台（OpenAI、Anthropic、DeepSeek 以及许多预设）。
**供应商**页面是**仅限管理人员**的。

## 添加供应商

1. 打开**供应商** → **添加供应商**。
2. 选择一个**适配器类型**。预设会填充合理的 Base URL 和默认模型列表；也有通用的
   OpenAI 兼容 catch-all 可用。全部内置适配器及其支持情况见[供应商目录](/admin/provider-catalog)。
3. 设置**名称**、**Base URL** 及其服务的**模型**（每行一个；`*` 匹配任何内容）。
4. 保存，然后加载其[密钥](/admin/keys)。

::: tip OpenAI Responses API
为使用 OpenAI 较新的
[Responses API](https://developers.openai.com/api/reference/resources/responses)
（`POST /v1/responses`）而非 Chat Completions 的上游选择 **`openai-resp`** 适配器。
网关将入站 OpenAI-chat / Anthropic 请求透明地转换为 Responses 格式（并将回复转换回来），
因此调用者无需更改任何内容。
:::

::: tip Grok（console.x.ai 免费模型）
- **`xai`** 适配器对接官方 `api.x.ai` REST API，密钥可以是标准 API Key，
  也可以是 xAI 的 **OAuth 凭证包**（含 `access_token` / `refresh_token`）。
  凭证包会在临近过期、缺少 access token 或收到 401 时，自动用 `refresh_token`
  向 `https://auth.x.ai/oauth2/token`（grok-cli 客户端）换取新的 access token，
  并把轮换后的凭证包回写到密钥。因此从 sub2api 导入的、仅含 `refresh_token`
  的 Grok 账号也能在 `xai` 供应商上直接使用。`api.x.ai` 对**无效密钥**返回的是
  HTTP 400（`Incorrect API key`）或 401（`No credentials`），网关据此把密钥标记为失效；
  而 HTTP **403**（地区/权限/风控等原因）被视为**临时错误**——只做轮换重试、冷却，
  **不会**禁用一个本身可用的密钥。
- **`grok`** 适配器对接 `console.x.ai` 网页后端（参考
  [grok2api](https://github.com/jiujiu532/grok2api)），密钥填**SSO Token**——
  即登录 console.x.ai 后浏览器 `sso` Cookie 的值（可带或不带 `sso=` 前缀）。
  它复用 Responses API 转换，因此入站 OpenAI-chat / Anthropic 请求同样无需改动。

暴露的模型名自带推理强度后缀，例如 `grok-4.3-console` / `-low` / `-medium` /
`-high`、`grok-4.20-multi-agent-console` / `-low` / `-medium` / `-high` / `-xhigh`、
`grok-4.20-0309-console`、`grok-build-console` 等，网关会自动映射到真实 console 模型
并注入推理强度与联网搜索工具。若上游需要 `cf_clearance`，在**额外请求头**里以
`Cookie: cf_clearance=...` 追加即可（会拼接到 SSO Cookie 之后，而非覆盖）。
SSO Token 过期会被识别为密钥失效（401/403），匿名配额耗尽（429）会触发限流冷却。
:::

::: tip Grok Build（OAuth 订阅登录）
`grok-build` 适配器对接 Grok CLI（`grok` 命令行）的订阅后端
`https://cli-chat-proxy.grok.com/v1`，默认模型 `grok-4.5`。它复用 grok-cli 的公共 OAuth
客户端（`b1a00492-…`），凭证会在临近过期时自动用 `refresh_token` 刷新。这是 Grok CLI 的
**订阅额度**，与 `xai`（官方 API Key）、`grok`（console.x.ai 网页后端）相互独立。

**添加密钥（OAuth 登录）：** 新建一个 `grok-build` 供应商后，进入其**密钥**页，
按“Grok Build 订阅登录”卡片操作：

1. 点击**开始登录**，在弹出的浏览器页面用 xAI 账号授权。
2. 授权后浏览器会跳转到 `http://127.0.0.1:56121/callback`——由于网关运行在服务端，
   该地址**无法打开是正常现象**。请从浏览器地址栏**完整复制**这个回调 URL。
3. 把完整 URL 粘贴回**完成登录**输入框并提交，网关会用其中的授权码换取凭证包
   （`access_token` / `refresh_token`）并保存为一条密钥。

与 `xai` 一致，`grok-build` 对无效凭证（HTTP 400 `Incorrect API key` / 401）会标记密钥失效，
而 HTTP **403**（地区/权限/风控）视为**临时错误**——仅轮换重试与冷却，不禁用可用密钥。
:::

::: warning Grok Build 合规与账号风险
`grok-build` 复用了 Grok CLI 的公共 OAuth 客户端与私有 `cli-chat-proxy` 端点，属于对官方
客户端的**逆向复用**，可能违反 xAI 服务条款，并存在账号被限制/封禁的风险。请自行评估后使用，
并优先考虑官方 `xai` API Key。
:::

## 关键设置

- **优先级 / 权重** — 优先级越低越优先；权重在同等优先级的供应商之间分配负载。
- **模型映射 / 路由** — 将入站模型 ID 重映射到上游 ID，可选地固定到特定密钥**池**
  （例如将 `-lkd` 别名路由到"泄露"密钥上）。
- **密钥选择** — 如何为每个请求选择密钥：轮询、随机、故障转移或按会话固定模式。
  所有模式都会故障转移到其余密钥。
- **出口代理** — 所有活跃代理、仅直连或选定的代理集。参见[代理](/admin/proxies)。
- **限流冷却** — 当上游未发送 `Retry-After` 时，被 429 的密钥在重试前等待的时间。
- **200 OK + 0 Token 自动重试** — 针对上游不稳定的情况：当上游返回 **200 但 Token 数为 0**
  （或流式响应在产生任何真实内容前就结束）时，将其视为临时故障，自动通过故障转移机制重试
  （下一个密钥 / 路由 / 供应商），空响应**永不**下发。流式请求会先缓冲上游流直到出现**第一个真实内容**
  才转发给客户端，因此空响应能在连接内被当场重试；正常生成不受影响（内容一到即实时转发）。
  全部尝试仍为空时返回上游错误。
- **额外请求头** — 自定义认证请求头。这些可能包含机密信息，因此被视为敏感信息，
  在审计记录中仅限所有者查看。

## 余额与健康

支持余额查询的适配器供应商会显示**余额**列和"刷新余额"操作。
后台探测会快速淘汰空余额密钥，重新扫描会重新启用已充值的密钥。

## Reveal 查找（仅限所有者）

供应商页面右上角的 reveal 入口可以输入一个密钥，并在供应商密钥、Void-Token 或全部范围内查找匹配项。
供应商密钥匹配时会显示所属供应商、第几个密钥、备注、池和添加者。该操作会写入审计记录。

## 删除

删除供应商（及其所有密钥）是**仅限所有者**的操作。

::: tip 成员看不到此页面
供应商对成员完全隐藏，供应商/密钥 API 会拒绝非管理人员请求。
:::
