# OpenCode plugin

VoidSwitch ships with a first-class [OpenCode](https://opencode.ai) provider plugin.
It registers VoidSwitch as a provider and reproduces the full Claude Code request capabilities at the wire level
(effort levels, fast mode, adaptive thinking, task budgets, 1M context).

The plugin comes in **two generations**, matching OpenCode's two plugin APIs:

| Plugin            | OpenCode | SDK                   | Entrypoint   |
| ----------------- | -------- | --------------------- | ------------ |
| **V2** (recommended) | 2.x      | `@opencode/plugin`    | `setup(ctx)` |
| V1 (legacy)       | 1.x      | `@opencode-ai/plugin` | `server()`   |

They are **not interchangeable**: a V1 plugin does not run in OpenCode 2, and vice versa. If you are unsure which you
have, run `opencode --version` first.

## One-line install (V2, recommended)

The gateway provides a self-contained installer. Run it against your VoidSwitch host — it drops the plugin where
OpenCode picks it up automatically:

::: code-group

```bash [macOS / Linux]
curl -fsSL https://voidswitch.siiway.org/install.sh | sh
```

```powershell [Windows]
irm https://voidswitch.siiway.org/install.ps1 | iex
```

:::

The V2 plugin is discovered automatically (it lives in `~/.config/opencode/plugins/`), so you do **not** need to edit
`opencode.json`. Restart `opencode` afterwards.

## One-line install (V1, legacy)

If you have not upgraded to OpenCode 2 yet, install the legacy plugin with `?v=1`:

::: code-group

```bash [macOS / Linux]
curl -fsSL "https://voidswitch.siiway.org/install.sh?v=1" | sh
```

```powershell [Windows]
irm "https://voidswitch.siiway.org/install.ps1?v=1" | iex
```

:::

The V1 plugin is **not** auto-discovered, so register it in `opencode.json` first:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["/home/you/.config/opencode/plugins/voidswitch.plugin.ts"]
}
```

The installer prints the plugin's absolute path. Restart `opencode` once it is saved.

## Connecting a token

If you did not embed a token during install:

1. Run `opencode`.
2. Use `/connect` and select **VoidSwitch**.
3. Paste your [Void-Token](/en/guide/api-keys) (`vs-…`).

## Manual install (without the script)

When you cannot run the install script, expand **Manual setup** in the OpenCode connection guide on the
[**My Tokens**](/en/guide/api-keys) page, which provides:

1. A complete `opencode.json` (with the VoidSwitch provider registered and all available models listed).
2. A **manually install the plugin** guide — this step gives manually configured users the full plugin capabilities as
   well (effort, fast mode, adaptive thinking, 1M context). It does the same thing as the one-line script: it **fetches
   the plugin source in real time** from the gateway (always in sync with the current server) and saves it to the
   OpenCode config directory.

### V2 plugin (recommended)

A V2 local plugin path must name a **directory**; a path to a single file is skipped with a warning in the log. Minimal
working config:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [
    { "package": "/home/you/.config/opencode/plugins/voidswitch", "options": { "url": "https://your-voidswitch-host" } }
  ]
}
```

### V1 plugin (legacy)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["/home/you/.config/opencode/plugins/voidswitch.plugin.ts"]
}
```

### Nix install

If you manage your OpenCode config with Nix, you can declare the plugin file into your user config directory and then
reference that path. The example below uses Home Manager; V2 and V1 differ only in the config key (`plugins` / `plugin`):

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

On the first write, build once with a placeholder hash and let Nix report the actual hash, then replace `sha256` with it.

## Refreshing the model list

The plugin reads the platform model catalog. Running `/sync-models` (`POST /v1/models/sync`) makes the plugin align its
model list with the models you **can currently call** — available to **all members**, no admin privileges required; it
only returns models you have access to and that are not hidden, and it also syncs the recommended `model` /
`small_model` top-level selectors.

This is distinct from **Sync from providers**: the latter (a button on the **Models** page) reshapes the *shared*
catalog, registering catalog rows for models newly served by providers, and is a **staff-only** action. A member's
`/sync-models` does not touch the shared catalog.

## Telling the plugin generations apart

The **OpenCode VS Plugin** field in the log detail shows `v2`, `v1`, or `—`, meaning the request went through the V2
plugin, the V1 plugin, or no plugin at all. This is handy during an upgrade to confirm which generation a client
actually loaded.

## Where the installer comes from

`/install.sh` picks the plugin generation from the `?v` parameter (or the `VOIDSWITCH_PLUGIN_V` environment variable),
defaulting to V2. The plugin source itself is served from `/opencode/voidswitch.ts` (V2) and
`/opencode/voidswitch-v1.ts` (V1), so a self-hosted gateway is fully self-contained and always hands out the source
matching its own release.
