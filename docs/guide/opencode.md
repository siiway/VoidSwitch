# OpenCode plugin

VoidSwitch ships a first-class [OpenCode](https://opencode.ai) provider plugin.
It registers VoidSwitch as a provider and reproduces the full Claude Code request
surface (effort levels, fast mode, adaptive thinking, task budgets, 1M context)
at the wire level.

## One-line install

The gateway serves a self-contained installer. Run it against your VoidSwitch
host — it merges a VoidSwitch provider into your `opencode.json`:

::: code-group

```bash [macOS / Linux]
curl -fsSL https://your-voidswitch-host/install | bash
```

```powershell [Windows]
irm https://your-voidswitch-host/install | iex
```

:::

You can embed your token so no manual `/connect` step is needed:

```bash
curl -fsSL "https://your-voidswitch-host/install?token=vs-your-token" | bash
```

## Connect a token

If you didn't embed a token during install:

1. Run `opencode`.
2. Use `/connect` and choose **VoidSwitch**.
3. Paste a [Void-Token](/guide/api-keys) (`vs-…`).

## Refresh the model list

The plugin reads the platform model catalog. New models served by providers
appear automatically. **Registering** them in the catalog (the sync step) is
staff-only: a staff member runs the OpenCode `/sync-models` command or uses the
**Models** page. Members don't need to sync.

## Where the installer comes from

`/install` content-negotiates on your shell (PowerShell → `.ps1`, otherwise
bash). Force one with `/install.sh` or `/install.ps1`. The plugin source itself is
served from `/opencode/voidswitch.ts`, so a self-hosted gateway is fully
self-contained.
