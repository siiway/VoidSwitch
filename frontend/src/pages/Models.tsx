import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  Option,
  Spinner,
  Switch,
  Text,
  Textarea,
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowRoutingRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  DeleteRegular,
  EditRegular,
  FolderAddRegular,
  PeopleTeamRegular,
  SearchRegular,
} from "@fluentui/react-icons";
import JSON5 from "json5";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  ModelCategory,
  ModelEntry,
  ModelsDevSearchResult,
  Provider,
  RoleGroup,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
import { BRAND_KEYS, getBrandIcon, resolveBrandKey } from "../components/brand_icons";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

const useStyles = makeStyles({
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "16px",
    flexWrap: "wrap",
  },
  search: { flex: "1 1 240px", maxWidth: "360px" },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: "14px",
  },
  card: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    ...shorthands.padding("16px"),
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
    transition: "box-shadow 0.15s",
    ":hover": {
      borderTopColor: tokens.colorNeutralForeground1,
      borderRightColor: tokens.colorNeutralForeground1,
      borderBottomColor: tokens.colorNeutralForeground1,
      borderLeftColor: tokens.colorNeutralForeground1,
    },
  },
  cardHidden: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    ...shorthands.padding("16px"),
    opacity: 0.55,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
  },
  head: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "8px",
  },
  modelId: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase300,
    wordBreak: "break-all",
  },
  desc: { color: tokens.colorNeutralForeground2, minHeight: "18px" },
  badges: { display: "flex", flexWrap: "wrap", gap: "6px" },
  actions: { display: "flex", gap: "4px" },
  dim: { color: tokens.colorNeutralForeground3 },
});

interface EditState {
  model_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
  config: string;
  limit_context: string;
  limit_input: string;
  limit_output: string;
  reasoning: boolean;
  capabilities: {
    text: boolean;
    image: boolean;
    audio: boolean;
    tool: boolean;
  };
  modalities_input: string;
  modalities_output: string;
  models_dev_id: string;
  category_id: string;
  brand: string;
}

interface CreateState {
  model_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
  provider_id: string;
  upstream_model: string;
  category_id: string;
}

type BatchEnabled = "unchanged" | "enabled" | "disabled";

// Which field(s) the catalog search box matches against.
type SearchField = "all" | "id" | "name" | "description";

function prettyJson(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value).length === 0)) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function parseConfig(text: string): Record<string, unknown> | "INVALID" {
  const trimmed = text.trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON5.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return "INVALID";
  } catch {
    return "INVALID";
  }
}

function intOrEmpty(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isNaN(n) ? null : Math.max(0, Math.floor(n));
}

// Brand-aware title-casing for the display-name placeholder, e.g.
// "claude-fable-5" -> "Claude Fable 5", "deepseek-v4-flash" -> "DeepSeek v4 Flash".
const BRAND_TITLES: Record<string, string> = {
  deepseek: "DeepSeek",
  openai: "OpenAI",
  gpt: "GPT",
  claude: "Claude",
  anthropic: "Anthropic",
  gemini: "Gemini",
  google: "Google",
  qwen: "Qwen",
  kimi: "Kimi",
  moonshot: "Moonshot",
  glm: "GLM",
  zhipu: "Zhipu",
  grok: "Grok",
  mistral: "Mistral",
  llama: "Llama",
  meta: "Meta",
  minimax: "MiniMax",
  sensenova: "SenseNova",
  doubao: "Doubao",
  step: "Step",
  yi: "Yi",
};

function titleWord(w: string): string {
  if (!w) return w;
  const lower = w.toLowerCase();
  if (BRAND_TITLES[lower]) return BRAND_TITLES[lower];
  if (/^\d+$/.test(w)) return w;
  // version-like token (letter + digits), e.g. "v4" — keep lowercase
  if (/^[a-z]\d+$/.test(lower) && lower.length <= 4) return lower;
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

export function displayNamePlaceholder(modelId: string): string {
  return modelId
    .split(/[-_]+/)
    .filter((part) => part.length > 0)
    .map(titleWord)
    .join(" ");
}

function providerNameOf(m: ModelEntry): string {
  const id = m.model_id ?? "";
  const slash = id.indexOf("/");
  if (slash > 0) return id.slice(0, slash);
  const u = (m.upstreams ?? [])[0];
  if (u) {
    const s = u.indexOf("/");
    return s > 0 ? u.slice(0, s) : u;
  }
  return "";
}

// Auto-fill an edit form from a models.dev model entry (leave existing values
// alone; only fill what's empty/unset).
function applyModelsDev(f: EditState, entry: Record<string, unknown>): EditState {
  const id = String(entry.id ?? "");
  const provider = String(entry.provider ?? "");
  const fullId = provider ? `${provider}/${id}` : id;
  const name = String(entry.name ?? "");
  const desc = String(entry.description ?? "");
  const limit = (entry.limit ?? {}) as Record<string, unknown>;
  const mods = (entry.modalities ?? {}) as { input?: unknown; output?: unknown };
  const inList = Array.isArray(mods.input) ? (mods.input as string[]) : [];
  const outList = Array.isArray(mods.output) ? (mods.output as string[]) : [];
  const family = String(entry.family ?? "");
  const brand = resolveBrandKey(family || provider) ?? resolveBrandKey(provider);

  return {
    ...f,
    models_dev_id: fullId,
    display_name: f.display_name || name,
    description: f.description || desc,
    limit_context: f.limit_context || (limit.context != null ? String(limit.context) : ""),
    limit_input: f.limit_input || (limit.input != null ? String(limit.input) : ""),
    limit_output: f.limit_output || (limit.output != null ? String(limit.output) : ""),
    reasoning: f.reasoning || entry.reasoning === true,
    capabilities: {
      text: f.capabilities.text || outList.includes("text") || inList.includes("text"),
      image: f.capabilities.image || outList.includes("image") || inList.includes("image"),
      audio: f.capabilities.audio || outList.includes("audio") || inList.includes("audio"),
      tool: f.capabilities.tool || entry.tool_call === true,
    },
    brand: f.brand || brand || "",
  };
}

function BrandIcon({ brand, modelId }: { brand?: string | null; modelId: string }) {
  const icon = getBrandIcon(brand, modelId);
  if (icon) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={24}
        height={24}
        role="img"
        aria-hidden="true"
        style={{
          flexShrink: 0,
          fill: "currentColor",
          color: tokens.colorNeutralForeground1,
        }}
      >
        <path d={icon.path} />
      </svg>
    );
  }
  // No brand/icon: fall back to the first letter of the model name.
  const nameToken = modelId.split(/[/-]+/).pop() ?? modelId;
  const firstLetter = (nameToken.charAt(0) || "?").toUpperCase();
  return (
    <span
      style={{
        width: 24,
        height: 24,
        flexShrink: 0,
        borderRadius: 6,
        background: tokens.colorNeutralBackground3,
        color: tokens.colorNeutralForeground3,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 13,
        fontWeight: 700,
        fontFamily: "system-ui, sans-serif",
      }}
    >
      {firstLetter}
    </span>
  );
}

