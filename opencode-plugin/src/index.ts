/**
 * VoidSwitch — deep OpenCode integration.
 *
 * Registers VoidSwitch as a first-class provider and reproduces the *full* Claude
 * Code request surface end-to-end, so OpenCode driving a VoidSwitch `claude-code`
 * upstream behaves like the real CLI:
 *
 *   • auth        — paste a `vs-…` token (stored by OpenCode, sent as x-api-key)
 *   • models      — pulled live from `<gateway>/v1/models`
 *   • effort      — `output_config.effort` ∈ low|medium|high|xhigh|max, picker variants
 *   • fast mode   — top-level `speed: "fast"` (Claude Code's /fast), picker variant
 *   • thinking    — adaptive extended thinking on 4.6+ models
 *   • betas       — the matching `anthropic-beta` tokens, unioned onto the request
 *
 * Why the design works: OpenCode is configured to speak the Anthropic dialect to
 * VoidSwitch (`@ai-sdk/anthropic` → `<gateway>/v1/messages`). The effort/speed
 * fields are native `/v1/messages` fields the AI SDK never emits, so we inject them
 * in the auth `loader`'s custom `fetch` — the one place that sees the fully
 * serialized request body. The per-request effort/mode is carried from the model
 * picker to that fetch via private `x-voidswitch-*` request headers (set in
 * `chat.headers`, consumed and stripped before the request leaves).
 *
 * Wire facts are taken verbatim from the Claude Code CLI bundle:
 *   - request body keys: ["model","system","tools","max_tokens","thinking","output_config","context_management","metadata"]
 *   - effort enum sN = ["low","medium","high","xhigh","max"], carried in output_config.effort
 *   - fast mode: top-level `speed: "fast"`
 *   - betas: effort-2025-11-24, fast-mode-2026-02-01, interleaved-thinking-2025-05-14
 */

import type { Hooks, Plugin, PluginInput, PluginOptions } from "@opencode-ai/plugin"

// --------------------------------------------------------------------------- //
// Constants mirrored from the Claude Code CLI wire format
// --------------------------------------------------------------------------- //

const PROVIDER_ID = "voidswitch"

/** Claude Code's effort enum (`sN`), lowest → highest. */
const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const
type Effort = (typeof EFFORT_LEVELS)[number]

/** Picker variant that turns on fast mode instead of selecting an effort. */
const FAST_VARIANT = "fast"

/**
 * Picker variant mirroring Claude Code's "ultracode" — it resolves to `xhigh`
 * effort (`output_config.effort = "xhigh"`). Claude Code's ultracode *also* turns
 * on standing dynamic-workflow orchestration, but that is a CLI harness behaviour
 * with no `/v1/messages` representation, so only the effort half is reproduced.
 */
const ULTRACODE_VARIANT = "ultracode"

/** `anthropic-beta` tokens each feature requires; unioned onto the outgoing header. */
const BETA_EFFORT = "effort-2025-11-24"
const BETA_FAST = "fast-mode-2026-02-01"
const BETA_THINKING = "interleaved-thinking-2025-05-14"
const BETA_TASK_BUDGET = "task-budgets-2026-03-13"
const BETA_CONTEXT_MGMT = "context-management-2025-06-27"
const BETA_LONG_CONTEXT = "context-1m-2025-08-07"

/** Verified context-management edit type Claude Code sends (this CLI build). */
const CONTEXT_EDIT_TYPE = "clear_thinking_20251015"
/** Anthropic's minimum cumulative agentic budget. */
const TASK_BUDGET_MIN = 20_000
/** Auto-enable 1M context once the serialized prompt is this large (~150k tokens). */
const LONG_CONTEXT_CHARS = 600_000

/** Private headers bridging the picker selection → the body-rewriting fetch. */
const H_EFFORT = "x-voidswitch-effort"
const H_SPEED = "x-voidswitch-speed"
const H_THINKING = "x-voidswitch-thinking"

const DEFAULT_GATEWAY = "http://localhost:8080"

/** Fallback model list when `/v1/models` is unreachable (offline picker). */
const FALLBACK_MODELS = [
  "claude-opus-4-8",
  "claude-opus-4-7",
  "claude-opus-4-6",
  "claude-sonnet-4-6",
  "claude-haiku-4-5",
]

