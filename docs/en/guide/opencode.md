# OpenCode plugin

VoidSwitch ships with a first-class [OpenCode](https://opencode.ai) provider plugin.
It registers VoidSwitch as a provider and reproduces the full Claude Code request capabilities at the wire level
(effort levels, fast mode, adaptive thinking, task budgets, 1M context).

## One-line install

The gateway provides a self-contained installer. Run it against your VoidSwitch host —
it merges the VoidSwitch provider into your `opencode.json`:

::: code-group

```bash [macOS / Linux]
curl -fsSL https://voidswitch.siiway.org/install | bash
```

```powershell [Windows]
irm https://voidswitch.siiway.org/install | iex
```

:::

You can embed your token so that no manual `/connect` step is needed:

```bash
curl -fsSL "https://voidswitch.siiway.org/install?token=vs-your-token" | bash
```

## Connecting a token

If you did not embed a token during install:

1. Run `opencode`.
2. Use `/connect` and select **VoidSwitch**.
3. Paste your [Void-Token](/en/guide/api-keys) (`vs-…`).

## Manual install (without the script)

When you cannot run the install script, expand **Manual setup** in the OpenCode connection guide on the
[**My Tokens**](/en/guide/api-keys) page, which provides:

1. A complete `opencode.json` (with the VoidSwitch provider registered and all available models listed) to paste directly into
   `~/.config/opencode/opencode.json`.
2. A **manually install the plugin** guide — this step gives manually configured users the full plugin capabilities as well
   (effort, fast mode, adaptive thinking, 1M context). It does the same thing as the one-line script: it **fetches the plugin source in real time** from the gateway
   (`/opencode/voidswitch.ts`, always in sync with the current server) and saves it to the OpenCode config directory:

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

The command prints the absolute path to the plugin. Add it to the `plugin` array at the top level of `opencode.json`, e.g.
`"plugin": ["/home/you/.config/opencode/voidswitch.plugin.ts"]`, then restart `opencode` to load it.
(The plugin file lives in the same directory as the config, `~/.config/opencode/`, which is exactly where the install script writes it.)

### Nix install

If you manage your OpenCode config with Nix, you can declare the plugin file into your user config directory and then reference that path in `opencode.json`.
The example below uses Home Manager to write to the same location as the install script:

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

On the first write, build once with a placeholder hash and let Nix report the actual hash, then replace `sha256` with it. If you already have
`opencode.json`, just merge the plugin path into the top-level `plugin` array.

## Refreshing the model list

The plugin reads the platform model catalog. Running `/sync-models` (`POST /v1/models/sync`) makes the plugin align its model list
with the models you **can currently call** — available to **all members**, no admin privileges required; it only returns models you have access to and that are
not hidden, and it also syncs the recommended `model` / `small_model` top-level selectors.

This is distinct from **Sync from providers**: the latter (a button on the **Models** page) reshapes the *shared* catalog, registering catalog rows for models
newly served by providers, and is a **staff-only** action. A member's `/sync-models` does not touch the shared catalog.

## Where the installer comes from

`/install` performs content negotiation based on your shell (PowerShell → `.ps1`, otherwise bash).
Force a specific one via `/install.sh` or `/install.ps1`. The plugin source itself is served from `/opencode/voidswitch.ts`,
so a self-hosted gateway is fully self-contained.
