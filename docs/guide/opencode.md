# OpenCode 插件

VoidSwitch 内置了一个一流的 [OpenCode](https://opencode.ai) 供应商插件。
它将 VoidSwitch 注册为供应商，并在线路层面复现完整的 Claude Code 请求功能
（effort levels、fast mode、adaptive thinking、task budgets、1M context）。

插件有**两个版本**，对应 OpenCode 的两代插件 API：

| 插件        | 适用 OpenCode | SDK                 | 入口         |
| ----------- | ------------- | ------------------- | ------------ |
| **V2**（推荐） | 2.x           | `@opencode/plugin`  | `setup(ctx)` |
| V1（旧版）  | 1.x           | `@opencode-ai/plugin` | `server()` |

两者**不可互换**：V1 插件代码无法在 OpenCode 2 中运行，反之亦然。若你不确定版本，
先运行 `opencode --version`。

## 一行安装（V2，推荐）

网关提供一个自包含的安装程序。针对你的 VoidSwitch 主机运行它 ——
它会将插件放进 OpenCode 会自动加载的目录：

::: code-group

```bash [macOS / Linux]
curl -fsSL https://voidswitch.siiway.org/install.sh | sh
```

```powershell [Windows]
irm https://voidswitch.siiway.org/install.ps1 | iex
```

:::

V2 插件是**目录插件**，会被自动发现（三个 part 一起装进
`~/.config/opencode/plugins/voidswitch/`：`index.ts`、`rpc.ts`、`tui.ts`），**无需**编辑
`opencode.json`。安装后重启 `opencode` 即可。Ctrl+P 面板命令（同步模型、切换网关）要求
OpenCode **≥ 2.3**；更旧的 2.x 上插件仍可用，只是没有面板命令。

安装程序会把**你获取它的主机**写进插件的默认网关（安装时烤入），因此自托管部署装完即指向
自己的网关，公共实例装完即指向公共实例。覆盖优先级：插件选项或 `VOIDSWITCH_URL` 环境变量 >
面板/`/connect` 里设置过的网关（持久化在 `opencode.json`）> 安装时烤入的网关 > 公共实例
`https://voidswitch.siiway.org`。因此若曾用面板的 **VoidSwitch: set gateway URL** 设置过地址，
重装换主机前需先在面板里重置（清空提交即可），否则烤入值会被持久化值压制。重装换主机时也可用
`VOIDSWITCH_GATEWAY=https://… curl -fsSL …/install.sh | sh` 直接指定。

## 一行安装（V1，旧版）

尚未升级到 OpenCode 2 时，用 `?v=1` 安装旧版插件：

::: code-group

```bash [macOS / Linux]
curl -fsSL "https://voidswitch.siiway.org/install.sh?v=1" | sh
```

```powershell [Windows]
irm "https://voidswitch.siiway.org/install.ps1?v=1" | iex
```

:::

V1 插件**不会**被自动发现，需要先把它登记到 `opencode.json` 中：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["/home/you/.config/opencode/plugins/voidswitch.plugin.ts"]
}
```

安装脚本会打印插件的绝对路径。写好后重启 `opencode` 即可加载。

## 连接令牌

若安装时没有嵌入令牌：

1. 运行 `opencode`。
2. 使用 `/connect` 并选择 **VoidSwitch**。
3. 粘贴 [Void-Token](/guide/api-keys)（`vs-…`）。

## 手动安装（不用脚本）

无法运行安装脚本时，可以在 [**我的令牌**](/guide/api-keys) 页面的 OpenCode 连接指南中展开
**手动设置**，其中提供：

1. 一份完整的 `opencode.json`（已注册 VoidSwitch 供应商并列出全部可用模型）。
2. **手动安装插件**指南 —— 这一步让手动配置的用户也能获得完整的插件功能
   （effort、fast mode、adaptive thinking、1M context）。它与一行脚本做的事一样，从网关
   **实时获取**插件源码（始终与当前服务器一致），把三个 part 分别保存为
   `plugins/voidswitch/` 目录下的 `index.ts`、`rpc.ts`、`tui.ts`。

### V2 插件（推荐）

V2 的本地插件路径必须是一个**目录**，指向单个文件会被跳过并在日志中告警。最小可用配置：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [
    { "package": "/home/you/.config/opencode/plugins/voidswitch", "options": { "url": "https://your-voidswitch-host" } }
  ]
}
```

