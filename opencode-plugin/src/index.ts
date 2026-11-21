/**
 * VoidSwitch — deep OpenCode **V2** integration.
 *
 * Registers VoidSwitch as a first-class provider and reproduces the *full* Claude
 * Code request surface end-to-end, so OpenCode driving a VoidSwitch `claude-code`
 * upstream behaves like the real CLI:
 *
 *   • auth        — paste a `vs-…` token via the integration key method
 *   • models      — pulled live from `<gateway>/v1/models`
 *   • palette     — Ctrl+P commands (sync models, set gateway, configure MCP
 *                   server) via the RPC contract in rpc.ts and the TUI part in
 *                   tui.ts; a directory plugin loads all three parts together
 *   • mcp         — the gateway's management API (`/api/v1/mcp`) registered as
 *                   an OpenCode MCP server from a `vsapi-…` platform API key
 *   • effort      — `output_config.effort` ∈ low|medium|high|xhigh|max, picker variants
 *   • fast mode   — top-level `speed: "fast"` (Claude Code's /fast), picker variant
 *   • thinking    — adaptive extended thinking on 4.6+ models
 *   • betas       — the matching `anthropic-beta` tokens, unioned onto the request
 *
 * Why the design works: OpenCode speaks the Anthropic dialect to VoidSwitch
 * (`@opencode/ai/providers/anthropic` → `<gateway>/v1/messages`). V2's Anthropic
 * route already lowers `output_config.effort`, `speed`, and `thinking` from
 * semantic request options, so this plugin does not rewrite a serialized request
 * body the way the V1 plugin had to. It sets those options from the `context`
 * hook and lets the route build the wire body.
 *
 * Wire facts are taken verbatim from the Claude Code CLI bundle:
 *   - effort enum = ["low","medium","high","xhigh","max"], carried in output_config.effort
 *   - fast mode: top-level `speed: "fast"`
 */

import { Model, Plugin, Provider } from "@opencode/plugin";
import { VoidSwitchRpc, type McpStatusInfo, type SyncResult } from "./rpc";
import {
  appendFileSync,
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

// --------------------------------------------------------------------------- //
// Constants mirrored from the Claude Code wire format
// --------------------------------------------------------------------------- //

const PROVIDER_ID = "voidswitch";
const DISPLAY_NAME = "VoidSwitch";

/** V2 provider runtime package: the native Anthropic Messages route. */
const ANTHROPIC_PACKAGE = "@opencode/ai/providers/anthropic";

/** Claude Code's effort enum, lowest → highest. */
const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const;
type Effort = (typeof EFFORT_LEVELS)[number];

/** Picker variant that turns on fast mode instead of selecting an effort. */
const FAST_VARIANT = "fast";

/**
 * Picker variant mirroring Claude Code's "ultracode" — it resolves to `xhigh`
 * effort. Claude Code's ultracode *also* turns on standing dynamic-workflow
 * orchestration, but that is a CLI harness behaviour with no `/v1/messages`
 * representation, so only the effort half is reproduced.
 */
const ULTRACODE_VARIANT = "ultracode";

/** `anthropic-beta` tokens each feature requires; unioned onto the outgoing header. */
const BETA_EFFORT = "effort-2025-11-24";
const BETA_TASK_BUDGET = "task-budgets-2026-03-13";
const BETA_CONTEXT_MGMT = "context-management-2025-06-27";
const BETA_LONG_CONTEXT = "context-1m-2025-08-07";

/** Verified context-management edit type Claude Code sends (this CLI build). */
const CONTEXT_EDIT_TYPE = "clear_thinking_20251015";
/** Anthropic's minimum cumulative agentic budget. */
const TASK_BUDGET_MIN = 20_000;
/** Auto-enable 1M context once the serialized prompt is this large (~150k tokens). */
const LONG_CONTEXT_CHARS = 600_000;

/** Gateway used when nothing is configured: the public VoidSwitch instance. */
const DEFAULT_GATEWAY = "https://voidswitch.siiway.org";
/**
 * Install-time gateway, baked into this file by the /install.sh (or /install.ps1)
 * script as the host the installer was fetched from — so a self-hosted install
 * points at its own gateway without extra configuration. Empty otherwise.
 */
const INSTALL_GATEWAY = ""; // @voidswitch-install-host

/** Header advertising this plugin to the gateway (consumed there, never forwarded). */
const CLIENT_HINT_HEADER = "x-voidswitch-client";
/** Value identifies the OpenCode client family to the gateway. */
const CLIENT_HINT_VALUE = "opencode-plugin";
/** Identifies this plugin generation, so the gateway can log v2 vs v1. */
const CLIENT_VERSION_HEADER = "x-voidswitch-client-version";
const CLIENT_VERSION_VALUE = "v2";
/** Native per-conversation session id, forwarded so per-session key pinning works. */
const SESSION_HEADER = "x-voidswitch-session";

/** MCP server name registered with OpenCode; also the name used in the palette. */
const MCP_SERVER_NAME = "voidswitch";
/** Platform API keys carry this prefix; a `vs-…` token only drives the gateway. */
const MCP_KEY_PREFIX = "vsapi-";
/** A platform-API probe must not stall the palette when the gateway hangs. */
const WHOAMI_TIMEOUT_MS = 10_000;

/** Fallback model list when `/v1/models` is unreachable (offline picker). */
const FALLBACK_MODELS = [
  "claude-opus-4-8",
  "claude-opus-4-7",
  "claude-opus-4-6",
  "claude-sonnet-4-6",
  "deepseek-v4-pro",
  "deepseek-v4-flash",
];

/**
 * `Integration.ID` is a bare branded string with no `make()` helper, so the
 * provider's integration linkage has to be asserted once here.
 */
const INTEGRATION_ID = PROVIDER_ID as unknown as NonNullable<
  Provider.Info["integrationID"]
>;

/**
 * A model id plus its optional VoidSwitch catalog metadata: a human description
 * and a custom OpenCode model config (deep-merged into the built model block, so
 * admins can tune name/limit/cost/capabilities/variants per model from the
 * dashboard's Models page). Both come from `<gateway>/v1/models`.
 */
type ModelInfo = {
  id: string;
  display_name?: string;
  description?: string;
  opencode?: Record<string, any>;
  opencode_v2?: Record<string, any>;
};

const FALLBACK_MODEL_INFOS: ModelInfo[] = FALLBACK_MODELS.map((id) => ({ id }));

/** Strip JSONC comments and trailing commas so standard JSON.parse can handle it. */
function stripJsonc(text: string): string {
  return text
    .replace(/(?<!:)\/\/.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/,(\s*[}\]])/g, "$1");
}

/**
 * Infer the indentation unit of an existing JSON/JSONC document from its first
 * indented line, so rewrites preserve the user's tabs-or-spaces style.
 */
function detectIndent(text: string): string {
  const m = text.match(/^([ \t]+)\S/m);
  return m && m[1] ? m[1] : "  ";
}

const isPlainObject = (v: unknown): v is Record<string, any> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Recursively merge `source` onto `target` (objects merge; arrays/scalars replace). */
function deepMerge<T extends Record<string, any>>(
  target: T,
  source: Record<string, any>,
): T {
  const out: Record<string, any> = { ...target };
  for (const [k, v] of Object.entries(source)) {
    out[k] =
      isPlainObject(v) && isPlainObject(out[k]) ? deepMerge(out[k], v) : v;
  }
  return out as T;
}

