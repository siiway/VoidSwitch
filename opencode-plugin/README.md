# opencode-voidswitch

Deep [VoidSwitch](../../) integration for [OpenCode](https://opencode.ai) **2.x**.
Registers VoidSwitch as a first-class provider and reproduces the **full Claude Code
request surface** end-to-end — so OpenCode driving a VoidSwitch `claude-code`
upstream behaves like the real CLI, **efforts and all**.

> **OpenCode 1.x?** Use [`opencode-plugin-v1`](../opencode-plugin-v1/) instead. That
> generation targets `@opencode-ai/plugin` and the V1 `server()` entrypoint. This
> package targets `@opencode/plugin` and the V2 `setup(ctx)` entrypoint, and the two
> are not interchangeable.

| Capability              | How it reaches the wire                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------ |
| **Auth**                | Paste a `vs-…` token through the integration key method (`/connect`)                             |
| **Management MCP**      | The gateway's `/api/v1/mcp` registered from a `vsapi-…` platform API key (palette-managed)       |
| **Models**              | Pulled live from `GET <gateway>/v1/models`                                                       |
| **Effort**              | `output_config.effort` ∈ `low · medium · high · xhigh · max`                                     |
| **ultracode**           | Picker variant → `xhigh` effort                                                                  |
| **Fast mode** (`/fast`) | Top-level `speed: "fast"`                                                                        |
| **Adaptive thinking**   | `thinking: { type: "adaptive" }` on 4.6+ models                                                  |
| **Surfaced thinking**   | `thinking.display: "summarized"` on Opus 4.7/4.8                                                 |
| **Task budgets**        | `output_config.task_budget` — cumulative agentic loop budget                                     |
| **Context management**  | `context_management` — server-side long-session editing                                          |
| **1M context**          | `context-1m-2025-08-07` — auto-enabled on large prompts                                          |
| **Betas**               | `effort-`, `interleaved-thinking-`, `task-budgets-`, `context-management-`, `context-1m-` unioned |

Every wire detail (the `output_config.effort` enum, the top-level `speed` field,
the beta tokens, the per-model effort gating) is taken verbatim from the Claude
Code CLI bundle — VoidSwitch then forwards the request to Anthropic under the
Claude Code identity.

## How it works

OpenCode speaks the **Anthropic** dialect to VoidSwitch
(`@opencode/ai/providers/anthropic` → `<gateway>/v1/messages`).

V2 changed where a plugin can reach the request, and this plugin uses the narrowest
layer that works for each feature:

| Layer                  | Used for                                                                  |
| ---------------------- | ------------------------------------------------------------------------- |
| `context` hook         | `effort`, `speed`, `thinking`, `temperature` — semantic request options    |
| `model.request` hook   | The `x-voidswitch-client` / `-session` headers                             |
| `http.request` hook    | The remaining Claude Code-only fields (`task_budget`, `1M`, extras betas) |

V2's Anthropic route already lowers `output_config.effort`, `speed` and `thinking`
from semantic options and adds the beta each one needs, so — unlike the V1 plugin —
there is no auth-`loader` fetch rewriting a serialized body. Only the fields with no
V2 semantic option need a body edit, and that happens in `http.request`; success
responses pass through untouched, so streaming is unaffected.

The per-turn selection from the model-variant picker reaches the request as
`event.model.variant`. V2 variants carry their own `body`, so the picker itself
declares the wire field:

```
OpenCode picker (variant)
   └─ context hook  → options.effort / options.speed / options.thinking
        └─ http.request  → adds task_budget / 1M + their betas
             └─ VoidSwitch /v1/messages  → Anthropic (as Claude Code)
```

## Install

The plugin is self-contained — it registers its own provider, so you only need to
make OpenCode load it and point it at your gateway.

### One-line installer

```bash
curl -fsSL "https://your-voidswitch-host/install.sh" | sh
```

This drops the directory plugin (server + rpc + tui parts) into
`~/.config/opencode/plugins/voidswitch/`, where OpenCode discovers it
automatically, and bakes the gateway you installed from into the server part.
Then run `/connect` → **VoidSwitch** and paste a `vs-…` token.

### Manual

Copy `src/index.ts`, `src/rpc.ts` and `src/tui.ts` into
`~/.config/opencode/plugins/voidswitch/` (or any directory you then reference
from `plugins`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [
    // V2 path: a directory. Point at your gateway.
    { "package": "/home/you/.config/opencode/plugins/voidswitch", "options": { "url": "https://your-voidswitch-host" } }
  ]
}
```

> V2 local plugin paths must name a **directory**, not a file. A configured
> `./plugin/local.ts` is skipped with a warning.

Then authenticate once:

```
/connect       # pick "VoidSwitch" → paste your vs-… token
```

The gateway URL may also come from `$VOIDSWITCH_URL` (default
`https://voidswitch.siiway.org`), or from `providers.voidswitch.settings.baseURL` in
`opencode.json`.

### Nix Flakes

The repository provides an `opencode-voidswitch` package via its flake. Add it as
an input and reference the store path:

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    voidswitch.url = "github:siiway/voidswitch";
  };

  outputs = { self, nixpkgs, voidswitch, ... }: {
    # voidswitch.packages.${system}.opencode-voidswitch
  };
}
```

```jsonc
{
  "plugins": [
    { "package": "/nix/store/...-opencode-voidswitch-0.2.0", "options": { "url": "https://your-voidswitch-host" } }
  ]
}
```

> The package ships only TypeScript source — no build step.
> `@opencode/plugin` is a peer dependency resolved by OpenCode at runtime.

## Plugin options

| Option              | Type                                                | Default                                     | Meaning                                                                                   |
| ------------------- | --------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `url`               | string                                              | `$VOIDSWITCH_URL` / `https://voidswitch.siiway.org` | Gateway base URL                                                                          |
| `effort`            | `low\|medium\|high\|xhigh\|max\|ultracode\|default` | `default`                                   | Effort used when no picker variant is chosen (`default` = let the model decide)           |
| `thinking`          | boolean                                             | `true`                                      | Enable adaptive extended thinking on 4.6+ models                                          |
| `thinkingDisplay`   | `summarized\|omitted`                               | `summarized`                                | Surface thinking text on Opus 4.7/4.8                                                     |
| `fast`              | boolean                                             | `false`                                     | Force fast mode on every request                                                          |
| `context1m`         | `boolean\|"auto"`                                   | `auto`                                      | 1M context: `true` always, `false` never, `auto` = enable on large prompts (~150k tokens) |
| `contextManagement` | boolean                                             | `false`                                     | Server-side context management (auto-clears old thinking blocks for long sessions)        |
| `taskBudget`        | number                                              | —                                           | Cumulative agentic token budget for the loop (min 20000)                                  |