// Per-session overrides set by the /effort, /fast, /ultracode slash commands. The
// command hook and chat.headers run in the same plugin instance, so this module Map
// bridges them (command sets it → the next turn's headers read it).
type SessionOverride = { effort?: Effort | "auto"; fast?: boolean }
const sessionState = new Map<string, SessionOverride>()

// --------------------------------------------------------------------------- //
// Plugin options (opencode.json: plugin: [["voidswitch", { ... }]])
// --------------------------------------------------------------------------- //

interface VoidSwitchOptions {
  /** Gateway base URL, e.g. "https://gw.example.com". Falls back to $VOIDSWITCH_URL. */
  url?: string
  /** Default effort when no picker variant is chosen. "default" = let the model decide. */
  effort?: Effort | "ultracode" | "default"
  /** Enable adaptive extended thinking on 4.6+ models (default: true). */
  thinking?: boolean
  /** Surface thinking text on Opus 4.7/4.8 (default: "summarized"; "omitted" hides it). */
  thinkingDisplay?: "summarized" | "omitted"
  /** Force fast mode on every request regardless of the selected variant. */
  fast?: boolean
  /** 1M context: true = always, false = never, "auto"/unset = enable on large prompts. */
  context1m?: boolean | "auto"
  /** Server-side context management (auto-clears old thinking blocks for long sessions). */
  contextManagement?: boolean
  /** Cumulative agentic token budget for the whole loop (output_config.task_budget). */
  taskBudget?: number
}

// --------------------------------------------------------------------------- //
// Model-capability helpers (mirror Claude Code's per-model effort gating)
// --------------------------------------------------------------------------- //

const isClaude = (id: string) => /claude/i.test(id)
const isOpus = (id: string) => /opus/i.test(id)
/**
 * Non-Claude upstreams that stream `reasoning_content` (DeepSeek R-series, etc.).
 * They must be marked reasoning-capable so OpenCode persists and *replays* their
 * thinking blocks: DeepSeek's interleaved thinking mode rejects any follow-up turn
 * whose assistant message dropped the prior `reasoning_content`
 * ("The reasoning_content in the thinking mode must be passed back to the API.").
 */
const isReasoningModel = (id: string) => isClaude(id) || /deepseek|reasoner|-r1\b|qwq|thinking/i.test(id)
/**
 * Reasoning models that VoidSwitch serves in the *OpenAI* dialect (DeepSeek &c).
 * These must be driven through `@ai-sdk/openai-compatible`, not Anthropic, because
 * their chain-of-thought round-trips as the `reasoning_content` field. OpenCode's
 * `interleaved:{field}` mechanism only re-attaches that field on the openai-compatible
 * SDK; on the Anthropic SDK it is silently dropped, so the upstream rejects the next
 * turn with "The reasoning_content in the thinking mode must be passed back to the API."
 * We keep them inside this single provider via a per-model `provider.npm` override
 * (which OpenCode honours above the provider-level npm), so they reuse the same token.
 */
const isOpenAICompatModel = (id: string) => /deepseek/i.test(id)
/** Effort param is GA on Opus 4.6+ and Sonnet 4.6 ("Opus 4.6+, Sonnet 4.6"). */
const effortCapable = (id: string) => /opus-4-[6-9]/.test(id) || /sonnet-4-[6-9]/.test(id)
/** `xhigh` is "Opus 4.8/4.7 only". */
const xhighCapable = (id: string) => /opus-4-[78]/.test(id)
/** `max` is Opus-tier only (4.6+). */
const maxCapable = (id: string) => /opus-4-[6-9]/.test(id)
/** Adaptive thinking is supported on the 4.6+ generation. */
const adaptiveCapable = (id: string) => /opus-4-[6-9]/.test(id) || /sonnet-4-[6-9]/.test(id)

/** Downgrade an effort the model can't honour, exactly as the CLI does (→ "high"). */
function clampEffort(id: string, effort: Effort): Effort {
  if (effort === "max" && !maxCapable(id)) return "high"
  if (effort === "xhigh" && !xhighCapable(id)) return "high"
  return effort
}

function isEffort(value: unknown): value is Effort {
  return typeof value === "string" && (EFFORT_LEVELS as readonly string[]).includes(value)
}

/** Resolve the effort for a turn: picker variant wins, else the configured default.
 * "ultracode" (variant or option) maps to xhigh, exactly as the Claude Code CLI. */
