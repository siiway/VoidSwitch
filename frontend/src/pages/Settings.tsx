import {
  Button,
  Card,
  Field,
  Input,
  SpinButton,
  Switch,
  Text,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useNotify,
} from "../components/ui";

type TK = keyof Translations;

interface SettingsResponse {
  values: Record<string, unknown>;
}

export function Settings() {
  const { t } = useTranslation();
  const notify = useNotify();
  const loaded = useAsync<SettingsResponse>(() =>
    api.get("/api/admin/settings"),
  );
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (loaded.data) setValues(loaded.data.values);
  }, [loaded.data]);

  function set(key: string, value: unknown) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function save() {
    setSaving(true);
    try {
      await api.put("/api/admin/settings", { values });
      notify(t("common.settingsSaved" as TK), undefined, "success");
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

  const labels = useMemo<Record<string, string>>(
    () => ({
      max_proxy_failures: t("settings.maxProxyFailures" as TK),
      max_key_failures: t("settings.maxKeyFailures" as TK),
      proxy_probe_interval_seconds: t("settings.proxyProbeInterval" as TK),
      balance_probe_interval_seconds: t("settings.balanceProbeInterval" as TK),
      balance_rescan_interval_seconds: t(
        "settings.balanceRescanInterval" as TK,
      ),
      balance_scan_rate_per_second: t("settings.balanceScanRate" as TK),
      request_timeout_seconds: t("settings.requestTimeout" as TK),
      connect_timeout_seconds: t("settings.connectTimeout" as TK),
      max_retries: t("settings.maxRetries" as TK),
      stream_idle_timeout_seconds: t("settings.streamIdleTimeout" as TK),
      auto_disable_zero_balance: t("settings.autoDisableZeroBalance" as TK),
      balance_probe_enabled: t("settings.balanceProbeEnabled" as TK),
      balance_rescan_enabled: t("settings.balanceRescanEnabled" as TK),
      proxy_resurrector_enabled: t("settings.proxyResurrectorEnabled" as TK),
      proxy_probe_url: t("settings.proxyProbeUrl" as TK),
    }),
    [t],
  );

  if (loaded.loading) return <Loading />;
  if (loaded.error) return <ErrorText error={loaded.error} />;

  return (
    <div>
      <PageHeader
        title={t("settings.title" as TK)}
        subtitle={t("settings.subtitle" as TK)}
        action={
          <Button appearance="primary" disabled={saving} onClick={save}>
            {t("common.saveChanges" as TK)}
          </Button>
        }
      />
      <Card
        style={{
          padding: 20,
          maxWidth: 560,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {Object.entries(values).map(([key, value]) => {
          const label = labels[key] ?? key;
          if (typeof value === "boolean") {
            return (
              <Switch
                key={key}
                label={label}
                checked={value}
                onChange={(_, d) => set(key, d.checked)}
              />
            );
          }
          if (typeof value === "number") {
            return (
              <Field key={key} label={label}>
                <SpinButton
                  value={value}
                  min={0}
                  onChange={(_, d) => set(key, d.value ?? value)}
                />
              </Field>
            );
          }
          return (
            <Field key={key} label={label}>
              <Input
                value={String(value)}
                onChange={(_, d) => set(key, d.value)}
              />
            </Field>
          );
        })}
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("common.settingsAppliedNote" as TK)}
        </Text>
      </Card>
    </div>
  );
}

export { Settings as SettingsPage };