## Choosing effort per request

Each Claude model appears in the model picker with **variants** — pick one to set
the effort/mode for that turn:

```
claude-opus-4-8            ← default effort
claude-opus-4-8:low
claude-opus-4-8:medium
claude-opus-4-8:high
claude-opus-4-8:xhigh      ← Opus 4.8/4.7 only
claude-opus-4-8:max        ← Opus-tier only
claude-opus-4-8:ultracode  ← = xhigh effort
claude-opus-4-8:fast       ← speed: "fast"
```

Unsupported levels are **clamped exactly as Claude Code does** — e.g. selecting
`xhigh` or `max` on Sonnet falls back to `high`; only Opus 4.8/4.7 expose
`xhigh`/`ultracode`.

## DeepSeek & other OpenAI-dialect reasoners

Claude (and MiMo) speak the **Anthropic** dialect. DeepSeek, however, is served by
VoidSwitch in the **OpenAI** dialect, and its chain-of-thought round-trips as the
`reasoning_content` field. On the Anthropic runtime that field is silently dropped,
and the upstream then rejects the next tool-call turn with:

> `The reasoning_content in the thinking mode must be passed back to the API.`

Any model id matching `deepseek` is therefore auto-wired: the plugin swaps in the
`@opencode/ai/providers/openai-compatible` runtime and sets
`compatibility.reasoningField = "reasoning_content"` — while reusing the **same**
VoidSwitch token and auth as your Claude models. Everything else stays on the
Anthropic dialect. (Effort/fast/thinking variants are Claude-only and are not
applied to DeepSeek.)

## Slash commands

The plugin registers Claude Code-style slash commands that set the effort/mode for
the rest of the session:

| Command                                                        | Effect                                                    |
| -------------------------------------------------------------- | --------------------------------------------------------- |
| `/effort high` (or `low\|medium\|xhigh\|max\|ultracode\|auto`) | Sets the session effort                                   |
| `/effort xhigh <prompt>`                                       | Sets effort **and** runs the prompt in one shot            |
| `/effort auto`                                                 | Clears the override (model decides)                        |
| `/fast` · `/fast off`                                          | Turns fast mode on / off for the session                   |
| `/ultracode`                                                   | xhigh effort for the session                               |

Palette commands (`Ctrl+P`, no session message) and external paths:

| Command                                                        | Effect                                                    |
| -------------------------------------------------------------- | --------------------------------------------------------- |
| **VoidSwitch: sync models** (palette)                          | Refresh the available-model list from the gateway          |
| **VoidSwitch: set gateway URL** (palette)                      | Switch gateways, then refresh the model list               |
| **VoidSwitch: configure mcp server** (palette)                 | Setup / enable / disable / uninstall the MCP server        |
| `opencode auth login` → VoidSwitch                             | Re-paste the token; refreshes the list on success          |

Precedence: a per-turn model-variant pick (e.g. `…:low`) overrides the session
command, which overrides the `effort` plugin option.

## Management MCP server

The gateway sells its management API (`/api/v1/mcp`) as an MCP server, authenticated
with a **platform API key** (`vsapi-…`, staff only) — a different credential from the
`vs-…` gateway token. The plugin registers it for you:

```
Ctrl+P → VoidSwitch: configure mcp server
   ├─ Setup / re-configure   paste a vsapi-… key (empty keeps the stored one;
   │                         a disabled server stays disabled)
   ├─ Enable                 turn the server on
   ├─ Disable                turn it off, keeping the key
   └─ Uninstall              remove the server and delete the stored key
```

Setup probes `GET <gateway>/api/v1/whoami` first and refuses to save a key the
gateway rejects (401/403, expired, disabled, non-staff); a gateway without the
platform API answers 404/501 and says so instead. The server URL is never stored:
it follows the current gateway, so switching gateways re-points the server and
re-checks the key against the new host.

**The scopes on the key are the permissions you hand the model.** Start with
`read` scopes only and add what you actually need — a write scope lets injected
context change providers, disable users or edit settings too. Revoke the key in
the dashboard when you stop using it.

The key lives in `$XDG_CONFIG_HOME/opencode/voidswitch-mcp.json` (falling back to
`~/.config/opencode/voidswitch-mcp.json`; mode `0600` on POSIX) and is never
written into `opencode.json`. Registration goes through `ctx.mcp.transform`, so
the server exists only while the plugin is loaded — exactly where its tools are
useful. Tools are exposed through Code Mode (the V2 default) rather than being
dumped into the context.

Builds without the second-level menu API get two standalone palette commands
instead: **VoidSwitch: setup mcp server** and **VoidSwitch: uninstall mcp server**
(no enable/disable). Builds without `ctx.mcp.transform` cannot register MCP
servers at all; the palette disables the actions and says to upgrade.

## Claude Code feature parity

**Reproduced at the wire level** (works through VoidSwitch → Anthropic):

- Effort levels `low … max` and `ultracode` (→ `output_config.effort`)
- Fast mode `/fast` (→ top-level `speed`)
- Adaptive extended thinking on 4.6+ (→ `thinking`), with summarized thinking surfaced on 4.7/4.8
- Task budgets — cumulative agentic loop budget (→ `output_config.task_budget`)
- Context management — server-side editing of old thinking blocks for long sessions
- 1M context — auto-enabled on large prompts (→ `context-1m` beta)
- The matching `anthropic-beta` tokens, unioned onto whatever the SDK already sends
- `temperature` forced to `1` when thinking is on (Anthropic requirement)

**Client/harness-only (no `/v1/messages` representation):**

- **ultracode's dynamic-workflow orchestration** — the effort half (`xhigh`) is
  reproduced; the standing workflow orchestration is a CLI-side behaviour.
- **`ultrathink`** — a magic keyword Claude Code detects in your *prompt text*. It
  is not a request field.

## Development

```
npm install
npm run typecheck
```
