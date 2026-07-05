# opencode-voidswitch

Deep [VoidSwitch](../) integration for [OpenCode](https://opencode.ai). Registers
VoidSwitch as a first-class provider and reproduces the **full Claude Code request
surface** end-to-end — so OpenCode driving a VoidSwitch `claude-code` upstream
behaves like the real CLI, **efforts and all**.

| Capability              | How it reaches the wire                                                                                                          |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Auth**                | Paste a `vs-…` token (stored by OpenCode, sent as `x-api-key`)                                                                   |
| **Models**              | Pulled live from `GET <gateway>/v1/models`                                                                                       |
| **Effort**              | `output_config.effort` ∈ `low · medium · high · xhigh · max`                                                                     |
| **ultracode**           | Picker variant → `xhigh` effort                                                                                                  |
| **Fast mode** (`/fast`) | Top-level `speed: "fast"`                                                                                                        |
| **Adaptive thinking**   | `thinking: { type: "adaptive" }` on 4.6+ models                                                                                  |
| **Surfaced thinking**   | `thinking.display: "summarized"` on Opus 4.7/4.8                                                                                 |
| **Task budgets**        | `output_config.task_budget` — cumulative agentic loop budget                                                                     |
| **Context management**  | `context_management` — server-side long-session editing                                                                          |
| **1M context**          | `context-1m-2025-08-07` — auto-enabled on large prompts                                                                          |
| **Betas**               | `effort-`, `fast-mode-`, `interleaved-thinking-`, `task-budgets-`, `context-management-`, `context-1m-` unioned onto the request |

Every wire detail (the `output_config.effort` enum, the top-level `speed` field,
the beta tokens, the per-model effort gating) is taken verbatim from the Claude
Code CLI bundle — VoidSwitch then forwards the request to Anthropic under the
Claude Code identity.

## How it works

OpenCode is configured to speak the **Anthropic** dialect to VoidSwitch
(`@ai-sdk/anthropic` → `<gateway>/v1/messages`). `effort` / `speed` are native
`/v1/messages` fields the AI SDK never emits, so the plugin injects them in the
auth `loader`'s custom `fetch` — the one place that sees the fully serialized
request body. The per-turn selection from the **model-variant picker** is carried
to that fetch via private `x-voidswitch-*` headers (set in `chat.headers`,
stripped before the request leaves the machine).

```
OpenCode picker (variant)
   └─ chat.headers  → x-voidswitch-effort / -speed / -thinking
        └─ auth.loader fetch  → rewrites body: output_config.effort, speed, thinking
                              → unions anthropic-beta
             └─ VoidSwitch /v1/messages  → Anthropic (as Claude Code)
```

## Install

The plugin is self-contained — it registers its own provider, so you only need to
add the plugin and point it at your gateway.

`opencode.json` (or `~/.config/opencode/opencode.json`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    ["opencode-voidswitch", { "url": "https://your-voidswitch-host", "effort": "high" }]
  ]
}
```

For local development against a checkout, point at the directory instead:

```jsonc
{ "plugin": [["./opencode-plugin", { "url": "http://localhost:8080" }]] }
```

### Nix Flakes

The repository provides a `opencode-voidswitch` package via its flake. Add it as
an input in your flake and reference the store path:

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    voidswitch.url = "github:siiway/voidswitch";
  };

  outputs = { self, nixpkgs, voidswitch, ... }: {
    # Refer to the plugin directory:
    #   voidswitch.packages.${system}.opencode-voidswitch
  };
}
```

In `opencode.json`, point to the Nix store path:

```jsonc
{
  "plugin": [
    ["/nix/store/...-opencode-voidswitch-0.1.0", { "url": "https://your-voidswitch-host" }]
  ]
}
```

Or resolve the path dynamically at build time:

```jsonc
{
  "plugin": [
    ["${voidswitch.packages.${system}.opencode-voidswitch}", { "url": "https://your-voidswitch-host" }]
  ]
}
```

> The package ships only TypeScript source — no build step.
> `@opencode-ai/plugin` is a peer dependency resolved by OpenCode at runtime.

Then authenticate once:

```
opencode auth login        # pick "VoidSwitch" → paste your vs-… token
```