export function Models() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const styles = useStyles();
  const notify = useNotify();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const { isStaff } = useAuth();
  const catalog = useAsync<ModelEntry[]>(() => api.get("/api/models"));
  const roleGroups = useAsync<RoleGroup[]>(() =>
    isStaff ? api.get("/api/admin/role-groups") : Promise.resolve([]),
  );
  const categories = useAsync<ModelCategory[]>(
    () => api.get<ModelCategory[]>("/api/models/categories").catch(() => []),
    [],
  );
  const providers = useAsync<Provider[]>(() =>
    isStaff ? api.get("/api/admin/providers") : Promise.resolve([]),
  );

  const [search, setSearch] = useState("");
  const [searchField, setSearchField] = useState<SearchField>("all");
  const [filterAvail, setFilterAvail] = useState("all");
  const [filterGroup, setFilterGroup] = useState("all");
  const [filterCategory, setFilterCategory] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<EditState | null>(null);
  const [create, setCreate] = useState<CreateState | null>(null);
  const [saving, setSaving] = useState(false);

  const [categoryOpen, setCategoryOpen] = useState(false);
  const [categoryName, setCategoryName] = useState("");
  const [categorySaving, setCategorySaving] = useState(false);

  // Collapsed model categories (persisted locally; default = all expanded).
  const COLLAPSED_KEY = "voidswitch.models.collapsedCategories";
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(COLLAPSED_KEY);
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });
  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed]));
  }, [collapsed]);

  function toggleCollapse(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const [groupEdit, setGroupEdit] = useState<{
    model_id: string;
    ids: Set<number>;
  } | null>(null);
  const [groupSearch, setGroupSearch] = useState("");
  const customGroups = (roleGroups.data ?? []).filter((g) => !g.builtin);

  function openGroupEdit(m: ModelEntry) {
    setGroupSearch("");
    setGroupEdit({ model_id: m.model_id, ids: new Set(m.allowed_role_group_ids) });
  }

  function toggleGroup(id: number) {
    setGroupEdit((g) => {
      if (!g) return g;
      const ids = new Set(g.ids);
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      return { ...g, ids };
    });
  }

  async function saveGroups() {
    if (!groupEdit) return;
    setSaving(true);
    try {
      await api.put("/api/models", {
        model_id: groupEdit.model_id,
        allowed_role_group_ids: [...groupEdit.ids],
      });
      notify(t("models.accessSaved" as TK), groupEdit.model_id, "success");
      setGroupEdit(null);
      catalog.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }
  const [cleaning, setCleaning] = useState(false);

  const [batchOpen, setBatchOpen] = useState(false);
  const [batchDescOn, setBatchDescOn] = useState(true);
  const [batchDesc, setBatchDesc] = useState("");
  const [batchEnabled, setBatchEnabled] = useState<BatchEnabled>("unchanged");
  const [batchGroupsOn, setBatchGroupsOn] = useState(false);
  const [batchGroupIds, setBatchGroupIds] = useState<Set<number>>(new Set());
  const [batchGroupSearch, setBatchGroupSearch] = useState("");
  const [batchConfigOn, setBatchConfigOn] = useState(false);
  const [batchConfig, setBatchConfig] = useState("");
  const [batchConfigMode, setBatchConfigMode] = useState<"merge" | "overwrite">(
    "merge",
  );
  const [batchCapabilitiesOn, setBatchCapabilitiesOn] = useState(false);
  const [batchCapabilities, setBatchCapabilities] = useState({
    text: false,
    image: false,
    audio: false,
    tool: false,
  });
  const [batchReasoningOn, setBatchReasoningOn] = useState(false);
  const [batchReasoning, setBatchReasoning] = useState<BatchEnabled>("unchanged");
  const [batchLimitsOn, setBatchLimitsOn] = useState(false);
  const [batchLimitContext, setBatchLimitContext] = useState("");
  const [batchLimitInput, setBatchLimitInput] = useState("");
  const [batchLimitOutput, setBatchLimitOutput] = useState("");
  const [batchCategoryOn, setBatchCategoryOn] = useState(false);
  const [batchCategoryId, setBatchCategoryId] = useState("");

  function openBatch() {
    setBatchDescOn(false);
    setBatchDesc("");
    setBatchEnabled("unchanged");
    setBatchGroupsOn(false);
    setBatchGroupIds(new Set());
    setBatchGroupSearch("");
    setBatchConfigOn(false);
    setBatchConfig("");
    setBatchConfigMode("merge");
    setBatchCapabilitiesOn(false);
    setBatchCapabilities({ text: false, image: false, audio: false, tool: false });
    setBatchReasoningOn(false);
    setBatchReasoning("unchanged");
    setBatchLimitsOn(false);
    setBatchLimitContext("");
    setBatchLimitInput("");
    setBatchLimitOutput("");
    setBatchCategoryOn(false);
    setBatchCategoryId("");
    setBatchOpen(true);
  }

  function toggleBatchGroup(id: number) {
    setBatchGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const items = catalog.data ?? [];

  const filtered = items.filter((m) => {
    const q = search.trim().toLowerCase();
    let match = true;
    if (q) {
      const modelId = m.model_id.toLowerCase();
      const name = (m.display_name ?? "").toLowerCase();
      const desc = (m.description ?? "").toLowerCase();
      switch (searchField) {
        case "id":
          match = modelId.includes(q);
          break;
        case "name":
          match = name.includes(q);
          break;
        case "description":
          match = desc.includes(q);
          break;
        default:
          match = modelId.includes(q) || name.includes(q) || desc.includes(q);
      }
    }
    if (match && filterAvail === "available") match = m.enabled;
    else if (match && filterAvail === "hidden") match = !m.enabled;
    if (match && filterGroup === "unassigned")
      match = m.allowed_role_group_ids.length === 0;
    else if (match && filterGroup !== "all")
      match = m.allowed_role_group_ids.includes(Number(filterGroup));
    if (match && filterCategory !== "all") {
      if (filterCategory === "uncategorized")
        match = (m.category_id == null) && !m.provider;
      else if (filterCategory.startsWith("provider:")) {
        const slug = filterCategory.slice("provider:".length);
        match = !!m.provider && providerNameOf(m) === slug;
      } else
        match = String(m.category_id ?? "") === filterCategory;
    }
    return match;
  });

// Unserved = exposed models with no reachable upstream. Passthrough virtual
// models (``provider`` bit set) are served directly by their provider, so they
// are never "unserved" even though they carry no route/upstreams.
const unserved = items.filter((m) => !m.provider && (m.upstreams ?? []).length === 0);
const cleanable = items.filter((m) => !m.provider && (m.upstreams ?? []).length === 0);

  const providerPassthroughSlugs = Array.from(
    new Set(
      items.filter((m) => m.provider).map(providerNameOf).filter(Boolean),
    ),
  ).sort((a, b) => a.localeCompare(b));

  // Group the filtered models by category (manual / provider passthrough /
  // uncategorized), preserving a stable order even when "all" is shown.
  interface CategoryGroup {
    key: string;
    label: string;
    provider: boolean;
    models: ModelEntry[];
  }
  const grouped = useMemo<CategoryGroup[]>(() => {
    const order: string[] = [];
    const map = new Map<string, CategoryGroup>();
    const push = (key: string, label: string, provider: boolean) => {
      if (!map.has(key)) {
        map.set(key, { key, label, provider, models: [] });
        order.push(key);
      }
    };
    for (const m of filtered) {
      let key: string;
      let label: string;
      let provider = false;
      if (m.provider) {
        key = `provider:${providerNameOf(m)}`;
        label = providerNameOf(m);
        provider = true;
      } else if (m.category_id != null) {
        key = `cat:${m.category_id}`;
        label = m.category_name ?? String(m.category_id);
      } else {
        key = "uncategorized";
        label = t("models.filterUncategorized" as TK);
      }
      push(key, label, provider);
      map.get(key)!.models.push(m);
    }
    // Manual categories first (DB order), then provider passthrough, then
    // uncategorized at the end.
    const sorted = order.sort((a, b) => {
      const at = a.startsWith("cat:") ? 0 : a.startsWith("provider:") ? 1 : 2;
      const bt = b.startsWith("cat:") ? 0 : b.startsWith("provider:") ? 1 : 2;
      if (at !== bt) return at - bt;
      if (a.startsWith("cat:")) {
        return (
          (categories.data ?? []).findIndex((c) => `cat:${c.id}` === a) -
          (categories.data ?? []).findIndex((c) => `cat:${c.id}` === b)
        );
      }
      return a.localeCompare(b);
    });
    return sorted.map((k) => map.get(k)!);
  }, [filtered, categories.data, t]);

  function categoryFilterLabel(): string {
    if (filterCategory === "all") return t("models.filterAllCategories" as TK);
    if (filterCategory === "uncategorized")
      return t("models.filterUncategorized" as TK);
    if (filterCategory.startsWith("provider:")) {
      const slug = filterCategory.slice("provider:".length);
      return `${slug} · ${t("models.providerBadge" as TK)}`;
    }
    const cat = (categories.data ?? []).find(
      (c) => String(c.id) === filterCategory,
    );
    return cat?.name ?? filterCategory;
  }

  function categoryLabel(catId: string): string {
    if (!catId) return t("models.filterUncategorized" as TK);
    const id = Number(catId);
    const cat = (categories.data ?? []).find((c) => c.id === id);
    return cat?.name ?? catId;
  }

  async function saveCategory() {
    const name = categoryName.trim();
    if (!name) return;
    setCategorySaving(true);
    try {
      await api.post("/api/models/categories", { name, position: 0 });
      notify(t("models.categoryCreated" as TK), name, "success");
      setCategoryName("");
      setCategoryOpen(false);
      categories.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setCategorySaving(false);
    }
  }

  function searchFieldLabel(field: SearchField): string {
    switch (field) {
      case "id":
        return t("models.searchFieldId" as TK);
      case "name":
        return t("models.searchFieldName" as TK);
      case "description":
        return t("models.searchFieldDescription" as TK);
      default:
        return t("models.searchFieldAll" as TK);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleFilteredSelection() {
    const ids = filtered.map((m) => m.model_id);
    const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  const filteredSelectedCount = filtered.filter((m) => selected.has(m.model_id)).length;
  const filteredAllSelected = filtered.length > 0 && filteredSelectedCount === filtered.length;
  const filteredSomeSelected = filteredSelectedCount > 0 && !filteredAllSelected;

  async function doClean() {
    if (!cleanable.length) return;
    const ok = await confirm({
      title: t("models.cleanTitle" as TK),
      message:
        t("models.cleanMsg" as TK).replace(
          "{count}",
          String(cleanable.length),
        ) +
        "\n" +
        cleanable.map((m) => `• ${m.model_id}`).join("\n"),
      confirmLabel: t("models.cleanConfirm" as TK),
      tone: "danger",
    });
    if (!ok) return;
    setCleaning(true);
    try {
      const r = await api.post<{ deleted: number; model_ids: string[] }>(
        "/api/models/clean",
      );
      notify(
        t("models.cleaned" as TK),
        t("models.cleanedDetail" as TK).replace(
          "{count}",
          String(r.deleted),
        ),
        "success",
      );
      catalog.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setCleaning(false);
    }
  }

  const CAP_WORDS: Array<keyof EditState["capabilities"]> = [
    "text",
    "image",
    "audio",
    "tool",
  ];

  function openEdit(m: ModelEntry) {
    const caps = (m.capabilities ?? {}) as Record<string, unknown>;
    const mods = (m.modalities ?? {}) as Record<string, unknown>;
    setEdit({
      model_id: m.model_id,
      display_name: m.display_name ?? "",
      description: m.description ?? "",
      enabled: m.enabled,
      config: prettyJson(m.opencode_config),
      limit_context: m.limit_context != null ? String(m.limit_context) : "",
      limit_input: m.limit_input != null ? String(m.limit_input) : "",
      limit_output: m.limit_output != null ? String(m.limit_output) : "",
      reasoning: !!m.reasoning,
      capabilities: {
        text: !!caps.text,
        image: !!caps.image,
        audio: !!caps.audio,
        tool: !!caps.tool,
      },
      modalities_input: Number(mods?.input) > 0 ? String(mods.input) : "",
      modalities_output: Number(mods?.output) > 0 ? String(mods.output) : "",
      models_dev_id: m.models_dev_id ?? "",
      category_id: m.category_id != null ? String(m.category_id) : "",
      brand: m.brand ?? "",
    });
  }

  async function saveEdit() {
    if (!edit) return;
    const config = parseConfig(edit.config);
    if (config === "INVALID") {
      notify(
        t("models.invalidConfig" as TK),
        t("models.invalidConfigMsg" as TK),
        "error",
      );
      return;
    }
    const payload: Record<string, unknown> = {
      model_id: edit.model_id,
      display_name: edit.display_name.trim(),
      description: edit.description,
      opencode_config: config,
      enabled: edit.enabled,
      reasoning: edit.reasoning,
      capabilities: {},
      modalities: {},
    };
    for (const w of CAP_WORDS) {
      if (edit.capabilities[w]) (payload.capabilities as Record<string, unknown>)[w] = true;
    }
    const mi = intOrEmpty(edit.modalities_input);
    const mo = intOrEmpty(edit.modalities_output);
    if (mi != null) (payload.modalities as Record<string, unknown>).input = mi;
    if (mo != null) (payload.modalities as Record<string, unknown>).output = mo;
    const lc = intOrEmpty(edit.limit_context);
    const li = intOrEmpty(edit.limit_input);
    const lo = intOrEmpty(edit.limit_output);
    if (lc != null) payload.limit_context = lc;
    if (li != null) payload.limit_input = li;
    if (lo != null) payload.limit_output = lo;
    if (edit.models_dev_id.trim()) payload.models_dev_id = edit.models_dev_id.trim();
    if (edit.category_id) payload.category_id = intOrEmpty(edit.category_id);
    payload.brand = edit.brand.trim() || null;
    setSaving(true);
    try {
      await api.put("/api/models", payload);
      notify(t("models.saved" as TK), edit.model_id, "success");
      setEdit(null);
      catalog.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function saveCreate() {
    if (!create) return;
    const modelId = create.model_id.trim();
    if (!modelId) {
      notify(
        t("models.invalidConfig" as TK),
        "Model ID is required.",
        "error",
      );
      return;
    }
    const payload: Record<string, unknown> = {
      model_id: modelId,
      enabled: create.enabled,
    };
    if (create.display_name.trim()) payload.display_name = create.display_name.trim();
    if (create.description.trim()) payload.description = create.description.trim();
    if (create.category_id) payload.category_id = intOrEmpty(create.category_id);
    setSaving(true);
    try {
      await api.put("/api/models", payload);
      // If a provider+upstream was picked, create the first route layer.
      if (create.provider_id && create.upstream_model.trim()) {
        try {
          await api.put(`/api/models/${encodeURIComponent(modelId)}/route`, {
            layers: [{
              max_attempts: 1,
              entries: [{
                provider_id: Number(create.provider_id),
                upstream_model: create.upstream_model.trim(),
                weight: 1,
                enabled: true,
                key_pool: "",
              }],
            }],
          });
        } catch {
          // Route creation failed silently; the model was already created.
        }
      }
      notify(t("models.created" as TK), modelId, "success");
      setCreate(null);
      catalog.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function saveBatch() {
    const ids = [...selected];
    if (ids.length === 0) return;
    const payload: Record<string, unknown> = { model_ids: ids };
    if (batchDescOn) payload.description = batchDesc;
    if (batchEnabled !== "unchanged") payload.enabled = batchEnabled === "enabled";
    if (batchGroupsOn) payload.allowed_role_group_ids = [...batchGroupIds];
    if (batchConfigOn) {
      const cfg = parseConfig(batchConfig);
      if (cfg === "INVALID") {
        notify(
          t("models.invalidConfig" as TK),
          t("models.invalidConfigMsg" as TK),
          "error",
        );
        return;
      }
      payload.opencode_config = cfg;
      payload.opencode_config_mode = batchConfigMode;
    }
    if (batchCapabilitiesOn) {
      const caps: Record<string, unknown> = {};
      for (const w of CAP_WORDS) {
        if (batchCapabilities[w]) caps[w] = true;
      }
      payload.capabilities = caps;
    }
    if (batchReasoningOn && batchReasoning !== "unchanged")
      payload.reasoning = batchReasoning === "enabled";
    if (batchLimitsOn) {
      const lc = intOrEmpty(batchLimitContext);
      const li = intOrEmpty(batchLimitInput);
      const lo = intOrEmpty(batchLimitOutput);
      if (lc != null) payload.limit_context = lc;
      if (li != null) payload.limit_input = li;
      if (lo != null) payload.limit_output = lo;
    }
    if (batchCategoryOn) {
      const cid = intOrEmpty(batchCategoryId);
      payload.category_id = cid;
    }
    setSaving(true);
    try {
      await api.post("/api/models/batch", payload);
      notify(t("models.updated" as TK), `${ids.length} model(s) updated.`, "success");
      setBatchOpen(false);
      setSelected(new Set());
      catalog.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(m: ModelEntry) {
    if (m.id == null) return;
    const ok = await confirm({
      title: t("models.deleteTitle" as TK),
      message: t("models.deleteMsgServed" as TK).replace("{id}", m.model_id),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/models/${m.id}`);
      notify(t("models.metadataRemoved" as TK), m.model_id, "success");
      catalog.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title={t("models.title" as TK)}
        subtitle={t("models.subtitle" as TK)}
        onRefresh={catalog.reload}
        action={
          <div style={{ display: "flex", gap: 8 }}>
            {isStaff && selected.size > 0 && (
              <Button icon={<EditRegular />} onClick={openBatch}>
                {t("models.editSelected" as TK).replace("{count}", String(selected.size))}
              </Button>
            )}
            {isStaff && unserved.length > 0 && (
              <Tooltip
                content={t("models.cleanTooltip" as TK)}
                relationship="label"
              >
                <Button
                  icon={<DeleteRegular />}
                  disabled={cleaning}
                  onClick={doClean}
                >
                  {cleaning
                    ? t("models.cleaning" as TK)
                    : t("models.clean" as TK)}
                </Button>
              </Tooltip>
            )}
            {isStaff && (
              <Button
                appearance="primary"
                icon={<AddRegular />}
                onClick={() =>
                  setCreate({
                    model_id: "",
                    display_name: "",
                    description: "",
                    enabled: true,
                    provider_id: "",
                    upstream_model: "",
                    category_id: "",
                  })
                }
              >
                {t("models.create" as TK)}
              </Button>
            )}
          </div>
        }
      />

      <div className={styles.toolbar}>
        {isStaff ? (
          <Checkbox
            checked={filteredSomeSelected ? "mixed" : filteredAllSelected}
            disabled={filtered.length === 0}
            onChange={toggleFilteredSelection}
            label={t("models.selectFiltered" as TK).replace(
              "{count}",
              String(filtered.length),
            )}
          />
        ) : null}
        <Dropdown
          aria-label={t("models.searchField" as TK)}
          style={{ minWidth: 130 }}
          selectedOptions={[searchField]}
          value={searchFieldLabel(searchField)}
          onOptionSelect={(_, d) =>
            setSearchField((d.optionValue as SearchField) ?? "all")
          }
        >
          <Option value="all">{t("models.searchFieldAll" as TK)}</Option>
          <Option value="id">{t("models.searchFieldId" as TK)}</Option>
          <Option value="name">{t("models.searchFieldName" as TK)}</Option>
          <Option value="description">
            {t("models.searchFieldDescription" as TK)}
          </Option>
        </Dropdown>
        <Input
          className={styles.search}
          contentBefore={<SearchRegular />}
          placeholder={t("models.search" as TK)}
          value={search}
          onChange={(_, d) => setSearch(d.value)}
        />
        <Text size={200} className={styles.dim}>
          {t("models.count" as TK)
            .replace("{filtered}", String(filtered.length))
            .replace("{total}", String(items.length))}
        </Text>
        {isStaff && selected.size > 0 ? (
          <Button size="small" appearance="subtle" onClick={() => setSelected(new Set())}>
            {t("models.clearSelection" as TK).replace(
              "{count}",
              String(selected.size),
            )}
          </Button>
        ) : null}
      </div>

      <div className={styles.toolbar}>
        <Dropdown
          aria-label={t("models.filterAvailability" as TK)}
          style={{ minWidth: 130 }}
          selectedOptions={[filterAvail]}
          value={
            filterAvail === "all"
              ? t("models.filterAllAvail" as TK)
              : filterAvail === "available"
                ? t("common.enabled" as TK)
                : t("models.unavailableHidden" as TK)
          }
          onOptionSelect={(_, d) => setFilterAvail(d.optionValue ?? "all")}
        >
          <Option value="all">{t("models.filterAllAvail" as TK)}</Option>
          <Option value="available">{t("common.enabled" as TK)}</Option>
          <Option value="hidden">{t("models.unavailableHidden" as TK)}</Option>
        </Dropdown>
        <Dropdown
          aria-label={t("models.filterCategory" as TK)}
          style={{ minWidth: 150 }}
          selectedOptions={[filterCategory]}
          value={categoryFilterLabel()}
          onOptionSelect={(_, d) => setFilterCategory(d.optionValue ?? "all")}
        >
          <Option value="all">{t("models.filterAllCategories" as TK)}</Option>
          <Option value="uncategorized">{t("models.filterUncategorized" as TK)}</Option>
          {(categories.data ?? []).map((c) => (
            <Option key={c.id} value={String(c.id)}>{c.name}</Option>
          ))}
          {providerPassthroughSlugs.map((slug) => {
            const label = `${slug} · ${t("models.providerBadge" as TK)}`;
            return (
              <Option key={`provider:${slug}`} value={`provider:${slug}`} text={label}>
                {label}
              </Option>
            );
          })}
        </Dropdown>
        {isStaff && (
          <Tooltip content={t("models.createCategory" as TK)} relationship="label">
            <Button
              aria-label={t("models.createCategory" as TK)}
              appearance="subtle"
              icon={<FolderAddRegular />}
              onClick={() => setCategoryOpen(true)}
            />
          </Tooltip>
        )}
        {isStaff && (
          <Dropdown
            aria-label={t("models.filterGroup" as TK)}
            style={{ minWidth: 150 }}
            selectedOptions={[filterGroup]}
            value={
              filterGroup === "all"
                ? t("models.filterAllGroups" as TK)
                : filterGroup === "unassigned"
                  ? t("models.filterUnassigned" as TK)
                  : (roleGroups.data ?? []).find((g) => String(g.id) === filterGroup)?.name ?? filterGroup
            }
            onOptionSelect={(_, d) => setFilterGroup(d.optionValue ?? "all")}
          >
            <Option value="all">{t("models.filterAllGroups" as TK)}</Option>
            <Option value="unassigned">{t("models.filterUnassigned" as TK)}</Option>
            {(roleGroups.data ?? []).filter((g) => !g.builtin).map((g) => (
              <Option key={g.id} value={String(g.id)}>{g.name}</Option>
            ))}
          </Dropdown>
        )}
      </div>

      {catalog.loading ? (
        <Loading />
      ) : catalog.error ? (
        <ErrorText error={catalog.error} />
      ) : filtered.length === 0 ? (
        <Text className={styles.dim}>
          {t("models.noModels" as TK)}
        </Text>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {grouped.map((g) => {
            const isCollapsed = collapsed.has(g.key);
            const chevron = isCollapsed ? <ChevronRightRegular /> : <ChevronDownRegular />;
            return (
              <div key={g.key}>
                <button
                  type="button"
                  onClick={() => toggleCollapse(g.key)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    width: "100%",
                    padding: "6px 4px",
                    marginBottom: 10,
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: tokens.colorNeutralForeground2,
                    fontSize: tokens.fontSizeBase400,
                    fontWeight: 600,
                  }}
                >
                  <span style={{ display: "inline-flex" }}>{chevron}</span>
                  <span>{g.label}</span>
                  {g.provider && (
                    <Badge appearance="tint" color="informative">
                      {t("models.providerBadge" as TK)}
                    </Badge>
                  )}
                  <span style={{ color: tokens.colorNeutralForeground3, fontWeight: 400 }}>
                    {g.models.length}
                  </span>
                </button>
                {!isCollapsed && (
                  <div className={styles.grid}>
                    {g.models.map((m) => {
                      const hasConfig =
                        m.opencode_config && Object.keys(m.opencode_config).length > 0;
                      return (
                        <div key={m.model_id} className={m.enabled ? styles.card : styles.cardHidden}>
                          <div className={styles.head}>
                            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", minWidth: 0 }}>
                              <BrandIcon brand={m.brand} modelId={m.model_id} />
                              <div style={{ minWidth: 0 }}>
                                {m.display_name && (
                                  <Text weight="semibold" block>
                                    {m.display_name}
                                  </Text>
                                )}
                                <Text weight={m.display_name ? "regular" : "semibold"} className={styles.modelId}>
                                  {m.model_id}
                                </Text>
                              </div>
                            </div>
                            {isStaff && (
                              <Checkbox
                                checked={selected.has(m.model_id)}
                                onChange={() => toggle(m.model_id)}
                                aria-label={`Select ${m.model_id}`}
                              />
                            )}
                          </div>

                          <Text size={200} className={styles.desc}>
                            {m.description || (
                              <span className={styles.dim}>{t("models.noDescription" as TK)}</span>
                            )}
                          </Text>

                          <div className={styles.badges}>
                            {!m.enabled && (
                              <Badge appearance="filled" color="subtle">
                                {t("models.unavailableHidden" as TK)}
                              </Badge>
                            )}
                            {m.reasoning && (
                              <Badge appearance="tint" color="brand">
                                {t("models.reasoningBadge" as TK)}
                              </Badge>
                            )}
                            {m.models_dev_id && (
                              <Badge appearance="tint" color="informative">
                                models.dev
                              </Badge>
                            )}
                            {hasConfig && (
                              <Badge appearance="tint" color="brand">
                                {t("common.customConfig" as TK)}
                              </Badge>
                            )}
                            {m.provider && (
                              <Badge appearance="tint" color="informative">
                                {t("models.providerBadge" as TK)}
                              </Badge>
                            )}
                            {m.category_name && !m.provider && (
                              <Badge appearance="outline" color="brand">
                                {m.category_name}
                              </Badge>
                            )}
                            {isStaff &&
                              (m.upstreams ?? []).map((u) => (
                                <Badge key={u} appearance="outline" color="informative">
                                  {u}
                                </Badge>
                              ))}
                          </div>

                          {isStaff && (
                            <div className={styles.actions}>
                              <Tooltip content={t("models.route" as TK)} relationship="label">
                                <Button
                                  size="small"
                                  appearance="subtle"
                                  icon={<ArrowRoutingRegular />}
                                  onClick={() => navigate(`/models/${encodeURIComponent(m.model_id)}/route`)}
                                  aria-label={t("models.route" as TK)}
                                />
                              </Tooltip>
                              <Tooltip content={t("common.edit" as TK)} relationship="label">
                                <Button
                                  size="small"
                                  appearance="subtle"
                                  icon={<EditRegular />}
                                  onClick={() => openEdit(m)}
                                  aria-label={t("common.edit" as TK)}
                                />
                              </Tooltip>
                              <Tooltip
                                content={
                                  m.allowed_role_group_ids.length > 0
                                    ? t("models.accessCount" as TK).replace(
                                        "{count}",
                                        String(m.allowed_role_group_ids.length),
                                      )
                                    : t("models.accessTooltip" as TK)
                                }
                                relationship="label"
                              >
                                <Button
                                  size="small"
                                  appearance={
                                    m.allowed_role_group_ids.length > 0 ? "primary" : "subtle"
                                  }
                                  icon={<PeopleTeamRegular />}
                                  onClick={() => openGroupEdit(m)}
                                  aria-label={t("models.access" as TK)}
                                />
                              </Tooltip>
                              <Tooltip content={t("common.delete" as TK)} relationship="label">
                                <Button
                                  size="small"
                                  appearance="subtle"
                                  icon={<DeleteRegular />}
                                  onClick={() => remove(m)}
                                  aria-label={t("common.delete" as TK)}
                                />
                              </Tooltip>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={edit !== null} onOpenChange={(_, d) => !d.open && setEdit(null)}>
        <DialogSurface
          style={{ maxWidth: 640 }}
        >
          <DialogBody>
            <DialogTitle>{t("models.editModel" as TK)}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Field label={t("models.modelId" as TK)}>
                <Input value={edit?.model_id ?? ""} disabled />
              </Field>
              <Field
                label={t("models.displayName" as TK)}
                hint={t("models.displayNameHint" as TK)}
              >
                <Input
                  value={edit?.display_name ?? ""}
                  placeholder={displayNamePlaceholder(edit?.model_id ?? "")}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, display_name: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("models.description" as TK)}>
                <Textarea
                  value={edit?.description ?? ""}
                  rows={3}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, description: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("models.category" as TK)}>
                <Dropdown
                  value={categoryLabel(edit?.category_id ?? "")}
                  selectedOptions={[edit?.category_id ?? ""]}
                  onOptionSelect={(_, d) =>
                    setEdit((f) =>
                      f ? { ...f, category_id: (d.optionValue ?? "") } : f,
                    )
                  }
                >
                  <Option value="">{t("models.filterUncategorized" as TK)}</Option>
                  {(categories.data ?? []).map((c) => (
                    <Option key={c.id} value={String(c.id)}>{c.name}</Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label={t("models.brand" as TK)} hint={t("models.brandHint" as TK)}>
                <Dropdown
                  value={edit?.brand ? edit.brand : t("models.brandAuto" as TK)}
                  selectedOptions={edit?.brand ? [edit.brand] : []}
                  onOptionSelect={(_, d) =>
                    setEdit((f) => (f ? { ...f, brand: d.optionValue ?? "" } : f))
                  }
                >
                  <Option value="">{t("models.brandAuto" as TK)}</Option>
                  {BRAND_KEYS.map((b) => (
                    <Option key={b} value={b}>{b}</Option>
                  ))}
                </Dropdown>
              </Field>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <Field label={t("models.limitContext" as TK)}>
                  <Input
                    type="number"
                    value={edit?.limit_context ?? ""}
                    placeholder="200000"
                    style={{ width: 140 }}
                    onChange={(_, d) =>
                      setEdit((f) => (f ? { ...f, limit_context: d.value } : f))
                    }
                  />
                </Field>
                <Field label={t("models.limitInput" as TK)}>
                  <Input
                    type="number"
                    value={edit?.limit_input ?? ""}
                    style={{ width: 140 }}
                    onChange={(_, d) =>
                      setEdit((f) => (f ? { ...f, limit_input: d.value } : f))
                    }
                  />
                </Field>
                <Field label={t("models.limitOutput" as TK)}>
                  <Input
                    type="number"
                    value={edit?.limit_output ?? ""}
                    style={{ width: 140 }}
                    onChange={(_, d) =>
                      setEdit((f) => (f ? { ...f, limit_output: d.value } : f))
                    }
                  />
                </Field>
              </div>
              <Switch
                label={t("models.reasoning" as TK)}
                checked={edit?.reasoning ?? false}
                onChange={(_, d) =>
                  setEdit((f) => (f ? { ...f, reasoning: d.checked } : f))
                }
              />
              <Field label={t("models.capabilities" as TK)}>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {CAP_WORDS.map((w) => (
                    <Checkbox
                      key={w}
                      label={w}
                      checked={edit?.capabilities[w] ?? false}
                      onChange={(_, d) =>
                        setEdit((f) =>
                          f
                            ? {
                                ...f,
                                capabilities: { ...f.capabilities, [w]: d.checked },
                              }
                            : f,
                        )
                      }
                    />
                  ))}
                </div>
              </Field>
              <div style={{ display: "flex", gap: 12 }}>
                <Field label={t("models.modalitiesInput" as TK)} hint={t("models.modalitiesHint" as TK)}>
                  <Input
                    type="number"
                    value={edit?.modalities_input ?? ""}
                    onChange={(_, d) =>
                      setEdit((f) => (f ? { ...f, modalities_input: d.value } : f))
                    }
                  />
                </Field>
                <Field label={t("models.modalitiesOutput" as TK)}>
                  <Input
                    type="number"
                    value={edit?.modalities_output ?? ""}
                    onChange={(_, d) =>
                      setEdit((f) => (f ? { ...f, modalities_output: d.value } : f))
                    }
                  />
                </Field>
              </div>
              <Field
                label={t("models.configLabel" as TK)}
                hint={t("models.configHint" as TK)}
              >
                <Textarea
                  value={edit?.config ?? ""}
                  rows={6}
                  placeholder={t("models.configPlaceholder" as TK)}
                  style={{ fontFamily: tokens.fontFamilyMonospace }}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, config: d.value } : f))
                  }
                />
              </Field>
              <Switch
                label={t("models.availableLabel" as TK)}
                checked={edit?.enabled ?? true}
                onChange={(_, d) =>
                  setEdit((f) => (f ? { ...f, enabled: d.checked } : f))
                }
              />
              <ModelsDevSection
                modelsDevId={edit?.models_dev_id ?? ""}
                onPick={(entry) =>
                  setEdit((f) => (f ? applyModelsDev(f, entry) : f))
                }
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEdit(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveEdit} data-shortcut="save">
                {t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={batchOpen} onOpenChange={(_, d) => !d.open && setBatchOpen(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("models.batchTitle" as TK).replace("{count}", String(selected.size))}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Checkbox
                checked={batchDescOn}
                onChange={(_, d) => setBatchDescOn(!!d.checked)}
                label={t("models.batchDescLabel" as TK)}
              />
              <Field>
                <Textarea
                  value={batchDesc}
                  rows={3}
                  disabled={!batchDescOn}
                  placeholder={t("models.batchDescPlaceholder" as TK)}
                  onChange={(_, d) => setBatchDesc(d.value)}
                />
              </Field>
              <Field label={t("models.batchAvailability" as TK)}>
                <Dropdown
                  value={
                    batchEnabled === "unchanged"
                      ? t("models.batchUnchanged" as TK)
                      : batchEnabled === "enabled"
                        ? t("models.batchAvailable" as TK)
                        : t("models.batchHidden" as TK)
                  }
                  selectedOptions={[batchEnabled]}
                  onOptionSelect={(_, d) =>
                    setBatchEnabled((d.optionValue as BatchEnabled) ?? "unchanged")
                  }
                >
                  <Option value="unchanged">{t("models.batchUnchanged" as TK)}</Option>
                  <Option value="enabled">{t("models.batchAvailable" as TK)}</Option>
                  <Option value="disabled">{t("models.batchHidden" as TK)}</Option>
                </Dropdown>
              </Field>

              <Checkbox
                checked={batchGroupsOn}
                onChange={(_, d) => setBatchGroupsOn(!!d.checked)}
                label={t("models.batchAccessLabel" as TK)}
              />
              {batchGroupsOn ? (
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 6 }}
                >
                  <Input
                    contentBefore={<SearchRegular />}
                    placeholder={t("models.accessSearch" as TK)}
                    value={batchGroupSearch}
                    onChange={(_, d) => setBatchGroupSearch(d.value)}
                  />
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      maxHeight: 180,
                      overflowY: "auto",
                    }}
                  >
                    {customGroups.length === 0 ? (
                      <Text size={200} className={styles.dim}>
                        {t("models.accessNoGroups" as TK)}
                      </Text>
                    ) : (
                      customGroups
                        .filter((g) => {
                          const q = batchGroupSearch.trim().toLowerCase();
                          if (!q) return true;
                          return (
                            g.name.toLowerCase().includes(q) ||
                            (g.description ?? "").toLowerCase().includes(q)
                          );
                        })
                        .map((g) => (
                          <Checkbox
                            key={g.id}
                            checked={batchGroupIds.has(g.id)}
                            onChange={() => toggleBatchGroup(g.id)}
                            label={g.name}
                          />
                        ))
                    )}
                  </div>
                  <Text size={100} className={styles.dim}>
                    {t("models.batchAccessHint" as TK)}
                  </Text>
                </div>
              ) : null}

              <Checkbox
                checked={batchConfigOn}
                onChange={(_, d) => setBatchConfigOn(!!d.checked)}
                label={t("models.batchConfigLabel" as TK)}
              />
              {batchConfigOn ? (
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 8 }}
                >
                  <Dropdown
                    value={
                      batchConfigMode === "merge"
                        ? t("models.batchConfigMerge" as TK)
                        : t("models.batchConfigOverwrite" as TK)
                    }
                    selectedOptions={[batchConfigMode]}
                    onOptionSelect={(_, d) =>
                      setBatchConfigMode(
                        (d.optionValue as "merge" | "overwrite") ?? "merge",
                      )
                    }
                  >
                    <Option value="merge">{t("models.batchConfigMerge" as TK)}</Option>
                    <Option value="overwrite">
                      {t("models.batchConfigOverwrite" as TK)}
                    </Option>
                  </Dropdown>
                  <Textarea
                    value={batchConfig}
                    rows={5}
                    placeholder={t("models.configPlaceholder" as TK)}
                    style={{ fontFamily: tokens.fontFamilyMonospace }}
                    onChange={(_, d) => setBatchConfig(d.value)}
                  />
                  <Text size={100} className={styles.dim}>
                    {batchConfigMode === "merge"
                      ? t("models.batchConfigMergeHint" as TK)
                      : t("models.batchConfigOverwriteHint" as TK)}
                  </Text>
                </div>
              ) : null}

              <Checkbox
                checked={batchCapabilitiesOn}
                onChange={(_, d) => setBatchCapabilitiesOn(!!d.checked)}
                label={t("models.batchCapabilitiesLabel" as TK)}
              />
              {batchCapabilitiesOn ? (
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {CAP_WORDS.map((w) => (
                    <Checkbox
                      key={w}
                      label={w}
                      checked={batchCapabilities[w]}
                      onChange={(_, d) =>
                        setBatchCapabilities((prev) => ({
                          ...prev,
                          [w]: !!d.checked,
                        }))
                      }
                    />
                  ))}
                </div>
              ) : null}

              <Checkbox
                checked={batchReasoningOn}
                onChange={(_, d) => setBatchReasoningOn(!!d.checked)}
                label={t("models.batchReasoningLabel" as TK)}
              />
              {batchReasoningOn ? (
                <Dropdown
                  value={
                    batchReasoning === "unchanged"
                      ? t("models.batchUnchanged" as TK)
                      : batchReasoning === "enabled"
                        ? t("models.batchAvailable" as TK)
                        : t("models.batchHidden" as TK)
                  }
                  selectedOptions={[batchReasoning]}
                  onOptionSelect={(_, d) =>
                    setBatchReasoning(
                      (d.optionValue as BatchEnabled) ?? "unchanged",
                    )
                  }
                >
                  <Option value="unchanged">{t("models.batchUnchanged" as TK)}</Option>
                  <Option value="enabled">{t("models.batchAvailable" as TK)}</Option>
                  <Option value="disabled">{t("models.batchHidden" as TK)}</Option>
                </Dropdown>
              ) : null}

              <Checkbox
                checked={batchLimitsOn}
                onChange={(_, d) => setBatchLimitsOn(!!d.checked)}
                label={t("models.batchLimitsLabel" as TK)}
              />
              {batchLimitsOn ? (
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  <Field label={t("models.limitContext" as TK)}>
                    <Input
                      type="number"
                      value={batchLimitContext}
                      placeholder="200000"
                      style={{ width: 140 }}
                      onChange={(_, d) => setBatchLimitContext(d.value)}
                    />
                  </Field>
                  <Field label={t("models.limitInput" as TK)}>
                    <Input
                      type="number"
                      value={batchLimitInput}
                      style={{ width: 140 }}
                      onChange={(_, d) => setBatchLimitInput(d.value)}
                    />
                  </Field>
                  <Field label={t("models.limitOutput" as TK)}>
                    <Input
                      type="number"
                      value={batchLimitOutput}
                      style={{ width: 140 }}
                      onChange={(_, d) => setBatchLimitOutput(d.value)}
                    />
                  </Field>
                </div>
              ) : null}

              <Checkbox
                checked={batchCategoryOn}
                onChange={(_, d) => setBatchCategoryOn(!!d.checked)}
                label={t("models.batchCategoryLabel" as TK)}
              />
              {batchCategoryOn ? (
                <Dropdown
                  value={categoryLabel(batchCategoryId)}
                  selectedOptions={[batchCategoryId]}
                  onOptionSelect={(_, d) =>
                    setBatchCategoryId(d.optionValue ?? "")
                  }
                >
                  <Option value="">{t("models.filterUncategorized" as TK)}</Option>
                  {(categories.data ?? []).map((c) => (
                    <Option key={c.id} value={String(c.id)}>{c.name}</Option>
                  ))}
                </Dropdown>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setBatchOpen(false)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveBatch} data-shortcut="apply">
                {t("common.apply" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={create !== null} onOpenChange={(_, d) => !d.open && setCreate(null)}>
        <DialogSurface style={{ maxWidth: 560 }}>
          <DialogBody>
            <DialogTitle>{t("models.createTitle" as TK)}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Field label={t("models.modelId" as TK)}>
                <Input
                  value={create?.model_id ?? ""}
                  placeholder={t("models.modelIdPlaceholder" as TK)}
                  onChange={(_, d) =>
                    setCreate((f) =>
                      f ? { ...f, model_id: d.value } : f,
                    )
                  }
                />
              </Field>
              <Field
                label={t("models.displayName" as TK)}
                hint={t("models.displayNameHint" as TK)}
              >
                <Input
                  value={create?.display_name ?? ""}
                  placeholder={displayNamePlaceholder(create?.model_id ?? "")}
                  onChange={(_, d) =>
                    setCreate((f) =>
                      f ? { ...f, display_name: d.value } : f,
                    )
                  }
                />
              </Field>
              <Field label={t("models.description" as TK)}>
                <Textarea
                  value={create?.description ?? ""}
                  rows={2}
                  onChange={(_, d) =>
                    setCreate((f) =>
                      f ? { ...f, description: d.value } : f,
                    )
                  }
                />
              </Field>
              <Field label={t("models.category" as TK)}>
                <Dropdown
                  value={categoryLabel(create?.category_id ?? "")}
                  selectedOptions={[create?.category_id ?? ""]}
                  onOptionSelect={(_, d) =>
                    setCreate((f) =>
                      f ? { ...f, category_id: (d.optionValue ?? "") } : f,
                    )
                  }
                >
                  <Option value="">{t("models.filterUncategorized" as TK)}</Option>
                  {(categories.data ?? []).map((c) => (
                    <Option key={c.id} value={String(c.id)}>{c.name}</Option>
                  ))}
                </Dropdown>
              </Field>
              <div
                style={{
                  border: `1px solid ${tokens.colorNeutralStroke2}`,
                  borderRadius: 8,
                  padding: 12,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  background: tokens.colorNeutralBackground2,
                }}
              >
                <Text size={200} className={styles.dim}>
                  {t("models.providerPickerHint" as TK)}
                </Text>
                <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                  <Field label={t("models.pickProvider" as TK)} style={{ flex: "1 1 180px" }}>
                    <Dropdown
                      value={
                        create?.provider_id
                          ? (providers.data ?? []).find(
                              (p) => String(p.id) === create.provider_id,
                            )?.slug ?? t("models.pickProvider" as TK)
                          : t("models.pickProvider" as TK)
                      }
                      selectedOptions={[create?.provider_id ?? ""]}
                      onOptionSelect={(_, d) =>
                        setCreate((f) =>
                          f ? { ...f, provider_id: (d.optionValue ?? "") } : f,
                        )
                      }
                    >
                      <Option value="">{t("models.pickProvider" as TK)}</Option>
                      {(providers.data ?? []).map((p) => (
                        <Option key={p.id} value={String(p.id)}>
                          {p.slug || p.name}
                        </Option>
                      ))}
                    </Dropdown>
                  </Field>
                  <Field label={t("models.upstreamModel" as TK)} style={{ flex: "1 1 180px" }}>
                    <Input
                      value={create?.upstream_model ?? ""}
                      placeholder={t("models.upstreamPlaceholder" as TK)}
                      onChange={(_, d) =>
                        setCreate((f) =>
                          f ? { ...f, upstream_model: d.value } : f,
                        )
                      }
                    />
                  </Field>
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCreate(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveCreate} data-shortcut="apply">
                {t("common.create" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={groupEdit !== null}
        onOpenChange={(_, d) => !d.open && setGroupEdit(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("models.accessTitle" as TK)}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Text size={200} className={styles.dim}>
                {t("models.accessHelp" as TK).replace(
                  "{id}",
                  groupEdit?.model_id ?? "",
                )}
              </Text>
              <Input
                contentBefore={<SearchRegular />}
                placeholder={t("models.accessSearch" as TK)}
                value={groupSearch}
                onChange={(_, d) => setGroupSearch(d.value)}
              />
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  maxHeight: 280,
                  overflowY: "auto",
                }}
              >
                {customGroups.length === 0 ? (
                  <Text size={200} className={styles.dim}>
                    {t("models.accessNoGroups" as TK)}
                  </Text>
                ) : (
                  customGroups
                    .filter((g) => {
                      const q = groupSearch.trim().toLowerCase();
                      if (!q) return true;
                      return (
                        g.name.toLowerCase().includes(q) ||
                        (g.description ?? "").toLowerCase().includes(q)
                      );
                    })
                    .map((g) => (
                      <Checkbox
                        key={g.id}
                        checked={groupEdit?.ids.has(g.id) ?? false}
                        onChange={() => toggleGroup(g.id)}
                        label={g.name}
                      />
                    ))
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setGroupEdit(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveGroups} data-shortcut="save">
                {t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={categoryOpen} onOpenChange={(_, d) => !d.open && setCategoryOpen(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("models.createCategory" as TK)}</DialogTitle>
            <DialogContent>
              <Field label={t("models.categoryName" as TK)}>
                <Input
                  value={categoryName}
                  autoFocus
                  onChange={(_, d) => setCategoryName(d.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveCategory();
                  }}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCategoryOpen(false)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={categorySaving || !categoryName.trim()}
                onClick={() => void saveCategory()}
              >
                {t("common.create" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}

function ModelsDevSection({
  modelsDevId,
  onPick,
}: {
  modelsDevId: string;
  onPick: (entry: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [searching, setSearching] = useState(false);
  const [syncingMd, setSyncingMd] = useState(false);

  async function search() {
    const query = q.trim();
    if (!query) return;
    setSearching(true);
    try {
      const r = await api.get<ModelsDevSearchResult>(
        "/api/models/models-dev/search",
        { q: query },
      );
      setResults(r.results ?? []);
    } catch (e) {
      notify(
        t("models.modelsDevSearchFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSearching(false);
    }
  }

  async function syncMd() {
    setSyncingMd(true);
    try {
      const r = await api.post<{ synced: number }>("/api/models/models-dev/sync");
      notify(
        t("models.modelsDevSynced" as TK),
        t("models.modelsDevSyncedDetail" as TK).replace(
          "{count}",
          String(r.synced),
        ),
        "success",
      );
    } catch (e) {
      notify(
        t("models.modelsDevSearchFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSyncingMd(false);
    }
  }

  function label(entry: Record<string, unknown>): string {
    return String(entry.name ?? entry.id ?? "");
  }

  function fullIdOf(entry: Record<string, unknown>): string {
    const id = String(entry.id ?? "");
    const provider = String(entry.provider ?? "");
    return provider ? `${provider}/${id}` : id;
  }

  return (
    <div
      style={{
        border: `1px solid ${tokens.colorNeutralStroke2}`,
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        background: tokens.colorNeutralBackground2,
      }}
    >
      <div style={{ fontWeight: 600 }}>{t("models.modelsDevTitle" as TK)}</div>
      {modelsDevId ? (
        <Field label={t("models.modelsDevLinked" as TK)}>
          <Input readOnly value={modelsDevId} />
        </Field>
      ) : (
        <Button
          size="small"
          appearance="subtle"
          disabled={syncingMd}
          onClick={syncMd}
        >
          {syncingMd
            ? t("models.modelsDevSyncing" as TK)
            : t("models.modelsDevSync" as TK)}
        </Button>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <Input
          placeholder={t("models.modelsDevSearch" as TK)}
          value={q}
          onChange={(_, d) => setQ(d.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") search();
          }}
        />
        <Button disabled={searching || !q.trim()} onClick={search}>
          {searching ? <Spinner size="tiny" /> : t("models.modelsDevSearchBtn" as TK)}
        </Button>
      </div>
      {results.length > 0 && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          {results.map((entry, i) => {
            const fullId = fullIdOf(entry);
            const selected = fullId === modelsDevId;
            return (
              <div
                key={fullId || i}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  justifyContent: "space-between",
                  border: `1px solid ${tokens.colorNeutralStroke2}`,
                  borderRadius: 6,
                  padding: "6px 8px",
                  background: tokens.colorNeutralBackground1,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {label(entry)}
                  </div>
                  <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>
                    {fullId}
                    {entry.provider_name ? ` · ${String(entry.provider_name)}` : ""}
                  </Text>
                </div>
                <Button
                  size="small"
                  appearance={selected ? "primary" : "subtle"}
                  onClick={() => onPick(entry)}
                  title={t("models.modelsDevAutoFill" as TK)}
                >
                  {selected
                    ? t("models.modelsDevSelected" as TK)
                    : t("models.modelsDevUse" as TK)}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
