/**
 * Build the manual (no-plugin) OpenCode `opencode.json` for VoidSwitch.
 *
 * This mirrors — one-to-one — the logic the VoidSwitch OpenCode *plugin* uses to
 * register the provider and build each model block (`buildModel` + the `config`
 * hook in `opencode-plugin/src/index.ts`). Keeping the two in lock-step means the
 * hand-pasted config a user copies from the dashboard behaves exactly like the
 * one the installed plugin generates at runtime, so there are no surprises when
 * switching between the scripted and manual setups.
 *
 * If you change the plugin's model construction, mirror it here (and vice-versa).
 */

const PROVIDER_ID = "voidswitch";

/** Claude Code's effort enum (`sN`), lowest → highest. */
const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const;

/** Picker variant that turns on fast mode instead of selecting an effort. */
const FAST_VARIANT = "fast";
/** Picker variant mirroring Claude Code's "ultracode" — resolves to `xhigh`. */
const ULTRACODE_VARIANT = "ultracode";

/**
 * A model id plus its optional VoidSwitch catalog metadata: a display name, a
 * human description, and a custom OpenCode model config (deep-merged into the
 * built model block). Same shape the plugin reads from `<gateway>/v1/models`.
 */
export interface ModelInfo {
  id: string;
  display_name?: string;
  description?: string;
  opencode?: Record<string, unknown>;
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Recursively merge `source` onto `target` (objects merge; arrays/scalars replace). */
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...target };
  for (const [k, v] of Object.entries(source)) {
    const existing = out[k];
    out[k] =
      isPlainObject(v) && isPlainObject(existing) ? deepMerge(existing, v) : v;
  }
  return out;
}

// --- Model-capability helpers (mirror Claude Code's per-model effort gating) - //

const isClaude = (id: string) => /claude/i.test(id);
const isOpus = (id: string) => /opus/i.test(id);
const isReasoningModel = (id: string) =>
  isClaude(id) || /deepseek|reasoner|-r1\b|qwq|thinking/i.test(id);
const isOpenAICompatModel = (id: string) => /deepseek/i.test(id);
const effortCapable = (id: string) =>
  /opus-4-[6-9]/.test(id) || /sonnet-4-[6-9]/.test(id);
const xhighCapable = (id: string) => /opus-4-[78]/.test(id);
const maxCapable = (id: string) => /opus-4-[6-9]/.test(id);

function prettyName(id: string): string {
  const m = id.match(/^claude-(opus|sonnet|haiku)-(\d)-(\d+)/i);
  if (m) return `Claude ${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`;
  return id;
}

/** Build one model block (shape mirrors the plugin's `buildModel`). */
function buildModel(info: ModelInfo, gatewayV1: string): Record<string, unknown> {
  const id = info.id;
  const claude = isClaude(id);
  const reasoning = isReasoningModel(id);
  const oaiCompat = isOpenAICompatModel(id);
  const npm = oaiCompat ? "@ai-sdk/openai-compatible" : "@ai-sdk/anthropic";
  const model: Record<string, unknown> = {
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
    limit: {
      context: claude ? 1_000_000 : 200_000,
      output: isOpus(id) ? 128_000 : claude ? 64_000 : 8_192,
    },
    options: {},
    headers: {},
  };

  // Per-model SDK override: keep DeepSeek &c inside the single VoidSwitch
  // provider but route them through the openai-compatible SDK.
  if (oaiCompat) model.provider = { npm: "@ai-sdk/openai-compatible", api: gatewayV1 };

  // Expose effort levels (and fast mode) as picker variants for capable models.
  if (claude && effortCapable(id)) {
    const variants: Record<string, Record<string, unknown>> = {};
    for (const e of EFFORT_LEVELS) {
      if (e === "xhigh" && !xhighCapable(id)) continue;
      if (e === "max" && !maxCapable(id)) continue;
      variants[e] = {};
    }
    if (xhighCapable(id)) variants[ULTRACODE_VARIANT] = {}; // → xhigh
    variants[FAST_VARIANT] = {};
    model.variants = variants;
  }

  if (info.description) model.description = info.description;
  // Deep-merge the admin's custom OpenCode config last, so it wins over the
  // computed defaults.
  return info.opencode ? deepMerge(model, info.opencode) : model;
}

/**
 * Build the complete manual `opencode.json` from the live catalog, matching what
 * the installed plugin produces at runtime: every served model gets a full model
 * block (with effort/fast variants and any per-model config), and the top-level
 * `model` / `small_model` selectors are set from the gateway's recommendations.
 *
 * `gatewayBase` is the API base (without the trailing `/v1`).
 */
export function buildOpencodeConfig(
  defaultModel: string,
  smallModel: string,
  models: ModelInfo[],
  gatewayBase: string,
): string {
  const gatewayV1 = `${gatewayBase.replace(/\/+$/, "")}/v1`;
  const modelMap: Record<string, unknown> = {};
  for (const info of models) {
    if (!info.id) continue;
    modelMap[info.id] = buildModel(info, gatewayV1);
  }
  // Guarantee the selected default + small models are present even if the
  // catalog hasn't been synced yet.
  const ensure = (id: string) => {
    if (id && !(id in modelMap)) modelMap[id] = buildModel({ id }, gatewayV1);
  };
  ensure(defaultModel);
  ensure(smallModel);

  const config: Record<string, unknown> = {
    $schema: "https://opencode.ai/config.json",
    model: `${PROVIDER_ID}/${defaultModel}`,
    ...(smallModel ? { small_model: `${PROVIDER_ID}/${smallModel}` } : {}),
    provider: {
      [PROVIDER_ID]: {
        npm: "@ai-sdk/anthropic",
        name: "VoidSwitch",
        options: { baseURL: gatewayV1 },
        models: modelMap,
      },
    },
  };
  return `// ~/.config/opencode/opencode.json\n${JSON.stringify(config, null, 2)}`;
}
