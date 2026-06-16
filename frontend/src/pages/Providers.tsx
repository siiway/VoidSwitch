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
  SpinButton,
  Spinner,
  Switch,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowLeftRegular,
  ArrowRightRegular,
  ArrowSwapRegular,
  DeleteRegular,
  EditRegular,
  KeyRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  AdapterMeta,
  ModelRoute,
  Provider,
  Proxy,
  ProxyMode,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

type TK = keyof Translations;

interface FormState {
  id?: number;
  name: string;
  type: string;
  base_url: string;
  models: string;
  priority: number;
  weight: number;
  enabled: boolean;
  drop_opencode_identity_block: boolean;
  proxy_mode: ProxyMode;
  proxy_ids: number[];
  model_routes: string;
}

const EMPTY: FormState = {
  name: "",
  type: "openai",
  base_url: "",
  models: "",
  priority: 100,
  weight: 1,
  enabled: true,
  drop_opencode_identity_block: false,
  proxy_mode: "all",
  proxy_ids: [],
  model_routes: "",
};

// Model routes use one line per route: `alias => upstream @ pool`
// (`=> upstream` and `@ pool` are both optional).
function parseRoutes(text: string): ModelRoute[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      let rest = line;
      let pool = "";
      const at = rest.lastIndexOf("@");
      if (at >= 0) {
        pool = rest.slice(at + 1).trim();
        rest = rest.slice(0, at).trim();
      }
      let alias = rest;
      let upstream = "";
      const arrow = rest.indexOf("=>");
      if (arrow >= 0) {
        alias = rest.slice(0, arrow).trim();
        upstream = rest.slice(arrow + 2).trim();
      }
      return { alias, upstream, pool };
    })
    .filter((r) => r.alias);
}

function formatRoutes(routes: ModelRoute[]): string {
  return (routes ?? [])
    .map((r) => {
      let s = r.alias;
      if (r.upstream) s += ` => ${r.upstream}`;
      if (r.pool) s += ` @ ${r.pool}`;
      return s;
    })
    .join("\n");
}