/**
 * Per-session overrides set by the /effort, /fast and /ultracode commands. The
 * command executor and the `context` hook run in the same plugin instance, so
 * this module Map bridges them.
 */
type SessionOverride = { effort?: Effort | "auto"; fast?: boolean };
const sessionState = new Map<string, SessionOverride>();

// --------------------------------------------------------------------------- //
// Plugin options (opencode.json: plugins: [{ package, options: { ... } }])
// --------------------------------------------------------------------------- //

interface VoidSwitchOptions {
  /** Gateway base URL, e.g. "https://gw.example.com". Falls back to $VOIDSWITCH_URL. */
  url?: string;
  /** Default effort when no picker variant is chosen. "default" = let the model decide. */
  effort?: Effort | "ultracode" | "default";
  /** Enable adaptive extended thinking on 4.6+ models (default: true). */
  thinking?: boolean;
  /** Surface thinking text on Opus 4.7/4.8 (default: "summarized"; "omitted" hides it). */
  thinkingDisplay?: "summarized" | "omitted";
  /** Force fast mode on every request regardless of the selected variant. */
  fast?: boolean;
  /** 1M context: true = always, false = never, "auto"/unset = enable on large prompts. */
  context1m?: boolean | "auto";
  /** Server-side context management (auto-clears old thinking blocks for long sessions). */
  contextManagement?: boolean;
  /** Cumulative agentic token budget for the whole loop (output_config.task_budget). */
  taskBudget?: number;
}

// --------------------------------------------------------------------------- //
// Model-capability helpers (mirror Claude Code's per-model effort gating)
// --------------------------------------------------------------------------- //

const isClaude = (id: string) => /claude/i.test(id);
const isOpus = (id: string) => /opus/i.test(id);
/**
 * Non-Claude upstreams that stream `reasoning_content` (DeepSeek R-series, etc.).
 * They must be marked reasoning-capable so OpenCode persists and replays their
 * thinking blocks: DeepSeek's interleaved thinking mode rejects any follow-up
 * turn whose assistant message dropped the prior `reasoning_content`.
 */
const isReasoningModel = (id: string) =>
  isClaude(id) || /deepseek|reasoner|-r1\b|qwq|thinking/i.test(id);
/**
 * Reasoning models that VoidSwitch serves in the *OpenAI* dialect (DeepSeek &c).
 * Their chain-of-thought round-trips as `reasoning_content`, so they must be
 * driven through the openai-compatible runtime, not Anthropic.
 */
const isOpenAICompatModel = (id: string) => /deepseek/i.test(id);
/** Effort param is GA on Opus 4.6+ and Sonnet 4.6 ("Opus 4.6+, Sonnet 4.6"). */
const effortCapable = (id: string) =>
  /opus-4-[6-9]/.test(id) || /sonnet-4-[6-9]/.test(id);
/** `xhigh` is "Opus 4.8/4.7 only". */
const xhighCapable = (id: string) => /opus-4-[78]/.test(id);
/** `max` is Opus-tier only (4.6+). */
const maxCapable = (id: string) => /opus-4-[6-9]/.test(id);
/** Adaptive thinking is supported on the 4.6+ generation. */
const adaptiveCapable = (id: string) =>
  /opus-4-[6-9]/.test(id) || /sonnet-4-[6-9]/.test(id);

/** Downgrade an effort the model can't honour, exactly as the CLI does (→ "high"). */
function clampEffort(id: string, effort: Effort): Effort {
  if (effort === "max" && !maxCapable(id)) return "high";
  if (effort === "xhigh" && !xhighCapable(id)) return "high";
  return effort;
}

function isEffort(value: unknown): value is Effort {
  return (
    typeof value === "string" &&
    (EFFORT_LEVELS as readonly string[]).includes(value)
  );
}

function prettyName(id: string): string {
  const m = id.match(/^claude-(opus|sonnet|haiku)-(\d)-(\d+)/i);
  if (m)
    return `Claude ${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`;
  return id;
}

function releaseDateMs(value: unknown): number {
  if (typeof value !== "string") return 0;
  const t = Date.parse(value);
  return Number.isFinite(t) && t > 0 ? Math.trunc(t) : 0;
}

// --------------------------------------------------------------------------- //
// Model construction (V2 Model.Info shape)
// --------------------------------------------------------------------------- //

/**
 * Build one V2 `Model.Info` entry. Start from `Model.Info.default` so every
 * required field exists, then layer on the computed capabilities, limits and
 * picker variants, and finally deep-merge the admin's custom OpenCode config so
 * it wins over the computed defaults.
 */
function buildModel(info: ModelInfo, gatewayV1: string): Model.Info {
  const id = info.id;
  const claude = isClaude(id);
  const reasoning = isReasoningModel(id);
  const oaiCompat = isOpenAICompatModel(id);

  const base = Model.Info.default(
    Provider.ID.make(PROVIDER_ID),
    Model.ID.make(id),
  );
  const model: any = {
    ...base,
    modelID: id,
    name: info.display_name || prettyName(id),
    capabilities: {
      ...base.capabilities,
      tools: true,
      // V2 expresses media support as string lists.
      input: claude ? ["text", "image", "pdf"] : ["text"],
      output: ["text"],
      // Anthropic requires temperature == 1 once extended thinking is on.
      temperature: true,
    },
    limit: {
      context: claude ? 1_000_000 : 200_000,
      output: isOpus(id) ? 128_000 : claude ? 64_000 : 8_192,
    },
    cost: [
      {
        input: 0,
        output: 0,
        cache: { read: 0, write: 0 },
      },
    ],
    status: "active" as const,
    enabled: true,
    variants: [] as any[],
  };

  // Keep OpenAI-dialect reasoners inside this single provider (one token, one
  // auth) but route them through the OpenAI-compatible runtime, and re-attach
  // chain-of-thought through `reasoning_content`.
  if (oaiCompat) {
    model.package = "@opencode/ai/providers/openai-compatible";
    model.compatibility = { reasoningField: "reasoning_content" };
  } else {
    model.compatibility = reasoning ? { requireReasoning: false } : undefined;
  }

  // Expose effort levels (and fast mode) as picker variants for capable models.
  // V2 variants carry their own `body`, so the route sends the right wire field
  // without any header round-trip.
  if (claude && effortCapable(id)) {
    const variants: any[] = [];
    for (const e of EFFORT_LEVELS) {
      if (e === "xhigh" && !xhighCapable(id)) continue;
      if (e === "max" && !maxCapable(id)) continue;
      variants.push({ id: e, body: { output_config: { effort: e } } });
    }
    if (xhighCapable(id))
      variants.push({
        id: ULTRACODE_VARIANT,
        body: { output_config: { effort: "xhigh" } },
      });
    variants.push({ id: FAST_VARIANT, body: { speed: "fast" } });
    model.variants = variants;
  }

  // Carry the dashboard-set description (shown by pickers that support it).
  if (info.description) model.name = info.display_name || prettyName(id);
  // Deep-merge the admin's custom OpenCode config last, so it wins over the
  // computed defaults (name, limit, cost, capabilities, variants, …). The V2
  // block is authoritative; a V1-only gateway is projected onto the V2 shape
  // first, because V1's dict `variants`/`options` are rejected by OpenCode 2.
  const override = modelOverride(info);
  return Object.keys(override).length > 0 ? deepMerge(model, override) : model;
}

// --------------------------------------------------------------------------- //
// Request diagnostics
// --------------------------------------------------------------------------- //

