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

The V2 plugin is a **directory plugin** discovered automatically (all three parts land in
`~/.config/opencode/plugins/voidswitch/`: `index.ts`, `rpc.ts`, `tui.ts`), so you do **not** need to edit
`opencode.json`. Restart `opencode` afterwards. The `Ctrl+P` palette commands (sync models, set gateway, configure
MCP server) require OpenCode **≥ 2.3**; on older 2.x the plugin still works, just without the palette commands.

The installer bakes **the host you fetched it from** into the plugin's default gateway, so a self-hosted install
points at its own gateway and the public instance at the public one. Precedence: plugin option or the
`VOIDSWITCH_URL` environment variable > a gateway previously set from the palette or `/connect` (persisted in
`opencode.json`) > the baked gateway > the public instance `https://voidswitch.siiway.org`. If you ever set the
gateway from the palette (**VoidSwitch: set gateway URL**), reset it there (submit empty) before reinstalling to a
new host — the persisted value outranks the baked one. To switch hosts on reinstall you can also pass it
explicitly: `VOIDSWITCH_GATEWAY=https://… curl -fsSL …/install.sh | sh`.

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

1. A complete `opencode.json` (with the VoidSwitch provider registered and all available models listed). It uses the
   OpenCode **1.x** singular `provider` format — on OpenCode 2.x use the one-line installer instead, so the plugin
   registers the provider itself.
2. A **manually install the plugin** guide — this step gives manually configured users the full plugin capabilities as
   well (effort, fast mode, adaptive thinking, 1M context). It does the same thing as the one-line script: it **fetches
   the plugin source in real time** from the gateway (always in sync with the current server) and saves the three parts
   as `index.ts`, `rpc.ts` and `tui.ts` under the `plugins/voidswitch/` directory.

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

The plugin reads the platform model catalog. Press `Ctrl+P` to open the command palette and run
**VoidSwitch: sync models** (`POST /v1/models/sync`) to align the plugin's model list with the models you
**can currently call** — available to **all members**, no admin privileges required; it only returns models you have
access to and that are not hidden, and it also syncs the recommended `model` / `small_model` top-level selectors. The
palette command runs through the plugin's RPC in the background and **never writes a message to the session** (the old
`/sync-models` slash command was removed, because slash commands always produce a session message).

Two paths exist outside the palette: run `opencode auth login`, pick VoidSwitch and paste the token again (the catalog
refreshes automatically), or run **VoidSwitch: set gateway URL** from the palette to switch gateways (it refreshes and
migrates the model cache automatically).

This is distinct from **Sync from providers**: the latter (a button on the **Models** page) reshapes the *shared*
catalog, registering catalog rows for models newly served by providers, and is a **staff-only** action. The palette
refresh does not touch the shared catalog.

## Configuring the management MCP server

The plugin can also wire the gateway's **management MCP** (`/api/v1/mcp`) into OpenCode, so the agent can call
platform API tools directly — models, providers, nodes, users, request logs, audit, stats and settings.

1. In the dashboard sidebar, open [Platform API keys](/en/admin/platform-api-keys) → create a key with the scopes
   you need, and copy the `vsapi-…` plaintext (shown once).
2. Press `Ctrl+P` → **VoidSwitch: configure mcp server**.
3. Pick **Setup** and paste the key. The plugin first checks it against `/api/v1/whoami`; an invalid, disabled,
   expired or non-staff key is **never saved** — the gateway's own reason is shown verbatim. A key with no
   effective scopes is saved, but the reply warns that it exposes no tools.

The menu always lists four actions; the ones that do not apply are greyed out:

| Action | Effect |
| --- | --- |
| Setup / re-configure | Replace the key (empty keeps the stored one); a disabled server stays disabled |
| Enable | Turn the server on (greyed out while it is already enabled) |
| Disable | Turn the server off but keep the key (greyed out while it is already disabled) |
| Uninstall | Remove the server and erase the key stored on this machine |

Worth knowing:

- This wants a **platform API key** (`vsapi-…`), not a gateway token (`vs-…`): the former only reaches the
  management surface, the latter only `/v1`, and neither works in the other's place. Platform API keys are
  **staff-only**.
- **The scopes on the key are the permissions you hand the model.** Start with `read` scopes only, then add
  what you actually need; a write scope means injected context can also make the agent change providers,
  disable users or edit settings. When you no longer need it, Uninstall and revoke the key under
  [Platform API keys](/en/admin/platform-api-keys).
- The URL is never stored separately — the server always follows the current gateway (`<gateway>/api/v1/mcp`).
  Switching gateways from the palette **re-points it automatically** and re-checks the key against the new host;
  if it does not work there, the palette tells you to run setup again.
- The key lives in `$XDG_CONFIG_HOME/opencode/voidswitch-mcp.json` (falling back to
  `~/.config/opencode/voidswitch-mcp.json` when `XDG_CONFIG_HOME` is unset; mode `0600` on POSIX) and is
  **never written into** `opencode.json`; Uninstall deletes it. The key itself stays valid in the dashboard.
- Tools are exposed through **Code Mode** (the V2 default), so dozens of tools are not dumped into the context at
  once.
- The key is visible while you paste it — TUI dialogs have no masked input — so mind screen sharing.
- The palette commands (this one included) require OpenCode **≥ 2.3**; on a build without the second-level menu
  API the palette only offers **VoidSwitch: setup mcp server** and **VoidSwitch: uninstall mcp server**, with no
  enable / disable.

## Telling the plugin generations apart

The **OpenCode VS Plugin** field in the log detail shows `v2`, `v1`, or `—`, meaning the request went through the V2
plugin, the V1 plugin, or no plugin at all. This is handy during an upgrade to confirm which generation a client
actually loaded.

## Where the installer comes from

`/install.sh` picks the plugin generation from the `?v` parameter (or the `VOIDSWITCH_PLUGIN_V` environment variable),
defaulting to V2. The V2 plugin source is served from `/opencode/voidswitch.ts` (server),
`/opencode/voidswitch-rpc.ts` (RPC contract) and `/opencode/voidswitch-tui.ts` (TUI part); the installer drops the
three into `~/.config/opencode/plugins/voidswitch/`. V1 is served from `/opencode/voidswitch-v1.ts` (baked into
`voidswitch.plugin.ts`). A self-hosted gateway is therefore fully self-contained and always hands out the source
matching its own release. If an old single-file `voidswitch.ts` sits next to the directory, the installer renames it
to `voidswitch.ts.bak` — otherwise the server part would load twice.

The script uses the host you visited as the gateway (proxy headers first, then the request Host, falling back to the
server's configured BaseURL) and, after downloading, rewrites the plugin's install-time gateway marker line to that
host (both V1 and V2 bake) — the same source bakes to whichever host it was installed from. The palette's
**VoidSwitch: set gateway URL** command or the `VOIDSWITCH_URL` environment variable still override it at runtime.
