import {
  Button,
  Checkbox,
  Combobox,
  Dropdown,
  Field,
  Input,
  Option,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowDownRegular,
  ArrowLeftRegular,
  ArrowUpRegular,
  DeleteRegular,
  SaveRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  ApiKey,
  ModelWithRoute,
  Provider,
  Route,
  RouteUpstream,
  UpstreamAllCooledBehavior,
  UpstreamRankAlgorithm,
  UpstreamSelectMode,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorText, Loading, useAsync, useNotify } from "../components/ui";
import type { Translations } from "../i18n/locales/en";
import { useModelHealth } from "../lib/useModelHealth";

type TK = keyof Translations;
type DraftUpstream = RouteUpstream & { pk: string };

const useStyles = makeStyles({
  flow: { display: "flex", flexDirection: "column", gap: "10px" },
  settings: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px",
    padding: "16px",
    marginBottom: "16px",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
  },
  entry: {
    display: "flex",
    gap: "8px",
    alignItems: "flex-end",
    flexWrap: "wrap",
    padding: "12px",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "8px",
    background: tokens.colorNeutralBackground1,
  },
  health: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    flexBasis: "100%",
    color: tokens.colorNeutralForeground3,
  },
});

let pkCounter = 0;
const nextPk = () => `upstream-${++pkCounter}`;
const pct = (value?: number | null) =>
  value == null ? "--" : `${(value <= 1 ? value * 100 : value).toFixed(1)}%`;