/** Cap on how much of a response body we echo into a diagnostic string. */
const DIAG_BODY_LIMIT = 800;

/**
 * Build a compact, human-readable diagnostic string for a *failed* gateway
 * response, so users can paste it verbatim when reporting an issue:
 *
 *   • request  — the exact URL that was hit (method optional);
 *   • status   — the HTTP status + reason phrase;
 *   • cf-ray   — Cloudflare's ray id when present (tells "CF blocked it" apart
 *                from a real gateway error);
 *   • response — a truncated copy of the body.
 */
async function describeHttpError(
  url: string,
  res: Response,
  method?: string,
): Promise<string> {
  const parts: string[] = [];
  parts.push(`request: ${method ? method + " " : ""}${url}`);
  parts.push(
    `status: ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`,
  );
  const cfRay = res.headers.get("cf-ray");
  if (cfRay) parts.push(`cf-ray: ${cfRay}`);
  const cfCacheStatus = res.headers.get("cf-cache-status");
  if (cfCacheStatus) parts.push(`cf-cache-status: ${cfCacheStatus}`);
  let body = "";
  try {
    body = (await res.clone().text()).trim();
  } catch {
    // Body already consumed or not readable — the status + cf-ray still help.
  }
  if (body) {
    parts.push(
      `response: ${body.length > DIAG_BODY_LIMIT ? body.slice(0, DIAG_BODY_LIMIT) + " …(truncated)" : body}`,
    );
  }
  return parts.join("\n");
}

/** Diagnostic string for a request that never produced a response (network/DNS/TLS). */
function describeFetchError(
  url: string,
  err: unknown,
  method?: string,
): string {
  return [
    `request: ${method ? method + " " : ""}${url}`,
    `error: ${err instanceof Error ? `${err.name}: ${err.message}` : String(err)}`,
  ].join("\n");
}

/** Max lines kept in voidswitch-error.log; older lines are dropped on write. */
const LOG_MAX_LINES = 1000;

/** Error log lives next to opencode.json so it's easy to find alongside the config. */
function errorLogPath(): string {
  return join(dirname(opencodeConfigPath()), "voidswitch-error.log");
}

/**
 * Append a timestamped, `[VoidSwitch]`-prefixed entry to voidswitch-error.log,
 * then rotate the file down to its last LOG_MAX_LINES lines so it never grows
 * unbounded. Logging must never throw — a failure here is swallowed.
 */
function logToFile(message: string): void {
  try {
    const path = errorLogPath();
    appendFileSync(
      path,
      `[${new Date().toISOString()}] [VoidSwitch] ${message}\n`,
    );
    const lines = readFileSync(path, "utf8").split("\n");
    if (lines[lines.length - 1] === "") lines.pop();
    if (lines.length > LOG_MAX_LINES) {
      writeFileSync(path, lines.slice(-LOG_MAX_LINES).join("\n") + "\n");
    }
  } catch {
    // Never let logging break a request.
  }
}

/**
 * Record a diagnostic. Always writes to voidswitch-error.log; also mirrors it to
 * the console when `toConsole` is true.
 */
function recordError(message: string, toConsole: boolean): void {
  if (toConsole) console.error(`[VoidSwitch] ${message}`);
  logToFile(message);
}

// --------------------------------------------------------------------------- //
// Config-file helpers
// --------------------------------------------------------------------------- //

function opencodeConfigPath(): string {
  return (
    process.env.OPENCODE_CONFIG ??
    join(
      process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"),
      "opencode",
      "opencode.json",
    )
  );
}

/** Strip ANSI escape sequences and non-printable control characters from readline input. */
function sanitizeInput(s: string): string {
  return s
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "");
}

const stripV1 = (u: unknown): string | undefined =>
  typeof u === "string"
    ? u.replace(/\/v1\/?$/, "").replace(/\/+$/, "")
    : undefined;

/**
 * Read the gateway base URL persisted by an earlier session. V2 keeps provider
 * settings under `providers` (plural) with `settings.baseURL`, but we also honour
 * a V1 `provider.<id>.options.baseURL` block so an in-place upgrade keeps working.
 */
function loadPersistedBaseUrl(): string | undefined {
  try {
    if (!existsSync(opencodeConfigPath())) return undefined;
    const raw = readFileSync(opencodeConfigPath(), "utf8");
    const cfg = JSON.parse(stripJsonc(raw));
    const v2 = cfg?.providers?.[PROVIDER_ID]?.settings?.baseURL;
    if (typeof v2 === "string") return stripV1(v2);
    const v1 = cfg?.provider?.[PROVIDER_ID]?.options?.baseURL;
    if (typeof v1 === "string") return stripV1(v1);
  } catch (e) {
    console.error("[VoidSwitch] loadPersistedBaseUrl failed:", e);
  }
  return undefined;
}

/**
 * Persist the gateway URL into the V2 `providers.voidswitch.settings.baseURL`
 * block so it survives a restart without re-running the command. Passing
 * `undefined` clears the key (back to the default).
 */
function persistBaseUrl(url: string | undefined): void {
  try {
    const path = opencodeConfigPath();
    if (!existsSync(path)) return;
    const raw = readFileSync(path, "utf8");
    const cfg = JSON.parse(stripJsonc(raw));
    if (!cfg) return;
    if (!cfg.providers) cfg.providers = {};
    if (!cfg.providers[PROVIDER_ID]) cfg.providers[PROVIDER_ID] = {};
    const block = cfg.providers[PROVIDER_ID];
    if (!block.settings) block.settings = {};
    if (url) {
      block.settings.baseURL = url.replace(/\/+$/, "") + "/v1";
    } else {
      delete block.settings.baseURL;
    }
    writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n");
  } catch (e) {
    console.error("[VoidSwitch] persistBaseUrl failed:", e);
  }
}

/**
 * Map the gateway's V1-shaped capability flags (`{text,image,tool}`) onto the
 * V2 config form (`{input:[...], tools:bool}`). Writing the V1 shape verbatim
 * makes OpenCode silently drop the capabilities.
 */
function v2Capabilities(raw: any): Record<string, any> | undefined {
  if (!isPlainObject(raw)) return undefined;
  const caps: Record<string, any> = {};
  const input: string[] = [];
  if (raw.text === true) input.push("text");
  if (raw.image === true) input.push("image");
  if (raw.audio === true) input.push("audio");
  if (raw.pdf === true) input.push("pdf");
  if (input.length > 0) caps.input = input;
  if (raw.tool === true) caps.tools = true;
  return Object.keys(caps).length > 0 ? caps : undefined;
}

/**
 * Project a V1-shaped model override onto the V2 vocabulary. Used when the
 * gateway predates `opencode_v2`: the V1 block keeps `variants` as a dict and
 * carries `options`/`reasoning`, which OpenCode 2 rejects (and which would make
 * it discard the whole provider block).
 */
function v2Override(meta: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  if (typeof meta.name === "string") out.name = meta.name;
  if (typeof meta.description === "string") out.description = meta.description;
  if (isPlainObject(meta.limit)) out.limit = meta.limit;
  const caps = v2Capabilities(meta.capabilities);
  if (caps) out.capabilities = caps;
  if (Array.isArray(meta.variants)) out.variants = meta.variants;
  return out;
}

/**
 * The model override to apply: the gateway's own V2 block when it carries
 * anything, otherwise the V1 block projected onto the V2 shape. An empty V2
 * block must not shadow a populated V1 block — a gateway that only configured
 * `opencode_config` would otherwise silently stop affecting V2 clients.
 */
