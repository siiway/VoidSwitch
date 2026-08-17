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
  ArrowRoutingRegular,
  ArrowSyncRegular,
  DeleteRegular,
  EditRegular,
  PeopleTeamRegular,
  SearchRegular,
} from "@fluentui/react-icons";
import JSON5 from "json5";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  ModelEntry,
  ModelSyncResult,
  ModelsDevSearchResult,
  RoleGroup,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
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

  const [search, setSearch] = useState("");
  const [searchField, setSearchField] = useState<SearchField>("all");
  const [filterAvail, setFilterAvail] = useState("all");
  const [filterGroup, setFilterGroup] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);

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
  const [syncing, setSyncing] = useState(false);
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
    return match;
  });

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

  async function sync() {
    setSyncing(true);
    try {
      const r = await api.post<ModelSyncResult>("/api/models/sync");
      notify(
        t("models.catalogSynced" as TK),
        t("models.syncResult" as TK)
          .replace("{added}", String(r.added))
          .replace("{total}", String(r.total)),
        "success",
      );
      catalog.reload();
    } catch (e) {
      notify(
        t("providerKeys.syncFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSyncing(false);
    }
  }

  // Exposed models with no resolvable upstream (empty or disabled route) are the
  // closest client-side signal that "clean" has work to do.
  const unserved = filtered.filter((m) => (m.upstreams ?? []).length === 0);
  // For the confirm dialog we look at the whole catalog, not the filtered view.
  const cleanable = items.filter((m) => (m.upstreams ?? []).length === 0);

  async function doClean() {
    if (!cleanable.length) return;
    const ok = await confirm({
      title: t("models.cleanTitle" as TK),
      message:
        t("models.cleanMsg" as TK).replace(
          "{count}",
          String(cleanable.length),
        ) +
        "\n\n" +
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
              <Tooltip
                content={t("models.syncTooltip" as TK)}
                relationship="label"
              >
                <Button
                  appearance="primary"
                  icon={<ArrowSyncRegular />}
                  disabled={syncing}
                  onClick={sync}
                >
                  {syncing ? t("models.syncing" as TK) : t("models.sync" as TK)}
                </Button>
              </Tooltip>
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
        <div className={styles.grid}>
          {filtered.map((m) => {
            const hasConfig =
              m.opencode_config && Object.keys(m.opencode_config).length > 0;
            return (
              <div key={m.model_id} className={m.enabled ? styles.card : styles.cardHidden}>
                <div className={styles.head}>
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
                  placeholder={t("models.displayNamePlaceholder" as TK)}
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
                onPick={(id) =>
                  setEdit((f) => (f ? { ...f, models_dev_id: id } : f))
                }
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEdit(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveEdit}>
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
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setBatchOpen(false)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveBatch}>
                {t("common.apply" as TK)}
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
              <Button appearance="primary" disabled={saving} onClick={saveGroups}>
                {t("common.save" as TK)}
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
  onPick: (id: string) => void;
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
            const id = String(entry.id ?? entry.name ?? "");
            const selected = id === modelsDevId;
            return (
              <div
                key={id || i}
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
                    {entry.description ? String(entry.description) : ""}
                  </Text>
                </div>
                <Button
                  size="small"
                  appearance={selected ? "primary" : "subtle"}
                  onClick={() => onPick(id)}
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
