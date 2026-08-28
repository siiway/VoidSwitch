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
  ReOrderDotsVerticalRegular,
  SaveRegular,
} from "@fluentui/react-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import type { ApiKey, ModelWithRoute, Provider, Route } from "../api/types";
import {
  ErrorText,
  Loading,
  useAsync,
  useNotify,
} from "../components/ui";

type TK = keyof Translations;

const useStyles = makeStyles({
  flow: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  layer: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "10px",
    padding: "12px",
    background: tokens.colorNeutralBackground1,
  },
  layerHead: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  layerBody: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  entry: {
    display: "flex",
    gap: "8px",
    alignItems: "flex-end",
    flexWrap: "wrap",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "8px",
    padding: "8px",
    background: tokens.colorNeutralBackground2,
  },
});

interface DraftEntry {
  pk: string;
  provider_id: number | null;
  upstream_model: string;
  weight: number;
  enabled: boolean;
  key_pool: string;
}

interface DraftLayer {
  pk: string;
  max_attempts: number;
  entries: DraftEntry[];
}

let pkCounter = 0;
function nextPk(): string {
  pkCounter += 1;
  return `pk-${pkCounter}`;
}

export function ModelRoute() {
  const { t } = useTranslation();
  const styles = useStyles();
  const notify = useNotify();
  const navigate = useNavigate();
  const { modelId } = useParams<{ modelId: string }>();
  const decoded = modelId ? decodeURIComponent(modelId) : "";

  const routeData = useAsync<ModelWithRoute | null>(
    () =>
      decoded ? api.get(`/api/models/${encodeURIComponent(decoded)}/route`) : Promise.resolve(null),
    [decoded],
  );
  const providers = useAsync<Provider[]>(() => api.get("/api/admin/providers"));

  const [draft, setDraft] = useState<DraftLayer[] | null>(null);
  const [saving, setSaving] = useState(false);

  const [providerQuery, setProviderQuery] = useState<Record<string, string>>({});

  const [poolsByProvider, setPoolsByProvider] = useState<Record<number, string[]>>({});
  const loadedPoolsRef = useRef<Set<number>>(new Set());

  const providerIds = useMemo(
    () =>
      [
        ...new Set(
          (draft ?? [])
            .flatMap((l) => l.entries.map((e) => e.provider_id))
            .filter((id): id is number => id != null),
        ),
      ].sort(),
    [draft],
  );

  useEffect(() => {
    for (const id of providerIds) {
      if (loadedPoolsRef.current.has(id)) continue;
      loadedPoolsRef.current.add(id);
      api
        .get<ApiKey[]>(`/api/admin/providers/${id}/keys`)
        .then((keys) => {
          const pools = [...new Set(keys.map((k) => k.pool ?? "").filter(Boolean))].sort();
          setPoolsByProvider((p) => ({ ...p, [id]: pools }));
        })
        .catch(() => {
          loadedPoolsRef.current.delete(id);
        });
    }
  }, [providerIds]);

  const [dragLayerPk, setDragLayerPk] = useState<string | null>(null);
  const [dragOverLayerIdx, setDragOverLayerIdx] = useState<number | null>(null);

  if (!decoded) {
    return <ErrorText error={t("nodes.title" as TK)} />;
  }

  function materialize(route: Route | null | undefined): DraftLayer[] {
    return (route?.layers ?? []).map((l) => ({
      pk: nextPk(),
      max_attempts: l.max_attempts,
      entries: l.entries.map((e) => ({
        pk: nextPk(),
        provider_id: e.provider_id ?? null,
        upstream_model: e.upstream_model,
        weight: e.weight,
        enabled: e.enabled,
        key_pool: e.key_pool,
      })),
    }));
  }

  if (routeData.data && draft === null) {
    setDraft(materialize(routeData.data.route));
  }

  function setLayer(layerPk: string, patch: Partial<DraftLayer>) {
    setDraft((d) =>
      (d ?? []).map((l) => (l.pk === layerPk ? { ...l, ...patch } : l)),
    );
  }

  function setEntry(layerPk: string, entryPk: string, patch: Partial<DraftEntry>) {
    setDraft((d) =>
      (d ?? []).map((l) =>
        l.pk === layerPk
          ? {
              ...l,
              entries: l.entries.map((e) =>
                e.pk === entryPk ? { ...e, ...patch } : e,
              ),
            }
          : l,
      ),
    );
  }

  function addLayer() {
    setDraft((d) => [...(d ?? []), { pk: nextPk(), max_attempts: 1, entries: [] }]);
  }

  function removeLayer(layerPk: string) {
    setDraft((d) => (d ?? []).filter((l) => l.pk !== layerPk));
  }

  function moveLayer(index: number, dir: -1 | 1) {
    setDraft((d) => {
      const arr = [...(d ?? [])];
      const target = index + dir;
      if (target < 0 || target >= arr.length) return arr;
      [arr[index], arr[target]] = [arr[target], arr[index]];
      return arr;
    });
  }

  function addEntry(layerPk: string) {
    setDraft((d) =>
      (d ?? []).map((l) =>
        l.pk === layerPk
          ? {
              ...l,
              entries: [
                ...l.entries,
                {
                  pk: nextPk(),
                  provider_id: null,
                  upstream_model: "",
                  weight: 1,
                  enabled: true,
                  key_pool: "",
                },
              ],
            }
          : l,
      ),
    );
  }

  function removeEntry(layerPk: string, entryPk: string) {
    setDraft((d) =>
      (d ?? []).map((l) =>
        l.pk === layerPk
          ? { ...l, entries: l.entries.filter((e) => e.pk !== entryPk) }
          : l,
      ),
    );
  }

  function providerById(id: number | null): Provider | undefined {
    return (providers.data ?? []).find((p) => p.id === id);
  }

  function onLayerDragStart(pk: string) {
    setDragLayerPk(pk);
  }

  function onLayerDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    setDragOverLayerIdx(idx);
  }

  function onLayerDrop(idx: number) {
    if (!dragLayerPk) return;
    const arr = [...(draft ?? [])];
    const from = arr.findIndex((l) => l.pk === dragLayerPk);
    if (from < 0 || from === idx) {
      setDragLayerPk(null);
      setDragOverLayerIdx(null);
      return;
    }
    const [moved] = arr.splice(from, 1);
    arr.splice(idx, 0, moved);
    setDraft(arr);
    setDragLayerPk(null);
    setDragOverLayerIdx(null);
  }

  function onLayerDragEnd() {
    setDragLayerPk(null);
    setDragOverLayerIdx(null);
  }

  async function save() {
    if (!decoded) return;
    const layers: Array<{
      max_attempts: number;
      entries: Array<{
        provider_id: number;
        upstream_model: string;
        weight: number;
        enabled: boolean;
        key_pool: string;
      }>;
    }> = (draft ?? []).map((l) => ({
      max_attempts: Math.max(1, l.max_attempts),
      entries: l.entries
        .filter((e) => e.provider_id != null)
        .map((e) => ({
          provider_id: e.provider_id as number,
          upstream_model: e.upstream_model.trim(),
          weight: Math.max(1, e.weight),
          enabled: e.enabled,
          key_pool: e.key_pool.trim(),
        })),
    }));
    setSaving(true);
    try {
      await api.put(`/api/models/${encodeURIComponent(decoded)}/route`, {
        layers,
      });
      notify(t("models.routeSaved" as TK), decoded, "success");
      navigate(`/models`);
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

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <Button
          appearance="subtle"
          icon={<ArrowLeftRegular />}
          onClick={() => navigate("/models")}
          aria-label={t("common.back" as TK)}
        >
          {t("common.back" as TK)}
        </Button>
        <Text size={600} weight="semibold" as="h1">
          {t("models.routeTitle" as TK).replace("{id}", "")}
          <Text size={300} as="span" style={{ fontFamily: tokens.fontFamilyMonospace }}>
            {decoded}
          </Text>
        </Text>
        <span style={{ flex: 1 }} />
        <Button
          appearance="primary"
          icon={<SaveRegular />}
          disabled={saving}
          onClick={save}
        >
          {saving ? t("models.routeSaving" as TK) : t("common.save" as TK)}
        </Button>
      </div>

      {routeData.loading || providers.loading ? (
        <Loading />
      ) : routeData.error ? (
        <ErrorText error={routeData.error} />
      ) : providers.error ? (
        <ErrorText error={providers.error} />
      ) : (
        <>
          <Text size={200} block style={{ color: tokens.colorNeutralForeground3, marginBottom: 16 }}>
            {t("models.routeHint" as TK)}
          </Text>
          <div className={styles.flow}>
            {(draft ?? []).map((layer, index) => {
              const showLine =
                dragLayerPk != null && dragOverLayerIdx === index;
              return (
                <div
                  key={layer.pk}
                  className={styles.layer}
                  style={{
                    borderTop: showLine
                      ? `2px solid ${tokens.colorBrandForeground1}`
                      : "2px solid transparent",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div className={styles.layerHead}>
                    <Tooltip content={t("models.dragHint" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="transparent"
                        icon={<ReOrderDotsVerticalRegular />}
                        style={{ cursor: "grab", flexShrink: 0 }}
                        draggable
                        onDragStart={() => onLayerDragStart(layer.pk)}
                        onDragOver={(e) => onLayerDragOver(e, index)}
                        onDrop={() => onLayerDrop(index)}
                        onDragEnd={onLayerDragEnd}
                        aria-label={t("models.dragHint" as TK)}
                      />
                    </Tooltip>
                    <Text weight="semibold">
                      {t("models.layerLabel" as TK).replace(
                        "{n}",
                        String(index + 1),
                      )}
                    </Text>
                    <Field label={t("models.maxAttempts" as TK)}>
                      <Input
                        type="number"
                        value={String(layer.max_attempts)}
                        min={1}
                        style={{ width: 80 }}
                        onChange={(_, d) =>
                          setLayer(layer.pk, {
                            max_attempts: Math.max(1, Number(d.value) || 1),
                          })
                        }
                      />
                    </Field>
                    <span style={{ flex: 1 }} />
                    <Tooltip content={t("common.up" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<ArrowUpRegular />}
                        disabled={index === 0}
                        onClick={() => moveLayer(index, -1)}
                        aria-label={t("common.up" as TK)}
                      />
                    </Tooltip>
                    <Tooltip content={t("common.down" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<ArrowDownRegular />}
                        disabled={index === (draft?.length ?? 0) - 1}
                        onClick={() => moveLayer(index, 1)}
                        aria-label={t("common.down" as TK)}
                      />
                    </Tooltip>
                    <Tooltip content={t("common.delete" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<DeleteRegular />}
                        onClick={() => removeLayer(layer.pk)}
                        aria-label={t("common.delete" as TK)}
                      />
                    </Tooltip>
                  </div>
                  <div className={styles.layerBody}>
                    {layer.entries.map((entry) => {
                      const provider = providerById(entry.provider_id);
                      const pQuery = providerQuery[entry.pk];
                      const typing = pQuery !== undefined;
                      const pFilter = (p: Provider) => {
                        if (!typing || !pQuery) return true;
                        const q = pQuery.toLowerCase();
                        return (
                          p.name.toLowerCase().includes(q) ||
                          p.slug.toLowerCase().includes(q)
                        );
                      };
                      const pools = poolsByProvider[entry.provider_id ?? 0] ?? [];

                      return (
                        <div key={entry.pk} className={styles.entry}>
                          <Button
                            size="small"
                            appearance="subtle"
                            icon={<DeleteRegular />}
                            onClick={() => removeEntry(layer.pk, entry.pk)}
                            aria-label={t("common.delete" as TK)}
                          />
                          <Checkbox
                            checked={entry.enabled}
                            onChange={(_, d) =>
                              setEntry(layer.pk, entry.pk, {
                                enabled: d.checked === true,
                              })
                            }
                            aria-label={t("common.enabled" as TK)}
                          />
                          <Field label={t("models.routeProvider" as TK)} style={{ flex: "1 1 180px" }}>
                            <Combobox
                              freeform
                              autoComplete="list"
                              placeholder={t("models.routeSelectProvider" as TK)}
                              value={
                                typing
                                  ? pQuery
                                  : provider
                                    ? `${provider.name} · ${provider.slug}`
                                    : ""
                              }
                              selectedOptions={
                                !typing && provider ? [String(provider.id)] : []
                              }
                              onOptionSelect={(_, d) => {
                                if (d.optionValue) {
                                  setEntry(layer.pk, entry.pk, {
                                    provider_id: Number(d.optionValue),
                                    key_pool: "",
                                  });
                                }
                                setProviderQuery((q) => {
                                  const n = { ...q };
                                  delete n[entry.pk];
                                  return n;
                                });
                              }}
                              onChange={(e) =>
                                setProviderQuery((q) => ({
                                  ...q,
                                  [entry.pk]: e.target.value,
                                }))
                              }
                              onBlur={() =>
                                setProviderQuery((q) => {
                                  const n = { ...q };
                                  delete n[entry.pk];
                                  return n;
                                })
                              }
                            >
                              {(providers.data ?? []).filter(pFilter).map((p) => (
                                <Option key={p.id} value={String(p.id)} text={`${p.name} · ${p.slug}`}>
                                  {p.name} · {p.slug} ({(p.models ?? []).length})
                                </Option>
                              ))}
                            </Combobox>
                          </Field>
                          <Field label={t("models.routeUpstream" as TK)} style={{ flex: "1 1 180px" }}>
                            <Combobox
                              freeform
                              autoComplete="list"
                              value={entry.upstream_model}
                              placeholder={t("models.routeUpstreamPlaceholder" as TK)}
                              onOptionSelect={(_, d) =>
                                d.optionValue &&
                                setEntry(layer.pk, entry.pk, {
                                  upstream_model: d.optionValue,
                                })
                              }
                              onChange={(e) =>
                                setEntry(layer.pk, entry.pk, {
                                  upstream_model: (e.target as HTMLInputElement).value,
                                })
                              }
                            >
                              {(provider?.models ?? []).map((m) => (
                                <Option key={m} value={m}>
                                  {m}
                                </Option>
                              ))}
                            </Combobox>
                          </Field>
                          <Field label={t("models.routeKeyPool" as TK)}>
                            <Dropdown
                              style={{ minWidth: 120 }}
                              value={entry.key_pool}
                              selectedOptions={entry.key_pool ? [entry.key_pool] : []}
                              placeholder={t("models.routeKeyPoolAny" as TK)}
                              onOptionSelect={(_, d) =>
                                setEntry(layer.pk, entry.pk, {
                                  key_pool: d.optionValue ?? "",
                                })
                              }
                            >
                              <Option value="">{t("models.routeKeyPoolAny" as TK)}</Option>
                              {pools.map((p) => (
                                <Option key={p} value={p}>
                                  {p}
                                </Option>
                              ))}
                            </Dropdown>
                          </Field>
                          <Field label={t("models.routeWeight" as TK)}>
                            <Input
                              type="number"
                              value={String(entry.weight)}
                              min={1}
                              style={{ width: 72 }}
                              onChange={(_, d) =>
                                setEntry(layer.pk, entry.pk, {
                                  weight: Math.max(1, Number(d.value) || 1),
                                })
                              }
                            />
                          </Field>
                        </div>
                      );
                    })}
                    <div>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<AddRegular />}
                        onClick={() => addEntry(layer.pk)}
                      >
                        {t("models.routeAddEntry" as TK)}
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 16 }}>
            <Button appearance="secondary" icon={<AddRegular />} onClick={addLayer}>
              {t("models.routeAddLayer" as TK)}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}