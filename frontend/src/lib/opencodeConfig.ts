/**
 * Build the manual (no-plugin) OpenCode `opencode.json` for VoidSwitch.
 *
 * This is the fallback a user pastes when they can't run the one-line installer.
 * It registers the VoidSwitch provider and lists every available model, but —
 * intentionally — keeps each model block minimal: only the admin-authored custom
 * OpenCode config and the model's display name are emitted (the custom config
 * wins over the name). All other per-model defaults (capabilities, limits, cost,
 * effort variants, …) are left to OpenCode/the plugin so the file stays short.
 */

const PROVIDER_ID = "voidswitch";

/**
 * A model id plus its optional VoidSwitch catalog metadata: a display name and a
 * custom OpenCode model config (deep-merged into the block). Same shape the
 * plugin reads from `<gateway>/v1/models`.
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

/**
 * Build one model block. Deliberately minimal: only the model-name setting
 * (from the admin's display name) and the admin's custom OpenCode config, with
 * the custom config taking priority over the name. Everything else is left to
 * OpenCode's defaults so the pasted config doesn't balloon.
 */
function buildModel(info: ModelInfo): Record<string, unknown> {
  const model: Record<string, unknown> = {};
  if (info.display_name) model.name = info.display_name;
  // Admin custom config wins over the name setting.
  return info.opencode ? deepMerge(model, info.opencode) : model;
}

/**
 * Build the complete manual `opencode.json`: register the VoidSwitch provider
 * (pointing at the gateway) and list every served model with only its custom
 * config + name. The top-level `model` / `small_model` selectors come from the
 * gateway's recommendations.
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
    modelMap[info.id] = buildModel(info);
  }
  // Guarantee the selected default + small models are present even if the
  // catalog hasn't been synced yet.
  const ensure = (id: string) => {
    if (id && !(id in modelMap)) modelMap[id] = {};
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