function modelOverride(info: ModelInfo): Record<string, any> {
  if (info.opencode_v2 && Object.keys(info.opencode_v2).length > 0)
    return info.opencode_v2;
  return v2Override(info.opencode ?? {});
}

/**
 * Write the live catalog into `providers.voidswitch.models` so an offline start
 * still shows the last-known model list.
 */
function persistModels(infos: ModelInfo[]): void {
  try {
    const path = opencodeConfigPath();
    if (!existsSync(path)) return;
    const raw = readFileSync(path, "utf8");
    const cfg = JSON.parse(stripJsonc(raw));
    // Only persist when the user already has a VoidSwitch block (the plugin's
    // provider is registered runtime-side otherwise).
    if (!cfg?.providers?.[PROVIDER_ID]) return;
    const block = cfg.providers[PROVIDER_ID];
    const existing: Record<string, any> = block.models ?? {};
    const models: Record<string, any> = {};
    for (const info of infos) {
      const prev: Record<string, any> = { ...(existing[info.id] ?? {}) };
      // OpenCode rejects the whole provider block when a recognised field has
      // the wrong shape, so scrub shapes written by older plugin builds: V1
      // keeps `variants` as a dict and uses `options`/`reasoning`, while V2
      // wants an array (and ignores the rest).
      if (prev.variants !== undefined && !Array.isArray(prev.variants))
        delete prev.variants;
      delete prev.options;
      delete prev.reasoning;
      // Scrub only shapes written by older builds: a user's hand-written V2
      // capabilities (input/output lists) must survive every sync.
      const rawCaps = prev.capabilities;
      if (isPlainObject(rawCaps)) {
        const hasV2Shape =
          Array.isArray(rawCaps.input) ||
          Array.isArray(rawCaps.output) ||
          rawCaps.tools !== undefined ||
          rawCaps.reasoning !== undefined;
        const looksV1 = ["text", "image", "audio", "pdf", "tool"].some(
          (k) => k in rawCaps,
        );
        if (looksV1 && !hasV2Shape) {
          const mapped = v2Capabilities(rawCaps);
          if (mapped) prev.capabilities = mapped;
          else delete prev.capabilities;
        }
      }

      // The gateway's dedicated V2 block is already in the right vocabulary;
      // a V1-only gateway is projected so the persisted config cannot poison
      // the provider with an unrecognised shape.
      const override = modelOverride(info);
      const merged = deepMerge(prev, override);
      if (!merged.name && info.display_name) merged.name = info.display_name;
      models[info.id] = merged;
    }
    block.models = models;
    writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n");
  } catch (e) {
    console.error("[VoidSwitch] persistModels failed:", e);
  }
}

/**
 * Sync OpenCode's top-level `model` selector from the gateway's recommended
 * default. Values are written as `voidswitch/<id>`. An unset key is filled
 * silently; a key holding a *different* value is left untouched (V2 commands run
 * without an interactive prompt, so we never overwrite the user's choice).
 */
function persistDefaultModels(remote: {
  defaultModel?: string;
  smallModel?: string;
}): string[] {
  const notes: string[] = [];
  const path = opencodeConfigPath();
  if (!existsSync(path)) {
    notes.push("no opencode.json found — skipped default model sync");
    return notes;
  }
  let raw: string;
  let cfg: any;
  try {
    raw = readFileSync(path, "utf8");
    cfg = JSON.parse(stripJsonc(raw));
  } catch (e) {
    console.error("[VoidSwitch] persistDefaultModels read failed:", e);
    return notes;
  }
  if (!cfg || typeof cfg !== "object") return notes;

  const targets: {
    key: "model" | "small_model";
    id?: string;
    label: string;
  }[] = [
    { key: "model", id: remote.defaultModel, label: "default model" },
    { key: "small_model", id: remote.smallModel, label: "small model" },
  ];

  let changed = false;
  for (const t of targets) {
    if (!t.id) continue;
    const want = `${PROVIDER_ID}/${t.id}`;
    const cur = cfg[t.key];
    if (cur === want) continue;
    if (cur === undefined || cur === null || cur === "") {
      cfg[t.key] = want;
      changed = true;
      notes.push(`${t.label}: set to ${want}`);
      continue;
    }
    notes.push(`${t.label}: kept "${cur}" (gateway recommends "${want}")`);
  }

  if (changed) {
    try {
      writeFileSync(path, JSON.stringify(cfg, null, detectIndent(raw)) + "\n");
    } catch (e) {
      console.error("[VoidSwitch] persistDefaultModels write failed:", e);
    }
  }
  return notes;
}

// --------------------------------------------------------------------------- //
// Platform MCP server sidecar (key + on/off state, never opencode.json)
// --------------------------------------------------------------------------- //

/** What the sidecar persists: key, the gateway's fingerprint for it, on/off. */
interface McpState {
  key: string;
  enabled: boolean;
  /** The gateway's own irreversible fingerprint, shown in status lines. */
  prefix?: string;
}

/**
 * Sidecar path under the user's config directory. It deliberately ignores
 * `OPENCODE_CONFIG`, which may point at a project file — a secret must never
 * land inside a repository.
 */
function mcpStatePath(): string {
  return join(
    process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"),
    "opencode",
    "voidswitch-mcp.json",
  );
}

/**
 * Read the sidecar; anything missing, malformed or not holding a platform key
 * counts as "not installed", so a hand-edited file cannot register junk.
 */
function readMcpState(): McpState | undefined {
  try {
    const state = JSON.parse(readFileSync(mcpStatePath(), "utf8"));
    const key = state?.key;
    if (typeof key !== "string" || !key.startsWith(MCP_KEY_PREFIX))
      return undefined;
    return {
      key,
      enabled: state.enabled !== false,
      prefix: typeof state.prefix === "string" ? state.prefix : undefined,
    };
  } catch {
    return undefined;
  }
}

/**
 * Persist the sidecar with owner-only permissions (or delete it for
 * `undefined`). A failure is returned instead of thrown, so an unwritable path
 * cannot leave memory and disk disagreeing.
 */
