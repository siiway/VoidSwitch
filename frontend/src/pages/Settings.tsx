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
import { BroomRegular } from "@fluentui/react-icons";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

type TK = keyof Translations;

interface SettingsResponse {
  values: Record<string, unknown>;
}

// Ordered, grouped layout of the operational settings. Keys absent from every
// section fall into a trailing "Other" card so nothing is ever hidden by accident.
const SECTIONS: { titleKey: string; keys: string[] }[] = [
  {
    titleKey: "settings.sectionProxy",
    keys: [
      "proxy_switching_enabled",
      "static_proxy_url",
      "max_proxy_failures",
      "proxy_probe_interval_seconds",
      "proxy_resurrector_enabled",
      "proxy_probe_url",
    ],
  },
  {
    titleKey: "settings.sectionKeys",
    keys: [
      "max_key_failures",
      "auto_disable_zero_balance",
      "balance_probe_enabled",
      "balance_probe_interval_seconds",
      "balance_rescan_enabled",
      "balance_rescan_interval_seconds",
      "balance_scan_rate_per_second",
    ],
  },
  {
    titleKey: "settings.sectionRateLimit",
    keys: ["rate_limit_recovery_seconds", "rate_limit_max_cooldown_seconds"],
  },
  {
    titleKey: "settings.sectionTimeouts",
    keys: [
      "connect_timeout_seconds",
      "request_timeout_seconds",
      "stream_idle_timeout_seconds",
      "max_retries",
    ],
  },
  {
    titleKey: "settings.sectionLogs",
    keys: [
      "logs_page_size",
      "log_cleanup_enabled",
      "log_cleanup_interval_seconds",
      "audit_log_retention_days",
      "request_log_retention_days",
      "debug_log_retention_days",
    ],
  },
  {
    titleKey: "settings.sectionOpencode",
    keys: ["opencode_default_model", "opencode_small_model"],
  },
];

// Proxy-pool settings that are meaningless when proxy switching is off.
const PROXY_SWITCHING_ONLY = new Set([
  "max_proxy_failures",
  "proxy_probe_interval_seconds",
]);

