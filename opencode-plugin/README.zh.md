# opencode-voidswitch

[VoidSwitch](../) 的 [OpenCode](https://opencode.ai) 深度集成插件。将 VoidSwitch
注册为一等提供者，完整复刻 **Claude Code 的请求表面**，让 OpenCode 驱动 VoidSwitch
`claude-code` 上游时行为与真实 CLI 一致，**含全套 effort**。

| 能力                   | 传输方式                                                     |
| ---------------------- | ------------------------------------------------------------ |
| **认证**               | 粘贴 `vs-…` 令牌（OpenCode 存储，以 `x-api-key` 发送）       |
| **模型列表**           | 从 `GET <网关>/v1/models` 实时拉取                           |
| **Effort**             | `output_config.effort` ∈ `low · medium · high · xhigh · max` |
| **ultracode**          | 选择器变体 → `xhigh` effort                                  |
| **极速模式** (`/fast`) | 顶层字段 `speed: "fast"`                                     |
| **自适应思考**         | `thinking: { type: "adaptive" }`（4.6+ 模型）                |
| **思考内容展示**       | `thinking.display: "summarized"`（Opus 4.7/4.8）             |
| **任务预算**           | `output_config.task_budget` — 累积智能体循环预算             |
| **上下文管理**         | `context_management` — 服务端长会话编辑                      |
| **1M 上下文**          | `context-1m-2025-08-07` — 大提示词自动启用                   |
| **Beta 标记**          | 自动合并 `effort-`、`fast-mode-`、`interleaved-thinking-` 等 |

所有线路细节（`output_config.effort` 枚举、顶层 `speed` 字段、beta 令牌、逐模型
effort 门控）均直接取自 Claude Code CLI 包，VoidSwitch 以 Claude Code 身份将请求
转发至 Anthropic。

## 工作原理

OpenCode 配置为向 VoidSwitch 发送 **Anthropic** 协议
（`@ai-sdk/anthropic` → `<网关>/v1/messages`）。`effort` / `speed` 是
`/v1/messages` 原生字段，AI SDK 不会主动发送，因此插件在认证 `loader` 的自定义
`fetch` 中注入——这是唯一能接触完整序列化请求体的位置。每次选择的**模型变体**通过
私有 `x-voidswitch-*` 头传递给 fetch（在 `chat.headers` 中设置，在请求发出前清除）。

```
OpenCode 选择器（变体）
   └─ chat.headers  → x-voidswitch-effort / -speed / -thinking
        └─ auth.loader fetch  → 重写请求体：output_config.effort, speed, thinking
                              → 合并 anthropic-beta
             └─ VoidSwitch /v1/messages  → Anthropic（以 Claude Code 身份）
```

## 安装

插件自包含，会自动注册提供者，只需添加插件并指向网关即可。

`opencode.json`（或 `~/.config/opencode/opencode.json`）：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    ["opencode-voidswitch", { "url": "https://你的-voidswitch-地址", "effort": "high" }]
  ]
}
```

本地开发时直接指向插件目录：

```jsonc
{ "plugin": [["./opencode-plugin", { "url": "http://localhost:8080" }]] }
```

### Nix Flakes

仓库 flake 提供了 `opencode-voidswitch` 包。将其添加为 flake 输入后引用 store 路径：

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    voidswitch.url = "github:siiway/voidswitch";
  };

  outputs = { self, nixpkgs, voidswitch, ... }: {
    # 引用插件目录：
    #   voidswitch.packages.${system}.opencode-voidswitch
  };
}
```

在 `opencode.json` 中指向 Nix store 路径：

```jsonc
{
  "plugin": [
    ["/nix/store/...-opencode-voidswitch-0.1.0", { "url": "https://你的-voidswitch-地址" }]
  ]
}
```

或在构建时动态解析路径：

```jsonc
{
  "plugin": [
    ["${voidswitch.packages.${system}.opencode-voidswitch}", { "url": "https://你的-voidswitch-地址" }]
  ]
}
```

> 包仅包含 TypeScript 源码，无需构建步骤。`@opencode-ai/plugin` 为 peer 依赖，
> 由 OpenCode 运行时解析。

安装后认证一次：

```
opencode auth login        # 选择 "VoidSwitch" → 粘贴 vs-… 令牌
```

网关地址也可通过 `$VOIDSWITCH_URL` 环境变量设置（默认 `http://localhost:8080`）。

## 插件选项

| 选项                | 类型                                                | 默认值                                      | 说明                                                              |
| ------------------- | --------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------- |
| `url`               | string                                              | `$VOIDSWITCH_URL` / `http://localhost:8080` | 网关地址                                                          |
| `effort`            | `low\|medium\|high\|xhigh\|max\|ultracode\|default` | `default`                                   | 未选择变体时的默认 effort（`default` = 让模型决定）               |
| `thinking`          | boolean                                             | `true`                                      | 在 4.6+ 模型上启用自适应扩展思考                                  |
| `thinkingDisplay`   | `summarized\|omitted`                               | `summarized`                                | Opus 4.7/4.8 展示思考内容                                         |
| `fast`              | boolean                                             | `false`                                     | 强制每次请求启用极速模式                                          |
| `context1m`         | `boolean\|"auto"`                                   | `auto`                                      | 1M 上下文：`true` 始终启用，`false` 禁用，`auto` 大提示词自动启用 |
| `contextManagement` | boolean                                             | `false`                                     | 服务端上下文管理（自动清理长会话中的旧思考块）                    |
| `taskBudget`        | number                                              | —                                           | 累计智能体循环令牌预算（最小 20000）                              |

