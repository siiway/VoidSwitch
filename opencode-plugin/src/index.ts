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
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

// --------------------------------------------------------------------------- //
// Constants mirrored from the Claude Code CLI wire format
// --------------------------------------------------------------------------- //

const PROVIDER_ID = "voidswitch"

/** Thrown in command.execute.before to cancel the LLM turn after a side-effect-only
 *  command (toast shown, state mutated). OpenCode catches this and does not forward
 *  the command to the model. */
class CommandHandledError extends Error {
  constructor() {
    super("voidswitch-command-handled")
    this.name = "CommandHandledError"
  }
}

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
const H_BASE_URL = "x-voidswitch-base-url"

/**
 * OpenCode's native per-conversation session id, forwarded to the gateway so its
 * per-session pinned key-select modes can keep one session glued to one upstream
 * key. Unlike the bridge headers above this one is *not* stripped before the
 * request leaves — it is sent to (and consumed by) the gateway, which never
 * forwards it to the real upstream provider.
 */
const H_SESSION = "x-voidswitch-session"

const DEFAULT_GATEWAY = "http://localhost:8080"

/** Fallback model list when `/v1/models` is unreachable (offline picker). */
const FALLBACK_MODELS = [
  "claude-opus-4-8",
  "claude-opus-4-7",
  "claude-opus-4-6",
  "claude-sonnet-4-6",
  "deepseek-v4-pro",
  "deepseek-v4-flash",
]

/**
 * A model id plus its optional VoidSwitch catalog metadata: a human description
 * and a custom OpenCode model config (deep-merged into the built model block, so
 * admins can tune name/limit/cost/capabilities/variants per model from the
 * dashboard's Models page). Both come from `<gateway>/v1/models`.
 */
type ModelInfo = { id: string; display_name?: string; description?: string; opencode?: Record<string, any> }

const FALLBACK_MODEL_INFOS: ModelInfo[] = FALLBACK_MODELS.map((id) => ({ id }))

/** Strip JSONC comments and trailing commas so standard JSON.parse can handle it. */
function stripJsonc(text: string): string {
  return text
    .replace(/(?<!:)\/\/.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/,(\s*[}\]])/g, "$1")
}

/**
 * Infer the indentation unit of an existing JSON/JSONC document from its first
 * indented line, so rewrites preserve the user's tabs-or-spaces style. Falls back
 * to two spaces when nothing can be detected (empty, single-line, or minified).
 */
function detectIndent(text: string): string {
  const m = text.match(/^([ \t]+)\S/m)
  return m && m[1] ? m[1] : "  "
}

const isPlainObject = (v: unknown): v is Record<string, any> =>
  typeof v === "object" && v !== null && !Array.isArray(v)

/** Recursively merge `source` onto `target` (objects merge; arrays/scalars replace). */
function deepMerge<T extends Record<string, any>>(target: T, source: Record<string, any>): T {
  const out: Record<string, any> = { ...target }
  for (const [k, v] of Object.entries(source)) {
    out[k] = isPlainObject(v) && isPlainObject(out[k]) ? deepMerge(out[k], v) : v
  }
  return out as T
}

// Per-session overrides set by the /effort, /fast, /ultracode slash commands. The
// command hook and chat.headers run in the same plugin instance, so this module Map
// bridges them (command sets it → the next turn's headers read it).
type SessionOverride = { effort?: Effort | "auto"; fast?: boolean; baseUrl?: string }
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