function writeMcpState(state: McpState | undefined): string | undefined {
  const path = mcpStatePath();
  try {
    if (!state) {
      if (existsSync(path)) unlinkSync(path);
      return undefined;
    }
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
    chmodSync(path, 0o600);
    return undefined;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

/** Half-masked key preview (`vsapi-ab12cd…wxyz`), safe for status lines. */
function maskPlatformKey(key: string): string {
  if (key.length <= 16) return `${key.slice(0, 6)}…`;
  return `${key.slice(0, 12)}…${key.slice(-4)}`;
}

/**
 * A `mcp.servers.voidswitch` block the user may have written into
 * `opencode.json` by hand. The plugin never writes one, but a leftover block
 * would silently lose to the transform, so setup mentions it.
 */
function configMcpServer(): Record<string, any> | undefined {
  try {
    const path = opencodeConfigPath();
    if (!existsSync(path)) return undefined;
    const cfg = JSON.parse(stripJsonc(readFileSync(path, "utf8")));
    const block = cfg?.mcp?.servers?.[MCP_SERVER_NAME];
    return isPlainObject(block) ? block : undefined;
  } catch {
    return undefined;
  }
}

// --------------------------------------------------------------------------- //
// Auth resolution (integration key method → credential)
// --------------------------------------------------------------------------- //

/** Pull the secret out of whatever shape a resolved credential arrives in. */
function extractCredentialKey(credential: unknown): string | undefined {
  if (!credential || typeof credential !== "object") return undefined;
  const c = credential as Record<string, any>;
  if (typeof c.key === "string" && c.key.length > 0) return c.key;
  for (const k of ["apiKey", "token", "value", "secret"]) {
    const v = c[k];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return undefined;
}

/**
 * Resolve the `vs-…` token concurrently in use. Tries the integration
 * connection first (the V2 `/connect` path), then the `VOIDSWITCH_TOKEN`
 * environment variable. Returns `undefined` when nothing is connected yet.
 */
async function resolveToken(ctx: Plugin.Context): Promise<string | undefined> {
  try {
    const connection = await ctx.integration.connection.active(PROVIDER_ID);
    if (connection) {
      const credential = await ctx.integration.connection.resolve(connection);
      const key = extractCredentialKey(credential);
      if (key) return key;
    }
  } catch (e) {
    console.error("[VoidSwitch] resolveToken failed:", e);
  }
  const env = process.env.VOIDSWITCH_TOKEN;
  return env && env.length > 0 ? env : undefined;
}

// --------------------------------------------------------------------------- //
// Plugin
// --------------------------------------------------------------------------- //

export default Plugin.define({
  id: PROVIDER_ID,
  async setup(ctx) {
    const opt = (ctx.options ?? {}) as VoidSwitchOptions;

    /**
     * Resolve the gateway from the option → env → persisted → install chain.
     * Shared by setup and the RPC gateway reset, so both stay in step.
     */
    function resolveGateway(): { url: string; source: string } {
      if (opt.url) return { url: opt.url, source: "option" };
      if (process.env.VOIDSWITCH_URL)
        return { url: process.env.VOIDSWITCH_URL, source: "env" };
      const persisted = loadPersistedBaseUrl();
      if (persisted) return { url: persisted, source: "config" };
      return {
        url: INSTALL_GATEWAY || DEFAULT_GATEWAY,
        source: INSTALL_GATEWAY ? "install" : "default",
      };
    }

    // Gateway precedence: plugin option → env → persisted config → install
    // host (baked in by the installer) → public default.
    const resolved = resolveGateway();
    let gateway = resolved.url.replace(/\/+$/, "");
    let gatewaySource = resolved.source;
    let gatewayV1 = `${gateway}/v1`;

    /**
     * Last token seen, so the palette sync and the credential watcher can
     * authenticate their refresh calls.
     */
    let lastToken: string | undefined;

    /**
     * The token to use right now. The stored credential always wins over the
     * cached value, so rotating a key and re-running `/connect` takes effect
     * immediately instead of replaying the old secret.
     */
    async function currentToken(): Promise<string | undefined> {
      const fresh = await resolveToken(ctx);
      if (fresh) {
        lastToken = fresh;
        return fresh;
      }
      return lastToken;
    }

    async function fetchModels(
      token: string | undefined,
    ): Promise<ModelInfo[]> {
      const url = `${gatewayV1}/models`;
      try {
        const res = await fetch(url, {
          headers: token ? { "x-api-key": token } : {},
        });
        if (!res.ok) {
          recordError(
            `couldn't fetch models — falling back to the built-in list.\n${await describeHttpError(url, res, "GET")}`,
            true,
          );
          return FALLBACK_MODEL_INFOS;
        }
        const json: any = await res.json();
        const infos: ModelInfo[] = (json?.data ?? [])
          .map((m: any): ModelInfo => ({
            id: m?.id,
            display_name:
              typeof m?.display_name === "string" ? m.display_name : undefined,
            description:
              typeof m?.description === "string" ? m.description : undefined,
            opencode: isPlainObject(m?.opencode) ? m.opencode : undefined,
            opencode_v2: isPlainObject(m?.opencode_v2)
              ? m.opencode_v2
              : undefined,
          }))
          .filter(
            (m: ModelInfo) => typeof m.id === "string" && m.id.length > 0,
          );
        return infos.length ? infos : FALLBACK_MODEL_INFOS;
      } catch (e) {
        recordError(
          `couldn't reach the gateway for models — falling back to the built-in list.\n${describeFetchError(url, e, "GET")}`,
          true,
        );
        return FALLBACK_MODEL_INFOS;
      }
    }

    /**
     * Gateway-recommended OpenCode top-level selectors, surfaced by
     * `POST /v1/models/sync`.
     */
    type RemoteDefaults = { defaultModel?: string; smallModel?: string };

    /**
     * Ask the gateway to refresh its catalog; returns an ok flag (false on any
     * failure), a status line plus the recommended default / small model ids.
     */
    async function syncModels(): Promise<{
      ok: boolean;
      note: string;
      defaults: RemoteDefaults;
    }> {
      const token = await currentToken();
      const fail = (note: string) => ({
        ok: false,
        note,
        defaults: {} as RemoteDefaults,
      });
      const url = `${gatewayV1}/models/sync`;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: token ? { "x-api-key": token } : {},
        });
        if (res.status === 401) {
          const detail = await describeHttpError(url, res, "POST");
          recordError(
            `models sync failed (401 — not authenticated).\n${detail}`,
            true,
          );
          return fail(
            "couldn't refresh models — not authenticated. Run /connect and paste a vs-… token first.\n" +
              detail,
          );
        }
        if (!res.ok) {
          const detail = await describeHttpError(url, res, "POST");
          recordError(
            `models sync failed (gateway returned ${res.status}).\n${detail}`,
            true,
          );
          return fail(
            `couldn't refresh models (gateway returned ${res.status}).\n` +
              detail,
          );
        }
        const j: any = await res.json();
        const pick = (v: unknown): string | undefined =>
          typeof v === "string" && v ? v : undefined;
        return {
          ok: true,
          note: `models synced — ${j?.total ?? "?"} available to you.`,
          defaults: {
            defaultModel: pick(j?.opencode_default_model),
            smallModel: pick(j?.opencode_small_model),
          },
        };
      } catch (e) {
        const detail = describeFetchError(url, e, "POST");
        recordError(
          `couldn't reach the gateway to refresh models.\n${detail}`,
          true,
        );
        return fail(
          "couldn't reach the VoidSwitch gateway to refresh models.\n" + detail,
        );
      }
    }

    // --------------------------------------------------------------------- //
    // Platform MCP server (management tools, driven by a `vsapi-…` key)
    // --------------------------------------------------------------------- //

    /**
     * The persisted key + on/off state, mirrored in memory so the transform
     * closure always replays the current value.
     */
    let mcpState = readMcpState();

    /**
     * Whether this instance ever contributed the server. Only then may the
     * transform drop the name on uninstall — a hand-written
     * `mcp.servers.voidswitch` in `opencode.json` must survive untouched.
     */
    let mcpInstalled = mcpState !== undefined;

    /** What a whoami probe learned about a platform key. */
    type PlatformCheck = {
      ok: boolean;
      note: string;
      tools: number;
      prefix?: string;
    };

    /**
     * Older 2.x builds have neither domain; every MCP action degrades to a
     * clear message instead of throwing.
     */
    function hasMcpDomain(): boolean {
      return (
        typeof ctx.mcp?.transform === "function" &&
        typeof ctx.mcp?.reload === "function"
      );
    }

    /**
     * Probe `GET <gateway>/api/v1/whoami` with a platform API key. A wrong,
     * disabled, expired or non-staff key answers 401/403; the diagnostic text is
     * passed through verbatim so the toast says what the gateway said.
     */
    async function verifyPlatformKey(key: string): Promise<PlatformCheck> {
      const url = `${gateway}/api/v1/whoami`;
      const fail = (note: string): PlatformCheck => ({
        ok: false,
        note,
        tools: 0,
      });
      try {
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${key}` },
          signal: AbortSignal.timeout(WHOAMI_TIMEOUT_MS),
        });
        if (!res.ok) {
          // A gateway without the platform API answers 404/501 with HTML; that
          // is a wrong gateway, not a wrong key.
          if (res.status === 404 || res.status === 501)
            return fail(
              `${url} is not served by this gateway — upgrade the gateway, or check the gateway URL.`,
            );
          return fail(
            `the gateway rejected this key.\n${await describeHttpError(url, res, "GET")}`,
          );
        }
        const body: any = await res.json();
        const toolCount = Array.isArray(body?.tools) ? body.tools.length : 0;
        const scopeCount = Array.isArray(body?.scopes) ? body.scopes.length : 0;
        const warning =
          scopeCount === 0
            ? "\nwarning: this key has no effective scopes, so the server exposes no tools."
            : "";
        return {
          ok: true,
          note: `${body?.user ?? "?"} · ${body?.role ?? "?"} · ${toolCount} tools${warning}`,
          tools: toolCount,
          prefix: typeof body?.prefix === "string" ? body.prefix : undefined,
        };
      } catch (e) {
        return fail(
          `couldn't reach ${url}.\n${describeFetchError(url, e, "GET")}`,
        );
      }
    }

    /**
     * Register the MCP server transform. It runs on every replay, so changing
     * `mcpState` and calling `reload()` is the whole update path. The URL follows
     * the resolved gateway instead of being stored, so switching gateways
     * re-points the server rather than leaving a stale host behind.
     */
    async function registerMcp(): Promise<void> {
      if (!hasMcpDomain()) {
        console.error(
          "[VoidSwitch] ctx.mcp.transform unavailable — the MCP server cannot be registered; upgrade OpenCode (2.3+).",
        );
        return;
      }
      await ctx.mcp.transform((editor) => {
        const state = mcpState;
        if (!state) {
          // Only clean up a name this instance contributed; otherwise leave a
          // hand-written `mcp.servers.voidswitch` alone.
          if (mcpInstalled) editor.remove(MCP_SERVER_NAME);
          return;
        }
        editor.set(MCP_SERVER_NAME, {
          type: "remote",
          url: `${gateway}/api/v1/mcp`,
          headers: { Authorization: `Bearer ${state.key}` },
          oauth: false,
          disabled: !state.enabled,
        });
      });
    }

    /** Replay the MCP transforms; a no-op on builds without the domain. */
    async function reloadMcp(): Promise<void> {
      if (typeof ctx.mcp?.reload === "function") await ctx.mcp.reload();
    }

    /**
     * Configure (or re-key) the server. An empty `rawKey` keeps the stored key,
     * so re-pointing at a new gateway does not require pasting it again.
     */
    async function setupMcp(rawKey: string): Promise<SyncResult> {
      if (!hasMcpDomain())
        return {
          ok: false,
          note: "this OpenCode build cannot register MCP servers — upgrade to OpenCode 2.3 or newer.",
        };
      const typed = sanitizeInput(rawKey).trim();
      const key = typed || mcpState?.key || "";
      if (!key)
        return {
          ok: false,
          note: "no key given — create a platform API key on the dashboard's Platform API Keys page first.",
        };
      if (!key.startsWith(MCP_KEY_PREFIX))
        return {
          ok: false,
          note: `that is not a platform API key (they start with ${MCP_KEY_PREFIX}); a vs-… token only drives the gateway.`,
        };
      const check = await verifyPlatformKey(key);
      if (!check.ok) return { ok: false, note: check.note };
      // Re-keying or re-pointing must not silently turn a disabled server on.
      const wasEnabled = mcpState?.enabled ?? true;
      const next: McpState = {
        key,
        enabled: wasEnabled,
        prefix: check.prefix ?? maskPlatformKey(key),
      };
      const failure = writeMcpState(next);
      if (failure)
        return {
          ok: false,
          note: `couldn't write ${mcpStatePath()}: ${failure}\nnothing changed.`,
        };
      mcpState = next;
      mcpInstalled = true;
      await reloadMcp();
      const manual = configMcpServer();
      const manualAuth =
        typeof manual?.headers?.Authorization === "string"
          ? manual.headers.Authorization
          : "";
      const clash =
        manual && manualAuth !== `Bearer ${key}`
          ? `\nnote: opencode.json also declares mcp.servers.${MCP_SERVER_NAME}; while the plugin is loaded its own server wins — delete that block to avoid confusion.`
          : "";
      const disabledNote = wasEnabled
        ? ""
        : "\nnote: it is currently disabled — pick Enable to turn it on.";
      return {
        ok: true,
        note: `MCP server ready — ${check.note}\n${gateway}/api/v1/mcp${disabledNote}${clash}`,
      };
    }

    /** Turn the server off/on without forgetting the key. */
    async function setMcpEnabled(enabled: boolean): Promise<SyncResult> {
      const current = mcpState;
      if (!current) return { ok: false, note: "no MCP server configured yet." };
      const next: McpState = { ...current, enabled };
      const failure = writeMcpState(next);
      if (failure)
        return {
          ok: false,
          note: `couldn't write ${mcpStatePath()}: ${failure}\nnothing changed.`,
        };
      mcpState = next;
      await reloadMcp();
      return {
        ok: true,
        note: enabled
          ? "MCP server enabled — OpenCode is reconnecting."
          : "MCP server disabled — no tools until you enable it again.",
      };
    }

    /** Remove the server and delete the stored key from this machine. */
    async function uninstallMcp(): Promise<SyncResult> {
      if (!mcpState) return { ok: false, note: "no MCP server configured." };
      const failure = writeMcpState(undefined);
      if (failure)
        return {
          ok: false,
          note: `couldn't delete ${mcpStatePath()}: ${failure}\nthe server is still registered.`,
        };
      mcpState = undefined;
      await reloadMcp();
      return {
        ok: true,
        note: "MCP server removed — the stored platform API key was deleted from this machine.",
      };
    }

    /** The TUI part's view of the server; the raw key never leaves the server. */
    function mcpStatusView(): McpStatusInfo {
      return {
        name: MCP_SERVER_NAME,
        supported: hasMcpDomain(),
        installed: mcpState !== undefined,
        enabled: mcpState?.enabled === true,
        url: `${gateway}/api/v1/mcp`,
        prefix: mcpState
          ? (mcpState.prefix ?? maskPlatformKey(mcpState.key))
          : "",
      };
    }

    /**
     * After a gateway switch the server has to re-point, and the stored key may
     * belong to another host: verify it and say so in the sync note. A disabled
     * server is not in use, so its key is not sent anywhere.
     */
    async function followGatewayForMcp(): Promise<string> {
      const current = mcpState;
      if (!current || !current.enabled || !hasMcpDomain()) return "";
      await reloadMcp();
      const check = await verifyPlatformKey(current.key);
      return check.ok
        ? `MCP server re-pointed to ${gateway} — ${check.tools} tools available.`
        : `MCP server re-pointed to ${gateway}, but the stored key could not be verified there — run "VoidSwitch: configure mcp server" to paste one for this host.\n${check.note}`;
    }

    // --------------------------------------------------------------------- //
    // Provider registration
    // --------------------------------------------------------------------- //

    /**
     * The provider definition handed to `ctx.provider.transform`. `activation`
     * stays "enabled" so the provider (and its models) exist before the first
     * `/connect`; `integrationID` links the key method registered below.
     */
    function providerInfo(): Provider.Info {
      return {
        ...Provider.Info.empty(Provider.ID.make(PROVIDER_ID)),
        name: DISPLAY_NAME,
        activation: "enabled",
        package: ANTHROPIC_PACKAGE,
        integrationID: INTEGRATION_ID,
        settings: { baseURL: gatewayV1 },
      };
    }

    async function registerProvider(): Promise<void> {
      await ctx.provider.transform((editor) => {
        const info = providerInfo();
        const existing = editor.get(PROVIDER_ID);
        if (existing) {
          editor.update(PROVIDER_ID, (draft) => {
            draft.name = info.name;
            draft.activation = info.activation;
            draft.package = info.package;
            draft.integrationID = info.integrationID;
            draft.settings = info.settings;
          });
          return;
        }
        editor.add({ info, models: [] });
      });
    }

    /**
     * Install the key method that backs `/connect` for this provider.
     *
     * No `form` fields: OpenCode renders a form field *before* asking for the
     * secret, so a `key` form field made users paste the same token twice (the
     * form answer and then the actual credential).
     */
    async function registerAuth(): Promise<void> {
      await ctx.integration.transform((editor) => {
        editor.method.update({
          integrationID: PROVIDER_ID,
          method: {
            type: "key",
            label: "Paste a VoidSwitch token (vs-…)",
          },
        });
      });
    }

    // --------------------------------------------------------------------- //
    // Commands
    // --------------------------------------------------------------------- //

    /** Register the Claude Code-style slash commands. */
    async function registerCommands(): Promise<void> {
      const setOverride = (
        sessionID: string,
        patch: Partial<SessionOverride>,
      ) => {
        const st = sessionState.get(sessionID) ?? {};
        sessionState.set(sessionID, { ...st, ...patch });
      };

      const prompt = async (sessionID: string, text: string) => {
        if (!text.trim()) return;
        await ctx.session.prompt({ sessionID, text });
      };

      await ctx.command.transform((editor) => {
        editor.add({
          name: "effort",
          description:
            "VoidSwitch reasoning effort: low|medium|high|xhigh|max|ultracode|auto [+ optional prompt]",
          execute: async ({ sessionID, prompt: p }) => {
            const arg = (p.text ?? "").trim();
            const [first, ...restWords] = arg.split(/\s+/).filter(Boolean);
            const head = (first ?? "").toLowerCase();
            const rest = restWords.join(" ").trim();
            if (head === "ultracode")
              setOverride(sessionID, { effort: "xhigh" });
            else if (head === "auto" || head === "default")
              setOverride(sessionID, { effort: "auto" });
            else if (isEffort(head)) setOverride(sessionID, { effort: head });
            await prompt(
              sessionID,
              isEffort(head) ||
                head === "auto" ||
                head === "default" ||
                head === "ultracode"
                ? rest
                : arg,
            );
          },
        });

        editor.add({
          name: "fast",
          description: "VoidSwitch fast mode: on|off [+ optional prompt]",
          execute: async ({ sessionID, prompt: p }) => {
            const arg = (p.text ?? "").trim();
            const [first, ...restWords] = arg.split(/\s+/).filter(Boolean);
            const head = (first ?? "").toLowerCase();
            const isFlag = ["on", "off", "true", "false"].includes(head);
            setOverride(sessionID, {
              fast: !(head === "off" || head === "false"),
            });
            await prompt(sessionID, isFlag ? restWords.join(" ").trim() : arg);
          },
        });

        editor.add({
          name: "ultracode",
          description:
            "VoidSwitch ultracode — xhigh effort [+ optional prompt]",
          execute: async ({ sessionID, prompt: p }) => {
            setOverride(sessionID, { effort: "xhigh" });
            await prompt(sessionID, (p.text ?? "").trim());
          },
        });
      });
    }

    /** Refresh the registered model inventory without re-running setup. */
    async function registerModels(infos: ModelInfo[]): Promise<void> {
      const models = infos.map((info) => buildModel(info, gatewayV1));
      await ctx.provider.transform((editor) => {
        if (editor.get(PROVIDER_ID)) {
          editor.models.set(PROVIDER_ID, models);
          return;
        }
        // A malformed config block is skipped by OpenCode's normalization;
        // re-register rather than silently dropping the fresh catalog.
        editor.add({ info: providerInfo(), models });
      });
    }

    // --------------------------------------------------------------------- //
    // RPC (drives the TUI part's palette commands; never touches a session)
    // --------------------------------------------------------------------- //

    /** Refresh the catalog from the gateway and persist it (RPC entry). */
    async function syncNow(): Promise<SyncResult> {
      const { ok, note, defaults } = await syncModels();
      if (!ok) return { ok: false, note };
      const infos = await fetchModels(await currentToken());
      if (infos === FALLBACK_MODEL_INFOS)
        return {
          ok: false,
          note:
            `${note}\n` +
            "but the catalog refresh failed — the picker falls back to the built-in list. " +
            'Run "opencode auth login", pick VoidSwitch and paste a fresh vs-… token.',
        };
      persistModels(infos);
      const notes = [
        note,
        `${infos.length} models written to config.`,
        ...persistDefaultModels(defaults),
      ];
      await registerModels(infos);
      return { ok: true, note: notes.join("\n") };
    }

    /** Point the plugin at another gateway; empty resets to the default. */
    async function setGateway(raw: string): Promise<SyncResult> {
      const url = raw.trim().replace(/\/+$/, "");
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
            throw new Error(parsed.protocol);
        } catch {
          return { ok: false, note: `not a valid http(s) URL: ${url}` };
        }
      }
      persistBaseUrl(url || undefined);
      const next = url ? { url, source: "config" } : resolveGateway();
      gateway = next.url.replace(/\/+$/, "");
      gatewaySource = next.source;
      gatewayV1 = `${gateway}/v1`;
      await registerProvider();
      const infos = await fetchModels(await currentToken());
      persistModels(infos);
      await registerModels(infos);
      const mcpNote = await followGatewayForMcp();
      const notes = (...extra: string[]) =>
        [extra.join(" "), mcpNote].filter(Boolean).join("\n");
      if (infos === FALLBACK_MODEL_INFOS)
        return {
          ok: false,
          note: notes(
            `Gateway is now ${gateway} (${gatewaySource}), but it rejected the current ` +
              "credential — the picker falls back to the built-in list. " +
              'Run "opencode auth login", pick VoidSwitch and paste a fresh vs-… token.',
          ),
        };
      return {
        ok: true,
        note: notes(
          `Gateway set to ${gateway} (${gatewaySource}) — ${infos.length} models loaded. Reopen the model picker to see changes.`,
        ),
      };
    }

    /** Expose the palette-command surface to the TUI part. */
    async function registerRpc(): Promise<void> {
      // Older OpenCode 2.x builds have no RPC domain; degrade to server-only
      // behaviour instead of failing the whole plugin.
      if (
        typeof (ctx as { rpc?: { register?: unknown } }).rpc?.register !==
        "function"
      ) {
        console.error(
          "[VoidSwitch] ctx.rpc.register unavailable — palette commands disabled; upgrade OpenCode.",
        );
        return;
      }
      await ctx.rpc.register(VoidSwitchRpc, {
        syncModels: async () => syncNow(),
        gateway: async () => ({ url: gateway, source: gatewaySource }),
        setGateway: async (input) =>
          setGateway(
            typeof (input as { url?: unknown })?.url === "string"
              ? (input as { url: string }).url
              : "",
          ),
        mcpStatus: async () => mcpStatusView(),
        mcpSetup: async (input) =>
          setupMcp(
            typeof (input as { key?: unknown })?.key === "string"
              ? (input as { key: string }).key
              : "",
          ),
        mcpEnable: async () => setMcpEnabled(true),
        mcpDisable: async () => setMcpEnabled(false),
        mcpUninstall: async () => uninstallMcp(),
      });
    }

    /**
     * Refresh the catalog whenever a VoidSwitch credential is stored — the
     * `opencode auth login` path, so an external command refresh stays working
     * after the slash command was removed.
     */
    function watchCredentials(): () => void {
      let stopped = false;
      const loop = (async () => {
        try {
          for await (const event of ctx.event.subscribe({
            types: ["credential.updated"],
          })) {
            if (stopped) break;
            if (event.data.integrationID !== PROVIDER_ID) continue;
            const infos = await fetchModels(await currentToken());
            persistModels(infos);
            await registerModels(infos);
          }
        } catch {
          // Subscription closed or the server restarted — nothing to do.
        }
      })();
      return () => {
        stopped = true;
        void loop.catch(() => {});
      };
    }

    // --------------------------------------------------------------------- //
    // Request hooks
    // --------------------------------------------------------------------- //

    /**
     * Resolve the effort for a turn: per-turn picker variant wins, then the
     * session command, then the plugin option default. "ultracode" maps to
     * `xhigh`, exactly as the Claude Code CLI.
     */
    function resolveTurnEffort(
      modelID: string,
      variant: string | undefined,
      st: SessionOverride,
    ): Effort | undefined {
      const variantEffort: Effort | undefined =
        variant === ULTRACODE_VARIANT
          ? "xhigh"
          : isEffort(variant)
            ? variant
            : undefined;
      if (variantEffort) return clampEffort(modelID, variantEffort);
      if (st.effort !== undefined)
        return st.effort === "auto"
          ? undefined
          : clampEffort(modelID, st.effort);
      if (opt.effort === "ultracode") return clampEffort(modelID, "xhigh");
      if (opt.effort && opt.effort !== "default")
        return clampEffort(modelID, opt.effort);
      return undefined;
    }

    // `context` runs immediately before an agent model request. Effort, fast mode
    // and adaptive thinking have first-class V2 semantic options, so set those
    // here; the Anthropic route lowers them to `output_config.effort`, `speed`
    // and `thinking` itself (and adds the beta those need).
    await ctx.session.hook(
      "context",
      (event) => {
        const modelID = event.model.id;
        if (!isClaude(modelID)) return;
        const st = sessionState.get(event.sessionID) ?? {};

        const effort = resolveTurnEffort(modelID, event.model.variant, st);
        if (effort) event.options.effort = effort;

        const fast =
          event.model.variant === FAST_VARIANT ||
          st.fast === true ||
          opt.fast === true;
        if (fast) event.options.speed = "fast";

        if (opt.thinking !== false && adaptiveCapable(modelID)) {
          const thinking: Record<string, any> = { type: "adaptive" };
          // Surface thinking text — Opus 4.7/4.8 only.
          if (/opus-4-[78]/.test(modelID)) {
            const disp = opt.thinkingDisplay ?? "summarized";
            if (disp !== "omitted") thinking.display = disp;
          }
          event.options.thinking = thinking;
          // Anthropic requires temperature == 1 once extended thinking is on.
          event.options.temperature = 1;
        }
      },
      { providerID: PROVIDER_ID },
    );

    // Stamp every VoidSwitch request with the client hint + session id so the
    // gateway can report the client family and keep a session on one key.
    await ctx.session.hook(
      "model.request",
      (event) => {
        event.headers[CLIENT_HINT_HEADER] = CLIENT_HINT_VALUE;
        event.headers[CLIENT_VERSION_HEADER] = CLIENT_VERSION_VALUE;
        event.headers[SESSION_HEADER] = event.sessionID;
      },
      { providerID: PROVIDER_ID },
    );

    // The remaining Claude Code fields have no V2 semantic option, so rewrite the
    // native `/v1/messages` body — the direct successor to the V1 plugin's
    // body-rewriting auth fetch. Success bodies are returned verbatim, so
    // streaming is unaffected.
    await ctx.session.hook(
      "http.request",
      async (event) => {
        const modelID = event.model.id;
        if (!isClaude(modelID)) return;

        const req = event.request;
        const url = req.url;
        let bodyText: string | undefined;
        try {
          bodyText = await req.clone().text();
        } catch {
          return; // Unreadable body — forward as-is.
        }
        if (!bodyText) return;

        let body: any;
        try {
          body = JSON.parse(bodyText);
        } catch {
          return; // Non-JSON body — forward as-is.
        }

        const headers = new Headers(req.headers);
        const betaBefore = headers.get("anthropic-beta") ?? "";
        const betas = new Set(
          betaBefore
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        );
        let changed = false;

        // Cumulative agentic token budget for the whole loop.
        if (
          typeof opt.taskBudget === "number" &&
          opt.taskBudget >= TASK_BUDGET_MIN &&
          !body.output_config?.task_budget
        ) {
          body.output_config = {
            ...(body.output_config ?? {}),
            task_budget: { type: "tokens", total: Math.floor(opt.taskBudget) },
          };
          betas.add(BETA_TASK_BUDGET);
          changed = true;
        }

        // Server-side context management for long sessions.
        if (opt.contextManagement === true && !body.context_management) {
          body.context_management = {
            edits: [{ type: CONTEXT_EDIT_TYPE, keep: "all" }],
          };
          betas.add(BETA_CONTEXT_MGMT);
          changed = true;
        }

        // 1M context window — forced, or auto once the prompt is large.
        const promptChars = bodyText.length;
        const wantLong =
          opt.context1m === true ||
          (opt.context1m !== false && promptChars > LONG_CONTEXT_CHARS);
        if (wantLong) {
          betas.add(BETA_LONG_CONTEXT);
        }

        // Request the beta that matches the effort field the route just emitted.
        if (body.output_config?.effort) betas.add(BETA_EFFORT);

        const betaAfter = [...betas].join(",");
        if (betaAfter !== betaBefore) {
          if (betaAfter) headers.set("anthropic-beta", betaAfter);
          changed = true;
        }

        if (changed) {
          headers.delete("content-length"); // re-derived from the new body
          event.request = new Request(url, {
            method: req.method,
            headers,
            body: JSON.stringify(body),
            signal: req.signal,
          });
        }
      },
      { providerID: PROVIDER_ID },
    );

    // --------------------------------------------------------------------- //
    // Startup
    // --------------------------------------------------------------------- //

    await registerAuth();
    await registerProvider();
    // Register even without a stored key: the transform drops the server when
    // there is none, and picking up a later setup only needs a reload. A failure
    // here must not take the provider and RPC surface down with it.
    try {
      await registerMcp();
    } catch (e) {
      console.error("[VoidSwitch] MCP server registration failed:", e);
    }

    // Seed the model inventory so the picker isn't empty before the first sync.
    const token = await currentToken();
    const infos = await fetchModels(token);
    await registerModels(infos);

    await registerCommands();
    await registerRpc();
    const stopWatcher = watchCredentials();

    return () => {
      stopWatcher();
      sessionState.clear();
    };
  },
});