## 选择每次请求的 effort

每个 Claude 模型在选择器中以**变体**形式出现——选择一个即可设置本次的 effort/模式：

```
claude-opus-4-8            ← 默认 effort
claude-opus-4-8:low
claude-opus-4-8:medium
claude-opus-4-8:high
claude-opus-4-8:xhigh      ← 仅 Opus 4.8/4.7
claude-opus-4-8:max        ← 仅 Opus 系列
claude-opus-4-8:ultracode  ← = xhigh effort
claude-opus-4-8:fast       ← speed: "fast"
```

不支持的级别会被**自动降级**——例如在 Sonnet 上选择 `xhigh` 或 `max` 会回退到
`high`；只有 Opus 4.8/4.7 支持 `xhigh`/`ultracode`。

## DeepSeek 及其他 OpenAI 协议推理模型

Claude（和 MiMo）使用 **Anthropic** 协议。而 DeepSeek 由 VoidSwitch 以 **OpenAI**
协议提供，其思维链作为 `reasoning_content` 字段传输。OpenCode 仅在
`@ai-sdk/openai-compatible` SDK 上支持该字段回传——在 Anthropic SDK 上会被静默
丢弃，导致上游拒绝下一次工具调用。

解决方法：**将 DeepSeek 模型 id 列在** `voidswitch` 提供者下。插件会自动配置：
为每个模型强制设置 `@ai-sdk/openai-compatible` 覆盖（路由到网关的 OpenAI
`/chat/completions` 端点），同时启用 `reasoning_content` 交错字段——并复用与
Claude 模型**相同的** VoidSwitch 令牌和认证。

```jsonc
{
  "provider": {
    "voidswitch": {
      "models": {
        // Claude / MiMo 无需额外配置，使用 Anthropic 协议。
        // DeepSeek：只需列出 id，插件自动设置 openai-compatible 覆盖
        // + reasoning_content 回传。
        "deepseek-v4-flash-lkd": { "name": "DeepSeek V4 Flash" },
        "deepseek-v4-pro-lkd":   { "name": "DeepSeek V4 Pro" }
      }
    }
  }
}
```

任何匹配 `deepseek` 的模型 id 都会自动配置；其他模型保持 Anthropic 协议。
（Effort/极速/思考变体仅适用于 Claude，不会应用到 DeepSeek。）

## 斜杠命令

插件还注册了 Claude Code 风格的斜杠命令，可设置整个会话的 effort/模式：

| 命令                                                            | 效果                                             |
| --------------------------------------------------------------- | ------------------------------------------------ |
| `/effort high`（或 `low\|medium\|xhigh\|max\|ultracode\|auto`） | 设置会话 effort                                  |
| `/effort xhigh <提示词>`                                        | 设置 effort **并**直接运行提示词                 |
| `/effort auto`                                                  | 清除覆盖值（由模型决定）                         |
| `/fast` · `/fast off`                                           | 启用/关闭极速模式                                |
| `/ultracode`                                                    | 设置 xhigh effort                                |
| `/sync-models`                                                  | 从网关刷新可用模型列表（然后重新打开模型选择器） |

优先级：每次选择的模型变体（如 `…:low`）> 会话命令 > `effort` 插件选项。

> 注意：OpenCode 没有"纯客户端"命令——每个命令都会消耗一次模型调用。因此单独
> 的 `/effort high` 会消耗一次廉价确认调用；`/effort high <提示词>` 则将这次
> 调用花在实际工作上。如需零开销切换，使用模型变体选择器（`/models`）代替。

## Claude Code 特性对比

**在线路层面复刻**（通过 VoidSwitch → Anthropic）：

- Effort 级别 `low … max` 和 `ultracode`（→ `output_config.effort`）
- 极速模式 `/fast`（→ 顶层 `speed`）
- 自适应扩展思考（4.6+），Opus 4.7/4.8 展示摘要思考内容
- 任务预算——累计智能体循环预算（→ `output_config.task_budget`）
- 上下文管理——服务端长会话清理旧思考块（→ `context_management`）
- 1M 上下文——大提示词自动启用（→ `context-1m` beta）
- 合并 `anthropic-beta` 令牌
- 启用思考时强制 `temperature = 1`（Anthropic 要求）

**仅客户端/运行环境层（无 `/v1/messages` 表示，无法从提供者插件复刻）：**

- **ultracode 的动态工作流编排**——effort 部分（`xhigh`）已复刻；常驻工作流编排
  属于 CLI 端行为
- **`ultrathink`**——Claude Code 在提示词文本中检测并注入"加强思考"提醒的魔法
  关键词，非请求字段

## 开发

```
bun install
bun run typecheck
```