function resolveEffort(variant: string | undefined, opt: VoidSwitchOptions, id: string): Effort | undefined {
  let raw: Effort | undefined
  if (variant === ULTRACODE_VARIANT) raw = "xhigh"
  else if (isEffort(variant)) raw = variant
  else if (opt.effort === "ultracode") raw = "xhigh"
  else if (opt.effort && opt.effort !== "default") raw = opt.effort
  return raw ? clampEffort(id, raw) : undefined
}

function prettyName(id: string): string {
  const m = id.match(/^claude-(opus|sonnet|haiku)-(\d)-(\d+)/i)
  if (m) return `Claude ${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`
  return id
}

// --------------------------------------------------------------------------- //
// Model construction (shape mirrors built-in dynamic-model plugins)
// --------------------------------------------------------------------------- //

function buildModel(id: string, gatewayV1: string): Record<string, any> {
  const claude = isClaude(id)
  const reasoning = isReasoningModel(id)
  const oaiCompat = isOpenAICompatModel(id)
  const npm = oaiCompat ? "@ai-sdk/openai-compatible" : "@ai-sdk/anthropic"
  const model: Record<string, any> = {
    id,
    providerID: PROVIDER_ID,
    name: prettyName(id),
    api: { id, url: gatewayV1, npm },
    status: "active",
    release_date: "2025-01-01",
    capabilities: {
      temperature: true,
      reasoning,
      attachment: true,
      toolcall: true,
      input: { text: true, image: claude, audio: false, video: false, pdf: claude },
      output: { text: true, image: false, audio: false, video: false, pdf: false },
      // OpenAI-dialect reasoners (DeepSeek) re-attach CoT via `reasoning_content`.
      ...(oaiCompat ? { interleaved: { field: "reasoning_content" } } : {}),
    },
    cost: { input: 0, output: 0, cache: { read: 0, write: 0 } },
    limit: { context: claude ? 1_000_000 : 200_000, output: isOpus(id) ? 128_000 : claude ? 64_000 : 8_192 },
    options: {},
    headers: {},
  }

  // Per-model SDK override: keep these inside the single VoidSwitch provider (one
  // token, one auth) but route them through the openai-compatible SDK → the gateway's
  // OpenAI `/chat/completions` endpoint. OpenCode resolves `provider.npm` ahead of the
  // provider-level npm, so the Anthropic default does not apply to these models.
  if (oaiCompat) model.provider = { npm: "@ai-sdk/openai-compatible", api: gatewayV1 }

  // Expose effort levels (and fast mode) as picker variants for capable models.
  if (claude && effortCapable(id)) {
    const variants: Record<string, Record<string, unknown>> = {}
    for (const e of EFFORT_LEVELS) {
      if (e === "xhigh" && !xhighCapable(id)) continue
      if (e === "max" && !maxCapable(id)) continue
      variants[e] = {} // selection is read by name in chat.headers; no option merge needed
    }
    if (xhighCapable(id)) variants[ULTRACODE_VARIANT] = {} // → xhigh
    variants[FAST_VARIANT] = {}
    model.variants = variants
  }
  return model
}

// --------------------------------------------------------------------------- //
// Header helpers for the body-rewriting fetch
// --------------------------------------------------------------------------- //

function applyInitHeaders(target: Headers, init?: RequestInit): void {
  const hs = init?.headers
  if (!hs) return
  if (hs instanceof Headers) hs.forEach((v, k) => target.set(k, v))
  else if (Array.isArray(hs)) for (const [k, v] of hs) target.set(k, String(v))
  else for (const [k, v] of Object.entries(hs)) if (v != null) target.set(k, String(v))
}

/** Read a header and remove it, so the private bridge headers never leave the host. */
function takeHeader(h: Headers, name: string): string | undefined {
  const v = h.get(name)
  if (v !== null) h.delete(name)
  return v ?? undefined
}

// --------------------------------------------------------------------------- //
// Slash-command helpers
// --------------------------------------------------------------------------- //

/** Replace the command's prompt text in place (parts are `[{type:"text",text}]`). */
function setCommandText(output: { parts: any[] }, text: string): void {
  const first = output.parts?.[0]
  if (first && first.type === "text") first.text = text
  else output.parts = [{ type: "text", text }]
}

