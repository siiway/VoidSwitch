// Brand icon mapping for model IDs, based on prefix matching.
// Returns a simple 24x24 SVG icon (brand logo or initial circle).

interface BrandInfo {
  svg: string;
  color: string;
}

const BRANDS: Record<string, BrandInfo> = {
  // Anthropic / Claude
  claude: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#d97706"/><circle cx="12" cy="12" r="8" fill="#f59e0b"/><path d="M12 7c-1.5 0-3 .5-4 1.5l1.5 1.5a2.5 2.5 0 015 0L16 8.5A5 5 0 0012 7zm-4 4c-.5 1-.5 2 0 3l1.5-1.5a1 1 0 012 0L13 14c1-.5 1.5-1.5 1.5-2.5L13 13a1 1 0 01-2 0L9.5 11.5z" fill="#fff"/></svg>`,
    color: "#d97706",
  },
  // OpenAI / GPT
  gpt: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#10a37f"/><path d="M15.5 8.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><path d="M18.5 15.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><path d="M9.5 15.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><line x1="12" y1="12" x2="12" y2="12" stroke="#10a37f" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="#10a37f"/></svg>`,
    color: "#10a37f",
  },
  openai: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#10a37f"/><path d="M15.5 8.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><path d="M18.5 15.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><path d="M9.5 15.5a3.5 3.5 0 00-7 0 3.5 3.5 0 007 0z" fill="#fff"/><line x1="12" y1="12" x2="12" y2="12" stroke="#10a37f" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="#10a37f"/></svg>`,
    color: "#10a37f",
  },
  // DeepSeek
  deepseek: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#4f46e5"/><path d="M7 7h4v4H7zM13 7h4v4h-4zM7 13h4v4H7zM13 13h4v4h-4z" fill="#fff" opacity="0.9"/><rect x="11" y="11" width="2" height="2" fill="#4f46e5" rx="0.5"/></svg>`,
    color: "#4f46e5",
  },
  // Google / Gemini
  gemini: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#4285f4"/><path d="M12 4l2.5 7.5H22l-6 4.5 2.5 7.5L12 18l-6.5 5.5L8 16l-6-4.5h7.5z" fill="#fff" opacity="0.85"/></svg>`,
    color: "#4285f4",
  },
  google: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#4285f4"/><path d="M12 4l2.5 7.5H22l-6 4.5 2.5 7.5L12 18l-6.5 5.5L8 16l-6-4.5h7.5z" fill="#fff" opacity="0.85"/></svg>`,
    color: "#4285f4",
  },
  // Qwen
  qwen: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#7c3aed"/><path d="M6 8h5v2H6zm7 0h5v2h-5zM6 14h5v2H6zm7 0h5v2h-5z" fill="#fff" opacity="0.85"/><circle cx="12" cy="12" r="2.5" fill="#7c3aed"/></svg>`,
    color: "#7c3aed",
  },
  // Kimi / Moonshot
  kimi: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#ec4899"/><path d="M7 8l5 8 5-8" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="2" fill="#fff"/></svg>`,
    color: "#ec4899",
  },
  moonshot: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#ec4899"/><path d="M7 8l5 8 5-8" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="2" fill="#fff"/></svg>`,
    color: "#ec4899",
  },
  // GLM / Zhipu
  glm: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#06b6d4"/><path d="M8 8h8v8H8z" fill="none" stroke="#fff" stroke-width="1.5" rx="2"/><path d="M10 10h4v4h-4z" fill="#fff" opacity="0.7"/></svg>`,
    color: "#06b6d4",
  },
  zhipu: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#06b6d4"/><path d="M8 8h8v8H8z" fill="none" stroke="#fff" stroke-width="1.5" rx="2"/><path d="M10 10h4v4h-4z" fill="#fff" opacity="0.7"/></svg>`,
    color: "#06b6d4",
  },
  // Grok / xAI
  grok: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#1d1d1f"/><path d="M7 12a5 5 0 0110 0" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="2.5" fill="#fff"/></svg>`,
    color: "#1d1d1f",
  },
  // Mistral
  mistral: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#f97316"/><path d="M6 6h12v12H6z" fill="none" stroke="#fff" stroke-width="1.5" rx="1"/><path d="M9 9h6M9 12h6M9 15h6" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/></svg>`,
    color: "#f97316",
  },
  // Llama / Meta
  llama: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#8b5cf6"/><ellipse cx="9" cy="10" rx="1.5" ry="2" fill="#fff"/><ellipse cx="15" cy="10" rx="1.5" ry="2" fill="#fff"/><path d="M8 14c1 2 2 3 4 3s3-1 4-3" fill="none" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/></svg>`,
    color: "#8b5cf6",
  },
  meta: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#8b5cf6"/><ellipse cx="9" cy="10" rx="1.5" ry="2" fill="#fff"/><ellipse cx="15" cy="10" rx="1.5" ry="2" fill="#fff"/><path d="M8 14c1 2 2 3 4 3s3-1 4-3" fill="none" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/></svg>`,
    color: "#8b5cf6",
  },
  // MiniMax
  minimax: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#eab308"/><path d="M7 12l5-5 5 5-5 5z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/><circle cx="12" cy="12" r="2" fill="#fff"/></svg>`,
    color: "#eab308",
  },
  // SenseNova
  sensenova: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#6366f1"/><path d="M6 12c0-3.3 2.7-6 6-6s6 2.7 6 6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><circle cx="12" cy="12" r="3" fill="#fff" opacity="0.7"/></svg>`,
    color: "#6366f1",
  },
  // Doubao / ByteDance
  doubao: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#22c55e"/><circle cx="12" cy="9" r="3" fill="#fff" opacity="0.7"/><path d="M8 16c0-2.2 1.8-4 4-4s4 1.8 4 4" fill="#fff" opacity="0.7"/></svg>`,
    color: "#22c55e",
  },
  // Step
  step: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#d97706"/><path d="M6 18V6l12 6-12 6z" fill="#fff" opacity="0.85"/></svg>`,
    color: "#d97706",
  },
  // Yi / 01.AI
  yi: {
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#f43f5e"/><path d="M8 8h8v8H8z" fill="none" stroke="#fff" stroke-width="1.5" rx="2"/><path d="M10 10h4v4h-4z" fill="#fff" opacity="0.6"/></svg>`,
    color: "#f43f5e",
  },
};

// Extract first prefix from model_id (e.g. "claude-opus-4-20250514" -> "claude")
function prefixOf(modelId: string): string {
  const dash = modelId.indexOf("-");
  return dash > 0 ? modelId.slice(0, dash).toLowerCase() : modelId.toLowerCase();
}

export function getBrandIcon(modelId: string): { svg: string | null; color: string } {
  const prefix = prefixOf(modelId);
  const brand = BRANDS[prefix];
  if (brand) return brand;

  // Fallback: colored circle with first 1-2 letters (rendered by the caller).
  const hash = modelId.split("").reduce((h, c) => h * 31 + c.charCodeAt(0), 0) & 0xffffff;
  const fallbackColor = `#${hash.toString(16).padStart(6, "0")}`;

  return { svg: null, color: fallbackColor };
}