export function ModelRoute() {
  const { t } = useTranslation();
  const styles = useStyles();
  const notify = useNotify();
  const navigate = useNavigate();
  const { isOwner } = useAuth();
  const { modelId } = useParams<{ modelId: string }>();
  const decoded = modelId ? decodeURIComponent(modelId) : "";
  const routeData = useAsync<ModelWithRoute | null>(
    () => decoded ? api.get(`/api/models/${encodeURIComponent(decoded)}/route`) : Promise.resolve(null),
    [decoded],
  );
  const providers = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const health = useModelHealth(decoded)[decoded];
  const [upstreams, setUpstreams] = useState<DraftUpstream[] | null>(null);
  const [selectMode, setSelectMode] = useState<UpstreamSelectMode>("");
  const [rankAlgorithm, setRankAlgorithm] = useState<UpstreamRankAlgorithm>("");
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [allCooled, setAllCooled] = useState<UpstreamAllCooledBehavior>("");
  const [saving, setSaving] = useState(false);
  const [providerQuery, setProviderQuery] = useState<Record<string, string>>({});
  const [poolsByProvider, setPoolsByProvider] = useState<Record<number, string[]>>({});
  const loadedPools = useRef(new Set<number>());

  useEffect(() => {
    const route = routeData.data?.route;
    if (!route || upstreams !== null) return;
    setSelectMode(route.upstream_select_mode);
    setRankAlgorithm(route.upstream_rank_algorithm);
    setMaxAttempts(route.max_upstream_attempts);
    setAllCooled(route.upstream_all_cooled_behavior);
    setUpstreams((route.upstreams ?? []).map((entry) => ({ ...entry, pk: nextPk() })));
  }, [routeData.data, upstreams]);

  const providerIds = useMemo(
    () => [...new Set((upstreams ?? []).map((entry) => entry.provider_id).filter((id): id is number => id != null))],
    [upstreams],
  );
  useEffect(() => {
    for (const id of providerIds) {
      if (loadedPools.current.has(id)) continue;
      loadedPools.current.add(id);
      api.get<ApiKey[]>(`/api/admin/providers/${id}/keys`).then((keys) => {
        setPoolsByProvider((current) => ({
          ...current,
          [id]: [...new Set(keys.map((key) => key.pool).filter(Boolean))].sort(),
        }));
      }).catch(() => loadedPools.current.delete(id));
    }
  }, [providerIds]);

  const patchUpstream = (pk: string, patch: Partial<DraftUpstream>) =>
    setUpstreams((current) => (current ?? []).map((entry) => entry.pk === pk ? { ...entry, ...patch } : entry));
  const moveUpstream = (index: number, direction: -1 | 1) => setUpstreams((current) => {
    const next = [...(current ?? [])];
    const target = index + direction;
    if (target < 0 || target >= next.length) return next;
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  });

  async function save() {
    const body: Omit<Route, "id" | "exposed_model_id"> = {
      upstream_select_mode: selectMode,
      upstream_rank_algorithm: rankAlgorithm,
      max_upstream_attempts: Math.max(0, maxAttempts),
      upstream_all_cooled_behavior: allCooled,
      upstreams: (upstreams ?? []).filter((entry) => entry.provider_id != null).map(({ pk: _pk, ...entry }) => ({
        ...entry,
        provider_id: entry.provider_id as number,
        upstream_model: entry.upstream_model.trim(),
        key_pool: entry.key_pool.trim(),
        weight: Math.max(1, entry.weight),
      })),
    };
    setSaving(true);
    try {
      await api.put(`/api/models/${encodeURIComponent(decoded)}/route`, body);
      notify(t("models.routeSaved" as TK), decoded, "success");
      navigate("/models");
    } catch (error) {
      notify(t("common.saveFailed" as TK), error instanceof Error ? error.message : String(error), "error");
    } finally { setSaving(false); }
  }

  async function clearCooldown(upstreamId: number) {
    try {
      await api.post(`/api/models/${encodeURIComponent(decoded)}/route/upstreams/${upstreamId}/clear-cooldown`);
      notify(t("models.cooldownCleared" as TK), undefined, "success");
    } catch (error) {
      notify(t("common.updateFailed" as TK), error instanceof Error ? error.message : String(error), "error");
    }
  }

  if (!decoded) return <ErrorText error={t("models.route" as TK)} />;
  if (routeData.loading || providers.loading) return <Loading />;
  if (routeData.error) return <ErrorText error={routeData.error} />;
  if (providers.error) return <ErrorText error={providers.error} />;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <Button appearance="subtle" icon={<ArrowLeftRegular />} onClick={() => navigate("/models")}>{t("common.back" as TK)}</Button>
        <Text size={600} weight="semibold" as="h1">{t("models.routeTitle" as TK).replace("{id}", decoded)}</Text>
        <span style={{ flex: 1 }} />
        <Button appearance="primary" icon={<SaveRegular />} disabled={saving} onClick={save}>
          {saving ? t("models.routeSaving" as TK) : t("common.save" as TK)}
        </Button>
      </div>
      <Text size={200} block style={{ color: tokens.colorNeutralForeground3, marginBottom: 16 }}>{t("models.routeHint" as TK)}</Text>
      <div className={styles.settings}>
        <Field label={t("models.upstreamSelectMode" as TK)}>
          <Dropdown selectedOptions={[selectMode]} value={selectMode || t("common.default" as TK)} onOptionSelect={(_, d) => setSelectMode((d.optionValue as UpstreamSelectMode) ?? "")}>
            <Option value="">{t("common.default" as TK)}</Option>
            {(["best", "balanced", "pinned_best", "pinned_balanced"] as const).map((mode) => <Option key={mode} value={mode}>{mode}</Option>)}
          </Dropdown>
        </Field>
        <Field label={t("models.upstreamRankAlgorithm" as TK)}>
          <Dropdown selectedOptions={[rankAlgorithm]} value={rankAlgorithm || t("common.default" as TK)} onOptionSelect={(_, d) => setRankAlgorithm((d.optionValue as UpstreamRankAlgorithm) ?? "")}>
            <Option value="">{t("common.default" as TK)}</Option>
            {(["weighted", "tiered"] as const).map((algorithm) => <Option key={algorithm} value={algorithm}>{algorithm}</Option>)}
          </Dropdown>
        </Field>
        <Field label={t("models.maxUpstreamAttempts" as TK)}><Input type="number" min={0} value={String(maxAttempts)} onChange={(_, d) => setMaxAttempts(Math.max(0, Number(d.value) || 0))} /></Field>
        <Field label={t("models.allCooledBehavior" as TK)}>
          <Dropdown selectedOptions={[allCooled]} value={allCooled || t("common.default" as TK)} onOptionSelect={(_, d) => setAllCooled((d.optionValue as UpstreamAllCooledBehavior) ?? "")}>
            <Option value="">{t("common.default" as TK)}</Option>
            {(["fail_fast", "ignore_cooldown"] as const).map((behavior) => <Option key={behavior} value={behavior}>{behavior}</Option>)}
          </Dropdown>
        </Field>
      </div>
      <div className={styles.flow}>
        {(upstreams ?? []).map((entry, index) => {
          const provider = (providers.data ?? []).find((item) => item.id === entry.provider_id);
          const query = providerQuery[entry.pk];
          const upstreamHealth = health?.upstreams?.find((item) => item.upstream_id === entry.id);
          return (
            <div key={entry.pk} className={styles.entry}>
              <Checkbox checked={entry.enabled} onChange={(_, d) => patchUpstream(entry.pk, { enabled: d.checked === true })} aria-label={t("common.enabled" as TK)} />
              <Field label={t("models.routeProvider" as TK)} style={{ flex: "1 1 180px" }}>
                <Combobox freeform autoComplete="list" value={query !== undefined ? query : provider ? `${provider.name} · ${provider.slug}` : ""} selectedOptions={query === undefined && provider ? [String(provider.id)] : []} onChange={(event) => setProviderQuery((current) => ({ ...current, [entry.pk]: event.target.value }))} onOptionSelect={(_, d) => {
                  if (d.optionValue) patchUpstream(entry.pk, { provider_id: Number(d.optionValue), key_pool: "" });
                  setProviderQuery((current) => { const next = { ...current }; delete next[entry.pk]; return next; });
                }} onBlur={() => setProviderQuery((current) => { const next = { ...current }; delete next[entry.pk]; return next; })}>
                  {(providers.data ?? []).filter((item) => !query || `${item.name} ${item.slug}`.toLowerCase().includes(query.toLowerCase())).map((item) => <Option key={item.id} value={String(item.id)} text={`${item.name} · ${item.slug}`}>{item.name} · {item.slug}</Option>)}
                </Combobox>
              </Field>
              <Field label={t("models.routeUpstream" as TK)} style={{ flex: "1 1 180px" }}>
                <Combobox freeform value={entry.upstream_model} onChange={(event) => patchUpstream(entry.pk, { upstream_model: event.target.value })} onOptionSelect={(_, d) => d.optionValue && patchUpstream(entry.pk, { upstream_model: d.optionValue })}>
                  {(provider?.models ?? []).map((name) => <Option key={name} value={name}>{name}</Option>)}
                </Combobox>
              </Field>
              <Field label={t("models.routeKeyPool" as TK)}><Dropdown value={entry.key_pool || t("models.routeKeyPoolAny" as TK)} selectedOptions={entry.key_pool ? [entry.key_pool] : []} onOptionSelect={(_, d) => patchUpstream(entry.pk, { key_pool: d.optionValue ?? "" })}><Option value="">{t("models.routeKeyPoolAny" as TK)}</Option>{(poolsByProvider[entry.provider_id ?? 0] ?? []).map((pool) => <Option key={pool} value={pool}>{pool}</Option>)}</Dropdown></Field>
              <Field label={t("models.routeWeight" as TK)}><Input type="number" min={1} style={{ width: 72 }} value={String(entry.weight)} onChange={(_, d) => patchUpstream(entry.pk, { weight: Math.max(1, Number(d.value) || 1) })} /></Field>
              <Tooltip content={t("common.up" as TK)} relationship="label"><Button appearance="subtle" icon={<ArrowUpRegular />} disabled={index === 0} onClick={() => moveUpstream(index, -1)} aria-label={t("common.up" as TK)} /></Tooltip>
              <Tooltip content={t("common.down" as TK)} relationship="label"><Button appearance="subtle" icon={<ArrowDownRegular />} disabled={index === (upstreams?.length ?? 0) - 1} onClick={() => moveUpstream(index, 1)} aria-label={t("common.down" as TK)} /></Tooltip>
              <Tooltip content={t("common.delete" as TK)} relationship="label"><Button appearance="subtle" icon={<DeleteRegular />} onClick={() => setUpstreams((current) => (current ?? []).filter((item) => item.pk !== entry.pk))} aria-label={t("common.delete" as TK)} /></Tooltip>
              <div className={styles.health}>
                <Text size={200}>{upstreamHealth ? `${t(`models.health.${upstreamHealth.status}` as TK)} · ${t("models.successRate" as TK)} ${pct(upstreamHealth.success_rate)} · ${t("models.ttft" as TK)} ${upstreamHealth.ttft_ms == null ? "--" : `${Math.round(upstreamHealth.ttft_ms)} ms`}` : t("models.healthLearning" as TK)}</Text>
                {upstreamHealth?.cooled_until && isOwner ? <Tooltip content={t("models.clearCooldown" as TK)} relationship="label"><Button size="small" appearance="subtle" icon={<WeatherSunnyRegular />} onClick={() => void clearCooldown(upstreamHealth.upstream_id)} aria-label={t("models.clearCooldown" as TK)} /></Tooltip> : null}
              </div>
            </div>
          );
        })}
      </div>
      <Button style={{ marginTop: 16 }} icon={<AddRegular />} onClick={() => setUpstreams((current) => [...(current ?? []), { pk: nextPk(), provider_id: null, upstream_model: "", weight: 1, enabled: true, key_pool: "" }])}>{t("models.routeAddEntry" as TK)}</Button>
    </div>
  );
}