const confirmText = (what: string) =>
  `Reply with one short line confirming VoidSwitch ${what} is set for this session. Do nothing else.`

// --------------------------------------------------------------------------- //
// Plugin
// --------------------------------------------------------------------------- //

const stripV1 = (u: unknown): string | undefined =>
  typeof u === "string" ? u.replace(/\/v1\/?$/, "").replace(/\/+$/, "") : undefined

const VoidSwitchPlugin: Plugin = async (_input: PluginInput, options?: PluginOptions): Promise<Hooks> => {
  const opt = (options ?? {}) as VoidSwitchOptions
  // Gateway precedence: plugin option → env → existing config baseURL (adopted in
  // the config hook) → default. `let` so the config hook can adopt the config URL,
  // which the later models()/fetch closures then observe.
  let gateway = (opt.url ?? process.env.VOIDSWITCH_URL ?? DEFAULT_GATEWAY).replace(/\/+$/, "")
  let gatewayV1 = `${gateway}/v1`

  async function fetchModelIds(token: string | undefined): Promise<string[]> {
    try {
      const res = await fetch(`${gatewayV1}/models`, {
        headers: token ? { "x-api-key": token } : {},
      })
      if (!res.ok) return FALLBACK_MODELS
      const json: any = await res.json()
      const ids = (json?.data ?? []).map((m: any) => m?.id).filter((x: any): x is string => typeof x === "string")
      return ids.length ? ids : FALLBACK_MODELS
    } catch {
      return FALLBACK_MODELS
    }
  }

  return {
    // Register the provider so it exists even before models are fetched. Anthropic
    // dialect is required for the effort/speed/thinking fields to be meaningful.
    config: async (cfg: any) => {
      cfg.provider = cfg.provider ?? {}
      const existing = cfg.provider[PROVIDER_ID] ?? {}
      // Adopt the gateway from the config's baseURL when not given explicitly — lets
      // the installer pass the URL via a plain provider block instead of plugin opts.
      if (!opt.url && !process.env.VOIDSWITCH_URL) {
        const fromCfg = stripV1(existing.options?.baseURL)
        if (fromCfg) {
          gateway = fromCfg
          gatewayV1 = `${gateway}/v1`
        }
      }
      // npm + baseURL are forced *after* the spread so a stale config block can't
      // downgrade the dialect. apiKey is stripped so the credential comes from the
      // auth store — only then does our loader (and its body-rewriting fetch) run.
      const opts = { ...(existing.options ?? {}), baseURL: gatewayV1 }
      delete (opts as any).apiKey
      // A provider with zero models is dropped by OpenCode (so it never shows in
      // /connect or the picker). Seed the default models when the config has none;
      // provider.models() replaces them with the live list + effort variants.
      const models =
        existing.models && Object.keys(existing.models).length
          ? existing.models
          : Object.fromEntries(FALLBACK_MODELS.map((id) => [id, {}]))
      // Auto-wire OpenAI-dialect reasoners (DeepSeek): a user only has to list the id
      // (e.g. "deepseek-v4-flash-lkd": {}). We force the per-model openai-compatible
      // SDK override + the `reasoning_content` interleaved field so chain-of-thought
      // round-trips correctly — while everything else stays on the Anthropic dialect
      // and the single shared VoidSwitch token. (User-supplied fields win, except the
      // provider override, which must point at this gateway's OpenAI endpoint.)
      for (const [mid, mcfg] of Object.entries(models)) {
        if (!isOpenAICompatModel(mid)) continue
        models[mid] = {
          reasoning: true,
          tool_call: true,
          interleaved: { field: "reasoning_content" },
          ...(mcfg as Record<string, any>),
          provider: { npm: "@ai-sdk/openai-compatible", api: gatewayV1 },
        }
      }
      cfg.provider[PROVIDER_ID] = {
        name: "VoidSwitch",
        ...existing,
        npm: "@ai-sdk/anthropic",
        options: opts,
        models,
      }

      // Register the Claude Code-style slash commands (templates are overridden in
      // command.execute.before; "$ARGUMENTS" just guarantees a text part exists).
      cfg.command = cfg.command ?? {}
      const addCommand = (name: string, description: string) => {
        if (!cfg.command[name]) cfg.command[name] = { description, template: "$ARGUMENTS" }
      }
      addCommand("effort", "VoidSwitch reasoning effort: low|medium|high|xhigh|max|ultracode|auto [+ optional prompt]")
      addCommand("fast", "VoidSwitch fast mode: on|off [+ optional prompt]")
      addCommand("ultracode", "VoidSwitch ultracode — xhigh effort [+ optional prompt]")
    },

    // /effort, /fast, /ultracode — set the per-session override, then either run the
    // appended prompt or emit a one-line confirmation. (OpenCode has no no-LLM
    // command, so a bare set costs one cheap turn; the model-variant picker is the
    // zero-cost alternative.)
    "command.execute.before": async (
      input: { command: string; sessionID: string; arguments: string },
      output: { parts: any[] },
    ) => {
      if (input.command !== "effort" && input.command !== "fast" && input.command !== "ultracode") return
      const arg = (input.arguments ?? "").trim()
      const [first, ...restWords] = arg.split(/\s+/).filter(Boolean)
      const head = (first ?? "").toLowerCase()
      const rest = restWords.join(" ").trim()
      const st = sessionState.get(input.sessionID) ?? {}
      let note: string

      if (input.command === "ultracode") {
        st.effort = "xhigh"
        note = "ultracode (xhigh effort)"
        sessionState.set(input.sessionID, st)
        return setCommandText(output, arg || confirmText(note))
      }
      if (input.command === "fast") {
        const isFlag = ["on", "off", "true", "false"].includes(head)
        st.fast = !(head === "off" || head === "false")
        note = `fast mode ${st.fast ? "ON" : "OFF"}`
        sessionState.set(input.sessionID, st)
        return setCommandText(output, (isFlag ? rest : arg) || confirmText(note))
      }
      // /effort
      let prompt = arg
      if (head === "ultracode") {
        st.effort = "xhigh"
        note = "ultracode (xhigh effort)"
        prompt = rest
      } else if (head === "auto" || head === "default") {
        st.effort = "auto"
        note = "auto (model decides)"
        prompt = rest
      } else if (isEffort(head)) {
        st.effort = head
        note = `effort ${head}`
        prompt = rest
      } else {
        note = `effort ${st.effort ?? "auto"}` // unrecognized level → treat whole arg as prompt
      }
      sessionState.set(input.sessionID, st)
      setCommandText(output, prompt || confirmText(note))
    },

    // Auth: paste a vs-… token. The loader hands the AI SDK the apiKey (sent as
    // x-api-key) plus a fetch that injects the Claude Code request fields.
    auth: {
      provider: PROVIDER_ID,
      async loader(getAuth) {
        const auth = await getAuth()
        const apiKey = auth?.type === "api" ? auth.key : ""
        return {
          apiKey,
          async fetch(reqInput: RequestInfo | URL, init?: RequestInit) {
            const headers = new Headers(reqInput instanceof Request ? reqInput.headers : undefined)
            applyInitHeaders(headers, init)

            const effort = takeHeader(headers, H_EFFORT)
            const speed = takeHeader(headers, H_SPEED)
            const thinking = takeHeader(headers, H_THINKING)

            let bodyText: string | undefined
            if (typeof init?.body === "string") bodyText = init.body
            else if (reqInput instanceof Request) bodyText = await reqInput.clone().text().catch(() => undefined)

            if (bodyText) {
              try {
                const body = JSON.parse(bodyText)
                const betaBefore = headers.get("anthropic-beta") ?? ""
                const betas = new Set(betaBefore.split(",").map((s) => s.trim()).filter(Boolean))
                const modelId: string = typeof body.model === "string" ? body.model : ""
                const claude = isClaude(modelId)
                let changed = false

                // Per-turn picker selection (bridged from chat.headers).
                if (effort) {
                  body.output_config = { ...(body.output_config ?? {}), effort }
                  betas.add(BETA_EFFORT)
                  changed = true
                }
                if (speed) {
                  body.speed = "fast"
                  betas.add(BETA_FAST)
                  changed = true
                }
                if (thinking && !body.thinking) {
                  body.thinking = { type: "adaptive" }
                  betas.add(BETA_THINKING)
                  changed = true
                }

                // Option-driven Claude Code extras (model gating read from the body).
                if (claude) {
                  // Surface thinking text — Opus 4.7/4.8 only.
                  if (body.thinking?.type === "adaptive" && /opus-4-[78]/.test(modelId)) {
                    const disp = opt.thinkingDisplay ?? "summarized"
                    if (disp !== "omitted" && body.thinking.display !== disp) {
                      body.thinking = { ...body.thinking, display: disp }
                      changed = true
                    }
                  }
                  // Cumulative agentic token budget.
                  if (typeof opt.taskBudget === "number" && opt.taskBudget >= TASK_BUDGET_MIN && !body.output_config?.task_budget) {
                    body.output_config = {
                      ...(body.output_config ?? {}),
                      task_budget: { type: "tokens", total: Math.floor(opt.taskBudget) },
                    }
                    betas.add(BETA_TASK_BUDGET)
                    changed = true
                  }
                  // Server-side context management for long sessions.
                  if (opt.contextManagement === true && !body.context_management) {
                    body.context_management = { edits: [{ type: CONTEXT_EDIT_TYPE, keep: "all" }] }
                    betas.add(BETA_CONTEXT_MGMT)
                    changed = true
                  }
                  // 1M context window — forced, or auto on a large prompt.
                  const wantLong =
                    opt.context1m === true || (opt.context1m !== false && bodyText.length > LONG_CONTEXT_CHARS)
                  if (wantLong) betas.add(BETA_LONG_CONTEXT)
                }

                const betaAfter = [...betas].join(",")
                if (betaAfter !== betaBefore) {
                  if (betaAfter) headers.set("anthropic-beta", betaAfter)
                  changed = true
                }

                if (changed) {
                  bodyText = JSON.stringify(body)
                  headers.delete("content-length") // re-derived from the new body
                }
              } catch {
                // Non-JSON body (shouldn't happen for /v1/messages) — forward as-is.
              }
            }

            const url = typeof reqInput === "string" ? reqInput : reqInput instanceof URL ? reqInput.toString() : reqInput.url
            const method = init?.method ?? (reqInput instanceof Request ? reqInput.method : "POST")
            return fetch(url, { ...init, method, headers, body: bodyText ?? init?.body })
          },
        }
      },
      methods: [{ type: "api", label: "Paste a VoidSwitch token (vs-…)" }],
    },

    // Live model list from the gateway; claude models get effort/fast variants.
    provider: {
      id: PROVIDER_ID,
      async models(_provider, ctx) {
        const token = ctx.auth?.type === "api" ? ctx.auth.key : undefined
        const ids = await fetchModelIds(token)
        const out: Record<string, any> = {}
        for (const id of ids) out[id] = buildModel(id, gatewayV1)
        return out
      },
    },

    // Carry the picker's effort/mode selection to the body-rewriting fetch, and
    // request the betas the chosen features need.
    "chat.headers": async (input: any, output: { headers: Record<string, string> }) => {
      if (input.model?.providerID !== PROVIDER_ID) return
      const id: string = input.model?.api?.id ?? input.model?.modelID ?? ""
      if (!isClaude(id)) return

      const st = sessionState.get(input.sessionID) ?? {}
      const variant: string | undefined = input.message?.model?.variant

      // Effort precedence: per-turn variant pick → session /effort → option default.
      const variantEffort: Effort | undefined =
        variant === ULTRACODE_VARIANT ? "xhigh" : isEffort(variant) ? variant : undefined
      let effort: Effort | undefined
      if (variantEffort) effort = clampEffort(id, variantEffort)
      else if (st.effort !== undefined) effort = st.effort === "auto" ? undefined : clampEffort(id, st.effort)
      else effort = resolveEffort(undefined, opt, id)

      const fast = variant === FAST_VARIANT || (st.fast ?? opt.fast === true)
      const thinking = opt.thinking !== false && adaptiveCapable(id)

      if (effort) output.headers[H_EFFORT] = effort
      if (fast) output.headers[H_SPEED] = "fast"
      if (thinking) output.headers[H_THINKING] = "adaptive"
    },

    // Anthropic requires temperature == 1 once extended thinking is enabled.
    "chat.params": async (input: any, output: { temperature: number; options: Record<string, any> }) => {
      if (input.model?.providerID !== PROVIDER_ID) return
      const id: string = input.model?.api?.id ?? input.model?.modelID ?? ""
      if (isClaude(id) && opt.thinking !== false && adaptiveCapable(id)) {
        output.temperature = 1
      }
    },
  }
}

export const id = PROVIDER_ID
export default { id, server: VoidSwitchPlugin }
