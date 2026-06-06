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
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ModelEntry, ModelSyncResult } from "../api/types";
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

/**
 * Parse the OpenCode-config textarea. Accepts JSONC / JSON5 (trailing commas,
 * comments, unquoted keys, single quotes) — the same lenient dialect OpenCode's
 * own `opencode.json` uses — so a config copied from there validates as-is.
 * Returns `"INVALID"` when it can't be parsed into a JSON object.
 */
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

  // Batch editor state.
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
        "Catalog synced",
        `${r.added} new model${r.added === 1 ? "" : "s"} registered (${r.total} total).`,
        "success",
      );
      catalog.reload();
    } catch (e) {
      notify("Sync failed", e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSyncing(false);
    }
  }

  function openEdit(m: ModelEntry) {
    setEdit({
      model_id: m.model_id,
      mapped_id: m.mapped_id ?? "",
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
        "Invalid config",
        "The OpenCode config must be a JSON / JSONC object.",
        "error",
      );
      return;
    }
    if (edit.mapped_id.trim() === edit.model_id) {
      notify("Invalid mapping", "The public id must differ from the model id.", "error");
      return;
    }
    setSaving(true);
    try {
      await api.put("/api/models", {
        model_id: edit.model_id,
        mapped_id: edit.mapped_id.trim(),
        description: edit.description,
        opencode_config: config,
        enabled: edit.enabled,
      });
      notify("Model saved", edit.model_id, "success");
      setEdit(null);
      catalog.reload();
    } catch (e) {
      notify("Save failed", e instanceof Error ? e.message : String(e), "error");
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
      notify("Models updated", `${ids.length} model(s) updated.`, "success");
      setBatchOpen(false);
      setSelected(new Set());
      catalog.reload();
    } catch (e) {
      notify("Update failed", e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(m: ModelEntry) {
    if (m.id == null) return;
    const ok = await confirm({
      title: "Delete model metadata",
      message: `Remove the description and OpenCode config for "${m.model_id}"? ${
        m.served
          ? "The model stays available (a provider still serves it) but loses its metadata."
          : "It is no longer served by any provider, so it will disappear from the catalog."
      }`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/models/${m.id}`);
      notify("Metadata removed", m.model_id, "success");
      catalog.reload();
    } catch (e) {
      notify("Delete failed", e instanceof Error ? e.message : String(e), "error");
    }
  }

  return (
    <div>
      <PageHeader
        title="Models"
        subtitle="Every model available across the platform"
        action={
          <div style={{ display: "flex", gap: 8 }}>
            {isStaff && selected.size > 0 && (
              <Button icon={<EditRegular />} onClick={() => setBatchOpen(true)}>
                Edit selected ({selected.size})
              </Button>
            )}
            <Tooltip
              content="Discover any newly-served models from the providers"
              relationship="label"
            >
              <Button
                appearance="primary"
                icon={<ArrowSyncRegular />}
                disabled={syncing}
                onClick={sync}
              >
                {syncing ? "Syncing…" : "Sync from providers"}
              </Button>
            </Tooltip>
          </div>
        }
      />

      <div className={styles.toolbar}>
        <Input
          className={styles.search}
          contentBefore={<SearchRegular />}
          placeholder="Search models, descriptions, providers…"
          value={search}
          onChange={(_, d) => setSearch(d.value)}
        />
        <Text size={200} className={styles.dim}>
          {filtered.length} of {items.length} models
        </Text>
      </div>

      {catalog.loading ? (
        <Loading />
      ) : catalog.error ? (
        <ErrorText error={catalog.error} />
      ) : filtered.length === 0 ? (
        <Text className={styles.dim}>
          No models yet. Add a provider with models, then use “Sync from
          providers”.
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
                    <Text weight="semibold" className={styles.modelId}>
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
                    <span className={styles.dim}>No description</span>
                  )}
                </Text>

                <div className={styles.badges}>
                  {!m.enabled && (
                    <Badge appearance="filled" color="subtle">
                      hidden
                    </Badge>
                  )}
                  {m.mapped_id && (
                    <Badge appearance="tint" color="success">
                      mapped
                    </Badge>
                  )}
                  {!m.served && (
                    <Badge appearance="tint" color="warning">
                      no provider
                    </Badge>
                  )}
                  {hasConfig && (
                    <Badge appearance="tint" color="brand">
                      custom config
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
                      Edit
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

      {/* Single-model editor */}
      <Dialog open={edit !== null} onOpenChange={(_, d) => !d.open && setEdit(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Edit model</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Field label="Model id">
                <Input value={edit?.model_id ?? ""} disabled />
              </Field>
              <Field
                label="Public id (mapping)"
                hint="Rename this model: when set, clients see and call only this id; the original id above is hidden and rejected. Leave blank for no mapping."
              >
                <Input
                  value={edit?.mapped_id ?? ""}
                  placeholder="e.g. fast-coder (blank = no mapping)"
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, mapped_id: d.value } : f))
                  }
                />
              </Field>
              <Field label="Description">
                <Textarea
                  value={edit?.description ?? ""}
                  rows={3}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, description: d.value } : f))
                  }
                />
              </Field>
              <Field
                label="Custom OpenCode config (JSON / JSONC)"
                hint="Deep-merged into the model block the OpenCode plugin builds. Accepts JSONC/JSON5 (trailing commas & comments OK) — e.g. {&quot;name&quot;: &quot;…&quot;, &quot;limit&quot;: {&quot;context&quot;: 200000}}."
              >
                <Textarea
                  value={edit?.config ?? ""}
                  rows={6}
                  placeholder={'{\n  "name": "My Model",\n  "limit": { "context": 200000 }\n}'}
                  style={{ fontFamily: tokens.fontFamilyMonospace }}
                  onChange={(_, d) =>
                    setEdit((f) => (f ? { ...f, config: d.value } : f))
                  }
                />
              </Field>
              <Switch
                label="Available (uncheck to hide from the model list)"
                checked={edit?.enabled ?? true}
                onChange={(_, d) =>
                  setEdit((f) => (f ? { ...f, enabled: d.checked } : f))
                }
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEdit(null)}>
                Cancel
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveEdit}>
                Save
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Batch editor */}
      <Dialog open={batchOpen} onOpenChange={(_, d) => !d.open && setBatchOpen(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Edit {selected.size} models</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              <Checkbox
                checked={batchDescOn}
                onChange={(_, d) => setBatchDescOn(!!d.checked)}
                label="Set description for all selected"
              />
              <Field>
                <Textarea
                  value={batchDesc}
                  rows={3}
                  disabled={!batchDescOn}
                  placeholder="Description applied to every selected model"
                  onChange={(_, d) => setBatchDesc(d.value)}
                />
              </Field>
              <Field label="Availability">
                <Dropdown
                  value={
                    batchEnabled === "unchanged"
                      ? "Leave unchanged"
                      : batchEnabled === "enabled"
                        ? "Available"
                        : "Hidden"
                  }
                  selectedOptions={[batchEnabled]}
                  onOptionSelect={(_, d) =>
                    setBatchEnabled((d.optionValue as BatchEnabled) ?? "unchanged")
                  }
                >
                  <Option value="unchanged">Leave unchanged</Option>
                  <Option value="enabled">Available</Option>
                  <Option value="disabled">Hidden</Option>
                </Dropdown>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setBatchOpen(false)}>
                Cancel
              </Button>
              <Button appearance="primary" disabled={saving} onClick={saveBatch}>
                Apply
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
