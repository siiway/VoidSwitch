# OpenCode 插件

VoidSwitch 内置了一个一流的 [OpenCode](https://opencode.ai) 供应商插件。
它将 VoidSwitch 注册为供应商，并在线路层面复现完整的 Claude Code 请求功能
（effort levels、fast mode、adaptive thinking、task budgets、1M context）。

## 一行安装

网关提供一个自包含的安装程序。针对你的 VoidSwitch 主机运行它 —
它会将 VoidSwitch 供应商合并到你的 `opencode.json` 中：

::: code-group

```bash [macOS / Linux]
curl -fsSL https://voidswitch.siiway.org/install | bash
```

```powershell [Windows]
irm https://voidswitch.siiway.org/install | iex
```

:::

你可以嵌入你的令牌，这样就不需要手动 `/connect` 步骤：

```bash
curl -fsSL "https://voidswitch.siiway.org/install?token=vs-your-token" | bash
```

## 连接令牌

如果在安装时没有嵌入令牌：

1. 运行 `opencode`。
2. 使用 `/connect` 并选择 **VoidSwitch**。
3. 粘贴 [Void-Token](/guide/api-keys)（`vs-…`）。

## 刷新模型列表

插件读取平台模型目录。供应商新服务的模型会自动出现。在目录中**注册**它们（同步步骤）是
仅限管理人员的操作：管理人员运行 OpenCode `/sync-models` 命令或使用**模型**页面。
成员无需同步。

## 安装程序的来源

`/install` 根据你的 shell 进行内容协商（PowerShell → `.ps1`，否则 bash）。
通过 `/install.sh` 或 `/install.ps1` 强制指定。插件源码本身从 `/opencode/voidswitch.ts` 提供，
因此自托管网关完全自包含。