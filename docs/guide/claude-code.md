# 与 Claude Code 一起使用

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) 使用 Anthropic API，
因此可以直接指向 VoidSwitch。

## 配置

设置 Base URL 和你的 [Void-Token](/guide/api-keys) 作为认证令牌：

```bash
export ANTHROPIC_BASE_URL=https://voidswitch.siiway.org
export ANTHROPIC_AUTH_TOKEN=vs-your-token
```

然后像往常一样运行 Claude Code。请求通过 VoidSwitch 流转，VoidSwitch 将其路由到服务
所请求 Claude 模型的供应商，并处理密钥/代理故障转移。

## 选择模型

使用 VoidSwitch 发布的模型 ID（参见[模型](/guide/models)或调用 `/v1/models`）。
如果你的平台将 Claude 模型映射到其他上游，映射是透明的 — 只需使用发布的 ID 即可。

## 注意事项

- 流式传输、工具调用和令牌用量报告均端到端支持。
- 如果你更倾向于使用 **OpenCode**，请安装专用插件 — 它在线路层面添加了完整的 Claude Code
  请求功能（effort levels、fast mode、thinking）。参见 [OpenCode 插件](/guide/opencode)。