The gateway URL may also come from `$VOIDSWITCH_URL` (default
`http://localhost:8080`).

## Plugin options

| Option              | Type                                                | Default                                     | Meaning                                                                                   |
| ------------------- | --------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `url`               | string                                              | `$VOIDSWITCH_URL` / `http://localhost:8080` | Gateway base URL                                                                          |
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

Claude (and MiMo) speak the **Anthropic** dialect, so they ride the provider's
`@ai-sdk/anthropic` path. DeepSeek, however, is served by VoidSwitch in the
**OpenAI** dialect, and its chain-of-thought round-trips as the `reasoning_content`
field. OpenCode only re-attaches that field (its `interleaved` mechanism) on the
`@ai-sdk/openai-compatible` SDK — on the Anthropic SDK it is silently dropped, and
the upstream then rejects the next tool-call turn with:

> `The reasoning_content in the thinking mode must be passed back to the API.`

To handle this, just **list the DeepSeek model id** under the `voidswitch` provider.
The plugin auto-wires it: it forces a per-model `@ai-sdk/openai-compatible` override
(routing it to the gateway's OpenAI `/chat/completions` endpoint) and enables the
`reasoning_content` interleaved field — all while reusing the **same** VoidSwitch
token and auth as your Claude models.

```jsonc
{
  "provider": {
    "voidswitch": {
      "models": {
        // Claude / MiMo need nothing — they use the Anthropic dialect.
        // DeepSeek: id is enough; the plugin sets the openai-compatible override
        // + reasoning_content passback automatically.
        "deepseek-v4-flash-lkd": { "name": "DeepSeek V4 Flash" },
        "deepseek-v4-pro-lkd":   { "name": "DeepSeek V4 Pro" }
      }
    }
  }
}
```

Any model id matching `deepseek` is auto-wired this way; everything else stays on
the Anthropic dialect. (Effort/fast/thinking variants are Claude-only and are not
applied to DeepSeek.)

## Slash commands

The plugin also registers Claude Code-style slash commands that set the effort/mode
for the rest of the session:

| Command                                                        | Effect                                                                                      |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `/effort high` (or `low\|medium\|xhigh\|max\|ultracode\|auto`) | Sets the session effort                                                                     |
| `/effort xhigh <prompt>`                                       | Sets effort **and** runs the prompt in one shot                                             |
| `/effort auto`                                                 | Clears the override (model decides)                                                         |
| `/fast` · `/fast off`                                          | Turns fast mode on / off for the session                                                    |
| `/ultracode`                                                   | xhigh effort for the session                                                                |
| `/sync-models`                                                 | Refresh the platform's available-model list from the gateway (then reopen the model picker) |

Precedence: a per-turn model-variant pick (e.g. `…:low`) overrides the session
command, which overrides the `effort` plugin option.

> Note: OpenCode has no "client-only" command — every command runs one model turn.
> So a bare `/effort high` costs one cheap confirmation turn; `/effort high <prompt>`
> spends that turn on real work. For a truly zero-cost switch, use the model-variant
> picker (`/models`) instead.

## Claude Code feature parity

**Reproduced at the wire level** (works through VoidSwitch → Anthropic):

- Effort levels `low … max` and `ultracode` (→ `output_config.effort`)
- Fast mode `/fast` (→ top-level `speed`)
- Adaptive extended thinking on 4.6+ (→ `thinking`), with summarized thinking surfaced on 4.7/4.8
- Task budgets — cumulative agentic loop budget (→ `output_config.task_budget`)
- Context management — server-side editing of old thinking blocks for long sessions (→ `context_management`)
- 1M context — auto-enabled on large prompts (→ `context-1m` beta)
- The matching `anthropic-beta` tokens, unioned onto whatever the SDK already sends
- `temperature` forced to `1` when thinking is on (Anthropic requirement)

**Client/harness-only (no `/v1/messages` representation, so not reproducible from
a provider plugin):**

- **ultracode's dynamic-workflow orchestration** — the effort half (`xhigh`) is
  reproduced; the standing workflow orchestration is a CLI-side behaviour.
- **`ultrathink`** — a magic keyword Claude Code detects in your *prompt text* and
  expands into an injected "think harder" reminder. It is not a request field.

## Development

```
bun install
bun run typecheck
```