### V1 插件（旧版）

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["/home/you/.config/opencode/plugins/voidswitch.plugin.ts"]
}
```

### Nix 安装

如果你用 Nix 管理 OpenCode 配置，可以把插件文件声明到用户配置目录，再在配置中引用该路径。
下面示例使用 Home Manager，V2 与 V1 的差别只在配置字段名（`plugins` / `plugin`）：

```nix
{ config, pkgs, ... }:

{
  xdg.configFile."opencode/plugins/voidswitch/index.ts".source = pkgs.fetchurl {
    url = "https://voidswitch.siiway.org/opencode/voidswitch.ts";
    sha256 = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };

  xdg.configFile."opencode/opencode.json".text = ''
    {
      "plugins": [
        { "package": "${config.xdg.configHome}/opencode/plugins/voidswitch" }
      ]
    }
  '';
}
```

首次写入时先用临时 hash 构建一次，让 Nix 输出实际 hash 后替换 `sha256`。

## 刷新模型列表

插件读取平台模型目录。按 `Ctrl+P` 打开命令面板，运行 **VoidSwitch: sync models**（
`POST /v1/models/sync`）即可把模型列表与你**当前可调用**的模型对齐 —— **所有成员**都能用，
无需管理员权限，只返回你有权访问且未被隐藏的模型，并同步推荐的 `model` / `small_model`
顶层选择器。面板命令经由插件 RPC 在后台完成，**不会向会话写入任何消息**（旧版的
`/sync-models` 斜杠命令已移除，因为斜杠命令必然产生一条会话消息）。

不走面板时也有两条路：运行 `opencode auth login` 选择 VoidSwitch 重新粘贴令牌（成功后自动
刷新），或在面板中运行 **VoidSwitch: set gateway URL** 更换网关地址（自动刷新并迁移模型
缓存）。

这与**从供应商同步**是两件事：后者（**模型**页面上的按钮）会重塑*共享*目录，为供应商
新服务的模型注册目录行，属于**仅限管理人员**的操作。面板的模型刷新不会改动共享目录。

## 判断请求来自哪个插件

日志详情中的 **OpenCode VS 插件** 字段会显示 `v2` / `v1` / `—`，分别表示请求经过 V2 插件、
经过 V1 插件、以及未使用插件。这有助于在升级期间确认客户端实际加载了哪一代插件。

## 安装程序的来源

`/install.sh` 根据 `?v` 参数（或 `VOIDSWITCH_PLUGIN_V` 环境变量）选择插件版本，缺省为 V2。
V2 插件源码由 `/opencode/voidswitch.ts`（server）、`/opencode/voidswitch-rpc.ts`（RPC 契约）与
`/opencode/voidswitch-tui.ts`（TUI part）提供，安装脚本把三者装进
`~/.config/opencode/plugins/voidswitch/`；V1 由 `/opencode/voidswitch-v1.ts` 提供（烤入目标为
`voidswitch.plugin.ts`）。因此自托管网关完全自包含，始终分发与自身版本匹配的源码。若目录旁留有
旧版单文件 `voidswitch.ts`，安装脚本会把它改名为 `voidswitch.ts.bak` —— 否则 server part 会被
加载两次。

安装脚本用你访问的主机作为网关（代理头优先，其次请求 Host，回退到服务器配置的 BaseURL），
下载后把插件源码中的安装时网关标记行改写为该主机（V1 与 V2 均烤入）—— 同一份插件源码，从
哪个主机装，默认就连哪个主机；运行时仍可用面板的 **VoidSwitch: set gateway URL** 或
`VOIDSWITCH_URL` 环境变量覆盖。