export function Settings() {
  const { t } = useTranslation();
  const notify = useNotify();
  const confirm = useConfirm();
  const { isOwner } = useAuth();
  const loaded = useAsync<SettingsResponse>(() =>
    api.get("/api/admin/settings"),
  );
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  useEffect(() => {
    if (loaded.data) setValues(loaded.data.values);
  }, [loaded.data]);

  function set(key: string, value: unknown) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  const proxySwitching = values.proxy_switching_enabled !== false;

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

  async function cleanLogsNow() {
    const ok = await confirm({
      title: t("settings.cleanNowTitle" as TK),
      message: t("settings.cleanNowMsg" as TK),
      confirmLabel: t("settings.cleanNow" as TK),
      tone: "danger",
    });
    if (!ok) return;
    setCleaning(true);
    try {
      const r = await api.post<{
        deleted_request_logs: number;
        deleted_audit_logs: number;
        stripped_debug_logs: number;
      }>("/api/admin/settings/clean-logs");
      notify(
        t("settings.cleanedTitle" as TK),
        t("settings.cleanedDetail" as TK)
          .replace("{requests}", String(r.deleted_request_logs))
          .replace("{audits}", String(r.deleted_audit_logs))
          .replace("{debug}", String(r.stripped_debug_logs)),
        "success",
      );
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setCleaning(false);
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
      rate_limit_recovery_seconds: t("settings.rateLimitRecovery" as TK),
      rate_limit_max_cooldown_seconds: t("settings.rateLimitMaxCooldown" as TK),
      auto_disable_zero_balance: t("settings.autoDisableZeroBalance" as TK),
      balance_probe_enabled: t("settings.balanceProbeEnabled" as TK),
      balance_rescan_enabled: t("settings.balanceRescanEnabled" as TK),
      proxy_resurrector_enabled: t("settings.proxyResurrectorEnabled" as TK),
      proxy_probe_url: t("settings.proxyProbeUrl" as TK),
      opencode_default_model: t("settings.opencodeDefaultModel" as TK),
      opencode_small_model: t("settings.opencodeSmallModel" as TK),
      audit_log_retention_days: t("settings.auditLogRetentionDays" as TK),
      request_log_retention_days: t("settings.requestLogRetentionDays" as TK),
      debug_log_retention_days: t("settings.debugLogRetentionDays" as TK),
      log_cleanup_enabled: t("settings.logCleanupEnabled" as TK),
      log_cleanup_interval_seconds: t("settings.logCleanupInterval" as TK),
      logs_page_size: t("settings.logsPageSize" as TK),
      proxy_switching_enabled: t("settings.proxySwitchingEnabled" as TK),
      static_proxy_url: t("settings.staticProxyUrl" as TK),
    }),
    [t],
  );

  function renderField(key: string) {
    if (!(key in values)) return null;
    // Hide proxy-pool settings that don't apply when switching is off.
    if (!proxySwitching && PROXY_SWITCHING_ONLY.has(key)) return null;
    const value = values[key];
    const label = labels[key] ?? key;

    if (typeof value === "boolean") {
      // The auto-cleanup toggle gets an inline "clean now" action (owner-only).
      if (key === "log_cleanup_enabled") {
        return (
          <div
            key={key}
            style={{ display: "flex", alignItems: "center", gap: 12 }}
          >
            <Switch
              label={label}
              checked={value}
              disabled={!isOwner}
              onChange={(_, d) => set(key, d.checked)}
            />
            {isOwner ? (
              <Button
                size="small"
                icon={<BroomRegular />}
                disabled={cleaning}
                onClick={cleanLogsNow}
              >
                {cleaning ? t("settings.cleaning" as TK) : t("settings.cleanNow" as TK)}
              </Button>
            ) : null}
          </div>
        );
      }
      return (
        <Switch
          key={key}
          label={label}
          checked={value}
          disabled={!isOwner}
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
            disabled={!isOwner}
            onChange={(_, d) => {
              const next =
                d.value ?? (d.displayValue ? Number(d.displayValue) : value);
              if (!Number.isNaN(next)) set(key, next);
            }}
          />
        </Field>
      );
    }
    return (
      <Field key={key} label={label}>
        <Input
          value={String(value)}
          disabled={!isOwner}
          onChange={(_, d) => set(key, d.value)}
        />
      </Field>
    );
  }

  if (loaded.loading) return <Loading />;
  if (loaded.error) return <ErrorText error={loaded.error} />;

  const known = new Set(SECTIONS.flatMap((s) => s.keys));
  const otherKeys = Object.keys(values).filter((k) => !known.has(k));
  const sections = [
    ...SECTIONS,
    ...(otherKeys.length
      ? [{ titleKey: "settings.sectionOther", keys: otherKeys }]
      : []),
  ];

  return (
    <div>
      <PageHeader
        title={t("settings.title" as TK)}
        subtitle={t("settings.subtitle" as TK)}
        onRefresh={loaded.reload}
        action={
          isOwner ? (
            <Button appearance="primary" disabled={saving} onClick={save}>
              {t("common.saveChanges" as TK)}
            </Button>
          ) : undefined
        }
      />
      {!isOwner ? (
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 12 }}
        >
          {t("settings.readOnlyNote" as TK)}
        </Text>
      ) : null}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          maxWidth: 560,
        }}
      >
        {sections.map((section) => {
          const fields = section.keys
            .map((k) => renderField(k))
            .filter((node): node is ReactElement => node !== null);
          if (fields.length === 0) return null;
          return (
            <Card
              key={section.titleKey}
              style={{
                padding: 20,
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              <Text weight="semibold" size={400}>
                {t(section.titleKey as TK)}
              </Text>
              {fields}
            </Card>
          );
        })}
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("common.settingsAppliedNote" as TK)}
        </Text>
      </div>
    </div>
  );
}

export { Settings as SettingsPage };
