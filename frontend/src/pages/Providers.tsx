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
  Text,
  Textarea,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowLeftRegular,
  ArrowRightRegular,
  ArrowSwapRegular,
  CheckmarkCircleFilled,
  DeleteRegular,
  DismissCircleFilled,
  EditRegular,
  EyeRegular,
  KeyRegular,
  ShieldKeyholeRegular,
} from "@fluentui/react-icons";
import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, API_BASE } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  AdapterMeta,
  ApiKey,
  KeySelectMode,
  ModelRoute,
  Provider,
  ProviderKeyApi,
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
import { PasswordInput } from "../components/PasswordInput";
import { KeyRevealDialog } from "../components/KeyRevealDialog";

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
  retry_on_zero_token: boolean;
  proxy_mode: ProxyMode;
  proxy_ids: number[];
  model_routes: string;
  key_select_mode: KeySelectMode;
  rate_limit_cooldown_seconds: number;
  initial_keys: string;
  initial_keys_pool: string;
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
  retry_on_zero_token: false,
  proxy_mode: "all",
  proxy_ids: [],
  model_routes: "",
  key_select_mode: "round_robin",
  rate_limit_cooldown_seconds: 0,
  initial_keys: "",
  initial_keys_pool: "",
};

// Model routes use one line per route: `alias => upstream @ pool`
// (`=> upstream` and `@ pool` are both optional).
//
// Parsing is done left-to-right and anchored on the ` => ` arrow first: the
// alias is everything before the *first* arrow, and ` @ pool` is only looked for
// in the remainder (the upstream side). This keeps an alias that itself contains
// ` @ ` from being mis-split as a pool separator. When there is no arrow the line
// is the short `alias` or `alias @ pool` form, where ` @ ` still delimits the
// pool (an alias containing ` @ ` is inherently ambiguous in that shorthand).
function parseRoutes(text: string): ModelRoute[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line): ModelRoute => {
      const arrow = line.indexOf(" => ");
      if (arrow >= 0) {
        const alias = line.slice(0, arrow).trim();
        // Everything after the arrow is `upstream[ @ pool]`.
        const rest = line.slice(arrow + 4);
        const at = rest.lastIndexOf(" @ ");
        if (at >= 0) {
          return {
            alias,
            upstream: rest.slice(0, at).trim(),
            pool: rest.slice(at + 3).trim(),
          };
        }
        return { alias, upstream: rest.trim(), pool: "" };
      }
      // No arrow: `alias` or `alias @ pool`.
      const at = line.lastIndexOf(" @ ");
      if (at >= 0) {
        return {
          alias: line.slice(0, at).trim(),
          upstream: "",
          pool: line.slice(at + 3).trim(),
        };
      }
      return { alias: line, upstream: "", pool: "" };
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
  const [placeholderVals, setPlaceholderVals] = useState<Record<string, string>>({});
  const [fetchMethod, setFetchMethod] = useState("GET");
  const [fetchPath, setFetchPath] = useState("/models");
  // Per-provider key-management API credential (owner-only).
  const [keyApiFor, setKeyApiFor] = useState<Provider | null>(null);
  const [keyApi, setKeyApi] = useState<ProviderKeyApi | null>(null);
  const [keyApiToken, setKeyApiToken] = useState("");
  const [keyApiBusy, setKeyApiBusy] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);
  // Key picker for fetch-models
  const [keyPickerOpen, setKeyPickerOpen] = useState(false);
  const [keyPickerKeys, setKeyPickerKeys] = useState<{ id: number; index: number; note: string; pool: string; status: string }[]>([]);
  const [keyPickerLoading, setKeyPickerLoading] = useState(false);
  // Provider filtering
  const [providerSearch, setProviderSearch] = useState("");
  const [providerFilterType, setProviderFilterType] = useState("");
  const [providerFilterAddedBy, setProviderFilterAddedBy] = useState("");
  const [providerFilterEnabled, setProviderFilterEnabled] = useState("");

  const phKeys = [
    ...new Set(
      ((form?.base_url ?? "").match(/\{(\w+)\}/g) ?? []).map((m) =>
        m.slice(1, -1),
      ),
    ),
  ];
  const allPhFilled = phKeys.every((k) => (placeholderVals[k] ?? "").trim());

  const PROXY_MODE_LABEL: Record<ProxyMode, string> = {
    all: t("providers.proxyModeAll" as TK),
    direct: t("providers.proxyModeDirect" as TK),
    selected: t("providers.proxyModeSelected" as TK),
  };

  const KEY_SELECT_MODE_LABEL: Record<KeySelectMode, string> = {
    round_robin: t("providers.keyModeRoundRobin" as TK),
    random: t("providers.keyModeRandom" as TK),
    fallback: t("providers.keyModeFallback" as TK),
    pinned_round_robin: t("providers.keyModePinnedRoundRobin" as TK),
    pinned_random: t("providers.keyModePinnedRandom" as TK),
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
      retry_on_zero_token: p.retry_on_zero_token,
      proxy_mode: p.proxy_mode,
      proxy_ids: p.proxy_ids ?? [],
      model_routes: formatRoutes(p.model_routes),
      key_select_mode: p.key_select_mode ?? "round_robin",
      rate_limit_cooldown_seconds: p.rate_limit_cooldown_seconds ?? 0,
      initial_keys: "",
      initial_keys_pool: "",
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
      const url = form.base_url.replace(/\{(\w+)\}/g, (_, k: string) =>
        placeholderVals[k]?.trim() || `{${k}}`,
      );
      const body: Record<string, unknown> = { base_url: url, method: fetchMethod, path: fetchPath };
      const kp = fetchToken.match(/^key_id:(\d+)$/);
      if (kp) {
        body.key_id = Number(kp[1]);
      } else {
        body.token = fetchToken;
      }
      const { models } = await api.post<{ models: string[] }>(
        "/api/admin/providers/fetch-models",
        body,
      );
      if (!models?.length) throw new Error("No models found in response");
      const sorted = [...models].sort();
      setFetchedModels(sorted);
      setSelectedIds(new Set(sorted));
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : String(e));
    } finally {
      setFetching(false);
    }
  }

  async function openKeyPicker() {
    if (!form?.id) return;
    setKeyPickerLoading(true);
    setKeyPickerOpen(true);
    try {
      const keys = await api.get<{ id: number; index: number; note: string; pool: string; status: string }[]>(
        `/api/admin/providers/${form.id}/fetch-models/keys`,
      );
      setKeyPickerKeys(keys);
    } catch (e) {
      notify(
        t("providers.keyApiActionFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setKeyPickerLoading(false);
    }
  }

  function selectKeyForFetch(keyId: number) {
    setFetchToken(`key_id:${keyId}`);
    setKeyPickerOpen(false);
  }

  // Filtered providers list
  const filteredProviders = useMemo(() => {
    if (!providers.data) return [];
    let list = providers.data;
    const s = providerSearch.trim().toLowerCase();
    if (s) {
      list = list.filter((p) =>
        p.name.toLowerCase().includes(s) ||
        p.type.toLowerCase().includes(s) ||
        (p.base_url ?? "").toLowerCase().includes(s) ||
        (p.added_by_name ?? "").toLowerCase().includes(s) ||
        (p.models ?? []).some((m) => m.toLowerCase().includes(s))
      );
    }
    if (providerFilterType) {
      list = list.filter((p) => p.type === providerFilterType);
    }
    if (providerFilterAddedBy) {
      list = list.filter((p) => (p.added_by_name ?? "") === providerFilterAddedBy);
    }
    if (providerFilterEnabled === "enabled") {
      list = list.filter((p) => p.enabled);
    } else if (providerFilterEnabled === "disabled") {
      list = list.filter((p) => !p.enabled);
    }
    return list;
  }, [providers.data, providerSearch, providerFilterType, providerFilterAddedBy, providerFilterEnabled]);

  const allTypes = useMemo(() => {
    const types = new Set<string>();
    (providers.data ?? []).forEach((p) => types.add(p.type));
    return [...types].sort();
  }, [providers.data]);

  const allAddedBy = useMemo(() => {
    const names = new Set<string>();
    (providers.data ?? []).forEach((p) => { if (p.added_by_name) names.add(p.added_by_name); });
    return [...names].sort();
  }, [providers.data]);

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
      retry_on_zero_token: form.retry_on_zero_token,
      proxy_mode: form.proxy_mode,
      proxy_ids: form.proxy_mode === "selected" ? form.proxy_ids : [],
      model_routes: parseRoutes(form.model_routes),
      key_select_mode: form.key_select_mode,
      rate_limit_cooldown_seconds: Math.max(
        0,
        form.rate_limit_cooldown_seconds,
      ),
    };
    setSaving(true);
    try {
      if (form.id) {
        await api.patch(`/api/admin/providers/${form.id}`, payload);
        notify(t("providers.updated" as TK), form.name, "success");
      } else {
        const created = await api.post<Provider>(
          "/api/admin/providers",
          payload,
        );
        notify(t("providers.created" as TK), form.name, "success");
        // Optionally seed upstream keys entered in the create dialog.
        const keyLines = form.initial_keys
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);
        if (keyLines.length && created?.id) {
          try {
            const createdKeys = await api.post<ApiKey[]>(
              `/api/admin/providers/${created.id}/keys`,
              { keys: keyLines, pool: form.initial_keys_pool.trim() },
            );
            notify(
              t("providerKeys.created" as TK),
              `${createdKeys.length} new key(s)${
                form.initial_keys_pool.trim()
                  ? ` in pool "${form.initial_keys_pool.trim()}"`
                  : ""
              }`,
              "success",
            );
          } catch (e) {
            notify(
              t("providerKeys.addFailed" as TK),
              e instanceof Error ? e.message : String(e),
              "error",
            );
          }
        }
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

  async function openKeyApi(p: Provider) {
    setKeyApiFor(p);
    setKeyApi(null);
    setKeyApiToken("");
    try {
      const data = await api.get<ProviderKeyApi>(
        `/api/admin/providers/${p.id}/key-api`,
      );
      setKeyApi(data);
    } catch (e) {
      notify(
        t("providers.keyApiActionFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function keyApiAction(
    action: "enable" | "rotate" | "reveal" | "disable",
    okMsg: TK,
  ) {
    if (!keyApiFor) return;
    setKeyApiBusy(true);
    try {
      const data = await api.post<ProviderKeyApi>(
        `/api/admin/providers/${keyApiFor.id}/key-api/${action}`,
      );
      setKeyApi(data);
      if (data.token) setKeyApiToken(data.token);
      if (action !== "reveal") {
        notify(t(okMsg), keyApiFor.name, "success");
        providers.reload();
      }
    } catch (e) {
      notify(
        t("providers.keyApiActionFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setKeyApiBusy(false);
    }
  }

  async function toggleEnabled(p: Provider) {
    try {
      await api.patch(`/api/admin/providers/${p.id}`, { enabled: !p.enabled });
      notify(t("providers.updated" as TK), p.name, "success");
      providers.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
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
        onRefresh={providers.reload}
        action={
          <div style={{ display: "flex", gap: 8 }}>
            {isOwner ? (
              <Tooltip content={t("reveal.title" as TK)} relationship="label">
                <Button
                  appearance="subtle"
                  icon={<EyeRegular />}
                  onClick={() => setRevealOpen(true)}
                  aria-label={t("reveal.title" as TK)}
                />
              </Tooltip>
            ) : null}
            <Button
              appearance="primary"
              icon={<AddRegular />}
              onClick={openCreate}
            >
              {t("providers.add" as TK)}
            </Button>
          </div>
        }
      />
      <KeyRevealDialog open={revealOpen} defaultScope="provider" onClose={() => setRevealOpen(false)} />

      {providers.loading ? (
        <Loading />
      ) : providers.error ? (
        <ErrorText error={providers.error} />
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <Input
              placeholder={t("providers.providerFilterSearch" as TK)}
              style={{ flex: "1 1 240px", minWidth: 200 }}
              value={providerSearch}
              onChange={(_, d) => setProviderSearch(d.value)}
            />
            <Dropdown
              style={{ minWidth: 150 }}
              placeholder={t("providers.providerFilterAllTypes" as TK)}
              value={
                providerFilterType
                  ? providerFilterType
                  : t("providers.providerFilterAllTypes" as TK)
              }
              selectedOptions={providerFilterType ? [providerFilterType] : []}
              onOptionSelect={(_, d) =>
                setProviderFilterType(d.optionValue ?? "")
              }
            >
              {allTypes.map((tpe) => (
                <Option key={tpe} value={tpe} text={tpe}>
                  {tpe}
                </Option>
              ))}
            </Dropdown>
            <Dropdown
              style={{ minWidth: 150 }}
              placeholder={t("providers.providerFilterAllAddedBy" as TK)}
              value={
                providerFilterAddedBy
                  ? providerFilterAddedBy
                  : t("providers.providerFilterAllAddedBy" as TK)
              }
              selectedOptions={providerFilterAddedBy ? [providerFilterAddedBy] : []}
              onOptionSelect={(_, d) =>
                setProviderFilterAddedBy(d.optionValue ?? "")
              }
            >
              {allAddedBy.map((name) => (
                <Option key={name} value={name} text={name}>
                  {name}
                </Option>
              ))}
            </Dropdown>
            <Dropdown
              style={{ minWidth: 150 }}
              placeholder={t("providers.providerFilterAllStatus" as TK)}
              value={
                providerFilterEnabled === "enabled"
                  ? t("providers.providerFilterEnabled" as TK)
                  : providerFilterEnabled === "disabled"
                    ? t("providers.providerFilterDisabled" as TK)
                    : t("providers.providerFilterAllStatus" as TK)
              }
              selectedOptions={providerFilterEnabled ? [providerFilterEnabled] : []}
              onOptionSelect={(_, d) =>
                setProviderFilterEnabled(d.optionValue ?? "")
              }
            >
              <Option
                value="enabled"
                text={t("providers.providerFilterEnabled" as TK)}
              >
                {t("providers.providerFilterEnabled" as TK)}
              </Option>
              <Option
                value="disabled"
                text={t("providers.providerFilterDisabled" as TK)}
              >
                {t("providers.providerFilterDisabled" as TK)}
              </Option>
            </Dropdown>
          </div>
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
              {filteredProviders.map((p) => (
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
                  {canEdit(p) ? (
                    <Tooltip
                      content={
                        p.enabled
                          ? t("providers.clickToDisable" as TK)
                          : t("providers.clickToEnable" as TK)
                      }
                      relationship="label"
                    >
                      <Button
                        size="small"
                        appearance="subtle"
                        onClick={() => toggleEnabled(p)}
                        aria-label={
                          p.enabled
                            ? t("providers.clickToDisable" as TK)
                            : t("providers.clickToEnable" as TK)
                        }
                        icon={
                          p.enabled ? (
                            <CheckmarkCircleFilled
                              style={{ color: tokens.colorPaletteGreenForeground1 }}
                            />
                          ) : (
                            <DismissCircleFilled
                              style={{ color: tokens.colorPaletteRedForeground1 }}
                            />
                          )
                        }
                      />
                    </Tooltip>
                  ) : (
                    <Tooltip
                      content={
                        p.enabled
                          ? t("providers.enabled" as TK)
                          : t("providers.disabled" as TK)
                      }
                      relationship="label"
                    >
                      <span
                        style={{ display: "inline-flex" }}
                        aria-label={
                          p.enabled
                            ? t("providers.enabled" as TK)
                            : t("providers.disabled" as TK)
                        }
                      >
                        {p.enabled ? (
                          <CheckmarkCircleFilled
                            style={{ color: tokens.colorPaletteGreenForeground1 }}
                          />
                        ) : (
                          <DismissCircleFilled
                            style={{ color: tokens.colorPaletteRedForeground1 }}
                          />
                        )}
                      </span>
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell>
                  <Tooltip content={t("providers.keys" as TK)} relationship="label">
                    <Button
                      size="small"
                      icon={<KeyRegular />}
                      appearance="subtle"
                      onClick={() => navigate(`/providers/${p.id}/keys`)}
                      aria-label={t("providers.keys" as TK)}
                    />
                  </Tooltip>
                  {canEdit(p) && (
                    <Tooltip content={t("common.edit" as TK)} relationship="label">
                      <Button
                        size="small"
                        icon={<EditRegular />}
                        appearance="subtle"
                        onClick={() => openEdit(p)}
                        aria-label={t("common.edit" as TK)}
                      />
                    </Tooltip>
                  )}
                  {isOwner && (
                    <Tooltip content={t("providers.keyApi" as TK)} relationship="label">
                      <Button
                        size="small"
                        icon={<ShieldKeyholeRegular />}
                        appearance="subtle"
                        onClick={() => openKeyApi(p)}
                        aria-label={t("providers.keyApi" as TK)}
                      />
                    </Tooltip>
                  )}
                  {isOwner && (
                    <Tooltip content={t("common.delete" as TK)} relationship="label">
                      <Button
                        size="small"
                        icon={<DeleteRegular />}
                        appearance="subtle"
                        onClick={() => remove(p)}
                        aria-label={t("common.delete" as TK)}
                      />
                    </Tooltip>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
        </>
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
              <Field
                label={t("providers.name" as TK)}
                hint={t("providers.nameEditHint" as TK)}
                required
              >
                <Input
                  value={form?.name ?? ""}
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
              {fetchOpen && (
                <div
                  style={{
                    border: `1px solid ${tokens.colorNeutralStroke2}`,
                    borderRadius: 8,
                    padding: 16,
                    display: "flex",
                    flexDirection: "column",
                    gap: 12,
                    background: tokens.colorNeutralBackground2,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 600 }}>
                      {t("providers.fetchModelsTitle" as TK)}
                    </span>
                    <Button
                      size="small"
                      appearance="subtle"
                      onClick={() => setFetchOpen(false)}
                    >
                      {t("common.close" as TK)}
                    </Button>
                  </div>
                  {form?.base_url?.includes("api.cloudflare.com") ? (
                    <div style={{ 
                      padding: 12, 
                      backgroundColor: tokens.colorStatusWarningBackground1,
                      border: `1px solid ${tokens.colorStatusWarningForeground1}`,
                      borderRadius: 4,
                      fontSize: 13,
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>
                        {t("providers.cfDetected" as TK)}
                      </div>
                      <div>
                        {t("providers.cfMessage" as TK)}{" "}
                        <a 
                          href="https://developers.cloudflare.com/workers-ai/models/" 
                          target="_blank" 
                          rel="noopener noreferrer"
                          style={{ color: tokens.colorBrandForeground1 }}
                        >
                          Cloudflare Workers AI Models
                        </a>
                      </div>
                    </div>
                  ) : (
                    <>
                  {phKeys.length > 0 && (
                    <>
                      {phKeys.map((k) => (
                        <Field key={k} label={k} required>
                          <Input
                            value={placeholderVals[k] ?? ""}
                            placeholder={`Enter value for {${k}}`}
                            onChange={(_, d) =>
                              setPlaceholderVals((prev) => ({
                                ...prev,
                                [k]: d.value,
                              }))
                            }
                          />
                        </Field>
                      ))}
                    </>
                  )}
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                    <Field label="Method" style={{ flex: "0 0 auto" }}>
                      <Dropdown
                        style={{ minWidth: 80 }}
                        selectedOptions={[fetchMethod]}
                        value={fetchMethod}
                        onOptionSelect={(_, d) =>
                          d.optionValue && setFetchMethod(d.optionValue)
                        }
                      >
                        <Option value="GET" text="GET">GET</Option>
                        <Option value="POST" text="POST">POST</Option>
                      </Dropdown>
                    </Field>
                    <Field label="Path" style={{ flex: 1 }}>
                      <Input
                        value={fetchPath}
                        placeholder="/models (use ../models for CF Workers AI, or https://… for full URL)"
                        onChange={(_, d) => setFetchPath(d.value)}
                      />
                    </Field>
                  </div>
                  <Field label={t("providers.fetchTokenLabel" as TK)} hint={t("providers.fetchTokenHint" as TK)}>
                    <PasswordInput
                      value={fetchToken}
                      placeholder="sk-…"
                      autoComplete="current-password"
                      onChange={(_, d) => setFetchToken(d.value)}
                    />
                  </Field>
                  {form?.id ? (
                    <div>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<KeyRegular />}
                        onClick={openKeyPicker}
                      >
                        {t("providers.useExistingKey" as TK)}
                      </Button>
                    </div>
                  ) : null}
                  <Button
                    appearance="primary"
                    disabled={fetching || !fetchToken || !form?.base_url || (phKeys.length > 0 && !allPhFilled)}
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
                          background: tokens.colorNeutralBackground1,
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
                    </>
                  )}
                </div>
              )}
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
                    onChange={(_, d) => {
                      const next =
                        d.value ??
                        (d.displayValue ? Number(d.displayValue) : undefined);
                      if (next != null && !Number.isNaN(next))
                        setForm((f) => (f ? { ...f, priority: next } : f));
                    }}
                  />
                </Field>
                <Field label={t("providers.weight" as TK)}>
                  <SpinButton
                    value={form?.weight ?? 1}
                    min={1}
                    onChange={(_, d) => {
                      const next =
                        d.value ??
                        (d.displayValue ? Number(d.displayValue) : undefined);
                      if (next != null && !Number.isNaN(next))
                        setForm((f) => (f ? { ...f, weight: next } : f));
                    }}
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
              <Field
                label={t("providers.keySelectMode" as TK)}
                hint={t("providers.keySelectModeHint" as TK)}
              >
                <Dropdown
                  value={
                    form
                      ? KEY_SELECT_MODE_LABEL[form.key_select_mode]
                      : KEY_SELECT_MODE_LABEL.round_robin
                  }
                  selectedOptions={
                    form ? [form.key_select_mode] : ["round_robin"]
                  }
                  onOptionSelect={(_, d) =>
                    d.optionValue &&
                    setForm((f) =>
                      f
                        ? {
                            ...f,
                            key_select_mode: d.optionValue as KeySelectMode,
                          }
                        : f,
                    )
                  }
                >
                  {(Object.keys(KEY_SELECT_MODE_LABEL) as KeySelectMode[]).map(
                    (m) => (
                      <Option key={m} value={m} text={KEY_SELECT_MODE_LABEL[m]}>
                        {KEY_SELECT_MODE_LABEL[m]}
                      </Option>
                    ),
                  )}
                </Dropdown>
              </Field>
              <Field
                label={t("providers.rateLimitCooldown" as TK)}
                hint={t("providers.rateLimitCooldownHint" as TK)}
              >
                <SpinButton
                  value={form?.rate_limit_cooldown_seconds ?? 0}
                  min={0}
                  onChange={(_, d) => {
                    const next =
                      d.value ??
                      (d.displayValue ? Number(d.displayValue) : undefined);
                    if (next != null && !Number.isNaN(next))
                      setForm((f) =>
                        f
                          ? { ...f, rate_limit_cooldown_seconds: Math.max(0, next) }
                          : f,
                      );
                  }}
                />
              </Field>
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
              <Field
                label={t("providers.retryZeroToken" as TK)}
                hint={t("providers.retryZeroTokenHint" as TK)}
              >
                <Switch
                  checked={form?.retry_on_zero_token ?? false}
                  onChange={(_, d) =>
                    setForm((f) =>
                      f ? { ...f, retry_on_zero_token: d.checked } : f,
                    )
                  }
                />
              </Field>
              {!form?.id && (
                <>
                  <Field
                    label={t("providers.initialKeys" as TK)}
                    hint={t("providers.initialKeysHint" as TK)}
                  >
                    <Textarea
                      value={form?.initial_keys ?? ""}
                      rows={4}
                      placeholder={"sk-...\nsk-... # optional description\nsk-..."}
                      onChange={(_, d) =>
                        setForm((f) => (f ? { ...f, initial_keys: d.value } : f))
                      }
                    />
                  </Field>
                  {(form?.initial_keys ?? "").trim() && (
                    <Field label={t("providers.initialKeysPool" as TK)}>
                      <Input
                        value={form?.initial_keys_pool ?? ""}
                        placeholder="(untagged)"
                        onChange={(_, d) =>
                          setForm((f) =>
                            f ? { ...f, initial_keys_pool: d.value } : f,
                          )
                        }
                      />
                    </Field>
                  )}
                </>
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

      <Dialog
        open={keyPickerOpen}
        onOpenChange={(_, d) => !d.open && setKeyPickerOpen(false)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {t("providers.useExistingKeyTitle" as TK)}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                paddingTop: 8,
                minWidth: 360,
              }}
            >
              {keyPickerLoading ? (
                <div style={{ display: "flex", justifyContent: "center", padding: 16 }}>
                  <Spinner size="small" />
                </div>
              ) : keyPickerKeys.length === 0 ? (
                <Text style={{ color: tokens.colorNeutralForeground3 }}>
                  {t("providers.useExistingKeyNoKeys" as TK)}
                </Text>
              ) : (
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {keyPickerKeys.map((k) => (
                    <Button
                      key={k.id}
                      appearance="subtle"
                      style={{ justifyContent: "flex-start" }}
                      onClick={() => selectKeyForFetch(k.id)}
                    >
                      {t("providers.useExistingKeyNum" as TK).replace("{index}", String(k.index))}
                      {k.pool ? ` · ${k.pool}` : ""}
                      {k.note ? ` · ${k.note}` : ""}
                    </Button>
                  ))}
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() => setKeyPickerOpen(false)}
              >
                {t("common.cancel" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={keyApiFor !== null}
        onOpenChange={(_, d) => {
          if (!d.open) {
            setKeyApiFor(null);
            setKeyApi(null);
            setKeyApiToken("");
          }
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {t("providers.keyApiTitle" as TK).replace(
                "{name}",
                keyApiFor?.name ?? "",
              )}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                paddingTop: 8,
              }}
            >
              <p style={{ color: tokens.colorNeutralForeground3, fontSize: 13 }}>
                {t("providers.keyApiDesc" as TK)}
              </p>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontWeight: 600 }}>
                  {t("providers.keyApiStatus" as TK)}:
                </span>
                <Badge
                  color={keyApi?.enabled ? "success" : "subtle"}
                  appearance="filled"
                >
                  {keyApi?.enabled
                    ? t("providers.keyApiEnabled" as TK)
                    : t("providers.keyApiDisabled" as TK)}
                </Badge>
                {keyApi?.token_preview && !keyApiToken && (
                  <code style={{ color: tokens.colorNeutralForeground3 }}>
                    {keyApi.token_preview}
                  </code>
                )}
              </div>

              {keyApiToken && (
                <Field label={t("providers.keyApiToken" as TK)}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Input
                      readOnly
                      value={keyApiToken}
                      style={{ flex: 1, fontFamily: "monospace" }}
                    />
                    <Button
                      onClick={() => {
                        navigator.clipboard?.writeText(keyApiToken);
                        notify(t("providers.keyApiCopied" as TK), "", "success");
                      }}
                    >
                      {t("providers.keyApiCopy" as TK)}
                    </Button>
                  </div>
                  <p
                    style={{
                      color: tokens.colorStatusWarningForeground1,
                      fontSize: 12,
                      marginTop: 4,
                    }}
                  >
                    {t("providers.keyApiTokenOnce" as TK)}
                  </p>
                </Field>
              )}

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {!keyApi?.enabled ? (
                  <Button
                    appearance="primary"
                    disabled={keyApiBusy}
                    onClick={() =>
                      keyApiAction("enable", "providers.keyApiEnabledMsg" as TK)
                    }
                  >
                    {t("providers.keyApiEnable" as TK)}
                  </Button>
                ) : (
                  <>
                    <Button
                      disabled={keyApiBusy}
                      onClick={async () => {
                        const ok = await confirm({
                          title: t("providers.keyApiRotate" as TK),
                          message: t("providers.keyApiRotateConfirm" as TK),
                          confirmLabel: t("providers.keyApiRotate" as TK),
                          tone: "danger",
                        });
                        if (ok)
                          keyApiAction(
                            "rotate",
                            "providers.keyApiRotatedMsg" as TK,
                          );
                      }}
                    >
                      {t("providers.keyApiRotate" as TK)}
                    </Button>
                    <Button
                      disabled={keyApiBusy}
                      onClick={() =>
                        keyApiAction("reveal", "providers.keyApiToken" as TK)
                      }
                    >
                      {t("providers.keyApiReveal" as TK)}
                    </Button>
                    <Button
                      disabled={keyApiBusy}
                      onClick={async () => {
                        const ok = await confirm({
                          title: t("providers.keyApiDisable" as TK),
                          message: t("providers.keyApiDisableConfirm" as TK),
                          confirmLabel: t("providers.keyApiDisable" as TK),
                          tone: "danger",
                        });
                        if (ok)
                          keyApiAction(
                            "disable",
                            "providers.keyApiDisabledMsg" as TK,
                          );
                      }}
                    >
                      {t("providers.keyApiDisable" as TK)}
                    </Button>
                  </>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() =>
                  window.open(`${API_BASE}/provider-api/docs`, "_blank")
                }
              >
                {t("providers.keyApiDocs" as TK)}
              </Button>
              <Button
                appearance="primary"
                onClick={() => {
                  setKeyApiFor(null);
                  setKeyApi(null);
                  setKeyApiToken("");
                }}
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
