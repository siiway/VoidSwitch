import {
  Badge,
  Button,
  Card,
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
  Switch,
  Text,
  Textarea,
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowSyncRegular,
  DeleteRegular,
  EditRegular,
  SearchRegular,
} from "@fluentui/react-icons";
import JSON5 from "json5";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ModelEntry, ModelSyncResult } from "../api/types";
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
  mapped_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
  config: string;
}

type BatchEnabled = "unchanged" | "enabled" | "disabled";

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

export function Models() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const styles = useStyles();
  const notify = useNotify();
  const confirm = useConfirm();
  const { isStaff } = useAuth();
  const catalog = useAsync<ModelEntry[]>(() => api.get("/api/models"));

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const [batchOpen, setBatchOpen] = useState(false);
  const [batchDescOn, setBatchDescOn] = useState(true);
  const [batchDesc, setBatchDesc] = useState("");
  const [batchEnabled, setBatchEnabled] = useState<BatchEnabled>("unchanged");

  const items = catalog.data ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (m) =>
        m.model_id.toLowerCase().includes(q) ||
        m.public_id.toLowerCase().includes(q) ||
        (m.description ?? "").toLowerCase().includes(q) ||
        m.providers.some((p) => p.toLowerCase().includes(q)),
    );
  }, [items, search]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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

  function openEdit(m: ModelEntry) {
    setEdit({
      model_id: m.model_id,
      mapped_id: m.mapped_id ?? "",
      display_name: m.display_name ?? "",
      description: m.description ?? "",
      enabled: m.enabled,
      config: prettyJson(m.opencode_config),
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
    if (edit.mapped_id.trim() === edit.model_id) {
      notify(
        t("models.invalidMapping" as TK),
        t("models.invalidMappingMsg" as TK),
        "error",
      );
      return;
    }
    setSaving(true);
    try {
      await api.put("/api/models", {
        model_id: edit.model_id,
        mapped_id: edit.mapped_id.trim(),
        display_name: edit.display_name.trim(),
        description: edit.description,
        opencode_config: config,
        enabled: edit.enabled,
      });
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
      message: m.served
        ? t("models.deleteMsgServed" as TK).replace("{id}", m.model_id)
        : t("models.deleteMsgUnserved" as TK).replace("{id}", m.model_id),
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
        action={
          <div style={{ display: "flex", gap: 8 }}>
            {isStaff && selected.size > 0 && (
              <Button icon={<EditRegular />} onClick={() => setBatchOpen(true)}>
                {t("models.editSelected" as TK).replace("{count}", String(selected.size))}
              </Button>
            )}
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
          </div>
        }
      />

      <div className={styles.toolbar}>
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
              <Card key={m.model_id} className={styles.card}>
                <div className={styles.head}>
                  <div style={{ minWidth: 0 }}>
                    {m.display_name && (
                      <Text weight="semibold" block>
                        {m.display_name}
                      </Text>
                    )}
                    <Text weight={m.display_name ? "regular" : "semibold"} className={styles.modelId}>
                      {m.public_id}
                    </Text>
                    {m.mapped_id ? (
                      <Text size={100} className={styles.dim} block>
                        ← {m.model_id}
                      </Text>
                    ) : null}
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
                      {t("common.hidden" as TK)}
                    </Badge>
                  )}
                  {m.mapped_id && (
                    <Badge appearance="tint" color="success">
                      {t("common.mapped" as TK)}
                    </Badge>
                  )}
                  {!m.served && (
                    <Badge appearance="tint" color="warning">
                      {t("common.noProvider" as TK)}
                    </Badge>
                  )}
                  {hasConfig && (
                    <Badge appearance="tint" color="brand">
                      {t("common.customConfig" as TK)}
                    </Badge>
                  )}
                  {m.providers.map((p) => (
                    <Badge key={p} appearance="outline" color="informative">
                      {p}
                    </Badge>
                  ))}
                </div>

                {isStaff && (
                  <div className={styles.actions}>
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      onClick={() => openEdit(m)}
                    >
                      {t("common.edit" as TK)}
                    </Button>
                    {m.registered && (
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<DeleteRegular />}
                        onClick={() => remove(m)}
                      />
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={edit !== null} onOpenChange={(_, d) => !d.open && setEdit(null)}>
        <DialogSurface>
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
              <Field
                label={t("models.publicId" as TK)}
                hint={t("models.publicIdHint" as TK)}
              >
                <Input
                  value={edit?.mapped_id ?? ""}
                  placeholder={t("models.publicIdPlaceholder" as TK)}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, mapped_id: d.value } : f))
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
    </div>
  );
}
