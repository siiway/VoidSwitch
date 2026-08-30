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
  NodeGroup,
  Provider,
  ProviderKeyApi,
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

import { KeyRevealDialog } from "../components/KeyRevealDialog";

type TK = keyof Translations;

interface FormState {
  id?: number;
  name: string;
  slug: string;
  type: string;
  base_url: string;
  models: string;
  enabled: boolean;
  drop_opencode_identity_block: boolean;
  retry_on_zero_token: boolean;
  node_group_id: number | null;
  node_group_direct: boolean;
  key_select_mode: KeySelectMode;
  rate_limit_cooldown_seconds: number;
  passthrough_enabled: boolean;
  passthrough_models: string;
  initial_keys: string;
  initial_keys_pool: string;
}

const EMPTY: FormState = {
  name: "",
  slug: "",
  type: "openai",
  base_url: "",
  models: "",
  enabled: true,
  drop_opencode_identity_block: false,
  retry_on_zero_token: false,
  node_group_id: null,
  node_group_direct: false,
  key_select_mode: "round_robin",
  rate_limit_cooldown_seconds: 0,
  passthrough_enabled: false,
  passthrough_models: "",
  initial_keys: "",
  initial_keys_pool: "",
};

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
  const nodeGroups = useAsync<NodeGroup[]>(() => api.get("/api/admin/node-groups"));
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
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
      slug: p.slug ?? "",
      type: p.type,
      base_url: p.base_url,
      models: p.models.join("\n"),
      enabled: p.enabled,
      drop_opencode_identity_block: p.drop_opencode_identity_block,
      retry_on_zero_token: p.retry_on_zero_token,
      node_group_id: p.node_group_id ?? null,
      node_group_direct: false,
      key_select_mode: p.key_select_mode ?? "round_robin",
      rate_limit_cooldown_seconds: p.rate_limit_cooldown_seconds ?? 0,
      passthrough_enabled: p.passthrough_enabled ?? false,
      passthrough_models: (p.passthrough_models ?? []).join("\n"),
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
      // Rank each provider by the highest-priority field that matches, then
      // sort best-first: id/slug > name > type > base URL > model id > added by.
      list = list
        .map((p) => {
          let rank = 6;
          if (String(p.id).toLowerCase().includes(s)) rank = Math.min(rank, 0);
          if ((p.slug ?? "").toLowerCase().includes(s)) rank = Math.min(rank, 0);
          if (p.name.toLowerCase().includes(s)) rank = Math.min(rank, 1);
          if (p.type.toLowerCase().includes(s)) rank = Math.min(rank, 2);
          if ((p.base_url ?? "").toLowerCase().includes(s)) rank = Math.min(rank, 3);
          if ((p.models ?? []).some((m) => m.toLowerCase().includes(s)))
            rank = Math.min(rank, 4);
          if ((p.added_by_name ?? "").toLowerCase().includes(s))
            rank = Math.min(rank, 5);
          return { p, rank };
        })
        .filter(({ rank }) => rank < 6)
        .sort((a, b) => a.rank - b.rank || a.p.id - b.p.id)
        .map(({ p }) => p);
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
  }

  async function save() {
    if (!form) return;
    const models = form.models
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      name: form.name,
      slug: form.slug,
      type: form.type,
      base_url: form.base_url,
      models,
      enabled: form.enabled,
      drop_opencode_identity_block: form.drop_opencode_identity_block,
      retry_on_zero_token: form.retry_on_zero_token,
      node_group_id: form.node_group_id,
      key_select_mode: form.key_select_mode,
      rate_limit_cooldown_seconds: Math.max(
        0,
        form.rate_limit_cooldown_seconds,
      ),
      passthrough_enabled: form.passthrough_enabled,
      passthrough_models: form.passthrough_models
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
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

  const systemGroup = (nodeGroups.data ?? []).find((g) => g.is_system);
  const nodeGroupKey = (() => {
    if (!form) return "default";
    if (form.node_group_direct) return "direct";
    if (form.node_group_id === null) return "default";
    if (form.node_group_id === systemGroup?.id) return "system";
    return String(form.node_group_id);
  })();
  const nodeGroupLabel = (() => {
    if (nodeGroupKey === "default") return t("providers.nodeGroupDefault" as TK);
    if (nodeGroupKey === "system") return t("providers.nodeGroupSystem" as TK);
    if (nodeGroupKey === "direct") return t("providers.nodeGroupDirect" as TK);
    const g = (nodeGroups.data ?? []).find((gg) => String(gg.id) === nodeGroupKey);
    return g?.name ?? `#${nodeGroupKey}`;
  })();
  const visibleGroups = (nodeGroups.data ?? []).filter(
    (g) => g.slug !== "default" && g.slug !== "system",
  );

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
              <details>
                <summary
                  style={{
                    cursor: "pointer",
                    padding: "8px 12px",
                    fontWeight: 600,
                    color: tokens.colorNeutralForeground1,
                  }}
                >
                  {t("providers.fetchModels" as TK)}
                </summary>
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
                  <span style={{ fontWeight: 600 }}>
                      {t("providers.fetchModelsTitle" as TK)}
                    </span>
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
                    <Input
                      type="text"
                      autoComplete="off"
                      value={fetchToken}
                      placeholder="sk-…"
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
              </details>
              <Field
                label={t("providers.slug" as TK)}
                hint={t("providers.slugHint" as TK)}
              >
                <Input
                  value={form?.slug ?? ""}
                  placeholder={
                    form?.slug?.trim()
                      ? ""
                      : form?.name
                          ?.toLowerCase()
                          .replace(/[^a-z0-9-_]/g, "-")
                          .replace(/-+/g, "-")
                          .replace(/^-+|-+$/g, "") || t("providers.slugPlaceholder" as TK)
                  }
                  onChange={(_, d) => {
                    const val = d.value
                      .toLowerCase()
                      .replace(/[^a-z0-9-_]/g, "-")
                      .replace(/-+/g, "-");
                    setForm((f) => (f ? { ...f, slug: val } : f));
                  }}
                />
              </Field>
              <Field
                label={t("providers.nodeGroup" as TK)}
              >
                <Dropdown
                  placeholder={t("providers.nodeGroupDefault" as TK)}
                  value={nodeGroupLabel}
                  selectedOptions={[nodeGroupKey]}
                  onOptionSelect={(_, d) => {
                    const v = d.optionValue ?? "default";
                    if (v === "default") {
                      setForm((f) => (f ? { ...f, node_group_id: null, node_group_direct: false } : f));
                    } else if (v === "system") {
                      setForm((f) => (f ? { ...f, node_group_id: systemGroup?.id ?? null, node_group_direct: false } : f));
                    } else if (v === "direct") {
                      setForm((f) => (f ? { ...f, node_group_id: null, node_group_direct: true } : f));
                    } else {
                      const n = Number(v);
                      setForm((f) => (f ? { ...f, node_group_id: Number.isNaN(n) ? null : n, node_group_direct: false } : f));
                    }
                  }}
                >
                  <Option value="default" text={t("providers.nodeGroupDefault" as TK)}>
                    {t("providers.nodeGroupDefault" as TK)}
                  </Option>
                  <Option value="system" text={t("providers.nodeGroupSystem" as TK)}>
                    {t("providers.nodeGroupSystem" as TK)}
                  </Option>
                  <Option value="direct" text={t("providers.nodeGroupDirect" as TK)}>
                    {t("providers.nodeGroupDirect" as TK)}
                  </Option>
                  {visibleGroups.map((g) => (
                    <Option key={g.id} value={String(g.id)} text={g.name}>
                      {g.name}
                      {g.is_system ? ` (${t("nodes.systemBadge" as TK)})` : ""}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Switch
                label={t("common.enabled" as TK)}
                checked={form?.enabled ?? true}
                onChange={(_, d) =>
                  setForm((f) => (f ? { ...f, enabled: d.checked } : f))
                }
              />
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
              <Field label={t("providers.passthroughEnabled" as TK)}>
                <Switch
                  checked={form?.passthrough_enabled ?? false}
                  onChange={(_, d) =>
                    setForm((f) =>
                      f ? { ...f, passthrough_enabled: d.checked } : f,
                    )
                  }
                />
              </Field>
              {form?.passthrough_enabled && (
                <Field
                  label={t("providers.passthroughModels" as TK)}
                  hint={t("providers.passthroughModelsHint" as TK)}
                >
                  <Textarea
                    value={form?.passthrough_models ?? ""}
                    rows={4}
                    placeholder={t("providers.passthroughModelsPlaceholder" as TK)}
                    onChange={(_, d) =>
                      setForm((f) =>
                        f ? { ...f, passthrough_models: d.value } : f,
                      )
                    }
                  />
                </Field>
              )}
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
                data-shortcut={form?.id ? "save" : "apply"}
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
              <div style={{ display: keyPickerLoading ? "flex" : "none", justifyContent: "center", padding: 16 }}>
                <Spinner size="small" />
              </div>
              <div style={{ display: !keyPickerLoading && keyPickerKeys.length === 0 ? "block" : "none" }}>
                <Text style={{ color: tokens.colorNeutralForeground3 }}>
                  {t("providers.useExistingKeyNoKeys" as TK)}
                </Text>
              </div>
              <div style={{ display: !keyPickerLoading && keyPickerKeys.length > 0 ? "flex" : "none", flexDirection: "column" }}>
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
