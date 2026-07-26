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

## 手动安装（不用脚本）

无法运行安装脚本时，可以在 [**我的令牌**](/guide/api-keys) 页面的 OpenCode 连接指南中展开
**手动设置**，其中提供：

1. 一份完整的 `opencode.json`（已注册 VoidSwitch 供应商并列出全部可用模型），直接粘贴到
   `~/.config/opencode/opencode.json`。
2. **手动安装插件**指南 —— 这一步让手动配置的用户也能获得完整的插件功能
   （effort、fast mode、adaptive thinking、1M context）。它与一行脚本做的事一样，从网关**实时获取**
   插件源码（`/opencode/voidswitch.ts`，始终与当前服务器一致），保存到 OpenCode 配置目录：

::: code-group

```bash [macOS / Linux]
mkdir -p ~/.config/opencode
curl -fsSL https://voidswitch.siiway.org/opencode/voidswitch.ts -o ~/.config/opencode/voidswitch.plugin.ts
echo "plugin: $HOME/.config/opencode/voidswitch.plugin.ts"
```

```powershell [Windows]
New-Item -ItemType Directory -Force -Path "$HOME\.config\opencode" | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri "https://voidswitch.siiway.org/opencode/voidswitch.ts" -OutFile "$HOME\.config\opencode\voidswitch.plugin.ts"
Write-Host "plugin: $HOME\.config\opencode\voidswitch.plugin.ts"
```

:::

命令会打印插件的绝对路径。把它加入到 `opencode.json` 顶层的 `plugin` 数组，例如
`"plugin": ["/home/you/.config/opencode/voidswitch.plugin.ts"]`，再重启 `opencode` 即可加载。
（插件文件与配置放在同一目录 `~/.config/opencode/`，与安装脚本写入的位置一致。）

### Nix 安装

如果你用 Nix 管理 OpenCode 配置，可以把插件文件声明到用户配置目录，再在 `opencode.json` 中引用该路径。
下面示例使用 Home Manager 写入与安装脚本相同的位置：

```nix
{ config, pkgs, ... }:

{
  xdg.configFile."opencode/voidswitch.plugin.ts".source = pkgs.fetchurl {
    url = "https://voidswitch.siiway.org/opencode/voidswitch.ts";
    sha256 = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };

  xdg.configFile."opencode/opencode.json".text = ''
    {
      "plugin": ["${config.xdg.configHome}/opencode/voidswitch.plugin.ts"]
    }
  '';
}
```

首次写入时先用临时 hash 构建一次，让 Nix 输出实际 hash 后替换 `sha256`。如果你已经有
`opencode.json`，只需要把插件路径合并到顶层 `plugin` 数组中。

## 刷新模型列表

插件读取平台模型目录。运行 `/sync-models`（`POST /v1/models/sync`）可让插件把模型列表
与你**当前可调用**的模型对齐 —— **所有成员**都能用，无需管理员权限，只会返回你有权访问且
未被隐藏的模型，并同步推荐的 `model` / `small_model` 顶层选择器。

这与**从供应商同步**是两件事：后者（**模型**页面上的按钮）会重塑*共享*目录，为供应商
新服务的模型注册目录行，属于**仅限管理人员**的操作。成员的 `/sync-models` 不会改动共享目录。

## 安装程序的来源

`/install` 根据你的 shell 进行内容协商（PowerShell → `.ps1`，否则 bash）。
通过 `/install.sh` 或 `/install.ps1` 强制指定。插件源码本身从 `/opencode/voidswitch.ts` 提供，
因此自托管网关完全自包含。
