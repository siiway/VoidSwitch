// Brand icons for model cards, sourced from Simple Icons (https://simpleicons.org)
// — a single monochrome path per brand. The rendered SVG uses `currentColor` so
// the glyph automatically adapts to the active light/dark theme (black on light,
// white on dark). Models whose brand has no known icon fall back to their first
// letter (rendered by the caller).
import {
  siAnthropic,
  siBytedance,
  siDeepseek,
  siGooglegemini,
  siKimi,
  siMeta,
  siMinimax,
  siMistralai,
  siMoonshotai,
  siNvidia,
  siQwen,
  siX,
} from "simple-icons";

// OpenAI's mark was removed from Simple Icons over a trademark request, so it is
// carried here from the last upstream revision that shipped it (the official
// hexagonal-knot wordmark), kept as a raw path like every other entry.
const OPENAI_PATH =
  "M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654 2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z";

// Canonical brand → Simple Icons glyph (path only). Aliases are normalised via
// ``ALIASES`` below.
const BRAND_PATHS: Record<string, string> = {
  anthropic: siAnthropic.path,
  deepseek: siDeepseek.path,
  googlegemini: siGooglegemini.path,
  meta: siMeta.path,
  nvidia: siNvidia.path,
  x: siX.path,
  qwen: siQwen.path,
  kimi: siKimi.path,
  minimax: siMinimax.path,
  bytedance: siBytedance.path,
  mistralai: siMistralai.path,
  moonshotai: siMoonshotai.path,
  openai: OPENAI_PATH,
};

// Brand aliases → canonical key (so "anthropic" and "claude" share one icon, and
// "gpt" resolves to OpenAI, "google"/"gemini" to Google Gemini, etc.).
const ALIASES: Record<string, string> = {
  claude: "anthropic",
  anthropic: "anthropic",
  deepseek: "deepseek",
  gemini: "googlegemini",
  google: "googlegemini",
  meta: "meta",
  llama: "meta",
  nvidia: "nvidia",
  nv: "nvidia",
  grok: "x",
  xai: "x",
  x: "x",
  openai: "openai",
  gpt: "openai",
  chatgpt: "openai",
  qwen: "qwen",
  kimi: "kimi",
  minimax: "minimax",
  doubao: "bytedance",
  bytedance: "bytedance",
  mistral: "mistralai",
  mistralai: "mistralai",
  moonshot: "moonshotai",
  moonshotai: "moonshotai",
};

// Known brand keys the user can pick in the edit dialog (ordered).
export const BRAND_KEYS: string[] = [
  "claude",
  "openai",
  "deepseek",
  "gemini",
  "meta",
  "nvidia",
  "grok",
  "mistral",
  "qwen",
  "kimi",
  "moonshot",
  "minimax",
  "doubao",
  "glm",
  "yi",
  "step",
  "sensenova",
];

export interface BrandIconGlyph {
  path: string;
}

// Resolve a brand key to a monochrome glyph path, when one exists. The rendered
// SVG uses `fill="currentColor"` so it follows the active theme foreground.
export function brandIconForKey(
  brand: string | null | undefined,
): BrandIconGlyph | null {
  if (!brand) return null;
  const key = ALIASES[brand.toLowerCase()] ?? brand.toLowerCase();
  const path = BRAND_PATHS[key];
  return path ? { path } : null;
}

// Resolve an arbitrary string (a family, provider id, or model prefix) to a
// canonical brand key, or null when none is known. e.g. "deepseek-flash" →
// "deepseek"; "anthropic" → "anthropic".
export function resolveBrandKey(input: string | null | undefined): string | null {
  if (!input) return null;
  const key = input.toLowerCase().trim();
  if (ALIASES[key]) return ALIASES[key];
  const first = key.split(/[-_/ ]+/)[0];
  if (ALIASES[first] || BRAND_PATHS[first]) return ALIASES[first] ?? first;
  return null;
}

// Extract a likely brand from a model id: the first dash/slash-delimited token.
export function deriveBrand(modelId: string): string | null {
  if (!modelId) return null;
  const first = modelId.split(/[/-]+/)[0];
  if (!first) return null;
  return resolveBrandKey(first);
}

export function getBrandIcon(
  brand: string | null | undefined,
  modelId: string,
): BrandIconGlyph | null {
  return brandIconForKey(brand) ?? brandIconForKey(deriveBrand(modelId));
}