export function Providers() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const { user: me, isStaff, isOwner } = useAuth();
  const canEdit = (p: Provider) => isStaff || p.added_by === me?.id;
  const providers = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const catalog = useAsync<AdapterMeta[]>(() =>
    api.get("/api/admin/providers/catalog/types"),
  );
  const proxies = useAsync<Proxy[]>(() => api.get("/api/admin/proxies"));
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [fetchOpen, setFetchOpen] = useState(false);
  const [fetchToken, setFetchToken] = useState("");
  const [fetching, setFetching] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [fetchError, setFetchError] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const PROXY_MODE_LABEL: Record<ProxyMode, string> = {
    all: t("providers.proxyModeAll" as TK),
    direct: t("providers.proxyModeDirect" as TK),
    selected: t("providers.proxyModeSelected" as TK),
  };

  function openCreate() {
    setForm({ ...EMPTY });
  }

  function openEdit(p: Provider) {
    setForm({
      id: p.id,
      name: p.name,
      type: p.type,
      base_url: p.base_url,
      models: p.models.join("\n"),
      priority: p.priority,
      weight: p.weight,
      enabled: p.enabled,
      drop_opencode_identity_block: p.drop_opencode_identity_block,
      proxy_mode: p.proxy_mode,
      proxy_ids: p.proxy_ids ?? [],
      model_routes: formatRoutes(p.model_routes),
    });
  }

  function applyType(type: string) {
    const meta = catalog.data?.find((c) => c.type === type);
    setForm((f) =>
      f
        ? {
            ...f,
            type,
            base_url: f.base_url || meta?.default_base_url || "",
            models: f.models || (meta?.default_models.join("\n") ?? ""),
          }
        : f,
    );
  }

  async function fetchModelsFromApi() {
    if (!form?.base_url || !fetchToken) return;
    setFetching(true);
    setFetchError("");
    setFetchedModels([]);
    try {
      const base = form.base_url.replace(/\/+$/, "");
      const url = `${base}/models`;
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${fetchToken}` },
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      const json = await res.json();
      let items: any[];
      if (Array.isArray(json)) {
        items = json;
      } else if (Array.isArray(json.data)) {
        items = json.data;
      } else if (Array.isArray(json.models)) {
        items = json.models;
      } else {
        throw new Error("Unexpected response format");
      }
      const ids: string[] = items
        .map((m: any) => (typeof m === "string" ? m : m?.id ?? m?.name ?? ""))
        .filter((id: string) => id.length > 0);
      if (!ids.length) throw new Error("No models found in response");
      ids.sort();
      setFetchedModels(ids);
      setSelectedIds(new Set(ids));
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : String(e));
    } finally {
      setFetching(false);
    }
  }

  function applyFetchedModels(mode: "prepend" | "append" | "replace") {
    if (!form || !selectedIds.size) return;
    const existing = form.models
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const picked = [...selectedIds];
    let merged: string[];
    if (mode === "replace") {
      merged = picked;
    } else if (mode === "prepend") {
      merged = [...picked, ...existing.filter((id) => !selectedIds.has(id))];
    } else {
      const existSet = new Set(existing);
      merged = [...existing, ...picked.filter((id) => !existSet.has(id))];
    }
    setForm({ ...form, models: merged.join("\n") });
    setFetchOpen(false);
  }

  async function save() {
    if (!form) return;
    const models = form.models
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      name: form.name,
      type: form.type,
      base_url: form.base_url,
      models,
      priority: form.priority,
      weight: form.weight,
      enabled: form.enabled,
      drop_opencode_identity_block: form.drop_opencode_identity_block,
      proxy_mode: form.proxy_mode,
      proxy_ids: form.proxy_mode === "selected" ? form.proxy_ids : [],
      model_routes: parseRoutes(form.model_routes),
    };
    setSaving(true);
    try {
      if (form.id) {
        await api.patch(`/api/admin/providers/${form.id}`, payload);
        notify(t("providers.updated" as TK), form.name, "success");
      } else {
        await api.post("/api/admin/providers", payload);
        notify(t("providers.created" as TK), form.name, "success");
      }
      setForm(null);
      providers.reload();
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

  async function remove(p: Provider) {
    const ok = await confirm({
      title: t("providers.deleteTitle" as TK),
      message: t("providers.deleteMsg" as TK).replace("{name}", p.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/providers/${p.id}`);
      notify(t("providers.deleted" as TK), p.name, "success");
      providers.reload();
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
        title={t("providers.title" as TK)}
        subtitle={t("providers.subtitle" as TK)}
        action={
          <Button
            appearance="primary"
            icon={<AddRegular />}
            onClick={openCreate}
          >
            {t("providers.add" as TK)}
          </Button>
        }
      />

      {providers.loading ? (
        <Loading />
      ) : providers.error ? (
        <ErrorText error={providers.error} />
      ) : (
        <DataTable ariaLabel={t("providers.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("providers.name" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.type" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.baseUrl" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.keys" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.addedBy" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.priority" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("providers.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(providers.data ?? []).map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.name}</TableCell>
                <TableCell>{p.type}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {p.base_url}
                </TableCell>
                <TableCell>
                  {p.active_key_count}/{p.key_count}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {p.added_by_name ?? "—"}
                </TableCell>
                <TableCell>{p.priority}</TableCell>
                <TableCell>
                  <Badge
                    color={p.enabled ? "success" : "subtle"}
                    appearance="filled"
                  >
                    {p.enabled
                      ? t("providers.enabled" as TK)
                      : t("providers.disabled" as TK)}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    icon={<KeyRegular />}
                    appearance="subtle"
                    onClick={() => navigate(`/providers/${p.id}/keys`)}
                  >
                    Keys
                  </Button>
                  {canEdit(p) && (
                    <Button
                      size="small"
                      icon={<EditRegular />}
                      appearance="subtle"
                      onClick={() => openEdit(p)}
                    />
                  )}
                  {isOwner && (
                    <Button
                      size="small"
                      icon={<DeleteRegular />}
                      appearance="subtle"
                      onClick={() => remove(p)}
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <Dialog
        open={form !== null}
        onOpenChange={(_, d) => !d.open && setForm(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {form?.id
                ? t("providers.edit" as TK)
                : t("providers.add" as TK)}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                paddingTop: 8,
              }}
            >
              <Field label={t("providers.name" as TK)} required>
                <Input
                  value={form?.name ?? ""}
                  disabled={!!form?.id}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, name: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("providers.adapterType" as TK)}>
                <Dropdown
                  value={form?.type ?? ""}
                  selectedOptions={form ? [form.type] : []}
                  onOptionSelect={(_, d) =>
                    d.optionValue && applyType(d.optionValue)
                  }
                >
                  {(catalog.data ?? []).map((c) => (
                    <Option key={c.type} value={c.type} text={c.type}>
                      {c.type} ({c.style})
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label={t("providers.baseUrl" as TK)}>
                <Input
                  value={form?.base_url ?? ""}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, base_url: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("providers.modelsHint" as TK)}>
                <Textarea
                  value={form?.models ?? ""}
                  rows={4}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, models: d.value } : f))
                  }
                />
              </Field>
              <div>
                <Button
                  size="small"
                  appearance="subtle"
                  onClick={() => setFetchOpen(true)}
                >
                  {t("providers.fetchModels" as TK)}
                </Button>
              </div>
              <Field
                label={t("providers.modelRoutes" as TK)}
                hint={t("providers.modelRoutesHint" as TK)}
              >
                <Textarea
                  value={form?.model_routes ?? ""}
                  rows={3}
                  placeholder={
                    "deepseek-v4-flash-lkd => deepseek-v4-flash @ leaked\ndeepseek-v4-flash => deepseek-v4-flash @ members"
                  }
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, model_routes: d.value } : f))
                  }
                />
              </Field>
              <div style={{ display: "flex", gap: 12 }}>
                <Field label={t("providers.priorityHint" as TK)}>
                  <SpinButton
                    value={form?.priority ?? 100}
                    onChange={(_, d) =>
                      setForm((f) =>
                        f ? { ...f, priority: d.value ?? f.priority } : f,
                      )
                    }
                  />
                </Field>
                <Field label={t("providers.weight" as TK)}>
                  <SpinButton
                    value={form?.weight ?? 1}
                    min={1}
                    onChange={(_, d) =>
                      setForm((f) =>
                        f ? { ...f, weight: d.value ?? f.weight } : f,
                      )
                    }
                  />
                </Field>
              </div>
              <Switch
                label={t("common.enabled" as TK)}
                checked={form?.enabled ?? true}
                onChange={(_, d) =>
                  setForm((f) => (f ? { ...f, enabled: d.checked } : f))
                }
              />
              <Field label={t("providers.outboundProxy" as TK)}>
                <Dropdown
                  value={
                    form
                      ? PROXY_MODE_LABEL[form.proxy_mode]
                      : PROXY_MODE_LABEL.all
                  }
                  selectedOptions={form ? [form.proxy_mode] : ["all"]}
                  onOptionSelect={(_, d) =>
                    d.optionValue &&
                    setForm((f) =>
                      f ? { ...f, proxy_mode: d.optionValue as ProxyMode } : f,
                    )
                  }
                >
                  {(Object.keys(PROXY_MODE_LABEL) as ProxyMode[]).map((m) => (
                    <Option key={m} value={m} text={PROXY_MODE_LABEL[m]}>
                      {PROXY_MODE_LABEL[m]}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              {form?.proxy_mode === "selected" && (
                <Field
                  label={t("providers.proxiesHint" as TK)}
                  hint={t("providers.proxiesHelp" as TK)}
                >
                  <Dropdown
                    multiselect
                    placeholder={t("providers.selectProxies" as TK)}
                    value={
                      (form?.proxy_ids ?? [])
                        .map(
                          (id) =>
                            (proxies.data ?? []).find((p) => p.id === id)
                              ?.url ?? `#${id}`,
                        )
                        .join(", ") || ""
                    }
                    selectedOptions={(form?.proxy_ids ?? []).map(String)}
                    onOptionSelect={(_, d) =>
                      setForm((f) =>
                        f
                          ? {
                              ...f,
                              proxy_ids: d.selectedOptions.map((s) =>
                                Number(s),
                              ),
                            }
                          : f,
                      )
                    }
                  >
                    {(proxies.data ?? []).map((p) => (
                      <Option key={p.id} value={String(p.id)} text={p.url}>
                        {p.url}
                        {p.status !== "active" ? ` (${p.status})` : ""}
                      </Option>
                    ))}
                  </Dropdown>
                </Field>
              )}
              {form?.type === "claude-code" && (
                <Switch
                  label={t("providers.dropIdentityLabel" as TK)}
                  checked={form?.drop_opencode_identity_block ?? false}
                  onChange={(_, d) =>
                    setForm((f) =>
                      f ? { ...f, drop_opencode_identity_block: d.checked } : f,
                    )
                  }
                />
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setForm(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={saving || !form?.name}
                onClick={save}
              >
                {form?.id ? t("common.save" as TK) : t("common.create" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={fetchOpen} onOpenChange={(_, d) => !d.open && setFetchOpen(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {t("providers.fetchModelsTitle" as TK)}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                paddingTop: 8,
                minWidth: 360,
              }}
            >
              <Field label={t("providers.fetchTokenLabel" as TK)} hint={t("providers.fetchTokenHint" as TK)}>
                <Input
                  type="password"
                  value={fetchToken}
                  placeholder="sk-…"
                  onChange={(_, d) => setFetchToken(d.value)}
                />
              </Field>
              <Button
                appearance="primary"
                disabled={fetching || !fetchToken || !form?.base_url}
                onClick={fetchModelsFromApi}
              >
                {fetching
                  ? t("providers.fetching" as TK)
                  : t("providers.fetchBtn" as TK)}
              </Button>
              {fetching && (
                <div style={{ display: "flex", justifyContent: "center", padding: 8 }}>
                  <Spinner size="small" />
                </div>
              )}
              {fetchError && (
                <div style={{ color: tokens.colorStatusDangerForeground1, fontSize: 13 }}>
                  {fetchError}
                </div>
              )}
              {fetchedModels.length > 0 && (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 13, color: tokens.colorNeutralForeground3 }}>
                      {fetchedModels.length} {t("providers.modelsFound" as TK)}
                    </span>
                    <Button
                      size="small"
                      appearance="subtle"
                      onClick={() =>
                        setSelectedIds(
                          selectedIds.size === fetchedModels.length
                            ? new Set()
                            : new Set(fetchedModels),
                        )
                      }
                    >
                      {selectedIds.size === fetchedModels.length
                        ? t("providers.deselectAll" as TK)
                        : t("providers.selectAll" as TK)}
                    </Button>
                  </div>
                  <div
                    style={{
                      maxHeight: 240,
                      overflowY: "auto",
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      padding: 4,
                      border: `1px solid ${tokens.colorNeutralStroke2}`,
                      borderRadius: 4,
                    }}
                  >
                    {fetchedModels.map((id) => (
                      <Checkbox
                        key={id}
                        label={id}
                        checked={selectedIds.has(id)}
                        onChange={(_, d) =>
                          setSelectedIds((prev) => {
                            const next = new Set(prev);
                            d.checked ? next.add(id) : next.delete(id);
                            return next;
                          })
                        }
                      />
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Button
                      appearance="primary"
                      icon={<ArrowLeftRegular />}
                      disabled={!selectedIds.size}
                      onClick={() => applyFetchedModels("prepend")}
                    >
                      {t("providers.prepend" as TK)}
                    </Button>
                    <Button
                      appearance="primary"
                      icon={<ArrowRightRegular />}
                      disabled={!selectedIds.size}
                      onClick={() => applyFetchedModels("append")}
                    >
                      {t("providers.append" as TK)}
                    </Button>
                    <Button
                      appearance="primary"
                      icon={<ArrowSwapRegular />}
                      disabled={!selectedIds.size}
                      onClick={() => applyFetchedModels("replace")}
                    >
                      {t("providers.replace" as TK)}
                    </Button>
                  </div>
                </>
              )}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() => setFetchOpen(false)}
              >
                {t("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