function buildModel(info: ModelInfo, gatewayV1: string): Record<string, any> {
  const id = info.id
  const claude = isClaude(id)
  const reasoning = isReasoningModel(id)
  const oaiCompat = isOpenAICompatModel(id)
  const npm = oaiCompat ? "@ai-sdk/openai-compatible" : "@ai-sdk/anthropic"
  const model: Record<string, any> = {
    id,
    providerID: PROVIDER_ID,
    name: info.display_name || prettyName(id),
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

  // Carry the dashboard-set description (shown by pickers that support it).
  if (info.description) model.description = info.description
  // Deep-merge the admin's custom OpenCode config last, so it wins over the
  // computed defaults (name, limit, cost, capabilities, variants, …).
  return info.opencode ? deepMerge(model, info.opencode) : model
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
// Upstream-unavailable detection
// --------------------------------------------------------------------------- //

/** Status text shown to OpenCode when the gateway has no upstream to serve a request. */
const UPSTREAM_FAILED_STATUS = "Upstream Failed"

/**
 * Header that advertises this plugin to the gateway so it can return a dedicated
 * "no upstream available" status code (see UPSTREAM_UNAVAILABLE_CODE) instead of a
 * generic 502. It is read and consumed by the gateway and never reaches the real
 * upstream provider.
 */
const H_CLIENT_HINT = "x-voidswitch-client"
const CLIENT_HINT_VALUE = "opencode-plugin"

/**
 * Non-standard code the gateway returns *only to this plugin* when it has no
 * upstream to forward to. It ships with an empty HTTP reason phrase, so without
 * this rewrite OpenCode would show a bare code; we relabel it "Upstream Failed".
 */
const UPSTREAM_UNAVAILABLE_CODE = 543

/**
 * When the gateway can reach *us* but has no upstream to forward to (no usable
 * key, no route, every key exhausted) it answers 502/503 with a body carrying the
 * `upstream_unavailable` error type. The HTTP reason phrase for those codes is the
 * generic "Bad Gateway" / "Service Unavailable", which reads like the relay itself
 * broke. Rewrite such responses so OpenCode surfaces a clear "Upstream Failed"
 * status + message instead, leaving genuine gateway/transport faults untouched.
 *
 * Only small JSON error bodies (never a live SSE stream) are inspected: success
 * responses are returned verbatim, so streaming is unaffected.
 */
async function rewriteUpstreamError(res: Response): Promise<Response> {
  if (res.ok) return res
  const isDedicatedCode = res.status === UPSTREAM_UNAVAILABLE_CODE
  if (!isDedicatedCode && res.status !== 502 && res.status !== 503) return res
  let text: string
  try {
    text = await res.clone().text()
  } catch {
    return res
  }
  // The dedicated code is set by the gateway exclusively for this case, so trust it
  // outright; for 502/503 fall back to sniffing the body so we don't relabel a
  // genuine relay/transport fault.
  let isUpstream = isDedicatedCode
  let message = ""
  try {
    const j: any = JSON.parse(text)
    const errType: unknown = j?.error?.type ?? j?.type
    message = typeof j?.error?.message === "string" ? j.error.message : ""
    if (errType === "upstream_unavailable" || /upstream failed|all upstreams failed/i.test(message)) {
      isUpstream = true
    }
  } catch {
    // Non-JSON (e.g. an HTML 502 from an intermediary proxy) — that *is* a relay
    // fault, so leave it as a plain Bad Gateway.
  }
  if (!isUpstream) return res
  const body = JSON.stringify({
    type: "error",
    error: {
      type: "upstream_unavailable",
      message:
        message ||
        "Upstream Failed — no upstream is currently available (e.g. no usable provider key). This is an upstream issue, not the relay.",
    },
  })
  return new Response(body, {
    status: res.status,
    statusText: UPSTREAM_FAILED_STATUS,
    headers: { "content-type": "application/json" },
  })
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

function opencodeConfigPath(): string {
  return (
    process.env.OPENCODE_CONFIG ??
    join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "opencode", "opencode.json")
  )
}

function authJsonPath(): string {
  return join(
    process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share"),
    "opencode",
    "auth.json",
  )
}

function loadAuthToken(): string | undefined {
  try {
    const path = authJsonPath()
    if (!existsSync(path)) return undefined
    const raw = readFileSync(path, "utf8")
    const auth = JSON.parse(raw)
    const entry = auth?.[PROVIDER_ID]
    if (entry?.type === "api" && typeof entry.key === "string" && entry.key.startsWith("vs-")) {
      return entry.key
    }
  } catch {
    // auth.json not present or malformed — auth loader will handle this.
  }
  return undefined
}

/** Strip ANSI escape sequences and non-printable control characters from readline input. */
function sanitizeInput(s: string): string {
  return s
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "")
}

function loadPersistedBaseUrl(): string | undefined {
  try {
    if (!existsSync(opencodeConfigPath())) return undefined
    const raw = readFileSync(opencodeConfigPath(), "utf8")
    const cfg = JSON.parse(stripJsonc(raw))
    const baseURL = cfg?.provider?.[PROVIDER_ID]?.options?.baseURL
    if (typeof baseURL === "string") return stripV1(baseURL)
  } catch (e) {
    console.error("[VoidSwitch] loadPersistedBaseUrl failed:", e)
  }
  return undefined
}

function persistBaseUrl(url: string | undefined): void {
  try {
    const path = opencodeConfigPath()
    if (!existsSync(path)) return
    const raw = readFileSync(path, "utf8")
    const cfg = JSON.parse(stripJsonc(raw))
    if (!cfg) return
    if (!cfg.provider) cfg.provider = {}
    if (!cfg.provider[PROVIDER_ID]) cfg.provider[PROVIDER_ID] = {}
    if (!cfg.provider[PROVIDER_ID].options) cfg.provider[PROVIDER_ID].options = {}
    if (url) {
      cfg.provider[PROVIDER_ID].options.baseURL = url.replace(/\/+$/, "") + "/v1"
    } else {
      delete cfg.provider[PROVIDER_ID].options.baseURL
    }
    writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n")
  } catch (e) {
    console.error("[VoidSwitch] persistBaseUrl failed:", e)
  }
}

function persistModels(infos: ModelInfo[]): void {
  try {
    const path = opencodeConfigPath()
    if (!existsSync(path)) return
    const raw = readFileSync(path, "utf8")
    const cfg = JSON.parse(stripJsonc(raw))
    if (!cfg || !cfg.provider || !cfg.provider[PROVIDER_ID]) return
    const existing: Record<string, any> = cfg.provider[PROVIDER_ID].models ?? {}
    const models: Record<string, any> = {}
    for (const info of infos) {
      const prev = existing[info.id] ?? {}
      // Build an override from display_name, so the dashboard's Display name
      // field overrides the model name in the OpenCode picker.
      const override: Record<string, any> = { ...(info.opencode ?? {}) }
      if (info.display_name && !override.name) override.name = info.display_name
      models[info.id] =
        Object.keys(override).length > 0 ? deepMerge(prev, override) : prev
    }
    cfg.provider[PROVIDER_ID].models = models
    writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n")
  } catch (e) {
    console.error("[VoidSwitch] persistModels failed:", e)
  }
}

/** Minimal readline interface for interactive overwrite prompts. */
type AsyncReadline = { question: (query: string) => Promise<string> }

/**
 * Sync OpenCode's top-level `model` and `small_model` selectors from the
 * gateway's recommended defaults. Values are written as `voidswitch/<id>` (the
 * provider-prefixed form OpenCode resolves against this plugin's provider).
 *
 * Per selector:
 *   • gateway has no recommendation → left untouched (we never *remove* a key);
 *   • unset locally → set silently (nothing to overwrite);
 *   • already matches → skipped;
 *   • set to a *different* value → the user is asked to confirm the overwrite on
 *     the given readline interface (y/N), and kept unless they answer "y".
 *
 * The config file is read and written at most once. Returns a short status line
 * per selector touched or deliberately kept.
 */
async function persistDefaultModels(
  remote: { defaultModel?: string; smallModel?: string },
  rl: AsyncReadline,
): Promise<string[]> {
  const notes: string[] = []
  const path = opencodeConfigPath()
  if (!existsSync(path)) {
    notes.push("no opencode.json found — skipped default/small model sync")
    return notes
  }
  let raw: string
  let cfg: any
  try {
    raw = readFileSync(path, "utf8")
    cfg = JSON.parse(stripJsonc(raw))
  } catch (e) {
    console.error("[VoidSwitch] persistDefaultModels read failed:", e)
    return notes
  }
  if (!cfg || typeof cfg !== "object") return notes

  const targets: { key: "model" | "small_model"; id?: string; label: string }[] = [
    { key: "model", id: remote.defaultModel, label: "default model" },
    { key: "small_model", id: remote.smallModel, label: "small model" },
  ]

  let changed = false
  for (const t of targets) {
    if (!t.id) continue // gateway has no recommendation — leave the local key as-is
    const want = `${PROVIDER_ID}/${t.id}`
    const cur = cfg[t.key]
    if (cur === want) continue // already in sync
    if (cur === undefined || cur === null || cur === "") {
      cfg[t.key] = want
      changed = true
      notes.push(`${t.label}: set to ${want}`)
      continue
    }
    // Local holds a different value — confirm before overwriting.
    const ans = sanitizeInput(
      await rl.question(
        `\nYour ${t.label} is "${cur}", gateway recommends "${want}". Overwrite? (y/N): `,
      ),
    ).trim().toLowerCase()
    if (ans === "y" || ans === "yes") {
      cfg[t.key] = want
      changed = true
      notes.push(`${t.label}: overwritten to ${want}`)
    } else {
      notes.push(`${t.label}: kept "${cur}"`)
    }
  }

  if (changed) {
    try {
      writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n")
    } catch (e) {
      console.error("[VoidSwitch] persistDefaultModels write failed:", e)
    }
  }
  return notes
}

// --------------------------------------------------------------------------- //
// Plugin
// --------------------------------------------------------------------------- //

const stripV1 = (u: unknown): string | undefined =>
  typeof u === "string" ? u.replace(/\/v1\/?$/, "").replace(/\/+$/, "") : undefined

const VoidSwitchPlugin: Plugin = async (_input: PluginInput, options?: PluginOptions): Promise<Hooks> => {
  const opt = (options ?? {}) as VoidSwitchOptions
  const opn = _input.client
  // Gateway precedence: plugin option → env → persisted state → existing config
  // baseURL (adopted in the config hook) → default.
  let gateway = (
    opt.url ??
    process.env.VOIDSWITCH_URL ??
    loadPersistedBaseUrl() ??
    DEFAULT_GATEWAY
  ).replace(/\/+$/, "")
  let gatewayV1 = `${gateway}/v1`
  // Last vs-… token observed (from the auth loader / models ctx), so the
  // /models slash command can authenticate its refresh call to the gateway.
  let lastToken: string | undefined

  async function fetchModels(token: string | undefined): Promise<ModelInfo[]> {
    try {
      const res = await fetch(`${gatewayV1}/models`, {
        headers: token ? { "x-api-key": token } : {},
      })
      if (!res.ok) return FALLBACK_MODEL_INFOS
      const json: any = await res.json()
      const infos: ModelInfo[] = (json?.data ?? [])
        .map((m: any): ModelInfo => ({
          id: m?.id,
          display_name: typeof m?.display_name === "string" ? m.display_name : undefined,
          description: typeof m?.description === "string" ? m.description : undefined,
          opencode: isPlainObject(m?.opencode) ? m.opencode : undefined,
        }))
        .filter((m: ModelInfo) => typeof m.id === "string" && m.id.length > 0)
      return infos.length ? infos : FALLBACK_MODEL_INFOS
    } catch {
      return FALLBACK_MODEL_INFOS
    }
  }

  /**
   * The gateway's recommended OpenCode top-level selectors (`model` /
   * `small_model`), as bare model ids. Surfaced by `POST /v1/models/sync` so the
   * plugin can sync them alongside the provider model map. Empty when the
   * gateway has no recommendation (e.g. an older backend that omits the fields).
   */
  type RemoteDefaults = { defaultModel?: string; smallModel?: string }

  /**
   * Ask the gateway to refresh its catalog from the providers; returns a status
   * line plus the gateway's recommended OpenCode default / small model ids (so
   * the caller can sync the top-level config selectors in the same flow).
   */
  async function syncModels(): Promise<{ note: string; defaults: RemoteDefaults }> {
    const token = lastToken ?? loadAuthToken()
    if (token && !lastToken) lastToken = token
    const fail = (note: string): { note: string; defaults: RemoteDefaults } => ({
      note,
      defaults: {},
    })
    try {
      const res = await fetch(`${gatewayV1}/models/sync`, {
        method: "POST",
        headers: token ? { "x-api-key": token } : {},
      })
      if (res.status === 401)
        return fail("couldn't refresh models — not authenticated. Run /connect and paste a vs-… token first.")
      if (!res.ok) return fail(`couldn't refresh models (gateway returned ${res.status}).`)
      const j: any = await res.json()
      const pick = (v: unknown): string | undefined =>
        typeof v === "string" && v ? v : undefined
      return {
        note: `model catalog refreshed — ${j?.added ?? 0} new, ${j?.total ?? "?"} total. Reopen the model picker to see changes.`,
        defaults: {
          defaultModel: pick(j?.opencode_default_model),
          smallModel: pick(j?.opencode_small_model),
        },
      }
    } catch {
      return fail("couldn't reach the VoidSwitch gateway to refresh models.")
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

    // /effort, /fast, /ultracode — set the per-session override, show a toast,
    // and throw to skip the LLM turn. If the user appended a prompt it flows
    // through to the model.
    "command.execute.before": async (
      input: { command: string; sessionID: string; arguments: string },
      output: { parts: any[] },
    ) => {
      try {
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
          await opn.tui.showToast({ body: { message: `VoidSwitch: ${note}`, variant: "success" } }).catch(() => {})
          if (arg) { setCommandText(output, arg); return }
          throw new CommandHandledError()
        }
        if (input.command === "fast") {
          const isFlag = ["on", "off", "true", "false"].includes(head)
          st.fast = !(head === "off" || head === "false")
          note = `fast mode ${st.fast ? "ON" : "OFF"}`
          sessionState.set(input.sessionID, st)
          await opn.tui.showToast({ body: { message: `VoidSwitch: ${note}`, variant: "success" } }).catch(() => {})
          const prompt = isFlag ? rest : arg
          if (prompt) { setCommandText(output, prompt); return }
          throw new CommandHandledError()
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
        await opn.tui.showToast({ body: { message: `VoidSwitch: ${note}`, variant: "success" } }).catch(() => {})
        if (prompt) { setCommandText(output, prompt); return }
        throw new CommandHandledError()
      } catch (err) {
        if (err instanceof Error &&
            (err.name === "CommandHandledError" || err.message?.includes("-command-handled"))) {
          return
        }
        console.error("[VoidSwitch] command.execute.before error:", err)
      }
    },

    // Auth: paste a vs-… token. The loader hands the AI SDK the apiKey (sent as
    // x-api-key) plus a fetch that injects the Claude Code request fields.
    auth: {
      provider: PROVIDER_ID,
      async loader(getAuth) {
        const auth = await getAuth()
        const apiKey = auth?.type === "api" ? auth.key : ""
        if (apiKey) lastToken = apiKey
        return {
          apiKey,
          async fetch(reqInput: RequestInfo | URL, init?: RequestInit) {
            const headers = new Headers(reqInput instanceof Request ? reqInput.headers : undefined)
            applyInitHeaders(headers, init)

            // Advertise ourselves so the gateway returns the dedicated
            // "upstream unavailable" code instead of a generic 502. Consumed by
            // the gateway; never forwarded to the real upstream provider.
            headers.set(H_CLIENT_HINT, CLIENT_HINT_VALUE)

            const effort = takeHeader(headers, H_EFFORT)
            const speed = takeHeader(headers, H_SPEED)
            const thinking = takeHeader(headers, H_THINKING)
            const baseUrlOverride = takeHeader(headers, H_BASE_URL)

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

            let url = typeof reqInput === "string" ? reqInput : reqInput instanceof URL ? reqInput.toString() : reqInput.url
            if (baseUrlOverride) {
              try {
                const parsed = new URL(url)
                const over = new URL(baseUrlOverride)
                parsed.protocol = over.protocol
                parsed.host = over.host
                parsed.hostname = over.hostname
                parsed.port = over.port
                url = parsed.toString()
              } catch {
                // keep original on malformed URL
              }
            }
            const method = init?.method ?? (reqInput instanceof Request ? reqInput.method : "POST")
            const res = await fetch(url, { ...init, method, headers, body: bodyText ?? init?.body })
            // Relabel "no upstream available" gateway errors so OpenCode shows
            // "Upstream Failed" rather than a generic "Bad Gateway".
            return rewriteUpstreamError(res)
          },
        }
      },
      methods: [
        { type: "api", label: "Paste a VoidSwitch token (vs-…)" },
        {
          type: "oauth" as const,
          label: "Configure VoidSwitch (Base URL / Sync Models)",
          async authorize() {
            const { createInterface } = await import("node:readline/promises")
            const { stdin, stdout } = await import("node:process")
            const rl = createInterface({ input: stdin, output: stdout })
            try {
              console.log("\n═══ VoidSwitch Configuration ═══")
              console.log("1. Switch Gateway Base URL")
              console.log("2. Sync Models from Gateway")
              const action = sanitizeInput(await rl.question("\nChoose an option (1-2, Enter to cancel): ")).trim()
              if (action === "1") {
                const current = loadPersistedBaseUrl() ?? gateway
                console.log(`Current base URL: ${current}`)
                const url = sanitizeInput(await rl.question("New Base URL (blank to reset to default): ")).trim()
                if (url) {
                  const normalised = url.replace(/\/+$/, "")
                  persistBaseUrl(normalised)
                  opt.url = normalised
                  gateway = normalised
                  gatewayV1 = `${gateway}/v1`
                  console.log(`\nBase URL set to ${gateway}.`)
                  console.log("Restart OpenCode for the change to take full effect.")
                } else {
                  persistBaseUrl(undefined)
                  opt.url = undefined
                  gateway = (process.env.VOIDSWITCH_URL ?? DEFAULT_GATEWAY).replace(/\/+$/, "")
                  gatewayV1 = `${gateway}/v1`
                  console.log(`\nBase URL reset to default: ${gateway}`)
                }
              } else if (action === "2") {
                console.log("\nSyncing models from gateway...")
                const { note, defaults } = await syncModels()
                console.log(note)
                if (!note.includes("couldn't") && !note.includes("not authenticated")) {
                  try {
                    const infos = await fetchModels(lastToken ?? loadAuthToken())
                    persistModels(infos)
                    console.log(`${infos.length} models written to config.`)
                    // Sync the top-level `model` / `small_model` selectors from
                    // the gateway's recommended defaults. A selector that is set
                    // locally to a *different* value prompts for overwrite
                    // confirmation on this same readline interface.
                    const defNotes = await persistDefaultModels(defaults, rl)
                    for (const n of defNotes) console.log(n)
                    console.log("Reopen the model picker to see changes.")
                  } catch (e) {
                    console.error("[VoidSwitch] model persist failed:", e)
                  }
                }
              }
            } finally {
              rl.close()
            }
            return {
              url: "",
              instructions: "",
              method: "auto" as const,
              async callback() {
                return { type: "success" as const }
              },
            }
          },
        },
      ],
    },

    // Live model list from the gateway; claude models get effort/fast variants.
    provider: {
      id: PROVIDER_ID,
      async models(_provider, ctx) {
        const token = ctx.auth?.type === "api" ? ctx.auth.key : undefined
        if (token) lastToken = token
        const infos = await fetchModels(token)
        const out: Record<string, any> = {}
        for (const info of infos) out[info.id] = buildModel(info, gatewayV1)
        return out
      },
    },

    // Carry the picker's effort/mode selection to the body-rewriting fetch, and
    // request the betas the chosen features need.
    "chat.headers": async (input: any, output: { headers: Record<string, string> }) => {
      if (input.model?.providerID !== PROVIDER_ID) return
      // Forward OpenCode's session id for *every* VoidSwitch model (not just
      // Claude) so the gateway's per-session pinned key modes work regardless of
      // upstream dialect. Sent straight to the gateway — not a stripped bridge header.
      if (input.sessionID) output.headers[H_SESSION] = input.sessionID
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
      const baseUrl = st.baseUrl

      if (effort) output.headers[H_EFFORT] = effort
      if (fast) output.headers[H_SPEED] = "fast"
      if (thinking) output.headers[H_THINKING] = "adaptive"
      if (baseUrl) output.headers[H_BASE_URL] = baseUrl
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
