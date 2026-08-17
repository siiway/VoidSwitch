import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
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
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import type { ModelWithRoute, Provider, Route } from "../api/types";
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
  const [picker, setPicker] = useState<{ layerPk: string } | null>(null);
  const [providerSearch, setProviderSearch] = useState("");
  // Filter for the upstream-model datalist suggestions.
  const [upstreamSearch, setUpstreamSearch] = useState("");

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

  const pickableProviders = (providers.data ?? []).filter((p) => {
    const q = providerSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      p.name.toLowerCase().includes(q) ||
      p.slug.toLowerCase().includes(q) ||
      (p.models ?? []).some((m) => m.toLowerCase().includes(q))
    );
  });

  function upstreamCandidates(providerId: number | null): string[] {
    const p = providerById(providerId);
    if (!p) return [];
    const list = p.models ?? [];
    const q = upstreamSearch.trim().toLowerCase();
    return q
      ? list.filter((m) => m.toLowerCase().includes(q))
      : list;
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
          {t("models.routeTitle" as TK)}
        </Text>
        <Text size={300} style={{ fontFamily: tokens.fontFamilyMonospace }}>
          {decoded}
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
            {(draft ?? []).map((layer, index) => (
              <div key={layer.pk} className={styles.layer}>
                <div className={styles.layerHead}>
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
                    return (
                      <div key={entry.pk} className={styles.entry}>
                        <Checkbox
                          checked={entry.enabled}
                          onChange={(_, d) =>
                            setEntry(layer.pk, entry.pk, {
                              enabled: d.checked === true,
                            })
                          }
                          aria-label={t("common.enabled" as TK)}
                        />
                        <Field label={t("models.routeProvider" as TK)} style={{ flex: "1 1 160px" }}>
                          <Button
                            appearance="outline"
                            style={{ width: "100%", justifyContent: "flex-start" }}
                            onClick={() => {
                              setPicker({ layerPk: layer.pk });
                              setProviderSearch("");
                            }}
                          >
                            {provider
                              ? provider.slug || provider.name
                              : t("models.routeSelectProvider" as TK)}
                          </Button>
                        </Field>
                        <Field label={t("models.routeUpstream" as TK)} style={{ flex: "1 1 160px" }}>
                          <Input
                            value={entry.upstream_model}
                            placeholder={t("models.routeUpstreamPlaceholder" as TK)}
                            list={`ul-${entry.pk}`}
                            onChange={(_, d) =>
                              setEntry(layer.pk, entry.pk, {
                                upstream_model: d.value,
                              })
                            }
                            onInput={(e) =>
                              setUpstreamSearch(
                                (e.target as HTMLInputElement).value,
                              )
                            }
                          />
                          <datalist id={`ul-${entry.pk}`}>
                            {upstreamCandidates(entry.provider_id).map((m) => (
                              <option key={m} value={m} />
                            ))}
                          </datalist>
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
                        <Field label={t("models.routeKeyPool" as TK)}>
                          <Input
                            value={entry.key_pool}
                            placeholder="(any)"
                            style={{ width: 110 }}
                            onChange={(_, d) =>
                              setEntry(layer.pk, entry.pk, { key_pool: d.value })
                            }
                          />
                        </Field>
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<DeleteRegular />}
                          onClick={() => removeEntry(layer.pk, entry.pk)}
                          aria-label={t("common.delete" as TK)}
                        />
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
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <Button appearance="secondary" icon={<AddRegular />} onClick={addLayer}>
              {t("models.routeAddLayer" as TK)}
            </Button>
          </div>
        </>
      )}

      {/* Provider picker (mounted as a dialog for picking an entry's provider) */}
      <Dialog
        open={picker !== null}
        onOpenChange={(_, d) => !d.open && setPicker(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("models.routePickProvider" as TK)}</DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                paddingTop: 8,
              }}
            >
              <Input
                contentBefore={<></>}
                placeholder={t("models.routeProviderSearch" as TK)}
                value={providerSearch}
                onChange={(_, d) => setProviderSearch(d.value)}
              />
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  maxHeight: 300,
                  overflowY: "auto",
                }}
              >
                {pickableProviders.length === 0 ? (
                  <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                    {t("models.noModels" as TK)}
                  </Text>
                ) : (
                  pickableProviders.map((p) => (
                    <Button
                      key={p.id}
                      appearance="subtle"
                      style={{ justifyContent: "flex-start" }}
                      onClick={() => {
                        if (picker) {
                          const layer = draft?.find((l) => l.pk === picker.layerPk);
                          const existing = layer?.entries.find(
                            (e2) => e2.provider_id == null,
                          );
                          if (existing) {
                            setEntry(picker.layerPk, existing.pk, {
                              provider_id: p.id,
                            });
                          } else {
                            // no blank entry — add one bound to this provider
                            const pk = nextPk();
                            setDraft((d) =>
                              (d ?? []).map((l) =>
                                l.pk === picker.layerPk
                                  ? {
                                      ...l,
                                      entries: [
                                        ...l.entries,
                                        {
                                          pk,
                                          provider_id: p.id,
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
                        }
                        setPicker(null);
                      }}
                    >
                      {p.slug || p.name} — {p.models?.length ?? 0} model(s)
                    </Button>
                  ))
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setPicker(null)}>
                {t("common.cancel" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
